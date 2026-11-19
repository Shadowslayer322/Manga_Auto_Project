"""Mascaras de produccion: una inferencia por pagina, sin comparativas ni previews."""
from __future__ import annotations
import argparse
from pathlib import Path
import time
import cv2
import numpy as np
from typeo_core import BASE,read_json,write_json,sha256,TypeoError

ENGINE_VERSION=9


def flat_white_background(gray,polygon):
    """Rechazar tramas de puntos aunque la mediana del fondo sea blanca."""
    inside=np.zeros_like(gray)
    cv2.fillPoly(inside,[np.asarray(polygon,dtype=np.int32)],255)
    inside=cv2.erode(inside,np.ones((5,5),np.uint8))
    if not inside.any() or np.median(gray[inside>0])<235:
        return False
    _,_,stats,_=cv2.connectedComponentsWithStats(((gray<170)&(inside>0)).astype(np.uint8))
    areas=stats[1:,cv2.CC_STAT_AREA]
    dots=areas[(areas>=2)&(areas<=25)]
    return not (len(dots)>30 and dots.sum()/max(1,np.count_nonzero(inside))>.002)


def white_container(gray, zone):
    polygon=zone.get('poligono_contenedor')
    if not polygon or (zone['origen']!='globo_solido_yolo' and not zone.get('fondo_plano_ocr')):
        return False
    x1,y1,x2,y2=zone['box_contenedor']
    return flat_white_background(gray[y1:y2,x1:x2],np.asarray(polygon,dtype=np.int32)-[x1,y1])


def route_masks(gray,mask,zones):
    white=np.zeros_like(mask);textured=np.zeros_like(mask)
    for zone in zones:
        flat=zone.get('fondo_limpieza_blanco')
        if flat is None:flat=white_container(gray,zone)
        polygon=zone.get('poligono_contenedor')
        if polygon:
            cv2.fillPoly(white if flat else textured,[np.asarray(polygon,dtype=np.int32)],255)
        zone['metodo_efectivo']='pincel_blanco' if flat else 'relleno_generativo'
    # Una falsa deteccion de globo puede cruzar el texto que va sobre dibujo.
    # La decision sobre el renglon prevalece en los pixeles que va a limpiar.
    from ocr_ingles import _text_area_roi
    for zone in zones:
        for polygon in zone.get('selecciones_fondo_complejo',[]):
            y1,y2,x1,x2,roi=_text_area_roi(gray.shape,polygon,8)
            if roi.size:
                textured[y1:y2,x1:x2]|=roi
    white &= cv2.bitwise_not(textured)
    return mask&white,mask&cv2.bitwise_not(white)


def save_page_masks(raw,output,zones,mask,seconds=0,expected_hash=None,ocr_info=None,*,gray=None):
    """Publicar las mascaras finales; reutilizable sin volver a inferir."""
    raw=Path(raw);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    source_hash=expected_hash or sha256(raw)
    if gray is None:
        gray=cv2.imread(str(raw),cv2.IMREAD_GRAYSCALE)
    brush,gen=route_masks(gray,mask,zones)
    png_params=[cv2.IMWRITE_PNG_COMPRESSION,1]
    def save(name,data):
        path=output/name
        if not cv2.imwrite(str(path),data,png_params):raise TypeoError('No se pudo guardar '+str(path))
        return signature(path,data)
    pincel=save('pincel.png',brush);generative=save('generativo.png',gen)
    pairs=[save(f'par_{n+1}.png',part) for n,part in enumerate(partition_mask(gen))]
    if sha256(raw)!=source_hash:raise TypeoError('La RAW cambio al publicar sus mascaras')
    record={'raw_sha256':source_hash,'engine_version':ENGINE_VERSION,'pincel':pincel,'genfill':generative,'pares':pairs,
            'zonas':zones,'seconds':round(seconds,3),
            'px_pincel':int(np.count_nonzero(brush)),'px_generativo':int(np.count_nonzero(gen))}
    if ocr_info is not None:record['ocr']=ocr_info
    write_json(output/'mascaras.json',record)
    used={Path(p['path']).name for p in pairs}
    for old in output.glob('par_*.png'):
        if old.stem[4:].isdigit() and old.name not in used:old.unlink()
    return record


