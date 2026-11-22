"""
================================================================================
PRUEBA EXPERIMENTAL: SEGMENTACIÓN REAL DE LETRAS A NIVEL DE PÍXEL (MANGA AI)
================================================================================
Este módulo es una prueba independiente y complementaria.
NO modifica ni sustituye el pipeline actual (pipeline_manga.py).
Su objetivo es evaluar y comparar la limpieza basada en cajas rectangulares vs.
la segmentación exacta a nivel de píxel (silueta real de caracteres japoneses,
furigana, relleno blanco con borde negro, trazos finos y halos).
================================================================================
"""

import os
import glob
import json
import time
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "01_RAW")
WORK_DIR = os.path.join(BASE_DIR, "02_TRABAJO_PSD")
DIAG_DIR = os.path.join(BASE_DIR, "04_DIAGNOSTICO")
MODELS_DIR = os.path.join(BASE_DIR, "models")
COMIC_DETECTOR_PATH = os.path.join(MODELS_DIR, "comic-text-detector.onnx")
MANIFEST_PATH = os.path.join(WORK_DIR, "zonas_limpieza_columnas.json")

# Configuración de Margen Adaptativo (Fase 4)
DEFAULT_MARGIN_PX = 2

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [SEGMENTACION_PIXEL] {msg}", flush=True)

# ==========================================================
# FASE 1: DIAGNÓSTICO DEL SISTEMA EXISTENTE
# ==========================================================
def diagnosticar_sistema():
    log("--------------------------------------------------")
    log("FASE 1: DIAGNÓSTICO DEL SISTEMA ACTUAL")
    log("  - Detector Primario: YOLOv8 (bubbles_detect.pt) para delimitación de regiones de globos/diálogo.")
    log("  - Detector Especializado: Comic-Text-Detector ONNX (DBNet para líneas + UNet para segmentación de texto).")
    log("  - Formato Actual: Cajas de búsqueda rectangulares (Cyan para bloques y Rojo/Morado para columnas).")
    log("  - Estrategia: Se conservan las cajas actuales como REGIONES DE BÚSQUEDA (bounding search priors),")
    log("    pero la máscara final de eliminación se construye estrictamente a NIVEL DE PÍXEL.")
    log("--------------------------------------------------")

