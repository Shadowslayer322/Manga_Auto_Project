"""OCR local de ingles, recuperacion selectiva y contrato comun para limpieza/typeo."""
from __future__ import annotations
import argparse
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import re
import math
import time
import unicodedata
import cv2
import numpy as np
from typeo_core import BASE,TypeoError,read_json,write_json,sha256
from text_policy import protected_reason

OCR_VERSION=3


def text_key(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC',text) if c.isalnum())


def box_of(poly):
    p=np.asarray(poly);return [float(p[:,0].min()),float(p[:,1].min()),float(p[:,0].max()),float(p[:,1].max())]


def coverage(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(1,(a[2]-a[0])*(a[3]-a[1]))


def polygon_overlap(a,b):
    p=np.asarray(a,dtype=np.float32);q=np.asarray(b,dtype=np.float32)
    area,_=cv2.intersectConvexConvex(p,q)
    return float(area)/max(1,cv2.contourArea(p)),float(area)/max(1,cv2.contourArea(q))


def valid_english(text,score,minimum):
    if score<minimum or not text.strip() or '\ufffd' in text:return False
    chars=[c for c in text if c.isalpha()]
    latin=[c for c in chars if 'LATIN' in unicodedata.name(c,'')]
    alpha_up=''.join(c.upper() for c in latin)
    if len(chars)==2 and len(latin)==2 and not any(c in 'AEIOUY' for c in alpha_up) and alpha_up not in {'HM','MM','SH','DR','MR','MS','VS','TV','PC','OK'}:
        return False
    if len(chars)>=2:return len(latin)/len(chars)>.95
    if len(chars)==1 and len(text.strip())>=2 and any(c in text for c in '.-…?!'):
        return len(latin)==1 and score>=minimum
    # Los mensajes pueden ser "I", "A", horas o numeros; evitar ruido aislado.
    if alpha_up in {'I','A'}:return score>=.96
    return not chars and len(re.sub(r'\D','',text))>=2 and score>=.96


def deduplicate(lines):
    kept=[]
    for line in sorted(lines,key=lambda x:x['confianza']+.003*min(40,len(text_key(x['texto']))),reverse=True):
        if any(min(polygon_overlap(line['poligono'],old['poligono']))>.55 or
               (text_key(line['texto']) in text_key(old['texto']) and polygon_overlap(line['poligono'],old['poligono'])[0]>.8) for old in kept):continue
        kept.append(line)
    return sorted(kept,key=lambda x:(round(x['box'][1]/8),x['box'][0]))


def paragraph_text(lines):
    # Agrupar palabras que comparten renglon antes de bajar a la siguiente linea.
    angles=[math.atan2(l['poligono'][1][1]-l['poligono'][0][1],l['poligono'][1][0]-l['poligono'][0][0]) for l in lines]
    angle=float(np.median(angles));c,s=math.cos(angle),math.sin(angle)
    projected=[]
    for line in lines:
        p=np.asarray(line['poligono']);x,y=p.mean(axis=0);height=float(np.linalg.norm(p[3]-p[0]))
        projected.append((c*x+s*y,-s*x+c*y,height,line))
    rows=[]
    for x,y,height,line in sorted(projected,key=lambda p:(p[1],p[0])):
        row=next((r for r in rows if abs(r['y']-y)<max(4,min(r['height'],height)*.45)),None)
        if row is None:row={'y':y,'height':height,'lines':[]};rows.append(row)
        row['lines'].append((x,line))
    return '\n'.join(' '.join(line['texto'] for _,line in sorted(row['lines'],key=lambda p:p[0])) for row in sorted(rows,key=lambda x:x['y']))


class EnglishOCR:
    def __init__(self,base=BASE):
        self.base=Path(base);self.config_path=self.base/'config/ocr_ingles.json';self.config=read_json(self.config_path)
        self.config_digest=sha256(self.config_path)
        model=self.base/self.config['modelo']
        if not model.is_file() or sha256(model)!=self.config['sha256']:
            raise TypeoError('Falta el modelo de OCR ingles verificado; ejecutar scripts/instalar_ocr_ingles.py')
        try:from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:raise TypeoError('Falta rapidocr_onnxruntime; instalar requirements-ocr.txt') from exc
        self.engine=RapidOCR(rec_model_path=str(model),text_score=.4,det_limit_side_len=self.config['lado_maximo'],
            det_limit_type='max',det_box_thresh=.35,intra_op_num_threads=4,inter_op_num_threads=1)

    def _read(self,image,offset=(0,0),scale=1,source='pagina'):
        result,_=self.engine(image,use_cls=False)
        h,w=image.shape[:2];lines=[]
        for poly,text,score in result or []:
            p=np.asarray(poly,dtype=float)/scale+np.asarray(offset)
            lines.append({'texto':unicodedata.normalize('NFKC',text).strip(),'confianza':float(score),
                          'poligono':p.tolist(),'box':box_of(p),'pasada':source})
        return lines

    def _deskew(self,image,lines):
        groups=[]
        for line in lines:
            p=line['poligono'];angle=math.degrees(math.atan2(p[1][1]-p[0][1],p[1][0]-p[0][0]))
            if not 7<abs(angle)<45 or len(text_key(line['texto']))<2:continue
            b=line['box']
            group=next((g for g in groups if abs(g['angle']-angle)<10 and
                max(0,max(g['box'][0],b[0])-min(g['box'][2],b[2]))<150 and
                max(0,max(g['box'][1],b[1])-min(g['box'][3],b[3]))<180),None)
            if group is None:groups.append({'box':list(b),'angle':angle,'angles':[angle]});continue
            group['box']=[min(b[0],group['box'][0]),min(b[1],group['box'][1]),max(b[2],group['box'][2]),max(b[3],group['box'][3])]
            group['angles'].append(angle);group['angle']=float(np.median(group['angles']))
        recovered=[]
        for group in groups[:min(2,self.config['max_recortes'])]:
            b=group['box'];pad=40;x1=max(0,int(b[0])-pad);y1=max(0,int(b[1])-pad)
            x2=min(image.shape[1],int(b[2])+pad);y2=min(image.shape[0],int(b[3])+pad)
            crop=image[y1:y2,x1:x2];h,w=crop.shape[:2]
            matrix=cv2.getRotationMatrix2D((w/2,h/2),group['angle'],1)
            c,s=abs(matrix[0,0]),abs(matrix[0,1]);nw=int(h*s+w*c)+2;nh=int(h*c+w*s)+2
            matrix[0,2]+=nw/2-w/2;matrix[1,2]+=nh/2-h/2
            rotated=cv2.warpAffine(crop,matrix,(nw,nh),borderValue=(255,255,255))
            inverse=cv2.invertAffineTransform(matrix)
            for line in self._read(rotated,source='enderezado_lectura'):
                poly=cv2.transform(np.asarray([line['poligono']],dtype=np.float32),inverse)[0]+[x1,y1]
                line['poligono']=poly.tolist();line['box']=box_of(poly);recovered.append(line)
        return recovered,len(groups[:2])

    def page(self,raw,zones,*,img=None,raw_hash=None,pre_lines=None):
        raw=Path(raw);digest=raw_hash or sha256(raw);image=img if img is not None else cv2.imread(str(raw))
        if image is None:raise TypeoError('No se puede abrir RAW para OCR: '+str(raw))
        start=time.monotonic();lines=[dict(l) for l in pre_lines] if pre_lines is not None else self._read(image)
        recovered,used=self._deskew(image,lines);lines.extend(recovered)
        # Reintentar solo zonas pequenas, vacias o dudosas; no cuatro inferencias
        # completas por pagina. Los recortes preservan el detalle nativo del objeto.
        retries=[]
        for zone in zones:
            if zone.get('no_procesar'):continue
            b=zone['box_contenedor'];found=[l for l in lines if coverage(l['box'],b)>.65]
            if not found or any(l['confianza']<self.config['confianza_minima'] or l['box'][3]-l['box'][1]<24 for l in found):
                retries.append(b)
        for b in retries[:max(0,self.config['max_recortes']-used)]:
            x1,y1,x2,y2=map(int,b);pad=8;x1=max(0,x1-pad);y1=max(0,y1-pad);x2=min(image.shape[1],x2+pad);y2=min(image.shape[0],y2+pad)
            crop=image[y1:y2,x1:x2]
            if crop.size and max(crop.shape[:2])<1200:
                lines.extend(self._read(cv2.resize(crop,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC),(x1,y1),2,'recorte_2x'))
        for line in lines:
            p=np.asarray(line['poligono']);p[:,0]=np.clip(p[:,0],0,image.shape[1]-1);p[:,1]=np.clip(p[:,1],0,image.shape[0]-1)
            line['poligono']=p.tolist();line['box']=box_of(p)
        lines=deduplicate(lines);accepted=[];pending=[];protected=[]
        for line in lines:
            reason=protected_reason(line['texto'])
            if reason and line['confianza']>=self.config['confianza_minima']:protected.append({**line,'motivo':reason})
            elif valid_english(line['texto'],line['confianza'],self.config['confianza_minima']):accepted.append(line)
            else:pending.append(line)
        if raw_hash is None and sha256(raw)!=digest:raise TypeoError('RAW cambiada durante el OCR')
        return {'version':OCR_VERSION,'raw_sha256':digest,'modelo_sha256':self.config['sha256'],
                'config_path':self.config_path.resolve().as_posix(),'config_sha256':self.config_digest,
                'lineas':accepted,'protegidos':protected,'pendientes':pending,'seconds':round(time.monotonic()-start,3)}


@lru_cache(maxsize=64)
def _ellipse_kernel(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1))


def expand_mask(mask, radius):
    if not radius:
        return mask
    return cv2.dilate(mask,_ellipse_kernel(radius))


def _glyph_crop(image,poly,padding_px=5):
    """Ajustar un renglon OCR a tinta y halo cercano dentro de su recorte local."""
    h,w=image.shape[:2]
    p=np.rint(poly).astype(np.int32)
    radius=max(0,min(12,int(padding_px)))
    room=max(3,radius)+2
    x1,y1,x2,y2=map(int,box_of(p))
    x1,y1=max(0,x1-room),max(0,y1-room)
    x2,y2=min(w,x2+room+1),min(h,y2+room+1)
    if x2<=x1 or y2<=y1:
        return 0,0,0,0,None
    crop=image[y1:y2,x1:x2]
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY) if crop.ndim==3 else crop
    area=np.zeros_like(gray)
    cv2.fillPoly(area,[p-[x1,y1]],255)
    interior=gray[area>0]
    if not interior.size:
        return 0,0,0,0,None
    oriented=gray if np.median(interior)>=128 else 255-gray
    threshold,_=cv2.threshold(oriented[area>0],0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    ink=((oriented<=np.clip(threshold,70,170))&(expand_mask(area,2)>0)).astype(np.uint8)*255
    height=max(1,np.linalg.norm(p[3]-p[0]))
    core=cv2.morphologyEx(ink,cv2.MORPH_OPEN,_ellipse_kernel(1)) if height>=24 else ink
    _,labels,stats,_=cv2.connectedComponentsWithStats(core)
    widths,heights,sizes=stats[:,2:].T
    valid=(heights>=max(3,height*.18))&(heights<=height*1.4)&(widths<=height*2.3)&(sizes>=8)
    valid[0]=False
    selected=valid[labels].astype(np.uint8)*255
    if selected.any():
        # Recover antialiased edges and separated punctuation near the glyphs.
        selected=expand_mask(selected,1)&ink
        _,labels,stats,_=cv2.connectedComponentsWithStats(ink&~selected)
        near=expand_mask(selected,max(2,round(height*.32)))>0
        nearby_ids=np.unique(labels[near])
        widths,heights,sizes=stats[:,2:].T
        punctuation=(sizes>=7)&(widths>=3)&(heights>=3)&(widths<=height*.65)&(heights<=height*.42)
        punctuation[0]=False
        selected|=(np.isin(labels,nearby_ids)&punctuation[labels]).astype(np.uint8)*255
    return y1,y2,x1,x2,expand_mask(selected,radius)


def glyph_mask(image,poly,padding_px=5):
    """Ajustar un renglon OCR a tinta y halo cercano sin rellenar su fondo."""
    h,w=image.shape[:2]
    output=np.zeros((h,w),np.uint8)
    y1,y2,x1,x2,crop_mask=_glyph_crop(image,poly,padding_px)
    if crop_mask is not None:
        output[y1:y2,x1:x2]=crop_mask
    return output


def reviewed_glyph_selection(gray,selection):
    """Extraer las letras de un titulo revisado con parametros ligados a su RAW."""
    x1,y1,x2,y2=selection['rectangulo']
    radius=selection['margen_px']
    ink=(gray[y1:y2,x1:x2]<selection['umbral']).astype(np.uint8)*255
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
    core=cv2.morphologyEx(ink,cv2.MORPH_OPEN,kernel)
    _,labels,stats,_=cv2.connectedComponentsWithStats(core)
    widths,heights,sizes=stats[:,2:].T
    valid=(heights>=selection['alto_minimo'])&(widths<=selection['ancho_maximo'])&(sizes>=selection['area_minima'])
    valid[0]=False
    output=np.zeros_like(gray)
    output[y1:y2,x1:x2]=valid[labels].astype(np.uint8)*255
    if not output.any():
        raise TypeoError('Seleccion de letras revisada sin trazos')
    return expand_mask(output,radius)


def proposed_context(text,existing=None,override=None):
    if override:return override
    # La decision semantica definitiva puede venir del proveedor visual o de una
    # zona revisada. Una forma rectangular por si sola no demuestra que sea movil.
    if re.search(r'\b\d{1,2}:\d{2}\b',text) or re.fullmatch(r'\s*(messages?|delivered|typing|send|sent|battery|wifi|inbox)[.!…: ]*',text,re.I):return 'pantalla'
    if re.match(r'^\s*(sign|notice|poster|label|warning)\s*:',text,re.I):return 'cartel'
    if existing:return existing.get('tipo_texto','dialogo')
    return 'texto_escena'


def _text_area_roi(shape,poly,padding_px=6):
    """Generar mascara solida de un renglon dentro de su ROI minimo."""
    h,w=shape[:2]
    p=np.rint(np.asarray(poly)).astype(np.int32)
    radius=max(0,min(32,int(padding_px)))
    x1=max(0,int(p[:,0].min())-radius);y1=max(0,int(p[:,1].min())-radius)
    x2=min(w,int(p[:,0].max())+1+radius);y2=min(h,int(p[:,1].max())+1+radius)
    if x2<=x1 or y2<=y1:
        return 0,0,0,0,np.zeros((0,0),dtype=np.uint8)
    roi=np.zeros((y2-y1,x2-x1),dtype=np.uint8)
    cv2.fillPoly(roi,[p-[x1,y1]],255)
    return y1,y2,x1,x2,expand_mask(roi,radius)


def text_area_mask(image,poly,padding_px=6):
    """Seleccion solida por renglon: incluye letras, huecos y espacio interior.

    Conservar el cuadrilatero OCR evita convertir una linea diagonal en una
    gran caja horizontal. La proteccion de SFX/horas se aplica despues.
    """
    area=np.zeros(image.shape[:2],dtype=np.uint8)
    y1,y2,x1,x2,roi=_text_area_roi(image.shape,poly,padding_px)
    if roi.size:
        area[y1:y2,x1:x2]=roi
    return area


def _is_english_page(lines,zones):
    if not zones or any(z.get('origen')=='ocr_ingles' for z in zones):
        return True
    alpha_lines=[l for l in lines if len(re.findall(r'[A-Za-z]{2,}',l.get('texto','')))>=1 and l.get('confianza',0)>=0.80]
    spaced=sum(1 for l in alpha_lines if ' ' in l.get('texto','').strip())
    strong=sum(1 for l in alpha_lines if len(re.findall(r'[A-Za-z]{3,}',l.get('texto','')))>=1 and l.get('confianza',0)>=0.88)
    return spaced>=2 or len(alpha_lines)>=5 or strong>=2


def _flat_zone_ink_mask(gray,zone,line_polys,base_mask,text_margin=6):
    """Extraer tinta y puntuacion adyacente dentro de un contenedor blanco sin tocar sus bordes."""
    h,w=gray.shape[:2]
    bx_orig=list(map(int,zone['box_contenedor']))
    x1,y1,x2,y2=bx_orig
    for r in zone.get('rectangulos_texto',[]):
        x1=min(x1,int(r[0]));y1=min(y1,int(r[1]));x2=max(x2,int(r[2]));y2=max(y2,int(r[3]))
    for poly in line_polys:
        bx1,by1,bx2,by2=map(int,box_of(poly))
        x1=min(x1,bx1);y1=min(y1,by1);x2=max(x2,bx2);y2=max(y2,by2)
    pad=28
    wx1,wy1=max(0,x1-pad),max(0,y1-pad)
    wx2,wy2=min(w,x2+pad),min(h,y2+pad)
    if wx2<=wx1 or wy2<=wy1:
        return 0,0,0,0,np.zeros((0,0),dtype=np.uint8)
    sub=gray[wy1:wy2,wx1:wx2]
    sh,sw=sub.shape
    seed=np.zeros((sh,sw),dtype=np.uint8)
    lines_hull=np.zeros((sh,sw),dtype=np.uint8)
    poly_inner=np.zeros((sh,sw),dtype=np.uint8)
    has_dark=bool(np.any(sub<225))
    for poly in line_polys:
        local_poly=np.asarray(poly,dtype=np.float32)-[wx1,wy1]
        ry1,ry2,rx1,rx2,broi=_text_area_roi(sub.shape,local_poly,3)
        if broi.size:lines_hull[ry1:ry2,rx1:rx2]|=broi
        p_int=np.rint(local_poly).astype(np.int32)
        p_mask=np.zeros((sh,sw),dtype=np.uint8)
        cv2.fillPoly(p_mask,[p_int],255)
        poly_inner|=cv2.erode(p_mask,np.ones((3,1),dtype=np.uint8))
        if has_dark:
            gy1,gy2,gx1,gx2,groi=_glyph_crop(sub,local_poly,3)
            if groi is not None and groi.any():
                # Strip any light-gray sparkle component (min gray >= 155) inside groi
                g_sub=sub[gy1:gy2,gx1:gx2]
                n_g,g_lbl,_,_=cv2.connectedComponentsWithStats((groi>0).astype(np.uint8))
                for gid in range(1,n_g):
                    g_comp=(g_lbl==gid)
                    if int(g_sub[g_comp].min())<155:
                        seed[gy1:gy2,gx1:gx2][g_comp]=255
                if zone.get('origen')=='ocr_ingles':
                    raw_ink=((sub<165)&(poly_inner>0)).astype(np.uint8)*255
                    if raw_ink.any():seed|=expand_mask(raw_ink,2)
                continue
        ry1,ry2,rx1,rx2,broi=_text_area_roi(sub.shape,local_poly,min(3,text_margin) if has_dark else text_margin)
        if broi.size:
            if has_dark:
                ink_b=((sub[ry1:ry2,rx1:rx2]<205)&(broi>0)).astype(np.uint8)*255
                if ink_b.any():
                    seed[ry1:ry2,rx1:rx2]|=expand_mask(ink_b,2)
                    continue
            seed[ry1:ry2,rx1:rx2]|=broi
    if zone.get('origen')=='globo_solido_yolo' and has_dark:
        b_sub=base_mask[wy1:wy2,wx1:wx2]
        if np.any(b_sub):
            near_hull=expand_mask(lines_hull,22)>0 if np.any(lines_hull) else np.ones((sh,sw),dtype=bool)
            n_b,b_lbl,b_stats,_=cv2.connectedComponentsWithStats((b_sub>0).astype(np.uint8))
            for bid in range(1,n_b):
                b_comp=(b_lbl==bid)
                if np.any(b_comp&near_hull) and int(sub[b_comp].min())<175:
                    seed[b_comp]=255
    if not has_dark or not seed.any():
        return wy1,wy2,wx1,wx2,seed
    seed_core=cv2.erode(seed,np.ones((3,3),np.uint8)) if np.any(seed) else seed
    dark=cv2.morphologyEx(((sub<222)&(seed_core==0)).astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    n_cc,lbl,stats,_=cv2.connectedComponentsWithStats(dark)
    border_ids=set()
    border_ids.update(np.unique(lbl[0,:]));border_ids.update(np.unique(lbl[-1,:]))
    border_ids.update(np.unique(lbl[:,0]));border_ids.update(np.unique(lbl[:,-1]))
    pcont_eroded=None
    if zone.get('poligono_contenedor') and zone.get('origen')=='globo_solido_yolo':
        pcont=np.zeros((sh,sw),dtype=np.uint8)
        cv2.fillPoly(pcont,[np.asarray(zone['poligono_contenedor'],dtype=np.int32)-[wx1,wy1]],255)
        pcont_eroded=cv2.erode(pcont,np.ones((3,3),np.uint8))
        border_ids.update(np.unique(lbl[pcont_eroded==0]))
    hull_outer=expand_mask(lines_hull,10)==0 if np.any(lines_hull) else np.zeros((sh,sw),dtype=bool)
    outer_ids=set(np.unique(lbl[hull_outer]))
    zw,zh=max(1,x2-x1),max(1,y2-y1)
    wall_keep=np.zeros(n_cc,dtype=bool)
    for cid in range(1,n_cc):
        cw_c=int(stats[cid,cv2.CC_STAT_WIDTH])
        ch_c=int(stats[cid,cv2.CC_STAT_HEIGHT])
        c_area=int(stats[cid,cv2.CC_STAT_AREA])
        c_mask=(lbl==cid)
        seed_ov=int(np.count_nonzero(c_mask&(seed_core>0)))
        in_hull=int(np.count_nonzero(c_mask&(lines_hull>0)))
        if cid in border_ids and seed_ov<0.35*c_area:
            wall_keep[cid]=True
        elif cid in outer_ids and in_hull<0.55*c_area and c_area>=90:
            wall_keep[cid]=True
        elif cw_c>=0.70*zw and ch_c>=0.70*zh and seed_ov<0.25*c_area:
            wall_keep[cid]=True
        elif max(cw_c,ch_c)>=0.88*max(zw,zh) and c_area>=360 and seed_ov<0.15*c_area:
            wall_keep[cid]=True
    wall=wall_keep[lbl].astype(np.uint8)*255
    # Strip wall pixels (excluding interior of OCR lines for room labels like Bathroom/Washroom)
    wall_clip=cv2.dilate(wall,np.ones((5,5),np.uint8))
    if zone.get('origen')=='ocr_ingles':
        wall_clip=cv2.dilate(wall&cv2.bitwise_not(poly_inner),np.ones((3,3),np.uint8))
    seed&=cv2.bitwise_not(wall_clip)
    glyph_seed=seed.copy()
    wall_buf=cv2.dilate(wall,np.ones((5,5),np.uint8))
    free=(wall_buf==0).astype(np.uint8)
    if pcont_eroded is not None:
        free&=(pcont_eroded>0).astype(np.uint8)
    n_f,flbl,_,_=cv2.connectedComponentsWithStats(free)
    seed_fids=np.unique(flbl[(seed>0)&(free>0)])
    seed_fids=seed_fids[seed_fids>0]
    if len(seed_fids):
        interior=np.isin(flbl,seed_fids)
        cand_ink=(sub<205)&interior&(~wall_keep[lbl])
        if np.any(cand_ink):
            n_ik,ik_lbl,ik_stats,_=cv2.connectedComponentsWithStats(cand_ink.astype(np.uint8))
            reach_inline=cv2.dilate(seed,cv2.getStructuringElement(cv2.MORPH_RECT,(35,13)))>0
            reach_near=expand_mask(seed,24)>0
            reach_vert=cv2.dilate(seed,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(35,115)))>0
            sy,sx=np.where(seed>0)
            s_xmin,s_xmax=int(sx.min()),int(sx.max())
            text_priors=np.zeros((sh,sw),dtype=bool)
            for r in zone.get('rectangulos_texto',[]):
                rx1,ry1=max(0,int(r[0])-wx1-18),max(0,int(r[1])-wy1-18)
                rx2,ry2=min(sw,int(r[2])-wx1+18),min(sh,int(r[3])-wy1+18)
                text_priors[ry1:ry2,rx1:rx2]=True
            for poly in line_polys:
                pb=box_of(poly)
                rx1,ry1=max(0,int(pb[0])-wx1-26),max(0,int(pb[1])-wy1-26)
                rx2,ry2=min(sw,int(pb[2])-wx1+26),min(sh,int(pb[3])-wy1+26)
                text_priors[ry1:ry2,rx1:rx2]=True
            dot_cands=[]
            for iid in range(1,n_ik):
                ix,iy,iw,ih,ia=[int(v) for v in ik_stats[iid]]
                if 3<=ia<=185 and iw<=26 and ih<=26 and (ix>=s_xmin-16) and (ix+iw<=s_xmax+18):
                    if np.any(reach_vert&(ik_lbl==iid)):
                        dot_cands.append((iid,ix,iy,iw,ih))
            collinear_dots=set()
            for idx_a,(iid_a,xa,ya,wa,ha) in enumerate(dot_cands):
                for iid_b,xb,yb,wb,hb in dot_cands[idx_a+1:]:
                    gap=max(xa-(xb+wb),xb-(xa+wa))
                    if abs((ya+ha/2)-(yb+hb/2))<=6 and -2<=gap<=28:
                        collinear_dots.add(iid_a);collinear_dots.add(iid_b)
            ik_keep=np.zeros(n_ik,dtype=bool)
            for iid in range(1,n_ik):
                ix,iy,iw,ih,ia=[int(v) for v in ik_stats[iid]]
                imask=(ik_lbl==iid)
                if iid in collinear_dots:
                    ik_keep[iid]=True
                elif 3<=ia<=200 and iw<=28 and ih<=28 and np.any(reach_inline&imask):
                    ik_keep[iid]=True
                elif pcont_eroded is not None and 200<ia<=6500 and ih<=190 and iw<=220:
                    if np.any(reach_near&imask) and np.any(text_priors&imask):
                        ik_keep[iid]=True
            if np.any(ik_keep):
                rec=expand_mask(ik_keep[ik_lbl].astype(np.uint8)*255,2)
                reach2=cv2.dilate(seed|rec,cv2.getStructuringElement(cv2.MORPH_RECT,(31,11)))>0
                for iid in range(1,n_ik):
                    if not ik_keep[iid]:
                        ix,iy,iw,ih,ia=[int(v) for v in ik_stats[iid]]
                        imask=(ik_lbl==iid)
                        if 3<=ia<=200 and iw<=28 and ih<=28 and np.any(reach2&imask):
                            ik_keep[iid]=True
                        elif pcont_eroded is not None and 200<ia<=6500 and np.any(expand_mask(seed|rec,18)>0&imask) and np.any(text_priors&imask):
                            ik_keep[iid]=True
                rec=expand_mask(ik_keep[ik_lbl].astype(np.uint8)*255,2)&(interior.astype(np.uint8)*255)
                seed=(glyph_seed&cv2.bitwise_not(wall_clip))|rec
            else:
                seed=glyph_seed&cv2.bitwise_not(wall_clip)
        else:
            seed=glyph_seed&cv2.bitwise_not(wall_clip)
    from prueba_segmentacion_pixel import parchar_huecos_mascara
    seed=parchar_huecos_mascara(seed,max_hole_area=2500)
    seed&=cv2.bitwise_not(wall_clip)
    return wy1,wy2,wx1,wx2,seed


def enrich_zones(raw,zones,mask,ocr,config,*,img=None,gray=None):
    """Enlazar por posicion, anadir ingles omitido y preservar IDs de la limpieza."""
    from limpieza_rapida import white_container

    if gray is None:
        image=img if img is not None else cv2.imread(str(raw))
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    h,w=gray.shape[:2]
    result=deepcopy(zones)
    for zone in result:
        zone['poligonos_ocr']=[]
        for key in ('alias_ocr','texto_original','ocr_id','rol_propuesto','no_procesar',
                    'fondo_limpieza_blanco','selecciones_fondo_complejo'):zone.pop(key,None)
    grouped={z['id']:[] for z in result};next_id=max(grouped,default=0)+1
    reviewed=config.get('zonas_revisadas',{})
    overrides=reviewed.get(ocr.get('raw_sha256')) or reviewed.get(Path(raw).name,{})
    if overrides and overrides.get('raw_sha256')!=ocr['raw_sha256']:raise TypeoError('Revision OCR de otra RAW')
    cleaning_review=config.get('limpieza_revisada',{}).get(ocr.get('raw_sha256'),{})
    active=[];protected=[]
    candidates=ocr['lineas']+ocr.get('protegidos',[])
    english_page=_is_english_page(candidates,result)
    if english_page and ocr.get('pendientes'):
        kept_pending=[]
        backed_zones=[z for z in result if any(coverage(l['box'],z['box_contenedor'])>=0.55 for l in ocr['lineas'])]
        for pline in ocr['pendientes']:
            ptxt=pline.get('texto','').strip()
            pconf=pline.get('confianza',0)
            preason=protected_reason(ptxt)
            alpha_only=re.sub(r'[^A-Za-z]','',ptxt)
            is_clean_word=bool(re.fullmatch(r"[A-Za-z'.…?!]+",ptxt) and valid_english(ptxt,pconf,0.72) and (len(alpha_only)>=2 or alpha_only.upper()=='I'))
            is_punct=bool(re.fullmatch(r'[.…?!]+',ptxt))
            in_backed_bubble=any(coverage(pline['box'],z['box_contenedor'])>=0.65 and (
                z.get('origen')=='globo_solido_yolo' or float(np.mean(gray[z['box_contenedor'][1]:z['box_contenedor'][3],z['box_contenedor'][0]:z['box_contenedor'][2]]>=245))>=0.70
            ) for z in backed_zones)
            if pconf>=0.72 and in_backed_bubble and (is_clean_word or is_punct) and (not preason or preason=='signo_aislado'):
                candidates.append(pline)
            else:
                kept_pending.append(pline)
        ocr['pendientes']=kept_pending
    ordinary=[l for l in candidates if not protected_reason(l['texto'])]
    for line in candidates:
        reason=protected_reason(line['texto'])
        # Un numero o signo en una frase no es un elemento aislado. Mantenerlo
        # con su parrafo si comparte zona y renglon/columna con las palabras.
        attached=False
        if reason in {'numero_aislado','signo_aislado'}:
            for zone in result:
                if coverage(line['box'],zone['box_contenedor'])<.5:continue
                if reason=='signo_aislado':
                    attached=any(coverage(other['box'],zone['box_contenedor'])>=.5 for other in ordinary)
                else:
                    attached=any(coverage(other['box'],zone['box_contenedor'])>.6 and
                        max(0,max(line['box'][1],other['box'][1])-min(line['box'][3],other['box'][3]))<max(12,2*(other['box'][3]-other['box'][1])) for other in ordinary)
                if attached:break
        if reason and not attached:protected.append({**line,'motivo':reason})
        else:active.append(line)
    ocr['lineas']=active;ocr['protegidos']=protected
    for line in active:
        if not english_page and not overrides:break
        candidates=[(coverage(line['box'],z['box_contenedor']),z.get('origen')=='globo_solido_yolo',-max(1,(z['box_contenedor'][2]-z['box_contenedor'][0])*(z['box_contenedor'][3]-z['box_contenedor'][1])),z) for z in result]
        score,_,_,zone=max(candidates,key=lambda x:(round(x[0],2),x[1],x[2])) if candidates else (0,False,0,None)
        if score<.65:
            if not english_page:continue
            if line['confianza']<config['confianza_nueva_zona']:
                ocr['pendientes'].append({**line,'motivo':'zona nueva con confianza insuficiente'});continue
            x1,y1,x2,y2=map(int,line['box']);pad=6
            box=[max(0,x1-pad),max(0,y1-pad),min(w,x2+pad),min(h,y2+pad)]
            crop=gray[box[1]:box[3],box[0]:box[2]]
            lh=float(np.linalg.norm(np.asarray(line['poligono'])[3]-np.asarray(line['poligono'])[0]))
            is_white_crop=bool(crop.size and ((np.mean(crop>=245)>=0.65 and np.percentile(crop,25)>=240) or (np.mean(crop>=245)>=0.42 and np.mean((crop>=60)&(crop<=235))<0.09)))
            if len(text_key(line['texto']))<2 or (lh>85 and not is_white_crop):
                ocr['pendientes'].append({**line,'motivo':'zona nueva descartada por tamano o fragmento'});continue
            zone={'id':next_id,'origen':'ocr_ingles','tipo':'relleno_generativo','box_contenedor':box,
                  'rectangulos_texto':[[x1,y1,x2,y2]],'orientacion':'horizontal','poligonos_ocr':[]}
            # No llamar globo a un cartel: blanco uniforme es un metodo de limpieza.
            if (np.mean(crop>225)>.65 and np.median(crop)>235) or is_white_crop:
                zone['fondo_plano_ocr']=True
                zone['poligono_contenedor']=[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]]
            result.append(zone);grouped[next_id]=[];next_id+=1
        grouped[zone['id']].append(line)
        zone.setdefault('poligonos_ocr',[]).append(line['poligono'])
    blocks=[]
    # Un detector puede haber partido una hora/etiqueta en dos zonas. Si una
    # zona vacia esta contenida en una linea ya leida, enlazarla en lugar de
    # pedir una segunda traduccion del mismo texto.
    for zone in result:
        if grouped[zone['id']]:continue
        hits=[l for l in protected if coverage(l['box'],zone['box_contenedor'])>.35 or coverage(zone['box_contenedor'],l['box'])>.35]
        if hits and english_page:
            zone['no_procesar']=hits[0]['motivo'];zone['texto_original']=paragraph_text(hits)
            zone['ocr_id']=Path(raw).stem+f'_{zone["id"]:02d}'
            continue
        area=(zone['box_contenedor'][2]-zone['box_contenedor'][0])*(zone['box_contenedor'][3]-zone['box_contenedor'][1])
        for other in result:
            if other is zone or not grouped[other['id']]:continue
            found=next((l for l in grouped[other['id']] if coverage(zone['box_contenedor'],l['box'])>.65 and
                area<(l['box'][2]-l['box'][0])*(l['box'][3]-l['box'][1])*.95),None)
            if found or coverage(zone['box_contenedor'],other['box_contenedor'])>=0.60:
                zone['alias_ocr']=Path(raw).stem+f'_{other["id"]:02d}';break
        if english_page and not zone.get('no_procesar') and not zone.get('alias_ocr'):
            zone['no_procesar']='arte_sin_ocr'
            zone['ocr_id']=Path(raw).stem+f'_{zone["id"]:02d}'
    screen_anchors=[l for l in ocr['lineas'] if proposed_context(l['texto'])=='pantalla']
    for zone in result:
        lines=grouped[zone['id']]
        if not lines:continue
        original=paragraph_text(lines)
        uid=Path(raw).stem+f'_{zone["id"]:02d}'
        override=overrides.get('bloques',{}).get(uid,{})
        if override.get('texto_original'):original=override['texto_original']
        kind=proposed_context(original,zone if zone['origen']!='ocr_ingles' else None,override.get('tipo_texto'))
        reason=protected_reason(original,kind)
        if reason and (english_page or reason not in {'numero_aislado','signo_aislado'}):
            zone.update({'no_procesar':reason,'texto_original':original,'ocr_id':uid})
            protected.extend({**line,'motivo':reason} for line in lines)
            continue
        if not override.get('tipo_texto') and kind!='pantalla':
            # Unificar mensajes inclinados y sus horas, sin clasificar todo
            # rectangulo vertical como telefono.
            for line in lines:
                p=line['poligono'];angle=math.degrees(math.atan2(p[1][1]-p[0][1],p[1][0]-p[0][0]))
                if abs(angle)<7:continue
                for anchor in screen_anchors:
                    q=anchor['poligono'];aa=math.degrees(math.atan2(q[1][1]-q[0][1],q[1][0]-q[0][0]))
                    if abs(angle-aa)<12 and abs(line['box'][1]-anchor['box'][1])<650 and abs(line['box'][0]-anchor['box'][0])<750:kind='pantalla'
        role={'pantalla':'pantalla','cartel':'cartel','texto_escena':'impreso'}.get(kind,'normal')
        zone.update({'texto_original':original,'tipo_texto':kind,'rol_propuesto':override.get('rol_fuente',role),'ocr_id':uid})
        heights=[float(np.linalg.norm(np.asarray(l['poligono'])[3]-np.asarray(l['poligono'])[0])) for l in lines]
        zone['alto_letra_ingles_px']=float(np.median(heights))
        zone['box_texto_ingles']=box_of(np.concatenate([l['poligono'] for l in lines]))
        if 'trazo_px' in override:zone['trazo_revisado_px']=override['trazo_px']
        if override.get('fondo_blanco'):
            zone['fondo_plano_ocr']=True
            x1,y1,x2,y2=zone['box_contenedor'];zone['poligono_contenedor']=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        # La polaridad del fondo de las lineas evita texto negro sobre pantalla negra.
        background=[]
        for line in lines:
            x1,y1,x2,y2=map(int,line['box']);x1=max(0,x1-3);y1=max(0,y1-3);x2=min(gray.shape[1],x2+3);y2=min(gray.shape[0],y2+3)
            sub=gray[y1:y2,x1:x2]
            if sub.size:background.append(float(np.median(np.concatenate((sub[0],sub[-1],sub[:,0],sub[:,-1])))))
        light=not background or np.median(background)>=128
        zone['ocr_relleno_rgb']=[0,0,0] if light else [255,255,255]
        zone['ocr_trazo_rgb']=[255,255,255] if light else [0,0,0]
        if override.get('texto_original'):zone['texto_original']=override['texto_original']
        blocks.append({'id':uid,'texto_original':zone['texto_original'],'tipo_texto':kind,'rol_fuente':zone['rol_propuesto'],
                       'box':zone['box_contenedor'],'lineas_ocr':lines,'repaso_fondo':override.get('repaso_fondo')})
    ocr['bloques']=blocks
    protected_keys={(l['texto'],tuple(np.asarray(l['poligono']).flatten())) for l in protected}
    # Sustituir el area heredada de cada renglon leido. Las zonas que solo
    # encontro el detector conservan su seleccion original.
    if english_page:
        recognized=np.zeros_like(mask);letters=np.zeros_like(mask)
        text_margin=config.get('margen_limpieza_texto_px',6)
        default_glyph_margin=config.get('margen_limpieza_glifo_px',5)
        for zone in result:
            if zone.get('no_procesar')=='arte_sin_ocr':
                x1,y1,x2,y2=map(int,zone['box_contenedor']);recognized[y1:y2,x1:x2]=255
                continue
            if zone.get('no_procesar') or zone.get('alias_ocr'):continue
            lines=grouped[zone['id']]
            if not lines:continue
            x1,y1,x2,y2=map(int,zone['box_contenedor']);recognized[y1:y2,x1:x2]=255
            if zone.get('origen')!='globo_solido_yolo' and not zone.get('fondo_plano_ocr'):
                crop=gray[y1:y2,x1:x2]
                if crop.size and float(np.mean(crop>=245))>=0.70 and float(np.percentile(crop,30))>=245:
                    zone['fondo_plano_ocr']=True
                    if not zone.get('poligono_contenedor'):
                        zone['poligono_contenedor']=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
            flat=white_container(gray,zone)
            zone['fondo_limpieza_blanco']=flat
            zone['selecciones_fondo_complejo']=[]
            glyph_margin=cleaning_review.get('margen_glifos_por_bloque',{}).get(
                zone['ocr_id'],default_glyph_margin)
            if not flat and zone.get('origen')=='texto_fuera_comic_detector' and len(lines)==1:
                letters[y1:y2,x1:x2]|=mask[y1:y2,x1:x2]
            active_polys=[]
            for line in lines:
                polygon=line['poligono']
                if (line['texto'],tuple(np.asarray(polygon).flatten())) in protected_keys:continue
                ry1,ry2,rx1,rx2,band_roi=_text_area_roi(gray.shape,polygon,text_margin)
                if band_roi.size:recognized[ry1:ry2,rx1:rx2]|=band_roi
                if flat:
                    active_polys.append(polygon)
                    continue
                zone['selecciones_fondo_complejo'].append(polygon)
                gy1,gy2,gx1,gx2,glyph_roi=_glyph_crop(gray,polygon,glyph_margin)
                if glyph_roi is not None and glyph_roi.any():
                    letters[gy1:gy2,gx1:gx2]|=glyph_roi
                elif band_roi.size:
                    letters[ry1:ry2,rx1:rx2]|=band_roi
            if flat and active_polys:
                fy1,fy2,fx1,fx2,fmask=_flat_zone_ink_mask(gray,zone,active_polys,mask,text_margin)
                if fmask.size:
                    recognized[fy1:fy2,fx1:fx2]=255
                    letters[fy1:fy2,fx1:fx2]|=fmask
        mask=(mask&cv2.bitwise_not(recognized))|letters
        if all(grouped[z['id']] or z.get('no_procesar') or z.get('alias_ocr') for z in result):mask=letters
    for selection in cleaning_review.get('selecciones',[]):
        x1,y1,x2,y2=selection['rectangulo']
        polygon=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        sy1,sy2,sx1,sx2,band_roi=_text_area_roi(gray.shape,polygon,selection['margen_reemplazo_px'])
        if band_roi.size:mask[sy1:sy2,sx1:sx2]&=~band_roi
        mask|=reviewed_glyph_selection(gray,selection)
        for zone in result:
            if coverage(zone['box_contenedor'],[x1,y1,x2,y2])>.5:
                zone['fondo_limpieza_blanco']=False
                zone.setdefault('selecciones_fondo_complejo',[]).append(polygon)
    protection=np.zeros_like(mask)
    if english_page:
        for line in protected:cv2.fillPoly(protection,[np.asarray(line['poligono'],dtype=np.int32)],255)
    ocr['arte_protegido']=cleaning_review.get('arte_protegido',[])
    for polygon in ocr['arte_protegido']:
        cv2.fillPoly(protection,[np.asarray(polygon,dtype=np.int32)],255)
    for zone in result:
        if zone.get('no_procesar') and zone.get('no_procesar')!='arte_sin_ocr':
            x1,y1,x2,y2=map(int,zone['box_contenedor']);protection[y1:y2,x1:x2]=255
    # Margen que tambien protege frente al expandir/feather de Photoshop.
    if protection.any():
        protection=expand_mask(protection,5)
        mask &= cv2.bitwise_not(protection)
    protected_keys={(l['texto'],tuple(np.asarray(l['poligono']).flatten())) for l in protected}
    ocr['lineas']=[l for l in active if (l['texto'],tuple(np.asarray(l['poligono']).flatten())) not in protected_keys]
    ocr['zonas_sin_lectura']=[Path(raw).stem+f'_{z["id"]:02d}' for z in result if not grouped[z['id']] and not z.get('alias_ocr') and not z.get('no_procesar')]
    ocr['ids_protegidos']=[z['ocr_id'] for z in result if z.get('no_procesar')]
    return result,mask,ocr


