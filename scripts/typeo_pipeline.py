"""Integracion de traduccion, composicion y Photoshop con resultados verificables."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from typeo_core import BASE, TypeoError, bind_translation, build_items, load_translation, point_in_polygon, read_json, resolve_photoshop_exe, sha256, write_json


def prepare_job(guion, geometria, output_root=None, base=BASE, selected=None):
    base, guion, geometria = Path(base), Path(guion), Path(geometria)
    geometry, translation = read_json(geometria), load_translation(guion)
    if selected:
        keep = set(selected)
        known = {Path(p['archivo']).stem for p in geometry['paginas']}
        if not keep <= known:
            raise TypeoError('Paginas desconocidas: ' + ', '.join(sorted(keep-known)))
        geometry['paginas'] = [p for p in geometry['paginas'] if Path(p['archivo']).stem in keep]
        translation['paginas'] = [p for p in translation['paginas'] if Path(p['archivo']).stem in keep]
    contract = bind_translation(translation, geometry, base)
    pages = build_items(contract, geometry)
    output_root = (Path(output_root) if output_root else base/'08_RESULTADOS_TYPEO').resolve()
    # No permitir que una salida se confunda con un original o con los datos de entrada.
    target = output_root.resolve()
    for protected in ('01_RAW', '02_TRABAJO_PSD', '03_TRADUCCIONES', 'scripts', 'config'):
        if target == (base/protected).resolve() or (base/protected).resolve() in target.parents:
            raise TypeoError('La salida no puede estar dentro de ' + protected)
    for p in pages:
        clean = base/'02_TRABAJO_PSD'/(Path(p['archivo']).stem+'.psd')
        if not clean.is_file():
            raise TypeoError('Falta PSD limpio: ' + str(clean))
    job_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    folder = output_root/job_id
    folder.mkdir(parents=True)
    configs, hashes = [], {}
    for p in pages:
        name = Path(p['archivo']).stem
        sub = folder/name
        sub.mkdir()
        clean = base/'02_TRABAJO_PSD'/(name+'.psd')
        copied = sub/(name+'_BASE.psd')
        before = sha256(clean)
        shutil.copy2(clean, copied)
        if sha256(copied) != before or sha256(clean) != before:
            raise TypeoError('El PSD cambio mientras se copiaba: ' + str(clean))
        hashes[str(clean)] = before
        configs.append({'page': p['archivo'], 'job_id': job_id, 'width': p['width'], 'height': p['height'],
                        'input': copied.as_posix(), 'output': (sub/(name+'_TRADUCIDO.psd')).as_posix(),
                        'preview': (sub/(name+'_PREVIEW.jpg')).as_posix(),
                        'log': (sub/'typeo_ps.txt').as_posix(), 'done': (sub/'EXITO.txt').as_posix(),
                        'result': (sub/'estado.json').as_posix(),
                        'revision_log': (sub/'revision.json').as_posix(), 'items': p['items']})
    job = {'version': 1, 'job_id': job_id, 'status': 'prepared', 'folder': str(folder.resolve()),
           'guion': str(guion.resolve()), 'geometria': str(geometria.resolve()),
           'original_sha256': hashes, 'pages': configs}
    write_json(folder/'contrato_traduccion.json', contract)
    write_json(folder/'trabajo.json', job)
    renderer = (base/'scripts/typeo_ps.jsx').read_text(encoding='utf-8')
    wrapper = '''
var jobs=__JOBS__;
var failed=false;
for(var offset=0;offset<jobs.length&&!failed;offset+=50){
    var end=Math.min(offset+50,jobs.length);
    try{for(var p=offset;p<end;p++)app.open(new File(jobs[p].input));}
    catch(e){resultBatchError(e.message);failed=true;break;}
    for(var p=offset;p<end;p++){if(!renderTypeo(jobs[p])){failed=true;break;}}
}
'''.replace('__JOBS__', json.dumps(configs, ensure_ascii=True))
    # Si falla la apertura antes de un renderer, el monitor tambien debe enterarse.
    error_path = json.dumps((folder/'ERROR_LOTE.txt').as_posix())
    wrapper = ('function resultBatchError(t){var f=new File('+error_path+
               ');f.encoding="UTF8";f.open("w");f.write(t);f.close();}\n')+wrapper
    (folder/'typeo_lote.jsx').write_text('#target photoshop\n'+renderer+'\n'+wrapper, encoding='utf-8')
    return folder/'trabajo.json'


def verify_job(job):
    from PIL import Image
    count = 0
    for page in job['pages']:
        result = read_json(page['result'])
        if result.get('job_id') != job['job_id'] or result.get('status') != 'complete':
            raise TypeoError('Resultado de otra ejecucion o incompleto: ' + page['page'])
        path = Path(page['output'])
        with path.open('rb') as f:
            if f.read(4) != b'8BPS':
                raise TypeoError('PSD invalido: ' + str(path))
        if page.get('preview'):
            with Image.open(page['preview']) as im:
                im.verify()
        review = read_json(page['revision_log'])
        if len(review) != len(page['items']):
            raise TypeoError('Revision incompleta: ' + page['page'])
        for item, measure in zip(page['items'], review):
            if measure['id'] != item['id'] or measure['font'] != item['font_ps'] or 'myriad' in measure['font'].lower():
                raise TypeoError('Fuente o ID incorrecto: ' + item['id'])
            if not measure['editable'] or abs(measure['rotation']-item.get('rotacion',0))>.1 or max(measure['centerErrorPx']) > 1.1:
                raise TypeoError('Revision de texto fallida: ' + item['id'])
            if item.get('interlineado_ratio') and abs(measure.get('leadingPx',-1)/measure['sizePx']-item['interlineado_ratio'])>.001:
                raise TypeoError('Proporcion de interlineado incorrecta: '+item['id'])
            if 'box_contenedor' in item:
                b, box = measure['after'], item['box_contenedor']
                if b[0] < box[0]-1 or b[1] < box[1]-1 or b[2] > box[2]+1 or b[3] > box[3]+1:
                    raise TypeoError('Limites renderizados fuera del contenedor: '+item['id'])
                if not item.get('permite_fuera_panel_raw'):
                    for x, y in (measure['corners'] if item.get('rotacion') else ((b[0]-2,b[1]-2),(b[2]+2,b[1]-2),(b[2]+2,b[3]+2),(b[0]-2,b[3]+2))):
                        if not point_in_polygon(x,y,item['poligono_panel']):
                            raise TypeoError('Limites renderizados fuera del panel: '+item['id'])
        count += len(review)
    for source, digest in job['original_sha256'].items():
        if sha256(source) != digest:
            raise TypeoError('El PSD fuente cambio durante la ejecucion: ' + source)
    return {'paginas': len(job['pages']), 'capas_editables': count, 'originales_sin_cambios': True}


def dispatch_job(job_path, timeout=900, photoshop=None):
    """Invocado exclusivamente desde ejecutar_todo.py para controlar Photoshop."""
    job_path = Path(job_path).resolve()
    job = read_json(job_path)
    if job['status'] != 'prepared':
        raise TypeoError('El trabajo ya fue enviado o terminado; crear una ejecucion nueva')
    folder = job_path.parent
    if Path(job['folder']).resolve() != folder:
        raise TypeoError('Carpeta del trabajo inconsistente')
    for page in job['pages']:
        if any(not Path(page[key]).resolve().is_relative_to(folder)
               for key in ('input','output','preview','log','done','result','revision_log')):
            raise TypeoError('Una ruta del trabajo sale de su carpeta')
        if Path(page['output']).exists():
            raise TypeoError('Un resultado ya existe; no se sobrescribe')
    lock = BASE/'02_TRABAJO_PSD/.typeo_photoshop.lock'
    release_lock = True
    detener_monitor_dialogos = lambda: None
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError as exc:
        raise TypeoError('Hay otra ejecucion de typeo en Photoshop; revisar su estado antes de continuar') from exc
    try:
        from auto_ok_photoshop import iniciar_monitor_dialogos, detener_monitor_dialogos
        iniciar_monitor_dialogos()
        with handle:
            handle.write(str(job_path))
        queue = BASE/'scripts/cola_limpieza_ps.jsx'
        queue.write_text((folder/'typeo_lote.jsx').read_text(encoding='utf-8'), encoding='utf-8')
        exe = resolve_photoshop_exe(photoshop)
        job['status'] = 'running'
        write_json(job_path, job)
        # Photoshop puede devolver 1 al reenviar el comando a la instancia abierta.
        # El resultado real se toma de los informes por pagina, no de ese codigo.
        subprocess.Popen([str(exe), '-r', str(queue)])
        release_lock = False  # Ante tiempo agotado, Photoshop podria seguir trabajando.
        started, reported = time.monotonic(), set()
        while time.monotonic()-started < timeout:
            if (folder/'ERROR_LOTE.txt').exists():
                release_lock = True
                raise TypeoError((folder/'ERROR_LOTE.txt').read_text(encoding='utf-8-sig'))
            complete = 0
            for p in job['pages']:
                if not Path(p['result']).exists():
                    continue
                try:
                    state = read_json(p['result'])
                except (ValueError, OSError):
                    continue  # Escritura de estado aun en curso.
                if state.get('job_id') != job['job_id']:
                    raise TypeoError('Estado ajeno al trabajo actual')
                if state.get('status') == 'error':
                    release_lock = True
                    raise TypeoError(p['page']+': '+state.get('message', 'Error en Photoshop'))
                if state.get('status') == 'complete':
                    complete += 1
                    if p['page'] not in reported:
                        print('[TYPEO] Pagina revisada: '+p['page'], flush=True)
                        reported.add(p['page'])
            if complete == len(job['pages']):
                release_lock = True
                summary = verify_job(job)
                job['status'], job['summary'] = 'complete', summary
                write_json(job_path, job)
                write_json(folder/'verificacion_final.json', summary)
                index = ['# Traduccion y typeo revisados', '', f'{summary["paginas"]} paginas; {summary["capas_editables"]} capas editables sueltas.', '']
                for p in job['pages']:
                    index.append(f'- {p["page"]}: [PSD]({p["output"]}) | [Vista]({p["preview"]})')
                (folder/'RESULTADOS.md').write_text('\n'.join(index), encoding='utf-8')
                print('[TYPEO] COMPLETADO: '+str(folder), flush=True)
                return summary
            time.sleep(.5)
        raise TypeoError('Photoshop no termino dentro del plazo. Revisar sus avisos y el trabajo; no reenviar automaticamente')
    except Exception as exc:
        job['status'], job['error'] = 'error', str(exc)
        write_json(job_path, job)
        raise
    finally:
        detener_monitor_dialogos()
        # Solo se borra nuestro archivo de coordinacion, nunca un PSD ni una capa.
        if release_lock:
            lock.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guion', type=Path)
    parser.add_argument('--geometria', type=Path, default=BASE/'config/typeo_geometria.json')
    parser.add_argument('--salida', type=Path)
    parser.add_argument('--paginas', help='Identificadores separados por coma, por ejemplo 001,003')
    parser.add_argument('--preparar', action='store_true', help='Validar y componer sin abrir Photoshop')
    parser.add_argument('--traducir', action='store_true')
    parser.add_argument('--motor', choices=['nativo', 'gemini'], default='nativo')
    parser.add_argument('--tiempo-maximo', type=int, default=900)
    args = parser.parse_args(argv)
    if args.tiempo_maximo <= 0:
        parser.error('El tiempo maximo debe ser positivo')
    if args.traducir and args.guion:
        parser.error('Usar --guion para una traduccion existente o --traducir para generar una nueva')
    if args.traducir:
        script = 'traducir_nativo_antigravity.py' if args.motor == 'nativo' else 'traducir_capitulo_gemini.py'
        subprocess.run([sys.executable, str(BASE/'scripts'/script)], check=True)
    guion = args.guion
    if guion is None:
        guion = BASE/'03_TRADUCCIONES'/('traduccion_capitulo.md' if args.traducir and args.motor == 'gemini' else 'guion_traducciones.md')
        if not guion.exists():
            guion = BASE/'03_TRADUCCIONES/traduccion_capitulo.md'
    try:
        job_path = prepare_job(guion, args.geometria, args.salida, selected=args.paginas.split(',') if args.paginas else None)
        print('[TYPEO] Trabajo preparado: '+str(job_path), flush=True)
        if not args.preparar:
            subprocess.run([sys.executable, str(BASE/'scripts/ejecutar_todo.py'), '--despachar-typeo', str(job_path),
                            '--tiempo-maximo', str(args.tiempo_maximo)], check=True)
        return job_path
    except (TypeoError, FileNotFoundError, json.JSONDecodeError) as exc:
        print('[TYPEO] REQUIERE REVISION: '+str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc


if __name__ == '__main__':
    main()
