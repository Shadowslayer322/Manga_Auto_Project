"""Abrir -> limpiar y traducir en paralelo -> typear/revisar -> un PSD final por pagina."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

from typeo_core import (BASE, TypeoError, bind_translation, build_items, load_translation,
                        parse_markdown, read_json, resolve_photoshop_exe, sha256, validate_geometry, write_json)
from typeo_pipeline import verify_job


class Events:
    def __init__(self, path):
        self.path, self.lock = Path(path), threading.Lock()

    def record(self, stage, page=None, **extra):
        event={'time_ms':round(time.time()*1000),'stage':stage,'page':page,**extra}
        with self.lock, self.path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(event,ensure_ascii=False)+'\n')


def prepare_run(geometry_path, output, *, selected=None, replace=False, base=BASE, clean_only=False,auto_geometry=False,reuse_final=False,pre_geometry=None):
    base,output=Path(base),Path(output).resolve()
    computed_fresh=bool(clean_only or auto_geometry)
    if computed_fresh:
        from PIL import Image
        pages=[]
        selected_set=set(selected) if selected else None
        for raw in sorted((base/'01_RAW').iterdir()):
            if raw.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:continue
            if selected_set is not None and raw.stem not in selected_set:continue
            with Image.open(raw) as im:width,height=im.size
            pages.append({'archivo':raw.name,'raw_sha256':sha256(raw),'width':width,'height':height,'zonas':[]})
        if selected_set is not None and not selected_set<={Path(p['archivo']).stem for p in pages}:
            raise TypeoError('Paginas desconocidas')
        if not pages:raise TypeoError('Geometria sin paginas')
        geometry={'version':1,'paginas':pages}
    else:
        geometry=pre_geometry if pre_geometry is not None else read_json(geometry_path)
        if selected:
            ids={Path(p['archivo']).stem for p in geometry['paginas']}
            if not set(selected)<=ids:raise TypeoError('Paginas desconocidas')
            geometry['paginas']=[p for p in geometry['paginas'] if Path(p['archivo']).stem in selected]
        if pre_geometry is None:
            validate_geometry(geometry,base)
    for protected in ('01_RAW','02_TRABAJO_PSD','03_TRADUCCIONES','scripts','config'):
        target=(base/protected).resolve()
        if output==target or target in output.parents:raise TypeoError('La carpeta final no puede ser '+protected)
    if not replace:
        existing=[output/(Path(p['archivo']).stem+'.psd') for p in geometry['paginas']]
        if any(p.exists() for p in existing):
            raise TypeoError('Ya existe un PSD final. Usar --reemplazar para actualizarlo en el mismo archivo, sin crear otra version.')
    elif clean_only:
        import mmap
        # Una repeticion de limpieza nunca debe borrar un typeo terminado.
        for pg in geometry['paginas']:
            existing=output/(Path(pg['archivo']).stem+'.psd')
            if existing.exists() and existing.stat().st_size>=8:
                with existing.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
                    if mm.find(b'8BIMTySh')!=-1:
                        raise TypeoError('El PSD contiene texto editable; no se reemplaza por solo limpieza: '+existing.name)
    job_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    folder=base/'04_DIAGNOSTICO/pipeline'/job_id
    folder.mkdir(parents=True)
    output.mkdir(parents=True,exist_ok=True)
    pages=[]
    for pg in geometry['paginas']:
        name=pg['archivo'];stem=Path(name).stem;p=folder/stem;p.mkdir()
        # Abrir la RAW directamente. Photoshop solo guarda como copia PSD final;
        # no hacen falta duplicados de imagen ni documentos PSD intermedios.
        source=base/'01_RAW'/name;raw=source
        if not computed_fresh and sha256(raw)!=pg['raw_sha256']:raise TypeoError('RAW cambiada durante la preparacion: '+name)
        pages.append({'page':name,'stem':stem,'raw':raw.as_posix(),'raw_original':source.as_posix(),
            'raw_sha256':pg['raw_sha256'],'geometry':pg,'folder':p.as_posix(),
            'clean_ready':(p/'limpieza_lista.json').as_posix(),'typeo_ready':(p/'traduccion_lista.json').as_posix(),
            'clean_report':(p/'limpieza_revisada.json').as_posix(),
            'geometry_ready':(p/'geometria_ocr.json').as_posix(),
            'ocr_ready':(p/'ocr_ingles.json').as_posix(),
            'output':(output/(stem+'.psd')).as_posix(),
            'result':(p/'estado.json').as_posix()})
    job={'version':1,'job_id':job_id,'status':'prepared','folder':folder.as_posix(),'output':output.as_posix(),'clean_only':clean_only,'auto_geometry':auto_geometry,
         'replace':replace,'pages':pages,'opened':(folder/'abiertas.json').as_posix(),
         'native_events':(folder/'eventos_photoshop.jsonl').as_posix(),
         'worker_error':(folder/'ERROR_TRABAJADOR.json').as_posix(),
         'native_status':(folder/'estado_photoshop.json').as_posix(),
         'cancel':(folder/'CANCELAR.txt').as_posix()}
    job['reuse_final']=reuse_final;job['old_typeo_ids']={};job['reuse_masks']={}
    if reuse_final:
        state=read_json(output/'estado_final.json')
        for page in pages:
            tracked=next((p for p in state.get('paginas',[]) if p['archivo']==page['page']),None)
            if not tracked:raise TypeoError('El PSD no tiene registro de origen verificable: '+page['page'])
            prior=read_json(base/'04_DIAGNOSTICO/pipeline'/tracked.get('job_id',state['job_id'])/'trabajo.json')
            if prior.get('status')!='complete':raise TypeoError('El PSD anterior no tiene finalizacion verificada')
            old=next((p for p in prior['pages'] if p['page']==page['page'] and p['raw_sha256']==page['raw_sha256']
                      and Path(p['output']).resolve()==Path(page['output']).resolve()),None)
            if not old or not Path(page['output']).is_file():raise TypeoError('No hay PSD verificado de esta RAW para revisar: '+page['page'])
            ready=Path(old['typeo_ready'])
            job['old_typeo_ids'][page['page']]=[i['id'] for i in read_json(ready)['items']] if ready.exists() else []
            if not reuse_final and Path(old['clean_ready']).exists():
                saved_masks=read_json(old['clean_ready'])
                job['reuse_masks'][page['page']]=saved_masks.get('capas_generativas_mascaras',saved_masks['pares'])
    write_json(folder/'trabajo.json',job)
    return job


def wait_opened(job, stop):
    while not stop.wait(.02):
        if Path(job['opened']).exists():
            try:opened=read_json(job['opened'])
            except (OSError,ValueError):continue
            if opened.get('job_id')==job['job_id']:return True
    return False


def mask_cache_valid(cache, pages, *, config_hashes=None, ocr_cache=None):
    from limpieza_rapida import ENGINE_VERSION
    for p in pages:
        record=cache.get('paginas',{}).get(p['page'])
        if not record or record.get('engine_version')!=ENGINE_VERSION or record['raw_sha256']!=p['raw_sha256']:return False
        ocr=record.get('ocr')
        if not ocr or not Path(ocr['path']).is_file() or sha256(ocr['path'])!=ocr['sha256']:return False
        data=read_json(ocr['path'])
        cfg_path=data.get('config_path')
        if data.get('version')!=3 or not cfg_path or not Path(cfg_path).is_file():return False
        if config_hashes is not None:
            cfg_sha=config_hashes.get(cfg_path)
            if cfg_sha is None:
                cfg_sha=sha256(cfg_path)
                config_hashes[cfg_path]=cfg_sha
        else:
            cfg_sha=sha256(cfg_path)
        if cfg_sha!=data.get('config_sha256'):return False
        for mask in [record['pincel'],record['genfill'],*record['pares']]:
            path=Path(mask['path'])
            if not path.is_file() or sha256(path)!=mask['sha256']:return False
            if mask['size']!=[p['geometry']['width'],p['geometry']['height']]:return False
        if ocr_cache is not None:
            ocr_cache[p['page']]=data
    return True


def masks_worker(job, stop, events, recalculate=False, base=BASE, local_session=None, local_folder=None):
    if not wait_opened(job,stop):return
    events.record('mask_preparation_start')
    if any(sha256(p['raw_original'])!=p['raw_sha256'] for p in job['pages']):
        raise TypeoError('Una RAW cambio antes de preparar las mascaras')
    base=Path(base)
    path=base/'config/limpieza_cache.json'
    cache=read_json(path) if path.exists() else {}
    cache.setdefault('paginas',{});engine=None
    cache_dirty=False;config_hashes={};ocr_cache={}
    local_active=job.get('cleaning_engine') in {'comic','hibrido'} and local_folder is not None
    local_manifest=None;rules={};created_local_session=False;ext_manifest=None
    if local_active:
        local_folder=Path(local_folder)
        local_manifest={'version':1,'motor':'comic','paginas':[]}
        rules_file=base/'config/zonas_genfill.json'
        if job.get('cleaning_engine')=='hibrido' and rules_file.exists():
            rules=read_json(rules_file)
        created_local_session=local_session is None
    elif job.get('external_clean'):
        ext_manifest=read_json(job['external_clean'])
    try:
        for page in job['pages']:
            if stop.is_set():return
            sidecar=base/'04_DIAGNOSTICO/mascaras_produccion'/page['stem']/'mascaras.json'
            valid=not recalculate and mask_cache_valid(cache,[page],config_hashes=config_hashes,ocr_cache=ocr_cache)
            if not recalculate and not valid and sidecar.exists():
                candidate=read_json(sidecar)
                valid=mask_cache_valid({'paginas':{page['page']:candidate}},[page],config_hashes=config_hashes,ocr_cache=ocr_cache)
                if valid:
                    cache['paginas'][page['page']]=candidate
                    cache_dirty=True
            changed=not valid
            if not valid:
                if engine is None:
                    from limpieza_rapida import MaskEngine
                    engine=MaskEngine(base)
                cache['paginas'][page['page']]=engine.page(page['raw'],base/'04_DIAGNOSTICO/mascaras_produccion'/page['stem'])
                cache_dirty=True
            if changed and not mask_cache_valid(cache,[page],config_hashes=config_hashes,ocr_cache=ocr_cache):raise TypeoError('Mascaras incompatibles con la RAW: '+page['page'])
            record=cache['paginas'][page['page']]
            ocr=ocr_cache.get(page['page']) or read_json(record['ocr']['path'])
            write_json(page['ocr_ready'],ocr)
            if job.get('auto_geometry'):
                from ocr_ingles import geometry_from_record
                generated=geometry_from_record(page['raw_original'],record,raw_hash=page['raw_sha256'])
                validate_geometry({'paginas':[generated]},base)
                write_json(page['geometry_ready'],generated)
            if local_active:
                from motores_abiertos import LocalInpainterSession,route_character_regions,validate_local_page
                stem=page['stem']
                reasons=[None]*len(record['pares'])
                rule=rules.get(page['page'])
                if rule and rule.get('raw_sha256')==page['raw_sha256'] and rule.get('zonas'):
                    routed_rec,reasons=route_character_regions(record,rule['zonas'],local_folder,stem)
                    record={**record,'pincel':routed_rec['pincel'],'genfill':routed_rec['genfill'],'pares':routed_rec['pares']}
                    routed_masks={key:routed_rec[key] for key in ('pincel','genfill','pares')}
                else:
                    routed_masks=None
                page_entry={'archivo':page['page'],'raw_sha256':page['raw_sha256'],'capas':[]}
                if routed_masks:
                    page_entry['mascaras_ruteadas']=routed_masks
                cases=[]
                for index,(mask,reason) in enumerate(zip(record['pares'],reasons)):
                    if not mask['nonempty']:continue
                    if reason is not None:
                        page_entry['capas'].append({'motor':'genfill','motivo':reason,'mascara_sha256':mask['sha256']})
                        print(f'[GENFILL] {page["page"]}: {reason}',flush=True)
                        continue
                    out_png=local_folder/f'{stem}_{index}.png'
                    cases.append({'id':f'{stem}_{index}','imagen':page['raw_original'],'mascara':mask['path'],'salida':str(out_png)})
                    page_entry['capas'].append({'path':str(out_png),'mascara_sha256':mask['sha256'],'mascara':mask['path']})
                if cases:
                    if local_session is None:
                        local_session=LocalInpainterSession('comic',local_folder)
                    infer_res=local_session.infer(cases,rgba=True)
                    sha_by_out={c['salida']:c['sha256'] for c in infer_res}
                    for layer in page_entry['capas']:
                        if layer.get('motor')!='genfill':
                            layer['sha256']=sha_by_out[layer['path']]
                local_manifest['paginas'].append(page_entry)
                write_json(local_folder/'capas.json',local_manifest)
            elif job.get('external_clean'):
                from motores_abiertos import manifest_page
                routed=manifest_page(job['external_clean'],page['raw_original'],manifest=ext_manifest,raw_hash=page['raw_sha256']).get('mascaras_ruteadas')
                if routed:
                    record={**record,**routed}
            target=Path(page['folder'])/'mascaras';target.mkdir(exist_ok=True)
            def copy_mask(mask,name):
                if not mask['nonempty']:return None
                mpath=target/name;shutil.copy2(mask['path'],mpath)
                if sha256(mpath)!=mask['sha256']:raise TypeoError('Mascara cambiada durante la copia')
                return mpath.as_posix() if mask['nonempty'] else None
            pincel=copy_mask(record['pincel'],'pincel.png')
            generativo=copy_mask(record['genfill'],'generativo.png')
            pairs=[copy_mask(m,f'par_{n+1}.png') for n,m in enumerate(record['pares'])]
            pairs=[p for p in pairs if p]
            if record['genfill']['nonempty'] and not pairs:raise TypeoError('Faltan pares generativos: '+page['page'])
            limits=[]
            if not job.get('external_clean') and not job.get('reuse_final') and job.get('reuse_masks',{}).get(page['page']):
                import cv2
                current=cv2.imread(record['genfill']['path'],0)
                for n,old in enumerate(job['reuse_masks'][page['page']]):
                    previous=cv2.imread(old,0)
                    if previous is None or current is None or previous.shape!=current.shape:raise TypeoError('Mascara anterior invalida: '+str(old))
                    bounded=previous&current
                    lpath=target/f'limite_{n+1}.png'
                    if not cv2.imwrite(str(lpath),bounded):raise TypeoError('No se pudo guardar '+str(lpath))
                    limits.append(lpath.as_posix())
            local_layers=[]
            if local_active:
                local_layers=validate_local_page(
                    job['external_clean'],page['raw_original'],pairs,
                    manifest=local_manifest,raw_hash=page['raw_sha256'],
                    raw_size=(page['geometry']['width'],page['geometry']['height']),
                )
            elif job.get('external_clean'):
                from motores_abiertos import validate_local_page
                local_layers=validate_local_page(
                    job['external_clean'],page['raw_original'],pairs,
                    manifest=ext_manifest,raw_hash=page['raw_sha256'],
                    raw_size=(page['geometry']['width'],page['geometry']['height']),
                )
            write_json(page['clean_ready'],{'job_id':job['job_id'],'page':page['page'],'pincel':pincel,'generativo':generativo,'pares':pairs,'limites_generativos':limits,'capas_generativas_mascaras':limits or pairs,
                'capas_locales':local_layers,
                'regiones_protegidas':[l['poligono'] for l in ocr.get('protegidos',[])],
                'arte_protegido':ocr.get('arte_protegido',[]),
                'repaso_fondos_ocr':[{**b['repaso_fondo'],'poligonos':[l['poligono'] for l in b['lineas_ocr']]} for b in ocr.get('bloques',[]) if b.get('repaso_fondo')]})
            events.record('mask_ready',page['page'],pairs=len(pairs))
        if local_active:
            events.record('local_clean_ready',engine=job['cleaning_engine'])
    finally:
        if cache_dirty:
            write_json(path,cache,compact=True)
        if local_active and local_session is not None:
            local_session.close()


def translation_worker(job, stop, events, *, guion=None, motor='nativo', base=BASE):
    if not wait_opened(job,stop):return
    base=Path(base)
    if guion:
        data=load_translation(guion);translated={p['archivo']:p for p in data['paginas']}
        if len(translated)!=len(data['paginas']):raise TypeoError('Pagina duplicada en el guion')
    elif motor=='nativo':
        import traducir_nativo_antigravity as native
        memory=native.inicializar_memoria()
    elif motor=='gemini':
        import traducir_capitulo_gemini as gemini
        client=None
    else:raise TypeoError('Proveedor de traduccion desconocido')
    contracts=[]
    for index,page in enumerate(job['pages']):
        if stop.is_set():return
        if job.get('auto_geometry'):
            while not Path(page['geometry_ready']).exists():
                if stop.wait(.02):return
            page['geometry']=read_json(page['geometry_ready'])
        events.record('translation_start',page['page'],provider='guion' if guion else motor)
        if job.get('auto_geometry') and not page['geometry']['zonas']:
            data={'version':1,'paginas':[{'archivo':page['page'],'bloques':[]}]}
        elif guion:
            if page['page'] not in translated:raise TypeoError('Falta pagina en el guion: '+page['page'])
            data={'version':1,'paginas':[translated[page['page']]]}
        elif motor=='nativo':
            data=parse_markdown(native.generar_tablas_markdown([page['page']],memory))
        else:
            if client is None:client=gemini.genai.Client()
            if job.get('auto_geometry'):
                ocr=read_json(page['ocr_ready'])
                hint={'geometry':{'archivo':page['page'],'zonas':[
                    {k:z.get(k) for k in ('id','texto_original','box_contenedor','tipo_texto','rol_revisado')} for z in page['geometry']['zonas']]},
                    'ocr':{'pendientes':[{k:l.get(k) for k in ('texto','confianza','box')} for l in ocr.get('pendientes',[])],
                           'zonas_sin_lectura':ocr.get('zonas_sin_lectura',[])}}
                translated_json=gemini.traducir_pagina(client,page['raw_original'],index+1,page['page'],ocr_page=hint)
                try:data=json.loads(translated_json)
                except ValueError as exc:raise TypeoError('El traductor no devolvio JSON OCR valido: '+page['page']) from exc
            else:data=parse_markdown(gemini.traducir_pagina(client,page['raw_original'],index+1,page['page']))
        geometry={'version':1,'paginas':[page['geometry']]}
        contract=bind_translation(data,geometry,base)
        if job.get('auto_geometry'):
            roles={b['id']:b['rol_fuente'] for b in contract['paginas'][0]['bloques']}
            for zone in geometry['paginas'][0]['zonas']:
                if roles.get(zone['id']) in {'cartel','pantalla','impreso'}:
                    zone.update({'tipo_contenedor':'rotulo','poligono_globo':None,'minimo_px':6,'margen_revision_px':1})
        events.record('translation_complete',page['page'])
        write_json(Path(page['folder'])/'contrato_traduccion.json',contract)
        items=build_items(contract,geometry)[0]['items']
        folder=Path(page['folder'])
        cfg={'page':page['page'],'job_id':job['job_id'],'input':page['raw'],
             'width':page['geometry']['width'],'height':page['geometry']['height'],
             'output':page['output'],'preview':None,
             'log':(folder/'typeo_ps.txt').as_posix(),'done':(folder/'EXITO.txt').as_posix(),
             'result':page['result'],'revision_log':(folder/'revision_typeo.json').as_posix(),
             'items':items,'reemplazar':job['replace']}
        cfg['revision_final_existente']=job.get('reuse_final',False)
        cfg['permitir_reemplazo_abierto']=job.get('allow_open_replacement',False)
        if Path(page['ocr_ready']).exists():
            source_ocr=read_json(page['ocr_ready'])
            cfg['regiones_protegidas']=[l['poligono'] for l in source_ocr.get('protegidos',[])]
            cfg['repaso_fondos']=[{**b['repaso_fondo'],'poligonos':[l['poligono'] for l in b['lineas_ocr']]} for b in source_ocr.get('bloques',[]) if b.get('repaso_fondo')]
        cfg['repaso_fondos']=cfg.get('repaso_fondos',[])+page['geometry'].get('repasos_limpieza',[])
        cfg['repaso_fondos_geometria']=page['geometry'].get('repasos_limpieza',[])
        write_json(page['typeo_ready'],cfg)
        events.record('typeo_inputs_ready',page['page'],texts=len(items))
        contracts.extend(contract['paginas'])
        print('[TRADUCCION] Lista para typeo: '+page['page'],flush=True)
        if not guion and motor=='nativo':native.actualizar_memoria(memory,[page['page']])
    write_json(Path(job['folder'])/'contrato_traduccion.json',{'version':1,'paginas':contracts})


def guarded_worker(function, job, stop, events, **kwargs):
    try:function(job,stop,events,**kwargs)
    except Exception as exc:
        write_json(job['worker_error'],{'job_id':job['job_id'],'status':'error','message':str(exc)})
        events.record('worker_error',message=str(exc));stop.set()


def verify_timeline(job):
    folder=Path(job['folder'])
    def events(name):
        return [json.loads(line) for line in (folder/name).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    native=events('eventos_photoshop.jsonl');workers=events('eventos_python.jsonl')
    def unique(records,stage,page=None):
        found=[r['time_ms'] for r in records if r['stage']==stage and r.get('page')==page]
        if len(found)!=1:raise TypeoError('Secuencia incompleta o repetida: '+stage+' '+str(page))
        return found[0]
    opened=unique(native,'pages_opened');previous=opened
    for page in job['pages']:
        name=page['page']
        clean_start=unique(native,'clean_start',name)
        clean_end=unique(native,'clean_complete',name)
        if job.get('clean_only'):
            complete=unique(native,'page_complete',name)
            if not opened<=clean_start<=clean_end<=complete:raise TypeoError('Orden de limpieza incorrecto: '+name)
            continue
        ready=unique(workers,'typeo_inputs_ready',name)
        type_start=unique(native,'typeo_start',name)
        complete=unique(native,'page_complete',name)
        translation=unique(workers,'translation_start',name)
        if not (opened<=translation<=ready and opened<=clean_start<=clean_end<=type_start<=complete and ready<=type_start and previous<=type_start):
            raise TypeoError('Orden de limpieza, traduccion, typeo o revision incorrecto: '+name)
        previous=complete
    return True


def finish_run(job):
    verify_timeline(job)
    if job.get('clean_only'):
        for page in job['pages']:
            state=read_json(page['result'])
            if state.get('job_id')!=job['job_id'] or state.get('status')!='complete':raise TypeoError('Estado de limpieza invalido')
            with Path(page['output']).open('rb') as f:
                if f.read(4)!=b'8BPS':raise TypeoError('PSD de limpieza invalido')
            if sha256(page['raw_original'])!=page['raw_sha256']:raise TypeoError('Original modificado')
        summary={'paginas':len(job['pages']),'capas_editables':0,'originales_sin_cambios':True,'fase':'limpieza'}
    else:
        configs=[read_json(p['typeo_ready']) for p in job['pages']]
        typeo_job={'job_id':job['job_id'],'pages':configs,
                   'original_sha256':{p['raw_original']:p['raw_sha256'] for p in job['pages']}}
        summary=verify_job(typeo_job)
    if list(Path(job['folder']).rglob('*.psd')):raise TypeoError('Se genero un PSD intermedio no permitido')
    clean_reports=[]
    for p in job['pages']:
        report=read_json(p['clean_report'])
        if report.get('status')!='complete' or not report.get('final_verified'):raise TypeoError('Limpieza incompleta: '+p['page'])
        clean_reports.append(report)
    summary.update({'un_psd_por_pagina':True,'psd_intermedios':0,'limpieza_revisada':True,'secuencia_verificada':True})
    job['status'],job['summary']='complete',summary
    write_json(Path(job['folder'])/'trabajo.json',job)
    final_state=Path(job['output'])/'estado_final.json'
    existing=read_json(final_state) if final_state.exists() else {}
    tracked={p['archivo']:{**p,'job_id':p.get('job_id',existing.get('job_id'))} for p in existing.get('paginas',[])}
    tracked.update({p['page']:{'archivo':p['page'],'psd':p['output'],'raw_sha256':p['raw_sha256'],'job_id':job['job_id']} for p in job['pages']})
    write_json(final_state,{'job_id':job['job_id'],'summary':summary,'paginas':list(tracked.values())})
    lines=['# Resultado: '+('limpieza' if job.get('clean_only') else 'limpieza, traduccion y typeo'),'',
           f'Ultima ejecucion: {summary["paginas"]} paginas; {summary["capas_editables"]} capas de texto editables. Un PSD final por pagina.','']
    for p in tracked.values():lines.append(f'- {p["archivo"]}: [PSD]({p["psd"]})')
    (Path(job['output'])/'RESULTADOS.md').write_text('\n'.join(lines),encoding='utf-8')
    return summary


def _should_prewarm_local_session(job, recalculate, base):
    if not job.get('pages') or recalculate:
        return bool(job.get('pages'))
    cache_path=Path(base)/'config/limpieza_cache.json'
    if not cache_path.exists():
        return True
    try:
        from limpieza_rapida import ENGINE_VERSION
        cache=read_json(cache_path).get('paginas',{})
    except (OSError,ValueError):
        return True
    rules={}
    if job.get('cleaning_engine')=='hibrido':
        rules_path=Path(base)/'config/zonas_genfill.json'
        if rules_path.exists():
            try:rules=read_json(rules_path)
            except (OSError,ValueError):return True
    for p in job['pages']:
        rec=cache.get(p['page'])
        if not rec or rec.get('engine_version')!=ENGINE_VERSION or rec.get('raw_sha256')!=p['raw_sha256']:
            return True
        if any(m.get('nonempty') for m in rec.get('pares',[])):
            return True
        rule=rules.get(p['page'])
        if rule and rule.get('raw_sha256')==p['raw_sha256'] and rule.get('zonas'):
            return True
    return False


def run(job, *, guion=None, motor='nativo', recalculate=False, timeout=1800, base=BASE):
    base=Path(base);folder=Path(job['folder']);events=Events(folder/'eventos_python.jsonl')
    lock=base/'02_TRABAJO_PSD/.typeo_photoshop.lock'
    try:handle=lock.open('x',encoding='utf-8')
    except FileExistsError as exc:raise TypeoError('Photoshop tiene otra ejecucion pendiente; revisar el bloqueo') from exc
    with handle:handle.write(str(folder/'trabajo.json'))
    release=True;stop=threading.Event();threads=[];dialog_monitor=None;local_session=None;local_folder=None
    try:
        if job.get('cleaning_engine') in {'comic','hibrido'}:
            engine=job['cleaning_engine']
            events.record('local_clean_start',engine=engine)
            local_folder=base/'04_DIAGNOSTICO/limpieza_local'/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
            local_folder.mkdir(parents=True,exist_ok=True)
            job['external_clean']=str((local_folder/'capas.json').resolve())
            if _should_prewarm_local_session(job,recalculate,base):
                from motores_abiertos import LocalInpainterSession
                local_session=LocalInpainterSession('comic',local_folder,timeout=timeout)
        renderer=(base/'scripts/typeo_ps.jsx').read_text(encoding='utf-8')
        controller=(base/'scripts/pipeline_ps.jsx').read_text(encoding='utf-8')
        queue=base/'scripts/cola_limpieza_ps.jsx'
        queue.write_text('#target photoshop\n'+renderer+'\n'+controller.replace('__PIPELINE__',json.dumps(job,ensure_ascii=True)),encoding='utf-8')
        workers=[(masks_worker,{'recalculate':recalculate,'base':base,'local_session':local_session,'local_folder':local_folder})]
        if not job.get('clean_only'):workers.append((translation_worker,{'guion':guion,'motor':motor,'base':base}))
        for fn,kwargs in workers:
            t=threading.Thread(target=guarded_worker,args=(fn,job,stop,events),kwargs=kwargs,daemon=True);t.start();threads.append(t)
        job['status']='running';write_json(folder/'trabajo.json',job)
        from auto_ok_photoshop import PhotoshopAutoDismisser
        dialog_monitor=PhotoshopAutoDismisser()
        dialog_monitor.start()
        events.record('photoshop_dispatch')
        subprocess.Popen([resolve_photoshop_exe(),'-r',str(queue)])
        release=False  # No liberar mientras Photoshop pueda seguir ejecutando una accion.
        start=time.monotonic();reported=set()
        while time.monotonic()-start<timeout:
            if Path(job['native_status']).exists():
                try:state=read_json(job['native_status'])
                except (OSError,ValueError):state={}
                if state.get('job_id')==job['job_id'] and state.get('status')=='error':
                    release=True;raise TypeoError(state.get('message','Error en Photoshop'))
                if state.get('job_id')==job['job_id'] and state.get('status')=='complete':
                    release=True
                    for t in threads:t.join(timeout=5)
                    summary=finish_run(job)
                    print('[COMPLETO] '+str(Path(job['output'])/'RESULTADOS.md'),flush=True)
                    return summary
            for p in job['pages']:
                if Path(p['result']).exists():
                    try:state=read_json(p['result'])
                    except (OSError,ValueError):continue
                    if state.get('job_id')!=job['job_id']:raise TypeoError('Estado de otra ejecucion')
                    if state.get('status')=='complete' and p['page'] not in reported:
                        try:clean=read_json(p['clean_report'])
                        except (ValueError,OSError):continue
                        if clean.get('final_verified'):
                            reported.add(p['page']);print('[FINAL] '+('Limpieza: ' if job.get('clean_only') else 'Limpieza + typeo + revision: ')+p['page'],flush=True)
            time.sleep(.05)
        Path(job['cancel']).write_text('Tiempo agotado; detener al terminar la operacion actual',encoding='utf-8')
        raise TypeoError('Tiempo agotado; Photoshop puede seguir terminando una accion. Revisar antes de liberar el bloqueo.')
    except Exception as exc:
        job['status'],job['error']='error',str(exc);write_json(folder/'trabajo.json',job);raise
    finally:
        stop.set()
        if local_session is not None:local_session.close()
        if dialog_monitor is not None:dialog_monitor.stop()
        if release:lock.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometria',type=Path,default=BASE/'config/typeo_geometria.json')
    parser.add_argument('--salida',type=Path,default=BASE/'09_PSD_FINAL')
    parser.add_argument('--guion',type=Path)
    parser.add_argument('--motor',choices=['nativo','gemini'],default='nativo')
    parser.add_argument('--paginas')
    parser.add_argument('--reemplazar',action='store_true')
    parser.add_argument('--recalcular-mascaras',action='store_true')
    cleaning=parser.add_mutually_exclusive_group()
    cleaning.add_argument('--limpieza-externa',type=Path,help='capas.json de motores_abiertos.py; valida RAW, mascaras y transparencia')
    cleaning.add_argument('--motor-limpieza',choices=['hibrido','genfill','comic'],
                          help='Hibrido por defecto. GenFill para zonas de personaje revisadas y LaMa para las demas')
    parser.add_argument('--preparar',action='store_true',help='Solo validar el plan; no abrir Photoshop')
    parser.add_argument('--solo-limpieza',action='store_true',help='Abrir y limpiar las RAW actuales sin traduccion ni geometria de typeo')
    parser.add_argument('--geometria-ocr',action='store_true',help='Usar coordenadas OCR actuales para globos, carteles y pantallas')
    parser.add_argument('--solo-revision-typeo',action='store_true',help='Actualizar el typeo del PSD final verificado, conservando su limpieza')
    parser.add_argument('--documento-preparado',type=Path,help='Retomar un documento preparado cuyo guardado se detuvo por cambios abiertos')
    parser.add_argument('--reemplazar-version-abierta',action='store_true',help='Autorizar expresamente sustituir la version abierta sin guardar del PSD seleccionado')
    parser.add_argument('--tiempo-maximo',type=int,default=1800)
    args=parser.parse_args(argv)
    if args.tiempo_maximo<=0:parser.error('El plazo debe ser positivo')
    if args.solo_revision_typeo and args.solo_limpieza:parser.error('La revision de typeo requiere el modo completo')
    if (args.limpieza_externa or args.motor_limpieza in {'comic','hibrido'}) and (args.solo_revision_typeo or args.documento_preparado):
        parser.error('La limpieza local requiere una ejecucion nueva')
    if args.limpieza_externa and args.recalcular_mascaras:
        parser.error('Regenerar primero las capas locales; no recalcular sus mascaras durante Photoshop')
    auto=args.geometria_ocr;pre_geometry=None
    if not args.solo_limpieza and not auto and args.geometria==BASE/'config/typeo_geometria.json':
        try:
            candidate=read_json(args.geometria)
            validate_geometry(candidate,BASE)
            pre_geometry=candidate
        except (TypeoError,FileNotFoundError):auto=True
    guion_path=args.guion
    if auto and not args.solo_limpieza and args.motor=='nativo' and not guion_path:
        candidate_guion=BASE/'03_TRADUCCIONES/guion_typeo.json'
        if candidate_guion.exists():guion_path=candidate_guion
        else:raise TypeoError('Capitulo nuevo: usar --guion con traduccion real, generar 03_TRADUCCIONES/guion_typeo.json con el skill traducir, o --motor gemini')
    job=prepare_run(args.geometria,args.salida,selected=args.paginas.split(',') if args.paginas else None,replace=args.reemplazar or args.solo_revision_typeo,
                    clean_only=args.solo_limpieza,auto_geometry=auto,reuse_final=args.solo_revision_typeo,pre_geometry=pre_geometry)
    job['allow_open_replacement']=args.reemplazar_version_abierta
    if not (args.limpieza_externa or args.solo_revision_typeo or args.documento_preparado):
        job['cleaning_engine']=args.motor_limpieza or 'hibrido'
    if args.limpieza_externa:
        from motores_abiertos import validate_local_page
        # Comprobar todo antes de abrir Photoshop, no descubrir una RAW incorrecta dentro del trabajador.
        for page in job['pages']:
            record=read_json(BASE/'04_DIAGNOSTICO/mascaras_produccion'/page['stem']/'mascaras.json')
            if not mask_cache_valid({'paginas':{page['page']:record}},[page]):
                raise TypeoError('Mascaras locales antiguas: regenerar con motores_abiertos.py limpieza')
            validate_local_page(args.limpieza_externa,page['raw_original'],[m['path'] for m in record['pares'] if m['nonempty']])
        job['external_clean']=str(args.limpieza_externa.resolve())
    if args.documento_preparado:
        source=args.documento_preparado.resolve();root=(BASE/'04_DIAGNOSTICO/pipeline').resolve()
        if root not in source.parents:raise TypeoError('El documento preparado no pertenece al flujo del proyecto')
        previous=read_json(source)
        if previous.get('status')!='error':
            raise TypeoError('El trabajo previo no esta detenido')
        prior_events=[json.loads(line) for line in Path(previous['native_events']).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        clean_pages={e.get('page') for e in prior_events if e.get('stage')=='clean_complete'}
        if any(p['page'] not in clean_pages for p in job['pages']):
            raise TypeoError('La limpieza anterior no termino en todas las paginas seleccionadas')
        job['prepared_inputs']={}
        for page in job['pages']:
            old=next((p for p in previous['pages'] if p['page']==page['page'] and p['raw_sha256']==page['raw_sha256'] and p['output']==page['output']),None)
            if not old:raise TypeoError('El documento preparado corresponde a otra RAW o salida')
            name='__raw_'+previous['job_id']+Path(old['raw']).suffix
            job['prepared_inputs'][page['page']]={'name':name,'path':str(Path(old['folder'])/name)}
            job['old_typeo_ids'][page['page']]=[i['id'] for i in read_json(old['typeo_ready'])['items']] if Path(old['typeo_ready']).exists() else []
    write_json(Path(job['folder'])/'trabajo.json',job)
    print('[COMPLETO] Preparado un unico PSD final por pagina: '+job['output'],flush=True)
    if not args.preparar:
        return run(job,guion=guion_path,motor=args.motor,recalculate=args.recalcular_mascaras,timeout=args.tiempo_maximo)
    return job


if __name__=='__main__':
    try:main()
    except TypeoError as exc:print('[COMPLETO] REQUIERE REVISION: '+str(exc),file=sys.stderr);raise SystemExit(2)