def partition_mask(mask):
    """Agrupar por bloques de texto; nunca gastar llamadas por cada letra."""
    if not np.any(mask):return []
    from particionar_genfill_pares import agrupar_en_pares_cercanos
    joined=cv2.dilate(mask,cv2.getStructuringElement(cv2.MORPH_RECT,(25,55)))
    count,labels,stats,centers=cv2.connectedComponentsWithStats(joined)
    blocks=[{'centroid':tuple(centers[i]),'label_id':i} for i in range(1,count) if stats[i,cv2.CC_STAT_AREA]>100]
    result=[]
    fg=mask>0
    for group in agrupar_en_pares_cercanos(blocks):
        ids=[blocks[index]['label_id'] for index in group]
        if len(ids)==1:sel=labels==ids[0]
        elif len(ids)==2:sel=(labels==ids[0])|(labels==ids[1])
        else:sel=np.isin(labels,ids)
        result.append(np.where(sel&fg,255,0).astype(np.uint8))
    if not result:result=[mask.copy()]
    combined=np.zeros_like(mask)
    for item in result:combined|=item
    if not np.array_equal(combined,mask):raise TypeoError('La particion perdio pixeles de texto')
    return result


def signature(path,mask_data=None):
    path=Path(path);mask=mask_data if mask_data is not None else cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
    if mask is None:raise TypeoError('No se puede leer mascara: '+str(path))
    return {'path':path.resolve().as_posix(),'sha256':sha256(path),'size':[mask.shape[1],mask.shape[0]],'nonempty':bool(np.any(mask))}


