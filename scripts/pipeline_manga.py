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
LOG_PATH = os.path.join(BASE_DIR, "logs_limpieza.txt")
YOLO_MODEL_PATH = os.path.join(MODELS_DIR, "bubbles_detect.pt")
COMIC_DETECTOR_PATH = os.path.join(MODELS_DIR, "comic-text-detector.onnx")

for d in [RAW_DIR, WORK_DIR, DIAG_DIR, MODELS_DIR]:
    os.makedirs(d, exist_ok=True)

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"{ts} [PIPELINE] {msg}"
    print(formatted, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as lf:
        lf.write(formatted + "\n")

def asegurar_comic_detector():
    if not os.path.exists(COMIC_DETECTOR_PATH) or os.path.getsize(COMIC_DETECTOR_PATH) < 1000:
        log("Descargando comic-text-detector.onnx (modelo especializado en manga)...")
        import requests
        url = "https://huggingface.co/mayocream/comic-text-detector-onnx/resolve/main/comic-text-detector.onnx"
        r = requests.get(url, stream=True)
        with open(COMIC_DETECTOR_PATH, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk: f.write(chunk)
        log("Descarga de comic-text-detector completada!")

# ==========================================================
# 1. MOTOR INTOCABLE: GLOBOS DE DIÁLOGO BLANCOS SÓLIDOS (YOLO)
# ==========================================================
def agrupar_columnas_con_furigana(raw_cols):
    raw_cols.sort(key=lambda r: r[0])
    merged = []
    i = 0
    while i < len(raw_cols):
        curr = raw_cols[i]
        if i + 1 < len(raw_cols):
            nxt = raw_cols[i+1]
            nw = nxt[2] - nxt[0]
            gap = nxt[0] - curr[2]
            y_overlap = max(0, min(curr[3], nxt[3]) - max(curr[1], nxt[1]))
            if nw <= 22 and gap <= 8 and y_overlap > 10:
                merged_col = [curr[0], min(curr[1], nxt[1]), nxt[2], max(curr[3], nxt[3])]
                merged.append(merged_col)
                i += 2
                continue
        merged.append(curr)
        i += 1
    return merged

def extraer_forma_globo_y_rectangulos(crop):
    ch, cw = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    med = float(np.median(gray))
    std = float(np.std(gray))
    
    if med > 140:
        _, bin_bubble = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    else:
        _, bin_bubble = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)
        
    cnts_b, _ = cv2.findContours(bin_bubble, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    poly_globo = None
    if cnts_b:
        c_max = max(cnts_b, key=cv2.contourArea)
        if cv2.contourArea(c_max) > (cw * ch * 0.20):
            peri = cv2.arcLength(c_max, True)
            poly_globo = cv2.approxPolyDP(c_max, 0.012 * peri, True)
            
    if med > 140:
        _, thresh = cv2.threshold(gray, min(200, med - 25), 255, cv2.THRESH_BINARY_INV)
    else:
        _, thresh = cv2.threshold(gray, max(50, med + 25), 255, cv2.THRESH_BINARY)
        
    num, labels, stats, _ = cv2.connectedComponentsWithStats(thresh)
    margin = 4
    text_mask = np.zeros((ch, cw), dtype=np.uint8)
    valid_comps = []
    
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if area < 6 or area > (cw * ch * 0.45): continue
        if x <= margin or y <= margin or (x + w) >= (cw - margin) or (y + h) >= (ch - margin): continue
        text_mask[labels == i] = 255
        valid_comps.append((x, y, w, h))
        
    if not valid_comps:
        return [], poly_globo, 'vacio', False, med
        
    all_x1 = min(c[0] for c in valid_comps)
    all_y1 = min(c[1] for c in valid_comps)
    all_x2 = max(c[0] + c[2] for c in valid_comps)
    all_y2 = max(c[1] + c[3] for c in valid_comps)
    tot_w = all_x2 - all_x1
    tot_h = all_y2 - all_y1
    
    es_horizontal = (tot_w > tot_h * 1.35) and (tot_h < 130)
    rects = []
    
    if es_horizontal:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (16, 2))
        line_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, kernel)
        cnts_l, _ = cv2.findContours(line_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts_l:
            x, y, w, h = cv2.boundingRect(c)
            if w >= 8 and h >= 5:
                rects.append([max(0, x-2), max(0, y-2), min(cw, x+w+2), min(ch, y+h+2)])
        rects.sort(key=lambda r: r[1])
        ori = 'horizontal'
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 16))
        col_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, kernel)
        cnts_c, _ = cv2.findContours(col_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        raw_cols = []
        for c in cnts_c:
            x, y, w, h = cv2.boundingRect(c)
            if w >= 4 and h >= 8:
                raw_cols.append([x, y, x + w, y + h])
                
        cols = agrupar_columnas_con_furigana(raw_cols)
        cols.sort(key=lambda r: -r[0])
        for r in cols:
            rects.append([max(0, r[0]-2), max(0, r[1]-2), min(cw, r[2]+2), min(ch, r[3]+2)])
        ori = 'vertical'
        
    min_m = min(all_x1, cw - all_x2, all_y1, ch - all_y2)
    desborda = (min_m <= 4) or (std > 35 and cw > 350)
    
    return rects, poly_globo, ori, desborda, med

# ==========================================================
# 2. MOTOR DE PRECISIÓN MILIMÉTRICA: TEXTOS FUERA DE GLOBOS,
# TÉCNICAS, CARTELES Y KANJIS CHIQUITOS (COMIC-TEXT-DETECTOR)
# ==========================================================
def expandir_linea_con_seg(linea, seg_map, img_w, img_h, es_horizontal=False):
    """
    Expande los límites de la línea detectada por DBNet usando la segmentación
    real de caracteres de Comic-Text-Detector (UNet Seg) para asegurar que:
    - No se corte el inicio (ej. comillas 『, kanjis iniciales).
    - No se corte el final (ej. comillas 』, katakana ン o signos ！).
    - No se corte el furigana lateral o superior (kanjis chiquitos).
    """
    lx1, ly1, lx2, ly2 = linea
    if es_horizontal:
        sx1 = max(0, lx1 - 35)
        sy1 = max(0, ly1 - 18)
        sx2 = min(img_w, lx2 + 35)
        sy2 = min(img_h, ly2 + 18)
    else:
        sx1 = max(0, lx1 - 22)
        sy1 = max(0, ly1 - 38)
        sx2 = min(img_w, lx2 + 22)
        sy2 = min(img_h, ly2 + 38)
        
    sub_seg = seg_map[sy1:sy2, sx1:sx2]
    ys, xs = np.where(sub_seg > 0.14)
    if len(ys) > 15:
        rx1 = sx1 + int(xs.min())
        ry1 = sy1 + int(ys.min())
        rx2 = sx1 + int(xs.max())
        ry2 = sy1 + int(ys.max())
        return [max(0, rx1 - 3), max(0, ry1 - 3), min(img_w, rx2 + 3), min(img_h, ry2 + 3)]
    return [max(0, lx1 - 3), max(0, ly1 - 3), min(img_w, lx2 + 3), min(img_h, ly2 + 3)]

def extraer_lineas_zona_outside(crop_box, det_map, seg_map, img_w, img_h):
    gx1, gy1, gx2, gy2 = crop_box
    sub_det = det_map[gy1:gy2, gx1:gx2]
    ch, cw = sub_det.shape[:2]
    
    k_check = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 2))
    cnts_chk, _ = cv2.findContours(cv2.morphologyEx((sub_det > 0.20).astype(np.uint8) * 255, cv2.MORPH_CLOSE, k_check), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    es_horizontal = any((cv2.boundingRect(c)[2] > cv2.boundingRect(c)[3] * 1.6 and cv2.boundingRect(c)[2] > 50) for c in cnts_chk) or ((cw > ch * 1.20) and (ch < 220))
    
    line_thresh = (sub_det > 0.20).astype(np.uint8) * 255
    if es_horizontal:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 2))
    else:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 28))
    m = cv2.morphologyEx(line_thresh, cv2.MORPH_CLOSE, k)
    
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    raw_lines = []
    for c in cnts:
        if cv2.contourArea(c) > 50:
            x, y, w, h = cv2.boundingRect(c)
            if w < 5 or h < 5: continue
            raw_lines.append([gx1 + x, gy1 + y, gx1 + x + w, gy1 + y + h])
            
    if not raw_lines:
        return []
        
    # Expandir cada columna/línea con el mapa de caracteres seg_map
    cols_expandidas = []
    for l in raw_lines:
        exp = expandir_linea_con_seg(l, seg_map, img_w, img_h, es_horizontal=es_horizontal)
        cols_expandidas.append(exp)
        
    # Fusionar componentes fuertemente solapados o furigana residual
    if es_horizontal:
        cols_expandidas.sort(key=lambda r: r[1])
        merged = []
        i = 0
        while i < len(cols_expandidas):
            cur = cols_expandidas[i]
            if i + 1 < len(cols_expandidas):
                nxt = cols_expandidas[i+1]
                gap_y = nxt[1] - cur[3]
                x_ov = max(0, min(cur[2], nxt[2]) - max(cur[0], nxt[0]))
                if gap_y <= 6 and x_ov > 20:
                    merged.append([min(cur[0], nxt[0]), min(cur[1], nxt[1]), max(cur[2], nxt[2]), max(cur[3], nxt[3])])
                    i += 2
                    continue
            merged.append(cur)
            i += 1
    else:
        cols_expandidas.sort(key=lambda r: r[0])
        merged = []
        i = 0
        while i < len(cols_expandidas):
            cur = cols_expandidas[i]
            if i + 1 < len(cols_expandidas):
                nxt = cols_expandidas[i+1]
                x_ov = max(0, min(cur[2], nxt[2]) - max(cur[0], nxt[0]))
                y_ov = max(0, min(cur[3], nxt[3]) - max(cur[1], nxt[1]))
                gap_x = nxt[0] - cur[2]
                if (x_ov > 5 or gap_x <= 6) and y_ov > 20:
                    merged.append([min(cur[0], nxt[0]), min(cur[1], nxt[1]), max(cur[2], nxt[2]), max(cur[3], nxt[3])])
                    i += 2
                    continue
            merged.append(cur)
            i += 1
        merged.sort(key=lambda r: -r[0])
        
    return merged