def _poly_entry(poly_list):
    arr=np.asarray(poly_list,dtype=np.int32)
    return poly_list,arr,cv2.contourArea(arr),(int(arr[:,0].min()),int(arr[:,1].min()),int(arr[:,0].max()),int(arr[:,1].max()))


def _pts_inside_entry(entry,pts_f,pts_minx,pts_miny,pts_maxx,pts_maxy):
    _,arr,_,(bx1,by1,bx2,by2)=entry
    if pts_minx<bx1 or pts_miny<by1 or pts_maxx>bx2 or pts_maxy>by2:return False
    return all(cv2.pointPolygonTest(arr,pt,False)>=0 for pt in pts_f)


def geometry_from_record(raw,record,*,gray=None,raw_hash=None):
    """Geometria automatica conservadora: mantener cada texto en su zona RAW.

    Los paneles detectados son limites adicionales. Sin panel fiable, el propio
    contenedor original limita el typeo; nunca usar toda la pagina como permiso
    para desplazar libremente un texto de un objeto.
    """
    raw=Path(raw);digest=raw_hash or sha256(raw)
    active_zones=[z for z in record['zonas'] if not (z.get('alias_ocr') or z.get('no_procesar') or protected_reason(z.get('texto_original'),z.get('tipo_texto')))]
    protected_zones=[{'id':z.get('ocr_id') or raw.stem+f'_{z["id"]:02d}','texto_original':z.get('texto_original',''),'motivo':z['no_procesar']} for z in record['zonas'] if z.get('no_procesar')]
    if not active_zones:
        if gray is not None:h,w=gray.shape[:2]
        else:
            from PIL import Image
            with Image.open(raw) as im:w,h=im.size
        return {'archivo':raw.name,'raw_sha256':digest,'width':w,'height':h,'zonas':[],'zonas_protegidas':protected_zones}
    if gray is None:
        image=cv2.imread(str(raw));h,w=image.shape[:2]
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    else:
        h,w=gray.shape[:2]
    has_scene_ocr=any(z.get('tipo_texto','dialogo') in {'pantalla','cartel','texto_escena'} and z.get('poligonos_ocr') for z in active_zones)
    has_white_ocr=any(z.get('tipo_texto','dialogo') not in {'pantalla','cartel','texto_escena'} and z.get('metodo_efectivo')=='pincel_blanco' and z.get('poligonos_ocr') for z in active_zones)
    has_non_scene=any(not (z.get('tipo_texto','dialogo') in {'pantalla','cartel','texto_escena'} and z.get('poligonos_ocr')) for z in active_zones)
    panels=[];objects=[];white_containers=[]
    if has_white_ocr:
        white_contours,_=cv2.findContours((gray>235).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        max_white=w*h*.3
        for c in white_contours:
            if len(c)<3:continue
            area=cv2.contourArea(c)
            if 1000<area<max_white:
                p=cv2.approxPolyDP(c,.004*cv2.arcLength(c,True),True)
                if len(p)>=4:white_containers.append(_poly_entry(p[:,0,:].tolist()))
    if has_scene_ocr or has_non_scene:
        contours,_=cv2.findContours((gray<110).astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        min_panel,max_panel=w*h*.02,w*h*.99
        for c in contours:
            if len(c)<3:continue
            area=cv2.contourArea(c)
            if has_scene_ocr and area>500:
                hull=cv2.convexHull(c);hull=cv2.approxPolyDP(hull,.008*cv2.arcLength(hull,True),True)
                if 4<=len(hull)<=20:objects.append(_poly_entry(hull[:,0,:].tolist()))
            if has_non_scene and min_panel<area<max_panel:
                poly=cv2.approxPolyDP(c,.015*cv2.arcLength(c,True),True)
                if 4<=len(poly)<=8 and cv2.isContourConvex(poly):panels.append(_poly_entry(poly[:,0,:].tolist()))
    zones=[]
    for z in active_zones:
        b=list(map(int,z['box_contenedor']));uid=z.get('ocr_id') or raw.stem+f'_{z["id"]:02d}'
        kind=z.get('tipo_texto','dialogo');scene=kind in {'pantalla','cartel','texto_escena'}
        object_poly=None;layout={}
        if scene and z.get('poligonos_ocr'):
            points=np.concatenate(z['poligonos_ocr'])
            pts=points.astype(float)
            pts_f=[(float(x),float(y)) for x,y in points]
            pminx,pminy=float(points[:,0].min()),float(points[:,1].min())
            pmaxx,pmaxy=float(points[:,0].max()),float(points[:,1].max())
            hull=cv2.convexHull(points.astype(np.float32))[:,0,:]
            max_obj_area=max(1000,cv2.contourArea(hull)*6)
            has_enclosing=any(entry[2]<max_obj_area and _pts_inside_entry(entry,pts_f,pminx,pminy,pmaxx,pmaxy) for entry in objects)
            if not has_enclosing and len(z['poligonos_ocr'])==1:
                has_enclosing=any(_pts_inside_entry(entry,pts_f,pminx,pminy,pmaxx,pmaxy) for entry in objects)
            if not has_enclosing:
                z['limite_objeto_estimado']=True
            # Componer en los ejes del texto RAW, no en su caja horizontal.
            angles=[math.atan2(p[1][1]-p[0][1],p[1][0]-p[0][0]) for p in z['poligonos_ocr']]
            angle=float(np.median(angles));c,sn=math.cos(angle),math.sin(angle)
            basis=np.array([[c,sn],[-sn,c]])
            aligned=pts@basis.T;lo=aligned.min(axis=0)-6;hi=aligned.max(axis=0)+6
            center=((lo+hi)/2)@basis;size=hi-lo
            local_box=[float(center[0]-size[0]/2),float(center[1]-size[1]/2),float(center[0]+size[0]/2),float(center[1]+size[1]/2)]
            quad=np.array([[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]]])@basis
            b=[max(0,int(quad[:,0].min())),max(0,int(quad[:,1].min())),min(w,int(np.ceil(quad[:,0].max()))),min(h,int(np.ceil(quad[:,1].max())))]
            layout={'rotacion':math.degrees(angle),'box_composicion':local_box,
                    'alineacion':z.get('alineacion_raw','izquierda' if kind=='pantalla' else 'centro')}
            object_poly=quad.tolist()

        role=z.get('rol_propuesto','normal')
        polygon=z.get('poligono_contenedor')
        white=z.get('metodo_efectivo')=='pincel_blanco'
        if not scene and white and z.get('poligonos_ocr'):
            pts=np.concatenate(z['poligonos_ocr'])
            pts_f=[(float(x),float(y)) for x,y in pts]
            pminx,pminy=float(pts[:,0].min()),float(pts[:,1].min())
            pmaxx,pmaxy=float(pts[:,0].max()),float(pts[:,1].max())
            zw,zh=max(1,b[2]-b[0]),max(1,b[3]-b[1])
            candidates=[]
            for entry in white_containers:
                bx1,by1,bx2,by2=entry[3]
                if (bx2-bx1)>zw*3 or (by2-by1)>zh*3:continue
                if (bx1<=2)+(by1<=2)+(bx2>=w-2)+(by2>=h-2)>=2:continue
                if _pts_inside_entry(entry,pts_f,pminx,pminy,pmaxx,pmaxy):
                    candidates.append(entry)
            if candidates:
                polygon=min(candidates,key=lambda entry:entry[2])[0]
                pb=box_of(polygon)
                # Aprovechar el globo real sin salir del panel: el tamano sigue
                # limitado por la letra inglesa, no por toda el area disponible.
                b=[max(0,int(pb[0])+5),max(0,int(pb[1])+5),min(w,int(pb[2])-5),min(h,int(pb[3])-5)]
        # La trama de una cama no es un contorno fiable de globo.
        container='globo' if not scene and white and polygon else 'rotulo'
        pad=4
        lx1,ly1,lx2,ly2=max(0,b[0]-pad),max(0,b[1]-pad),min(w,b[2]+pad),min(h,b[3]+pad)
        local=[[lx1,ly1],[lx2,ly1],[lx2,ly2],[lx1,ly2]]
        eligible=[]
        if not object_poly:
            local_f=[(float(x),float(y)) for x,y in local]
            eligible=[entry for entry in panels if _pts_inside_entry(entry,local_f,lx1,ly1,lx2,ly2)]
        panel=object_poly or (min(eligible,key=lambda entry:entry[2])[0] if eligible else local)
        height=b[3]-b[1]
        zones.append({**layout,'id':uid,'texto_original':z.get('texto_original',''),'box_contenedor':b,
            'poligono_globo':polygon if container=='globo' else None,'tipo_contenedor':container,
            'poligono_objeto':object_poly,
            'poligono_panel':panel,'permite_fuera_panel_raw':False,'tipo_texto':kind,'rol_revisado':role,
            'metodo_limpieza':z.get('metodo_efectivo','relleno_generativo'),
            'trazo_px':z.get('trazo_revisado_px',0 if white else 5),'trazo_rgb':z.get('ocr_trazo_rgb',[255,255,255]),'relleno_rgb':z.get('ocr_relleno_rgb',[0,0,0]),
            'minimo_px':6 if scene else 12,'margen_revision_px':1 if scene else 4,
            'tamano_px':min(48,max(12,int(height*.65))) if scene else 42,
            'alto_letra_ingles_px':z.get('alto_letra_ingles_px'),
            'box_texto_ingles':z.get('box_texto_ingles'),
            'lineas_maximas':1 if scene and '\n' not in z.get('texto_original','') and len(z.get('texto_original',''))<30 else 24,
            'geometria_origen':'ocr_automatico','limite_origen':('zona_ocr_orientada' if z.get('limite_objeto_estimado') else 'objeto_detectado') if object_poly else ('panel_detectado' if eligible else 'zona_raw'),
            'ocr_pendiente':not bool(z.get('texto_original'))})
    return {'archivo':raw.name,'raw_sha256':digest,'width':w,'height':h,'zonas':zones,
            'zonas_protegidas':protected_zones}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paginas');args=parser.parse_args(argv)
    selected=set(args.paginas.split(',')) if args.paginas else None
    engine=EnglishOCR()
    for raw in sorted((BASE/'01_RAW').iterdir()):
        if raw.suffix.lower() not in {'.jpg','.jpeg','.png','.webp'} or selected and raw.stem not in selected:continue
        folder=BASE/'04_DIAGNOSTICO/mascaras_produccion'/raw.stem
        cached=read_json(folder/'mascaras.json') if (folder/'mascaras.json').exists() else None
        zones=cached['zonas'] if cached and cached['raw_sha256']==sha256(raw) else []
        result=engine.page(raw,zones);write_json(folder/'ocr_lectura.json',result)
        print(f'[OCR EN] {raw.name}: {len(result["lineas"])} lineas; {len(result["pendientes"])} pendientes; {result["seconds"]} s',flush=True)


if __name__=='__main__':main()