# ==========================================================
# FASE 2 Y 3: SEGMENTACIÓN REAL Y REFINAMIENTO OPENCV
# ==========================================================
def segmentar_caracteres_region(sub_img, sub_seg, origen, margin_px=DEFAULT_MARGIN_PX, estilo=None):
    """
    Analiza una región de búsqueda local y reconstruye la máscara a nivel de píxel
    de cada carácter, considerando:
    1. Trazos oscuros en fondo claro (globos blancos).
    2. Relleno blanco con contorno negro (técnicas sobre tramas).
    3. Trazos oscuros con halo blanco protector.
    4. Kanjis pequeños, radicales desconectados y furigana.
    """
    sh, sw = sub_img.shape[:2]
    if sh < 4 or sw < 4:
        return np.zeros((sh, sw), dtype=np.uint8)
        
    gray = cv2.cvtColor(sub_img, cv2.COLOR_BGR2GRAY) if len(sub_img.shape) == 3 else sub_img
    es_tinta_color = False
    
    if origen == "globo_solido_yolo":
        # 1. Globos de diálogo sólidos blancos:
        # Los caracteres son trazos oscuros sobre fondo blanco limpio (>200).
        # Combinamos umbral adaptativo local con la probabilidad del modelo U-Net
        _, dark_chars = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY_INV)
        
        # Filtrar ruido de fondo: el píxel debe tener probabilidad de texto U-Net
        prob_mask = (sub_seg > 0.07)
        char_raw = (dark_chars > 0) & prob_mask
        
    else:
        # 2. Textos fuera de globos (técnicas, textos en tramas, bordes complejos, furigana):
        k_5x5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        k_7x7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        has_real_seg = float(sub_seg.min()) < 0.5

        # A) Trazos con alta probabilidad U-Net y tinta a color (portadas)
        strong_seg = (sub_seg > 0.25) if has_real_seg else np.zeros_like(gray, dtype=bool)
        if len(sub_img.shape) == 3:
            sub_chroma = sub_img.max(axis=2).astype(np.int16) - sub_img.min(axis=2).astype(np.int16)
            color_ink = np.zeros_like(gray, dtype=bool)
            chroma_bin = (sub_chroma > 14).astype(np.uint8)
            if np.any(chroma_bin):
                n_col, col_lbl, col_stats, _ = cv2.connectedComponentsWithStats(chroma_bin)
                keep_col = np.zeros(n_col, dtype=bool)
                if estilo == "color_portada":
                    seed_seg = sub_seg > 0.02
                    seed_hi = sub_chroma > 22
                    for ci in range(1, n_col):
                        cx, cy, cw_c, ch_c, area_ci = [int(v) for v in col_stats[ci]]
                        roi_lbl = col_lbl[cy:cy+ch_c, cx:cx+cw_c] == ci
                        if np.any(seed_seg[cy:cy+ch_c, cx:cx+cw_c] & roi_lbl) or (
                            area_ci >= 40 and np.any(seed_hi[cy:cy+ch_c, cx:cx+cw_c] & roi_lbl)
                        ):
                            keep_col[ci] = True
                else:
                    seed_std = (sub_chroma > 16) & (sub_seg > 0.04)
                    for ci in range(1, n_col):
                        cx, cy, cw_c, ch_c, _ = [int(v) for v in col_stats[ci]]
                        roi_lbl = col_lbl[cy:cy+ch_c, cx:cx+cw_c] == ci
                        if np.any(seed_std[cy:cy+ch_c, cx:cx+cw_c] & roi_lbl):
                            keep_col[ci] = True
                color_ink = keep_col[col_lbl]
            if np.any(color_ink):
                color_ink = color_ink | ((cv2.dilate(color_ink.astype(np.uint8), k_5x5) > 0) & (sub_chroma > 10))
        else:
            color_ink = np.zeros_like(gray, dtype=bool)

        # B) Letras oscuras estandar y furigana sobre tramas grises
        _, otsu_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        dark_text = (otsu_inv > 0) & (sub_seg > 0.10) & (gray < 155)
        if has_real_seg and estilo is None and np.any(dark_text):
            n_dt, dt_lbl, dt_stats, _ = cv2.connectedComponentsWithStats(dark_text.astype(np.uint8))
            keep_dt = np.ones(n_dt, dtype=bool)
            keep_dt[0] = False
            for di in range(1, n_dt):
                dx, dy, dw_d, dh_d, area_d = [int(v) for v in dt_stats[di]]
                if area_d >= 120:
                    comp_d = dt_lbl[dy:dy+dh_d, dx:dx+dw_d] == di
                    if float(np.mean(sub_seg[dy:dy+dh_d, dx:dx+dw_d][comp_d] > 0.25)) < 0.20:
                        keep_dt[di] = False
            dark_text = keep_dt[dt_lbl]

        # C) Halo blanco protector cenido alrededor de trazos de texto
        halo_anchor = dark_text | strong_seg | color_ink
        if np.any(halo_anchor):
            dil_anchor = cv2.dilate(halo_anchor.astype(np.uint8), k_7x7)
            white_halo = (dil_anchor > 0) & (gray > 215) & (sub_seg > 0.10)
        else:
            white_halo = np.zeros_like(dark_text)

        # D) Nucleo blanco de texto hueco/contorneado y su contorno negro adyacente (sin inundar fondos blancos)
        white_core = (gray > 200) & (sub_seg > 0.22)
        if np.any(white_core):
            dil_white = cv2.dilate(white_core.astype(np.uint8), k_5x5)
            black_border = (dil_white > 0) & (gray < 100) & (sub_seg > 0.05)
            if np.any(black_border):
                dil_border = cv2.dilate(black_border.astype(np.uint8), k_7x7)
                white_outlined = white_core & (dil_border > 0)
            else:
                white_outlined = np.zeros_like(white_core)
        else:
            black_border = np.zeros_like(white_core)
            white_outlined = np.zeros_like(white_core)

        char_raw = strong_seg | color_ink | dark_text | white_halo | white_outlined | black_border
        if has_real_seg and estilo is None and 125 <= float(np.median(gray)) <= 195:
            if int(np.count_nonzero((gray > 220) & (sub_seg > 0.12))) >= 80:
                char_raw = char_raw | ((gray > 210) & (sub_seg > 0.08))
        if estilo == "contorneado":
            white_bin = (gray > 195).astype(np.uint8)
            n_w, w_lbl, w_stats, _ = cv2.connectedComponentsWithStats(white_bin)
            enclosed_white = np.zeros_like(gray, dtype=bool)
            for wi in range(1, n_w):
                wx, wy, ww, wh, warea = [int(v) for v in w_stats[wi]]
                if warea < 14 or warea > 0.25 * sh * sw:
                    continue
                if wx == 0 or wy == 0 or (wx + ww) >= sw or (wy + wh) >= sh:
                    continue
                rx1, ry1 = max(0, wx - 2), max(0, wy - 2)
                rx2, ry2 = min(sw, wx + ww + 2), min(sh, wy + wh + 2)
                comp_roi = (w_lbl[ry1:ry2, rx1:rx2] == wi)
                ring = (cv2.dilate(comp_roi.astype(np.uint8), k_5x5) > 0) & (~comp_roi)
                if np.count_nonzero(ring) < 8:
                    continue
                if float(np.mean(gray[ry1:ry2, rx1:rx2][ring] < 130)) >= 0.50:
                    if float(sub_seg[ry1:ry2, rx1:rx2][comp_roi].max()) > 0.08 or warea >= 45:
                        enclosed_white[ry1:ry2, rx1:rx2] |= comp_roi
            outline_dark = (cv2.dilate(enclosed_white.astype(np.uint8), k_7x7) > 0) & (gray < 145)
            char_raw = char_raw | enclosed_white | outline_dark
        es_tinta_color = (estilo == "color_portada") or (
            int(np.count_nonzero(color_ink)) >= max(150, int(0.25 * max(1, np.count_nonzero(char_raw))))
        )
        
    char_uint8 = char_raw.astype(np.uint8) * 255
    
    # Cerrar micro-interrupciones en trazos finos sin fusionar letras distintas
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    char_closed = cv2.morphologyEx(char_uint8, cv2.MORPH_CLOSE, k_close)
    
    # ==========================================================
    # FASE 4: MARGEN CONFIGURABLE Y PROTECCIÓN FRENTE A DIBUJO
    # ==========================================================
    if margin_px > 0:
        eff_margin = margin_px + 3 if es_tinta_color else margin_px
        k_size = 2 * eff_margin + 1
        k_margen = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_size, k_size))
        char_dilated = cv2.dilate(char_closed, k_margen, iterations=1)
    else:
        char_dilated = char_closed
        
    # PARCHEO TOTAL DE HUECOS INTERIORES (SOLICITUD CRÍTICA)
    # Rellena cualquier hueco o punto no sombreado en el interior o intersección de trazos
    char_final = parchar_huecos_mascara(char_dilated, max_hole_area=3500)
        
    return char_final