def nms_boxes(boxes, iou_thresh=0.45):
    if not boxes: return []
    boxes = sorted(boxes, key=lambda b: -b['conf'])
    selected = []
    for b in boxes:
        keep = True
        bx1, by1, bx2, by2 = b['coords']
        area_b = (bx2 - bx1) * (by2 - by1)
        for s in selected:
            sx1, sy1, sx2, sy2 = s['coords']
            area_s = (sx2 - sx1) * (sy2 - sy1)
            ix1, iy1 = max(bx1, sx1), max(by1, sy1)
            ix2, iy2 = min(bx2, sx2), min(by2, sy2)
            iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
            inter = iw * ih
            containment = inter / float(min(area_b, area_s) + 1e-6)
            iou = inter / float(area_b + area_s - inter + 1e-6)
            if iou > iou_thresh or containment > 0.60:
                keep = False
                break
        if keep:
            selected.append(b)
    return selected

# ==========================================================
# 3. PIPELINE UNIFICADO
# ==========================================================
def procesar_pagina(img_path, yolo_model, comic_session, return_maps=False, *, img=None, pre_det_seg=None, pre_yolo=None):
    nombre = os.path.basename(img_path)
    log(f"Detectando textos: {nombre}")
    if img is None:
        img = cv2.imread(img_path)
    if img is None: return None
    h, w = img.shape[:2]
    
    # 1. Inferencia DBNet + UNet Seg de Comic-Text-Detector
    if pre_det_seg is not None:
        seg_map, det_map = pre_det_seg
    else:
        resized = cv2.resize(img, (1024, 1024))
        inp = (resized.astype(np.float32) / 255.0).transpose((2, 0, 1))[None, ...]
        blk, seg, det = comic_session.run(None, {'images': inp})
        seg_map = cv2.resize(seg[0, 0], (w, h))
        det_map = cv2.resize(det[0, 0], (w, h))
    
    zonas = []
    id_zona = 1
    
    # 2. Inferencia YOLO para detectar diálogos, globos y técnicas (omitiendo SFX)
    res_yolo = pre_yolo if pre_yolo is not None else yolo_model(img, conf=0.35, verbose=False)[0]
    
    raw_boxes = []
    for b in res_yolo.boxes:
        coords = [int(x) for x in b.xyxy[0].tolist()]
        conf = float(b.conf[0])
        raw_boxes.append({'coords': coords, 'conf': conf})
        
    # Aplicar NMS para evitar zonas duplicadas
    boxes_filtradas = nms_boxes(raw_boxes, iou_thresh=0.45)
    # El detector de globos omite cartelas y narracion horizontal. Recuperar
    # lineas de CTD fuera de sus cajas, usando la misma inferencia de la pagina.
    covered=np.zeros((h,w),dtype=np.uint8)
    for b in boxes_filtradas:
        x1,y1,x2,y2=b['coords'];covered[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]=1
    cnts,_=cv2.findContours((det_map>.25).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        x,y,cw,ch=cv2.boundingRect(c)
        if cw<8 or ch<8 or cv2.contourArea(c)<80:continue
        if np.mean(covered[y:y+ch,x:x+cw])>.45:continue
        if np.count_nonzero(seg_map[y:y+ch,x:x+cw]>.1)<20:continue
        pad=24
        boxes_filtradas.append({'coords':[max(0,x-pad),max(0,y-pad),min(w,x+cw+pad),min(h,y+ch+pad)],'conf':.25})
    
    for item in boxes_filtradas:
        coords = item['coords']
        gx1, gy1 = max(0, coords[0]), max(0, coords[1])
        gx2, gy2 = min(w, coords[2]), min(h, coords[3])
        gw, gh = gx2 - gx1, gy2 - gy1
        if gw < 15 or gh < 15: continue
        crop = img[gy1:gy2, gx1:gx2]
        if crop.size == 0: continue
        
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        med = float(np.median(gray))
        _, bin_w = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
        cnts_w, _ = cv2.findContours(bin_w, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        max_area_w = max([cv2.contourArea(c) for c in cnts_w]) if cnts_w else 0
        ratio_w = max_area_w / (crop.shape[0] * crop.shape[1])
        
        # Criterio estricto de GLOBO BLANCO SÓLIDO (Intocable)
        # Debe tener fondo blanco uniforme con ratio >= 0.70 y med >= 200
        es_globo_solido = (med >= 200 and ratio_w >= 0.70)
        
        if es_globo_solido:
            rects, poly, ori, desborda, _ = extraer_forma_globo_y_rectangulos(crop)
            # El fondo decide la limpieza; horizontal/vertical no cambia el metodo.
            if rects and poly is not None:
                poly_abs = [[int(pt[0][0] + gx1), int(pt[0][1] + gy1)] for pt in poly] if poly is not None else []
                rects_abs = [[int(gx1 + r[0]), int(gy1 + r[1]), int(gx1 + r[2]), int(gy1 + r[3])] for r in rects]
                
                zonas.append({
                    "id": int(id_zona),
                    "tipo": "dialogo_blanco",
                    "origen": "globo_solido_yolo",
                    "orientacion": ori,
                    "box_contenedor": [int(gx1), int(gy1), int(gx2), int(gy2)],
                    "poligono_contenedor": poly_abs,
                    "rectangulos_texto": rects_abs,
                    "desborda": False
                })
                id_zona += 1
                continue
                
        # ZONAS FUERA DE GLOBOS SÓLIDOS (Técnicas, textos en tramas, diálogos flotantes, carteles)
        cols = extraer_lineas_zona_outside([gx1, gy1, gx2, gy2], det_map, seg_map, w, h)
        if cols:
            all_x1 = min(c[0] for c in cols)
            all_y1 = min(c[1] for c in cols)
            all_x2 = max(c[2] for c in cols)
            all_y2 = max(c[3] for c in cols)
            
            pad_gen = 12
            cx1 = max(0, all_x1 - pad_gen)
            cy1 = max(0, all_y1 - pad_gen)
            cx2 = min(w, all_x2 + pad_gen)
            cy2 = min(h, all_y2 + pad_gen)
            
            zonas.append({
                "id": int(id_zona),
                "tipo": "relleno_generativo",
                "origen": "texto_fuera_comic_detector",
                "box_contenedor": [int(cx1), int(cy1), int(cx2), int(cy2)],
                "rectangulos_texto": cols,
                "desborda": True
            })
            id_zona += 1
            
    log(f"Completado {nombre}: {len(zonas)} zonas candidatas.")
    result={"archivo": nombre, "ruta": img_path, "w": int(w), "h": int(h), "zonas": zonas}
    return (result,seg_map) if return_maps else result

def generar_diagnostico_visual(paginas_data):
    for info in paginas_data:
        nombre = info["archivo"]
        img = cv2.imread(info["ruta"])
        vis = img.copy()
        
        for z in info["zonas"]:
            origen = z.get("origen")
            
            if origen == "globo_solido_yolo":
                # Silueta exacta en CYAN
                poly = z.get("poligono_contenedor")
                if poly and len(poly) > 2:
                    pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(vis, [pts], True, (255, 200, 0), 2, cv2.LINE_AA)
                else:
                    gx1, gy1, gx2, gy2 = z["box_contenedor"]
                    cv2.rectangle(vis, (gx1, gy1), (gx2, gy2), (255, 200, 0), 2)
                    
                # Columnas en MORADO ceñidas en escalera
                color_morado = (220, 20, 200)
                for r in z["rectangulos_texto"]:
                    rx1, ry1, rx2, ry2 = r
                    cv2.rectangle(vis, (rx1, ry1), (rx2, ry2), color_morado, 2)
            else:
                # Textos fuera de globos (Comic-Text-Detector):
                # 1. Margen General Exterior en CYAN (12px)
                bx1, by1, bx2, by2 = z["box_contenedor"]
                cv2.rectangle(vis, (bx1, by1), (bx2, by2), (255, 200, 0), 2)
                
                # 2. Líneas interiores ceñidas en ROJO (3px) con kanjis y furigana completos
                for r in z["rectangulos_texto"]:
                    rx1, ry1, rx2, ry2 = r
                    cv2.rectangle(vis, (rx1, ry1), (rx2, ry2), (0, 0, 255), 2)
                
        out_p = os.path.join(DIAG_DIR, f"TRAZADO_COLUMNAS_{nombre}")
        cv2.imwrite(out_p, vis)
        log(f"Diagnóstico guardado: {out_p}")
        
    # Generar zooms de verificación automática
    img5 = cv2.imread(os.path.join(DIAG_DIR, "TRAZADO_COLUMNAS_005.jpg"))
    if img5 is not None:
        h5 = img5.shape[0]
        cv2.imwrite(os.path.join(DIAG_DIR, "PREVIEW_ZOOM_005_TECHNIQUES.jpg"), img5[int(h5*0.02):int(h5*0.50), :])
        
    img4 = cv2.imread(os.path.join(DIAG_DIR, "TRAZADO_COLUMNAS_004.jpg"))
    if img4 is not None:
        h4 = img4.shape[0]
        cv2.imwrite(os.path.join(DIAG_DIR, "PREVIEW_ZOOM_004_NUN.jpg"), img4[int(h4*0.0):int(h4*0.85), :])
        cv2.imwrite(os.path.join(DIAG_DIR, "PREVIEW_ZOOM_004_CARD.jpg"), img4[int(h4*0.75):int(h4*1.0), :])
        
    img2 = cv2.imread(os.path.join(DIAG_DIR, "TRAZADO_COLUMNAS_002.jpg"))
    if img2 is not None:
        h2 = img2.shape[0]
        cv2.imwrite(os.path.join(DIAG_DIR, "PREVIEW_ZOOM_002.jpg"), img2[int(h2*0.1):int(h2*0.55), :])
        
    img1 = cv2.imread(os.path.join(DIAG_DIR, "TRAZADO_COLUMNAS_001.jpg"))
    if img1 is not None:
        h1 = img1.shape[0]
        cv2.imwrite(os.path.join(DIAG_DIR, "PREVIEW_ZOOM_001.jpg"), img1[int(h1*0.0):int(h1*0.60), :])
    log("Previsualizaciones de zoom actualizadas.")

if __name__ == "__main__":
    import sys
    if '--diagnostico' not in sys.argv:
        from limpieza_rapida import main
        main(sys.argv[1:]);raise SystemExit(0)
    t_start = time.time()
    log("==================================================")
    log("INICIANDO MANGA PIPELINE HÍBRIDO (PRECISIÓN MILIMÉTRICA + SIN SFX)")
    log("==================================================")
    
    import onnxruntime as ort
    from ultralytics import YOLO
    asegurar_comic_detector()
    yolo = YOLO(YOLO_MODEL_PATH)
    comic_session = ort.InferenceSession(COMIC_DETECTOR_PATH, providers=['CPUExecutionProvider'])
    
    imagenes = sorted(glob.glob(os.path.join(RAW_DIR, "*.*")))
    paginas = [img for img in imagenes if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    
    paginas_info = []
    for p in paginas:
        info = procesar_pagina(p, yolo, comic_session)
        if info:
            paginas_info.append(info)
            
    manifest_path = os.path.join(WORK_DIR, "zonas_limpieza_columnas.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(paginas_info, f, ensure_ascii=False, indent=2)
    log(f"Manifiesto guardado en: {manifest_path}")
    
    generar_diagnostico_visual(paginas_info)
    
    log(f"¡PROCESO FINALIZADO EN {time.time() - t_start:.2f} SEGUNDOS!")
    log("==================================================")