class MaskEngine:
    def __init__(self,base=BASE):
        self.base=Path(base)
        self.yolo=None;self.session=None
        from ocr_ingles import EnglishOCR
        self.ocr=EnglishOCR(base)

    def _load_detection(self):
        if self.yolo is not None:return
        import os
        import onnxruntime as ort
        from ultralytics import YOLO
        self.yolo=YOLO(str(self.base/'models/bubbles_detect.pt'))
        so=ort.SessionOptions()
        so.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.inter_op_num_threads=1
        cpus=os.cpu_count() or 8
        so.intra_op_num_threads=max(2,cpus-min(4,max(2,cpus//3)))
        self.session=ort.InferenceSession(str(self.base/'models/comic-text-detector.onnx'),sess_options=so,providers=['CPUExecutionProvider'])

    def page(self,raw,output):
        raw=Path(raw);output=Path(output);output.mkdir(parents=True,exist_ok=True)
        start=time.monotonic();raw_hash=sha256(raw)
        cache_path=output/'mascaras.json';cached=read_json(cache_path) if cache_path.exists() else None
        img=cv2.imread(str(raw))
        if img is None:raise TypeoError('No se puede abrir RAW: '+str(raw))
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        pre_lines=None
        # Conservar las zonas y los IDs existentes. El OCR vuelve a construir
        # sus selecciones aun cuando la mascara anterior era solida.
        if cached and cached['raw_sha256']==raw_hash and cached.get('engine_version') in range(3,ENGINE_VERSION+1) and all(
                Path(cached[k]['path']).is_file() and sha256(cached[k]['path'])==cached[k]['sha256'] for k in ('pincel','genfill')):
            info={'zonas':cached['zonas']}
            mask=cv2.imread(cached['pincel']['path'],0)|cv2.imread(cached['genfill']['path'],0)
            ocr=self.ocr.page(raw,info['zonas'],img=img,raw_hash=raw_hash) if hasattr(self.ocr,'_read') else self.ocr.page(raw,info['zonas'])
        else:
            from concurrent.futures import ThreadPoolExecutor
            from pipeline_manga import procesar_pagina
            from prueba_segmentacion_pixel import procesar_mascara_pagina
            self._load_detection()
            h,w=img.shape[:2]
            def run_ctd():
                resized=cv2.resize(img,(1024,1024))
                inp=(resized.astype(np.float32)/255.0).transpose((2,0,1))[None,...]
                _,seg,det=self.session.run(None,{'images':inp})
                return cv2.resize(seg[0,0],(w,h)),cv2.resize(det[0,0],(w,h))
            def run_yolo():
                return self.yolo(img,conf=0.35,verbose=False)[0]
            with ThreadPoolExecutor(max_workers=3 if hasattr(self.ocr,'_read') else 2) as ex:
                f_ctd=ex.submit(run_ctd)
                f_yolo=ex.submit(run_yolo)
                f_ocr=ex.submit(self.ocr._read,img) if hasattr(self.ocr,'_read') else None
                seg,det=f_ctd.result()
                res_yolo=f_yolo.result()
                if f_ocr is not None:pre_lines=f_ocr.result()
            info,seg=procesar_pagina(str(raw),self.yolo,self.session,return_maps=True,img=img,pre_det_seg=(seg,det),pre_yolo=res_yolo)
            mask,_=procesar_mascara_pagina(str(raw),info,seg_map=seg,img=img)
            ocr=self.ocr.page(raw,info['zonas'],img=img,raw_hash=raw_hash,pre_lines=pre_lines) if hasattr(self.ocr,'_read') else self.ocr.page(raw,info['zonas'])
        from ocr_ingles import enrich_zones
        zones,mask,ocr=enrich_zones(raw,info['zonas'],mask,ocr,self.ocr.config,img=img,gray=gray)
        write_json(output/'ocr_ingles.json',ocr)
        if sha256(raw)!=raw_hash:raise TypeoError('La RAW cambio durante la deteccion')
        record=save_page_masks(raw,output,zones,mask,time.monotonic()-start,expected_hash=raw_hash,
                              ocr_info={'path':(output/'ocr_ingles.json').resolve().as_posix(),'sha256':sha256(output/'ocr_ingles.json')},
                              gray=gray)
        print(f'[LIMPIEZA] {raw.name}: {len(zones)} zonas, {len(record["pares"])} llamadas generativas; {record["seconds"]} s',flush=True)
        return record


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paginas',help='Nombres sin extension separados por coma')
    parser.add_argument('--salida',type=Path,default=BASE/'04_DIAGNOSTICO/mascaras_produccion')
    args=parser.parse_args(argv)
    selected=set(args.paginas.split(',')) if args.paginas else None
    raws=sorted(p for p in (BASE/'01_RAW').iterdir() if p.suffix.lower() in {'.png','.jpg','.jpeg','.webp'} and (selected is None or p.stem in selected))
    if not raws:raise TypeoError('No hay paginas seleccionadas')
    engine=MaskEngine();records={};start=time.monotonic()
    for raw in raws:records[raw.name]=engine.page(raw,args.salida/raw.stem)
    write_json(args.salida/'indice.json',{'version':ENGINE_VERSION,'paginas':records,'seconds':round(time.monotonic()-start,3)})
    path=BASE/'config/limpieza_cache.json'
    cache=read_json(path) if path.exists() else {'paginas':{}}
    cache['version']=ENGINE_VERSION;cache.setdefault('paginas',{}).update(records)
    write_json(path,cache,compact=True)
    pages=[]
    for name,record in records.items():
        ocr=read_json(record['ocr']['path'])
        pages.append({'archivo':name,'raw_sha256':record['raw_sha256'],**{k:ocr.get(k) for k in ('bloques','zonas_sin_lectura','pendientes')}})
    write_json(BASE/'03_TRADUCCIONES/ocr_capitulo.json',{'version':1,'idioma':'en','paginas':pages})


if __name__=='__main__':main()