def parchar_huecos_mascara(mask, max_hole_area=3500):
    """
    Rellena huecos interiores y puntos negros no sombreados en el interior de los
    caracteres mediante análisis de jerarquía de contornos (RETR_CCOMP), garantizando
    que el texto quede 100% parchado y sólido sin invadir el exterior.
    """
    if np.count_nonzero(mask) == 0:
        return mask.copy()
    cnts, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None or len(cnts) == 0:
        return mask.copy()
    filled = mask.copy()
    hier = hier[0]
    for idx, h_info in enumerate(hier):
        # h_info: [Next, Previous, First_Child, Parent]
        parent = h_info[3]
        if parent >= 0: # Es un hueco interior dentro de un carácter
            area = cv2.contourArea(cnts[idx])
            if area <= max_hole_area:
                cv2.drawContours(filled, [cnts[idx]], -1, 255, -1)
    return filled

# ==========================================================
# GENERADOR COMPLETO DE MÁSCARAS POR PÁGINA
# ==========================================================
def procesar_mascara_pagina(img_path, page_info, comic_session=None, margin_px=DEFAULT_MARGIN_PX, seg_map=None, *, img=None):
    nombre = os.path.basename(img_path)
    if img is None:
        img = cv2.imread(img_path)
    if img is None: return None, None
    h, w = img.shape[:2]
    
    # Inferencia de segmentación U-Net en Comic-Text-Detector
    if seg_map is None:
        resized = cv2.resize(img, (1024, 1024))
        inp = (resized.astype(np.float32) / 255.0).transpose((2, 0, 1))[None, ...]
        blk, seg, det = comic_session.run(None, {'images': inp})
        seg_map = cv2.resize(seg[0, 0], (w, h))
    
    # Lienzo de máscara en escala de grises a resolución nativa 1:1
    mascara_pixel = np.zeros((h, w), dtype=np.uint8)
    
    zonas = page_info.get("zonas", [])
    total_rects_area = 0
    k_dilate_globo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin_px + 1, 2 * margin_px + 1)) if margin_px > 0 else None
    k_erode_3x3 = np.ones((3, 3), np.uint8)
    
    for z in zonas:
        origen = z.get("origen", "globo_solido_yolo")
        rects = z.get("rectangulos_texto", [])
        if not rects:
            continue
        pad_x = 6
        pad_y = 8
        zx1 = max(0, min(r[0] for r in rects) - pad_x)
        zy1 = max(0, min(r[1] for r in rects) - pad_y)
        zx2 = min(w, max(r[2] for r in rects) + pad_x)
        zy2 = min(h, max(r[3] for r in rects) + pad_y)
        if zx2 <= zx1 or zy2 <= zy1:
            for r in rects:
                total_rects_area += (r[2] - r[0]) * (r[3] - r[1])
            continue
        zone_roi = np.zeros((zy2 - zy1, zx2 - zx1), dtype=np.uint8)
        
        for r in rects:
            rx1, ry1, rx2, ry2 = r
            total_rects_area += (rx2 - rx1) * (ry2 - ry1)
            
            # Ventana de análisis con holgura adaptativa generosa para no recortar
            # caracteres iniciales/finales (『, 』, ン, ！), furigana ni signos
            sx1 = max(0, rx1 - pad_x)
            sy1 = max(0, ry1 - pad_y)
            sx2 = min(w, rx2 + pad_x)
            sy2 = min(h, ry2 + pad_y)
            if sx2 <= sx1 or sy2 <= sy1:
                continue
            
            sub_img = img[sy1:sy2, sx1:sx2]
            sub_seg = seg_map[sy1:sy2, sx1:sx2]
            
            if origen=='globo_solido_yolo':
                # El contenedor blanco ya limita el dibujo: recuperar tambien
                # letras/signos que UNet omita, sin volver a inferir.
                gray=cv2.cvtColor(sub_img,cv2.COLOR_BGR2GRAY)
                sub_mask=(gray<220).astype(np.uint8)*255
                if seg_map is not None and float(seg_map.min())<0.5:
                    if z.get('poligono_contenedor'):
                        p_local=np.array(z['poligono_contenedor'],dtype=np.int32)-[sx1,sy1]
                        p_in=np.zeros_like(sub_mask)
                        cv2.fillPoly(p_in,[p_local],255)
                        p_in=cv2.erode(p_in,k_erode_3x3)
                        sub_mask&=p_in
                    ix1,iy1=max(0,rx1-sx1-1),max(0,ry1-sy1-1)
                    ix2,iy2=min(sx2-sx1,rx2-sx1+1),min(sy2-sy1,ry2-sy1+1)
                    n_cc,cc_lbl,cc_stats,_=cv2.connectedComponentsWithStats((sub_mask>0).astype(np.uint8))
                    seg_hit=sub_seg>0.08
                    keep_cc=np.zeros(n_cc,dtype=bool)
                    inner_ids=set(np.unique(cc_lbl[iy1:iy2,ix1:ix2])) if (ix2>ix1 and iy2>iy1) else set(range(1,n_cc))
                    for ci in range(1,n_cc):
                        if ci not in inner_ids:
                            continue
                        area_c=int(cc_stats[ci,cv2.CC_STAT_AREA])
                        if area_c<=120:
                            keep_cc[ci]=True
                        else:
                            overlap=float(np.count_nonzero(seg_hit&(cc_lbl==ci)))/max(1,area_c)
                            if overlap>=0.12:
                                keep_cc[ci]=True
                    sub_mask=np.where(keep_cc[cc_lbl],255,0).astype(np.uint8)
                if k_dilate_globo is not None:
                    sub_mask=cv2.dilate(sub_mask,k_dilate_globo)
                sub_mask=parchar_huecos_mascara(sub_mask)
            else:
                sub_mask = segmentar_caracteres_region(sub_img, sub_seg, origen, margin_px=margin_px, estilo=z.get("estilo"))
                if np.any(sub_mask):
                    ix1, iy1 = max(0, rx1 - sx1), max(0, ry1 - sy1)
                    ix2, iy2 = min(sx2 - sx1, rx2 - sx1), min(sy2 - sy1, ry2 - sy1)
                    if ix2 > ix1 and iy2 > iy1:
                        n_sm, sm_lbl, _, _ = cv2.connectedComponentsWithStats((sub_mask > 0).astype(np.uint8))
                        if n_sm > 2:
                            keep_sm = np.zeros(n_sm, dtype=bool)
                            inner_lbls = np.unique(sm_lbl[iy1:iy2, ix1:ix2])
                            keep_sm[inner_lbls[inner_lbls > 0]] = True
                            sub_mask = np.where(keep_sm[sm_lbl], 255, 0).astype(np.uint8)
            
            # Combinar en la máscara local de la zona
            zone_roi[sy1-zy1:sy2-zy1, sx1-zx1:sx2-zx1] |= sub_mask
        # No convertir los margenes de busqueda de un globo blanco en GenFill.
        # Recortar al interior blanco detectado protege el contorno y el dibujo.
        if origen=='globo_solido_yolo' and z.get('poligono_contenedor'):
            poly=np.array(z['poligono_contenedor'],dtype=np.int32)
            cx1,cy1=max(0,min(zx1,int(poly[:,0].min()))-1),max(0,min(zy1,int(poly[:,1].min()))-1)
            cx2,cy2=min(w,max(zx2,int(poly[:,0].max())+1)+1),min(h,max(zy2,int(poly[:,1].max())+1)+1)
            container=np.zeros((cy2-cy1,cx2-cx1),dtype=np.uint8)
            cv2.fillPoly(container,[poly-[cx1,cy1]],255)
            container=cv2.erode(container,k_erode_3x3)
            clipped=zone_roi & container[zy1-cy1:zy2-cy1, zx1-cx1:zx2-cx1]
            if z.get('from_yolo',True) or np.count_nonzero(clipped)>=0.85*max(1,np.count_nonzero(zone_roi)):
                seg_zone=seg_map[zy1:zy2,zx1:zx2]>0.22
                lost_seg=(zone_roi>0)&(clipped==0)&seg_zone
                if int(np.count_nonzero(lost_seg))>=250:
                    zone_roi=clipped|(zone_roi&seg_zone.astype(np.uint8)*255)
                else:
                    zone_roi=clipped
        mascara_pixel[zy1:zy2, zx1:zx2] |= zone_roi
            
    # Métricas comparativas (Fase 6)
    area_pixel = np.count_nonzero(mascara_pixel)
    reduccion_pct = (1.0 - (area_pixel / max(1, total_rects_area))) * 100.0
    
    if comic_session is not None:
        log(f"[{nombre}] Área Rectángulos: {total_rects_area:,} px | Área Píxel Real: {area_pixel:,} px | Reducción de área a limpiar: {reduccion_pct:.1f}%")
    
    return mascara_pixel, reduccion_pct

# ==========================================================
# FASE 5 Y 6: VISUALIZACIÓN COMPARATIVA E HÍBRIDA
# ==========================================================
def generar_visualizacion_hibrida(img_path, page_info, mascara_pincel, mascara_genfill, out_vis_path):
    """
    Genera la visualización del nuevo modelo híbrido solicitado por el usuario:
    1. Polígonos y figuras geométricas en CYAN: delimitación de globos para centrado del typeo.
    2. Texto interior en VERDE: limpieza con pincel/borrador (parchado sólido sin huecos).
    3. Texto exterior y desbordamientos en MAGENTA: Relleno Generativo de Photoshop (capa independiente).
    """
    img = cv2.imread(img_path)
    h, w = img.shape[:2]
    vis = img.copy()
    overlay = img.copy()
    
    # 1. Aplicar máscara de Pincel (Verde esmeralda)
    overlay[mascara_pincel > 0] = [0, 255, 0]
    
    # 2. Aplicar máscara de Relleno Generativo (Magenta brillante)
    overlay[mascara_genfill > 0] = [255, 0, 220]
    
    # Mezcla translúcida
    blended = cv2.addWeighted(vis, 0.45, overlay, 0.55, 0)
    
    # 3. Dibujar figuras geométricas y polígonos de globos para el futuro Typeo
    for z in page_info.get("zonas", []):
        origen = z.get("origen")
        poly = z.get("poligono_contenedor", [])
        box = z.get("box_contenedor", [0, 0, 0, 0])
        
        if origen == "globo_solido_yolo" and len(poly) >= 3:
            pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(blended, [pts], True, (255, 255, 0), 2, cv2.LINE_AA) # Cyan
            cv2.rectangle(blended, (box[0], box[1]), (box[2], box[3]), (255, 200, 0), 1, cv2.LINE_AA)
            cv2.putText(blended, f"GLOBO TYPE #{z.get('id', '')}", (box[0], max(15, box[1] - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1, cv2.LINE_AA)
        elif origen == "texto_fuera_comic_detector":
            cv2.rectangle(blended, (box[0], box[1]), (box[2], box[3]), (0, 0, 255), 1, cv2.LINE_AA)
            cv2.putText(blended, "GEN_FILL (IA)", (box[0], max(15, box[1] - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

    # Leyenda superior informativa
    cv2.rectangle(blended, (0, 0), (w, 55), (0, 0, 0), -1)
    cv2.putText(blended, "DELIMITACION HIBRIDA: Px Real + Globos Geometricos", (15, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(blended, "CYAN: Globo (Type) | VERDE: Pincel/Borrador (Interior) | MAGENTA: GenFill (Fuera/Desborde)",
                (15, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
                
    cv2.imwrite(out_vis_path, blended)
    log(f"Visualización híbrida guardada: {out_vis_path}")

def generar_comparativa_visual(img_path, page_info, mascara_pixel, out_vis_path):
    img = cv2.imread(img_path)
    h, w = img.shape[:2]
    
    # 1. LADO IZQUIERDO: Visualización Actual de Rectángulos
    vis_cajas = img.copy()
    for z in page_info.get("zonas", []):
        origen = z.get("origen")
        bx1, by1, bx2, by2 = z.get("box_contenedor", [0, 0, 0, 0])
        cv2.rectangle(vis_cajas, (bx1, by1), (bx2, by2), (255, 200, 0), 2)
        color_col = (220, 20, 200) if origen == "globo_solido_yolo" else (0, 0, 255)
        for r in z.get("rectangulos_texto", []):
            cv2.rectangle(vis_cajas, (r[0], r[1]), (r[2], r[3]), color_col, 2)
            
    # Añadir encabezado
    cv2.rectangle(vis_cajas, (0, 0), (w, 40), (0, 0, 0), -1)
    cv2.putText(vis_cajas, "METODO ANTERIOR: CAJAS RECTANGULARES", (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2, cv2.LINE_AA)
    
    # 2. LADO DERECHO: Visualización Nueva de Segmentación a Nivel de Píxel (Parchada)
    vis_pixel = img.copy()
    overlay = img.copy()
    # Color verde esmeralda translúcido sobre los caracteres reales parchados
    overlay[mascara_pixel > 0] = [0, 255, 0]
    blended = cv2.addWeighted(vis_pixel, 0.50, overlay, 0.50, 0)
    
    # Añadir encabezado
    cv2.rectangle(blended, (0, 0), (w, 40), (0, 0, 0), -1)
    cv2.putText(blended, "METODO NUEVO: SILUETA PIXEL PARCHADA", (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2, cv2.LINE_AA)
    
    # Concatenar lado a lado
    comparativa = np.hstack((vis_cajas, blended))
    cv2.imwrite(out_vis_path, comparativa)
    log(f"Comparativa guardada: {out_vis_path}")

# ==========================================================
# EJECUCIÓN PRINCIPAL DE LA PRUEBA EXPERIMENTAL
# ==========================================================
if __name__ == "__main__":
    t_start = time.time()
    log("==================================================")
    log("INICIANDO PRUEBA DE SEGMENTACIÓN A NIVEL DE PÍXEL")
    log("==================================================")
    
    diagnosticar_sistema()
    
    if not os.path.exists(MANIFEST_PATH):
        log(f"ERROR: No se encontró el manifiesto {MANIFEST_PATH}. Ejecuta primero pipeline_manga.py.")
        exit(1)
        
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        paginas_info = json.load(f)
        
    import onnxruntime as ort
    comic_session = ort.InferenceSession(COMIC_DETECTOR_PATH, providers=['CPUExecutionProvider'])
    
    imagenes = sorted(glob.glob(os.path.join(RAW_DIR, "*.*")))
    paginas = [img for img in imagenes if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    
    reporte_metricas = []
    manifiesto_hibrido = []
    
    for p in paginas:
        nombre = os.path.basename(p)
        nombre_base, _ = os.path.splitext(nombre)
        info = next((item for item in paginas_info if item["archivo"] == nombre), None)
        if not info: continue
        h, w = info["h"], info["w"]
        
        # Fase 2, 3, 4: Generar máscara a nivel de píxel sólida y parchada
        mascara_pixel, reduccion = procesar_mascara_pagina(p, info, comic_session, margin_px=DEFAULT_MARGIN_PX)
        
        if mascara_pixel is not None:
            # Construir máscara acumulada de los globos sólidos de diálogo
            mascara_globos = np.zeros((h, w), dtype=np.uint8)
            for z in info.get("zonas", []):
                if z.get("origen") == "globo_solido_yolo" and z.get("poligono_contenedor"):
                    pts = np.array(z["poligono_contenedor"], dtype=np.int32)
                    cv2.fillPoly(mascara_globos, [pts], 255)
                    
            # ==========================================================
            # PARTICIÓN INTELIGENTE DE LIMPIEZA SOLICITADA POR EL USUARIO:
            # 1. Dentro del globo -> Pincel / Borrador blanco
            # 2. Fuera del globo o desbordado hacia el dibujo -> Relleno Generativo IA
            # ==========================================================
            mascara_pincel = cv2.bitwise_and(mascara_pixel, mascara_globos)
            mascara_genfill = cv2.bitwise_and(mascara_pixel, cv2.bitwise_not(mascara_globos))
            
            px_pincel = np.count_nonzero(mascara_pincel)
            px_genfill = np.count_nonzero(mascara_genfill)
            
            # Guardar máscaras PNG 1:1 en escala de grises
            out_mask_total = os.path.join(DIAG_DIR, f"MASCARA_PIXEL_{nombre_base}.png")
            out_mask_pincel = os.path.join(DIAG_DIR, f"MASCARA_PINCEL_{nombre_base}.png")
            out_mask_genfill = os.path.join(DIAG_DIR, f"MASCARA_GENFILL_{nombre_base}.png")
            
            cv2.imwrite(out_mask_total, mascara_pixel)
            cv2.imwrite(out_mask_pincel, mascara_pincel)
            cv2.imwrite(out_mask_genfill, mascara_genfill)
            
            # Generar trazado híbrido (Globos en Cyan, Pincel en Verde, GenFill en Magenta)
            out_trazado_hibrido = os.path.join(DIAG_DIR, f"TRAZADO_HIBRIDO_{nombre_base}.jpg")
            generar_visualizacion_hibrida(p, info, mascara_pincel, mascara_genfill, out_trazado_hibrido)
            
            # Generar comparativa lado a lado (Cajas anteriores vs Píxel nuevo)
            out_comp = os.path.join(DIAG_DIR, f"COMPARATIVA_CAJAS_VS_PIXEL_{nombre_base}.jpg")
            generar_comparativa_visual(p, info, mascara_pixel, out_comp)
            
            reporte_metricas.append({
                "archivo": nombre,
                "mascara_total_png": out_mask_total,
                "mascara_pincel_png": out_mask_pincel,
                "mascara_genfill_png": out_mask_genfill,
                "px_pincel_blanco": px_pincel,
                "px_relleno_generativo": px_genfill,
                "trazado_hibrido_jpg": out_trazado_hibrido,
                "comparativa_jpg": out_comp,
                "reduccion_area_pct": round(reduccion, 2)
            })
            
            manifiesto_hibrido.append({
                "archivo": nombre,
                "w": w,
                "h": h,
                "mascara_pincel": out_mask_pincel,
                "mascara_genfill": out_mask_genfill,
                "zonas_globos_type": [
                    {
                        "id": z["id"],
                        "box_contenedor": z["box_contenedor"],
                        "poligono_contenedor": z.get("poligono_contenedor", []),
                        "orientacion": z.get("orientacion", "vertical")
                    }
                    for z in info.get("zonas", []) if z.get("origen") == "globo_solido_yolo"
                ]
            })
            
    # Guardar reporte de evaluación y manifiesto
    rep_path = os.path.join(WORK_DIR, "reporte_evaluacion_segmentacion_pixel.json")
    with open(rep_path, "w", encoding="utf-8") as rf:
        json.dump(reporte_metricas, rf, ensure_ascii=False, indent=2)
        
    man_hibrido_path = os.path.join(WORK_DIR, "manifiesto_limpieza_hibrida.json")
    with open(man_hibrido_path, "w", encoding="utf-8") as mf:
        json.dump(manifiesto_hibrido, mf, ensure_ascii=False, indent=2)
        
    # ==========================================================
    # GENERAR CROPS DE ZOOM EN ALTA RESOLUCIÓN PARA REVISIÓN
    # ==========================================================
    log("Generando recortes de zoom para evaluación visual...")
    
    # 1. ZOOM HIBRIDO 005: Técnicas en Magenta (GenFill) y Globos en Cyan
    hibrido_005_path = os.path.join(DIAG_DIR, "TRAZADO_HIBRIDO_005.jpg")
    if os.path.exists(hibrido_005_path):
        h005 = cv2.imread(hibrido_005_path)
        zoom_h005 = h005[420:1180, :]
        out_zh005 = os.path.join(DIAG_DIR, "ZOOM_HIBRIDO_005_TECHNIQUES.jpg")
        cv2.imwrite(out_zh005, zoom_h005)
        log(f"Zoom híbrido 005 guardado: {out_zh005}")

    # 2. ZOOM HIBRIDO 004: Monja con textos en Magenta (GenFill) y furigana
    hibrido_004_path = os.path.join(DIAG_DIR, "TRAZADO_HIBRIDO_004.jpg")
    if os.path.exists(hibrido_004_path):
        h004 = cv2.imread(hibrido_004_path)
        zoom_h004 = h004[200:1800, :]
        out_zh004 = os.path.join(DIAG_DIR, "ZOOM_HIBRIDO_004_NUN.jpg")
        cv2.imwrite(out_zh004, zoom_h004)
        log(f"Zoom híbrido 004 guardado: {out_zh004}")

    # 3. ZOOM HIBRIDO 001: Globos en Cyan + Pincel Verde + GenFill Magenta
    hibrido_001_path = os.path.join(DIAG_DIR, "TRAZADO_HIBRIDO_001.jpg")
    if os.path.exists(hibrido_001_path):
        h001 = cv2.imread(hibrido_001_path)
        # Globos superiores
        zoom_h001_top = h001[80:550, 480:980]
        out_zh001_top = os.path.join(DIAG_DIR, "ZOOM_HIBRIDO_001_TOP.jpg")
        cv2.imwrite(out_zh001_top, zoom_h001_top)
        # Grito / Desborde central
        zoom_h001_bot = h001[500:1100, 450:1250]
        out_zh001_bot = os.path.join(DIAG_DIR, "ZOOM_HIBRIDO_001_OVERFLOW.jpg")
        cv2.imwrite(out_zh001_bot, zoom_h001_bot)
        log(f"Zooms híbridos 001 guardados")

    # 4. ZOOM PARCHADO 001: Verificación de relleno sólido sin huecos interiores
    comp_001_path = os.path.join(DIAG_DIR, "COMPARATIVA_CAJAS_VS_PIXEL_001.jpg")
    if os.path.exists(comp_001_path):
        c001 = cv2.imread(comp_001_path)
        h1, w1 = c001.shape[:2]
        single_w = w1 // 2
        # Crop de la zona de diálogo derecha para verificar el parcheo sólido de caracteres
        z1_left = c001[80:550, 480:980]
        z1_right = c001[80:550, single_w + 480 : single_w + 980]
        zoom_001 = np.hstack((z1_left, z1_right))
        out_z001 = os.path.join(DIAG_DIR, "ZOOM_PARCHADO_001.jpg")
        cv2.imwrite(out_z001, zoom_001)
        log(f"Zoom parchado 001 guardado: {out_z001}")
        
    log("==================================================")
    log(f"PRUEBA DE SEGMENTACIÓN FINALIZADA EN {time.time() - t_start:.2f}s")
    log(f"Reporte de evaluación guardado en: {rep_path}")
    log("==================================================")
