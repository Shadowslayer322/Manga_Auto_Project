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
                merged_col = [min(curr[0], nxt[0]), min(curr[1], nxt[1]), max(curr[2], nxt[2]), max(curr[3], nxt[3])]
                merged.append(merged_col)
                i += 2
                continue
        merged.append(curr)
        i += 1
    return merged

def extraer_forma_globo_y_rectangulos(crop, sub_seg=None, sub_det=None):
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
    border_touch = 0.0
    if cnts_b:
        c_max = max(cnts_b, key=cv2.contourArea)
        if cv2.contourArea(c_max) > (cw * ch * 0.20):
            peri = cv2.arcLength(c_max, True)
            poly_globo = cv2.approxPolyDP(c_max, 0.012 * peri, True)
            pmask_tmp = np.zeros((ch, cw), dtype=np.uint8)
            cv2.fillPoly(pmask_tmp, [poly_globo], 255)
            perim = np.concatenate([pmask_tmp[0, :], pmask_tmp[-1, :], pmask_tmp[:, 0], pmask_tmp[:, -1]])
            border_touch = float(np.mean(perim > 0))
            
    if med > 140:
        _, thresh = cv2.threshold(gray, min(200, med - 25), 255, cv2.THRESH_BINARY_INV)
    else:
        _, thresh = cv2.threshold(gray, max(50, med + 25), 255, cv2.THRESH_BINARY)
        
    num, labels, stats, _ = cv2.connectedComponentsWithStats(thresh)
    has_real_seg = sub_seg is not None and float(sub_seg.min()) < 0.5
    text_mask = np.zeros((ch, cw), dtype=np.uint8)
    valid_comps = []
    
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if area > (cw * ch * 0.45): continue
        if area < 6:
            if not (has_real_seg and area >= 3 and float(np.mean(sub_seg[labels == i] > 0.15)) >= 0.50):
                continue
        if x <= 1 or y <= 1 or (x + w) >= (cw - 1) or (y + h) >= (ch - 1):
            if w > cw * 0.60 or h > ch * 0.60 or area > (cw * ch * 0.18):
                continue
            if has_real_seg:
                overlap = float(np.count_nonzero((sub_seg > 0.10) & (labels == i))) / max(1, area)
                if overlap < 0.15:
                    continue
            else:
                continue
        elif not has_real_seg:
            if x <= 4 or y <= 4 or (x + w) >= (cw - 4) or (y + h) >= (ch - 4):
                continue
        elif border_touch > 0.50:
            overlap = float(np.count_nonzero((sub_seg > 0.10) & (labels == i))) / max(1, area)
            if overlap < 0.15:
                continue
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
        line_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        cnts_l, _ = cv2.findContours(line_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts_l:
            x, y, w, h = cv2.boundingRect(c)
            if w >= 8 and h >= 5:
                rects.append([max(0, x-2), max(0, y-2), min(cw, x+w+2), min(ch, y+h+2)])
        rects.sort(key=lambda r: r[1])
        ori = 'horizontal'
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 16))
        col_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        cnts_c, _ = cv2.findContours(col_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        raw_cols = []
        for c in cnts_c:
            x, y, w, h = cv2.boundingRect(c)
            if (w >= 4 and h >= 8) or (w >= 2 and h >= 22 and (not has_real_seg or float(sub_seg[y:y+h, x:x+w].max()) >= 0.25)):
                raw_cols.append([x, y, x + w, y + h])
                
        cols = agrupar_columnas_con_furigana(raw_cols)
        cols.sort(key=lambda r: -r[0])
        for r in cols:
            rects.append([max(0, r[0]-2), max(0, r[1]-2), min(cw, r[2]+2), min(ch, r[3]+2)])
        ori = 'vertical'

    if has_real_seg and rects:
        filtered_rects = [
            r for r in rects
            if not (float(sub_seg[r[1]:r[3], r[0]:r[2]].max()) < 0.20
                    and int(np.count_nonzero(sub_seg[r[1]:r[3], r[0]:r[2]] > 0.10)) < 10)
        ]
        if filtered_rects:
            rects = filtered_rects
        if sub_det is not None and len(rects) > 1:
            strong_rects = [r for r in rects if float(sub_det[r[1]:r[3], r[0]:r[2]].max()) >= 0.35]
            if strong_rects:
                kept = []
                for r in rects:
                    d_r = float(sub_det[r[1]:r[3], r[0]:r[2]].max())
                    if d_r >= 0.18:
                        kept.append(r)
                    else:
                        # Conservar únicamente si es furigana/signo pegado a una columna fuerte
                        near_strong = any(
                            max(0, min(r[3], sr[3]) - max(r[1], sr[1])) > 10
                            and max(0, max(sr[0] - r[2], r[0] - sr[2])) <= 12
                            and (r[2] - r[0]) <= 26
                            for sr in strong_rects
                        )
                        if near_strong:
                            kept.append(r)
                if kept:
                    rects = kept
        
    min_m = min(all_x1, cw - all_x2, all_y1, ch - all_y2)
    desborda = (min_m <= 4) or (std > 35 and cw > 350)
    
    return rects, poly_globo, ori, desborda, med

# ==========================================================
# 2. MOTOR DE PRECISIÓN MILIMÉTRICA: TEXTOS FUERA DE GLOBOS,
# TÉCNICAS, CARTELES Y KANJIS CHIQUITOS (COMIC-TEXT-DETECTOR)
# ==========================================================
def expandir_linea_con_seg(linea, seg_map, img_w, img_h, es_horizontal=False, bounds=None):
    """
    Expande los límites de la línea detectada por DBNet usando la segmentación
    real de caracteres de Comic-Text-Detector (UNet Seg) conectada al núcleo de la línea.
    """
    lx1, ly1, lx2, ly2 = linea
    if es_horizontal:
        sx1 = max(0, lx1 - 24)
        sy1 = max(0, ly1 - 14)
        sx2 = min(img_w, lx2 + 24)
        sy2 = min(img_h, ly2 + 14)
    else:
        sx1 = max(0, lx1 - 16)
        sy1 = max(0, ly1 - 24)
        sx2 = min(img_w, lx2 + 16)
        sy2 = min(img_h, ly2 + 24)
    if bounds is not None:
        bx1, by1, bx2, by2 = bounds
        sx1 = max(sx1, max(0, bx1))
        sy1 = max(sy1, max(0, by1))
        sx2 = min(sx2, min(img_w, bx2))
        sy2 = min(sy2, min(img_h, by2))
    if sx2 <= sx1 or sy2 <= sy1:
        return [max(0, lx1 - 3), max(0, ly1 - 3), min(img_w, lx2 + 3), min(img_h, ly2 + 3)]
        
    sub_seg = seg_map[sy1:sy2, sx1:sx2]
    seg_bin = (sub_seg > 0.16).astype(np.uint8)
    core = np.zeros_like(seg_bin)
    cx1 = max(0, lx1 - sx1 - (6 if es_horizontal else 10))
    cy1 = max(0, ly1 - sy1 - (10 if es_horizontal else 6))
    cx2 = min(sx2 - sx1, lx2 - sx1 + (6 if es_horizontal else 10))
    cy2 = min(sy2 - sy1, ly2 - sy1 + (10 if es_horizontal else 6))
    core[cy1:cy2, cx1:cx2] = 1
    n_c, lbl, _, _ = cv2.connectedComponentsWithStats(seg_bin)
    keep = np.zeros(n_c, dtype=bool)
    for ci in range(1, n_c):
        if np.any((lbl == ci) & (core > 0)):
            keep[ci] = True
    ys, xs = np.where(keep[lbl])
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
    sub_seg = seg_map[gy1:gy2, gx1:gx2]
    ch, cw = sub_det.shape[:2]
    
    det_bin = (sub_det > 0.20)
    if float(sub_seg.min()) < 0.5:
        n_det_px = int(np.count_nonzero(det_bin))
        if n_det_px < 30:
            det_bin = det_bin | (sub_seg > (0.15 if (cw > ch * 2.5 and int(np.count_nonzero(sub_seg > 0.15)) >= 120) else 0.30))
        else:
            det_near = cv2.dilate(det_bin.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
            det_bin = det_bin | ((sub_seg > 0.45) & det_near)
    k_check = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 2))
    cnts_chk, _ = cv2.findContours(cv2.morphologyEx(det_bin.astype(np.uint8) * 255, cv2.MORPH_CLOSE, k_check), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    es_horizontal = any((cv2.boundingRect(c)[2] > cv2.boundingRect(c)[3] * 1.6 and cv2.boundingRect(c)[2] > 50) for c in cnts_chk) or ((cw > ch * 1.20) and (ch < 220))
    
    line_thresh = det_bin.astype(np.uint8) * 255
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

    if len(raw_lines) > 1 and any(float(det_map[ry1:ry2, rx1:rx2].max()) >= 0.35 for rx1, ry1, rx2, ry2 in raw_lines):
        filtered_raw = [
            [rx1, ry1, rx2, ry2]
            for rx1, ry1, rx2, ry2 in raw_lines
            if float(det_map[ry1:ry2, rx1:rx2].max()) >= 0.18
        ]
        if filtered_raw:
            raw_lines = filtered_raw
            
    if not raw_lines:
        return []
        
    # Expandir cada columna/línea con el mapa de caracteres seg_map
    cols_expandidas = []
    bounds = [gx1 - 6, gy1 - 6, gx2 + 6, gy2 + 6]
    for l in raw_lines:
        exp = expandir_linea_con_seg(l, seg_map, img_w, img_h, es_horizontal=es_horizontal, bounds=bounds)
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

def decodificar_bloques_ctd(blk, w, h, conf_th=0.45):
    if blk is None:
        return []
    arr = blk[0]
    if len(arr) == 0:
        return []
    scores = arr[:, 4] * np.max(arr[:, 5:], axis=1) if arr.shape[1] >= 6 else arr[:, 4]
    keep = scores >= conf_th
    arr = arr[keep]
    scores = scores[keep]
    raw = []
    for row, sc in zip(arr, scores):
        cx, cy, bw, bh = row[:4]
        x1 = max(0, int((cx - bw / 2) * w / 1024))
        y1 = max(0, int((cy - bh / 2) * h / 1024))
        x2 = min(w, int((cx + bw / 2) * w / 1024))
        y2 = min(h, int((cy + bh / 2) * h / 1024))
        if x2 > x1 + 4 and y2 > y1 + 4:
            raw.append({'coords': [x1, y1, x2, y2], 'conf': float(sc)})
    return nms_boxes(raw, iou_thresh=0.45)


# ==========================================================
# 3. PIPELINE UNIFICADO
# ==========================================================
def procesar_pagina(img_path, yolo_model, comic_session, return_maps=False, *, img=None, pre_det_seg=None, pre_yolo=None):
    from limpieza_rapida import flat_white_background
    nombre = os.path.basename(img_path)
    log(f"Detectando textos: {nombre}")
    if img is None:
        img = cv2.imread(img_path)
    if img is None: return None
    h, w = img.shape[:2]
    
    # 1. Inferencia DBNet + UNet Seg + Blk de Comic-Text-Detector
    blk = None
    if pre_det_seg is not None:
        if len(pre_det_seg) == 3:
            seg_map, det_map, blk = pre_det_seg
        else:
            seg_map, det_map = pre_det_seg
    else:
        resized = cv2.resize(img, (1024, 1024))
        inp = (resized.astype(np.float32) / 255.0).transpose((2, 0, 1))[None, ...]
        blk, seg, det = comic_session.run(None, {'images': inp})
        seg_map = cv2.resize(seg[0, 0], (w, h))
        det_map = cv2.resize(det[0, 0], (w, h))
    
    zonas = []
    id_zona = 1
    has_real_seg = float(seg_map.min()) < 0.5
    ctd_blks = decodificar_bloques_ctd(blk, w, h, conf_th=0.45) if blk is not None else []
    
    # 2. Inferencia YOLO para detectar diálogos, globos y técnicas (omitiendo SFX)
    res_yolo = pre_yolo if pre_yolo is not None else yolo_model(img, conf=0.35, verbose=False)[0]
    
    raw_boxes = []
    for b in res_yolo.boxes:
        coords = [int(x) for x in b.xyxy[0].tolist()]
        conf = float(b.conf[0])
        x1, y1, x2, y2 = max(0, coords[0]), max(0, coords[1]), min(w, coords[2]), min(h, coords[3])
        if x2 <= x1 + 4 or y2 <= y1 + 4:
            continue
        if blk is not None and has_real_seg:
            sub_s = seg_map[y1:y2, x1:x2]
            sub_d = det_map[y1:y2, x1:x2]
            spx = int(np.count_nonzero(sub_s > 0.25))
            dmax = float(sub_d.max()) if sub_d.size else 0.0
            d50 = int(np.count_nonzero(sub_d > 0.50))
            if spx < 50 or (dmax < 0.30 and d50 == 0):
                continue
            area = max(1, (x2 - x1) * (y2 - y1))
            max_ov = max(
                [max(0, min(x2, q['coords'][2]) - max(x1, q['coords'][0]))
                 * max(0, min(y2, q['coords'][3]) - max(y1, q['coords'][1])) / area
                 for q in ctd_blks],
                default=0.0,
            )
            if max_ov < 0.15 and d50 < 250 and spx >= 2000:
                sm = (sub_s > 0.35).astype(np.uint8)
                if np.any(sm) and float(np.percentile(cv2.distanceTransform(sm, cv2.DIST_L2, 5)[sm > 0], 85)) >= 4.8:
                    continue
            if conf < 0.55:
                if dmax < 0.82 or d50 < 120:
                    continue
                is_margin_banner = (y1 < 0.12 * h or y2 > 0.88 * h) and (x2 - x1) > 250 and (x2 - x1) / max(1, y2 - y1) > 4.5
                has_strong_det = (dmax >= 0.82 and d50 >= 250)
                if max_ov < 0.20 and not is_margin_banner and not has_strong_det:
                    continue
        raw_boxes.append({'coords': coords, 'conf': conf, 'from_yolo': True})
        
    # Aplicar NMS para evitar zonas duplicadas
    boxes_filtradas = nms_boxes(raw_boxes, iou_thresh=0.45)

    if blk is not None and ctd_blks:
        for item in boxes_filtradas:
            x1, y1, x2, y2 = item['coords']
            area_item = max(1, (x2 - x1) * (y2 - y1))
            for q in ctd_blks:
                if q['conf'] < 0.70:
                    continue
                qx1, qy1, qx2, qy2 = q['coords']
                area_q = max(1, (qx2 - qx1) * (qy2 - qy1))
                ix1, iy1 = max(x1, qx1), max(y1, qy1)
                ix2, iy2 = min(x2, qx2), min(y2, qy2)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                if inter / max(1, min(area_item, area_q)) >= 0.75:
                    ext = max(x1 - qx1, y1 - qy1, qx2 - x2, qy2 - y2)
                    if ext <= 18:
                        item['coords'] = [
                            max(0, min(x1, qx1 - 2)),
                            max(0, min(y1, qy1 - 2)),
                            min(w, max(x2, qx2 + 2)),
                            min(h, max(y2, qy2 + 2)),
                        ]
                        break
                    elif ext > 25:
                        exp_coords = [
                            max(0, min(x1, qx1 - 4)),
                            max(0, min(y1, qy1 - 4)),
                            min(w, max(x2, qx2 + 4)),
                            min(h, max(y2, qy2 + 4)),
                        ]
                        item['coords'] = exp_coords
                        exp_crop = img[exp_coords[1]:exp_coords[3], exp_coords[0]:exp_coords[2]]
                        exp_gray = cv2.cvtColor(exp_crop, cv2.COLOR_BGR2GRAY) if exp_crop.size else np.empty((0, 0), dtype=np.uint8)
                        if not (exp_gray.size and float(np.mean(exp_gray >= 245)) >= 0.70 and float(np.percentile(exp_gray, 25)) >= 240):
                            item['force_genfill'] = True
                        break
    
    def _procesar_item(item, id_z):
        coords = item['coords']
        from_yolo = item.get('from_yolo', True)
        gx1, gy1 = max(0, int(coords[0])), max(0, int(coords[1]))
        gx2, gy2 = min(w, int(coords[2])), min(h, int(coords[3]))
        gw, gh = gx2 - gx1, gy2 - gy1
        if gw < 15 or gh < 15: return None
        crop = img[gy1:gy2, gx1:gx2]
        if crop.size == 0: return None
        
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        med = float(np.median(gray))
        _, bin_w = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
        cnts_w, _ = cv2.findContours(bin_w, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        max_area_w = max([cv2.contourArea(c) for c in cnts_w]) if cnts_w else 0
        ratio_w = max_area_w / (crop.shape[0] * crop.shape[1])
        
        # Criterio estricto de GLOBO BLANCO SÓLIDO (validando trama real y contencion de texto)
        es_globo_solido = (
            not item.get('force_genfill', False)
            and med >= (200 if from_yolo else 230)
            and ratio_w >= (0.58 if from_yolo else 0.70)
        )
        
        if es_globo_solido:
            sub_seg_crop = seg_map[gy1:gy2, gx1:gx2]
            sub_det_crop = det_map[gy1:gy2, gx1:gx2]
            rects, poly, ori, desborda, _ = extraer_forma_globo_y_rectangulos(crop, sub_seg=sub_seg_crop, sub_det=sub_det_crop)
            flat_ok = False
            if rects and poly is not None and flat_white_background(gray, poly, rects=rects):
                flat_ok = True
                if has_real_seg:
                    pmask = np.zeros_like(gray)
                    cv2.fillPoly(pmask, [poly], 255)
                    rim = (cv2.dilate(pmask, np.ones((7, 7), np.uint8)) > 0) & (pmask == 0)
                    perim = np.concatenate([pmask[0, :], pmask[-1, :], pmask[:, 0], pmask[:, -1]])
                    border_touch = float(np.mean(perim > 0))
                    es_globo_cerrado = bool(
                        from_yolo and (
                            (np.count_nonzero(rim) >= 30 and float(np.median(gray[rim])) < 150)
                            or (border_touch < 0.12 and np.count_nonzero(rim) >= 30)
                        )
                    )
                    if not es_globo_cerrado:
                        seg_hi = sub_seg_crop > 0.25
                        n_seg = int(np.count_nonzero(seg_hi))
                        if n_seg >= 30 and np.count_nonzero(seg_hi & (pmask > 0)) / n_seg < 0.80:
                            flat_ok = False
            if flat_ok:
                poly_abs = [[int(pt[0][0] + gx1), int(pt[0][1] + gy1)] for pt in poly]
                rects_abs = [[int(gx1 + r[0]), int(gy1 + r[1]), int(gx1 + r[2]), int(gy1 + r[3])] for r in rects]
                
                return {
                    "id": int(id_z),
                    "tipo": "dialogo_blanco",
                    "origen": "globo_solido_yolo",
                    "from_yolo": bool(from_yolo),
                    "orientacion": ori,
                    "box_contenedor": [int(gx1), int(gy1), int(gx2), int(gy2)],
                    "poligono_contenedor": poly_abs,
                    "rectangulos_texto": rects_abs,
                    "desborda": False
                }
                
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
            
            return {
                "id": int(id_z),
                "tipo": "relleno_generativo",
                "origen": "texto_fuera_comic_detector",
                "from_yolo": bool(from_yolo),
                "box_contenedor": [int(cx1), int(cy1), int(cx2), int(cy2)],
                "rectangulos_texto": cols,
                "desborda": True
            }
        return None

    covered = np.zeros((h, w), dtype=np.uint8)
    def _registrar_zona(z):
        nonlocal id_zona
        if z is None:
            return
        zonas.append(z)
        id_zona += 1
        if z.get("poligono_contenedor"):
            cv2.fillPoly(covered, [np.asarray(z["poligono_contenedor"], dtype=np.int32)], 1)
        else:
            for rx1, ry1, rx2, ry2 in z.get("rectangulos_texto", []):
                covered[max(0, ry1 - 6):min(h, ry2 + 6), max(0, rx1 - 6):min(w, rx2 + 6)] = 1

    for item in boxes_filtradas:
        _registrar_zona(_procesar_item(item, id_zona))

    if blk is not None:
        img_gray_full = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 4a. Bloques de alta confianza de CTD (sin absorber SFX sueltas)
        for cb in ctd_blks:
            bx1, by1, bx2, by2 = cb['coords']
            if has_real_seg:
                sub_s_cb = seg_map[by1:by2, bx1:bx2]
                sub_d_cb = det_map[by1:by2, bx1:bx2]
                spx_cb = int(np.count_nonzero(sub_s_cb > 0.25))
                dmax_cb = float(sub_d_cb.max()) if sub_d_cb.size else 0.0
                d50_cb = int(np.count_nonzero(sub_d_cb > 0.50))
                if dmax_cb < 0.30 and d50_cb == 0:
                    continue
                if cb['conf'] < 0.60 and d50_cb < 120 and (d50_cb / max(1, spx_cb)) < 0.08:
                    continue
                sm_cb = (sub_s_cb > 0.35).astype(np.uint8)
                if np.any(sm_cb):
                    seg_p85_cb = float(np.percentile(cv2.distanceTransform(sm_cb, cv2.DIST_L2, 5)[sm_cb > 0], 85))
                    if seg_p85_cb >= 6.0:
                        if d50_cb / max(1, spx_cb) < 0.08:
                            continue
                        sub_g_cb = img_gray_full[by1:by2, bx1:bx2]
                        dfg_cb = ((sub_g_cb < 140) & (sub_s_cb > 0.15)).astype(np.uint8)
                        if np.any(dfg_cb) and float(np.percentile(cv2.distanceTransform(dfg_cb, cv2.DIST_L2, 5)[dfg_cb > 0], 85)) >= 5.0:
                            continue
            cov_mean = float(np.mean(covered[by1:by2, bx1:bx2]))
            if cov_mean > 0.45:
                uncov_seg = (seg_map[by1:by2, bx1:bx2] > 0.25) & (covered[by1:by2, bx1:bx2] == 0)
                n_uncov = int(np.count_nonzero(uncov_seg))
                if n_uncov >= 350 and float(det_map[by1:by2, bx1:bx2][uncov_seg].max()) > 0.50:
                    det50_ratio = int(np.count_nonzero((det_map[by1:by2, bx1:bx2] > 0.50) & uncov_seg)) / max(1, n_uncov)
                    if det50_ratio < 0.35:
                        continue
                    uy, ux = np.where(uncov_seg)
                    ux1, uy1 = bx1 + int(ux.min()), by1 + int(uy.min())
                    ux2, uy2 = bx1 + int(ux.max()), by1 + int(uy.max())
                    pad = 8
                    _registrar_zona(_procesar_item(
                        {'coords': [max(0, ux1 - pad), max(0, uy1 - pad), min(w, ux2 + pad), min(h, uy2 + pad)],
                         'conf': cb['conf'], 'from_yolo': False}, id_zona))
                continue
            cand_coords = [max(0, bx1 - 8), max(0, by1 - 8), min(w, bx2 + 8), min(h, by2 + 8)]
            if cov_mean > 0.15:
                uncov_seg = (seg_map[by1:by2, bx1:bx2] > 0.25) & (covered[by1:by2, bx1:bx2] == 0)
                if int(np.count_nonzero(uncov_seg)) >= 120:
                    uy, ux = np.where(uncov_seg)
                    ux1, uy1 = bx1 + int(ux.min()), by1 + int(uy.min())
                    ux2, uy2 = bx1 + int(ux.max()), by1 + int(uy.max())
                    cand_coords = [max(0, ux1 - 8), max(0, uy1 - 8), min(w, ux2 + 8), min(h, uy2 + 8)]
            _registrar_zona(_procesar_item(
                {'coords': cand_coords,
                 'conf': cb['conf'], 'from_yolo': False}, id_zona))

        # 4b. Banners horizontales en margenes superior/inferior
        banner_src = ((det_map > 0.22) | (seg_map > 0.40)).astype(np.uint8)
        det_h = cv2.dilate(banner_src, cv2.getStructuringElement(cv2.MORPH_RECT, (75, 5)))
        cnts_h, _ = cv2.findContours(det_h, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts_h:
            x, y, cw, ch = cv2.boundingRect(c)
            if cw > 220 and ch < 75 and (cw / max(1, ch)) > 3.8 and (y < 0.10 * h or (y + ch) > 0.90 * h):
                if np.mean(covered[y:y+ch, x:x+cw]) > 0.45:
                    continue
                pad = 12
                _registrar_zona(_procesar_item(
                    {'coords': [max(0, x - pad), max(0, y - pad), min(w, x + cw + pad), min(h, y + ch + pad)],
                     'conf': 0.30, 'from_yolo': False}, id_zona))

        # 4c. Respaldo para paginas vacias (ej. pág. 14 con texto corto aislado)
        if not zonas:
            for cb in decodificar_bloques_ctd(blk, w, h, conf_th=0.18):
                bx1, by1, bx2, by2 = cb['coords']
                if det_map[by1:by2, bx1:bx2].max() > 0.60 and np.count_nonzero(seg_map[by1:by2, bx1:bx2] > 0.14) >= 40:
                    pad = 12
                    _registrar_zona(_procesar_item(
                        {'coords': [max(0, bx1 - pad), max(0, by1 - pad), min(w, bx2 + pad), min(h, by2 + pad)],
                         'conf': cb['conf'], 'from_yolo': False}, id_zona))

        # 4c-2. Bloques manuscritos de trazo fino (0.06 <= conf < 0.45) sin capturar SFX gruesos ni titulos de cartel
        k5_h = np.ones((5, 5), np.uint8)
        k11_h = np.ones((11, 11), np.uint8)
        for cb in decodificar_bloques_ctd(blk, w, h, conf_th=0.06):
            if cb['conf'] >= 0.45:
                continue
            bx1, by1, bx2, by2 = cb['coords']
            if np.mean(covered[by1:by2, bx1:bx2]) > 0.35:
                continue
            ar = (bx2 - bx1) / max(1, by2 - by1)
            sub_det = det_map[by1:by2, bx1:bx2]
            sub_seg = seg_map[by1:by2, bx1:bx2]
            sub_g = img_gray_full[by1:by2, bx1:bx2]
            if ar > 2.8:
                if cb['conf'] >= 0.25 and ar >= 3.2 and by1 >= 0.88 * h and sub_g.size > 0:
                    med_p = float(np.median(sub_g))
                    if 130 <= med_p <= 190 and int(np.count_nonzero((sub_g > 220) & (sub_seg > 0.12))) >= 100:
                        pad = 8
                        _registrar_zona(_procesar_item(
                            {'coords': [max(0, bx1 - pad), max(0, by1 - pad), min(w, bx2 + pad), min(h, by2 + pad)],
                             'conf': cb['conf'], 'from_yolo': False}, id_zona))
                continue
            spx = int(np.count_nonzero(sub_seg > 0.25))
            dmax = float(sub_det.max())
            d50 = int(np.count_nonzero(sub_det > 0.50))
            sm = (sub_seg > 0.35).astype(np.uint8)
            if int(np.count_nonzero(sm)) == 0:
                continue
            seg_p85 = float(np.percentile(cv2.distanceTransform(sm, cv2.DIST_L2, 5)[sm > 0], 85))
            dark_fg = ((sub_g < 140) & (sub_seg > 0.15)).astype(np.uint8)
            if int(np.count_nonzero(dark_fg)) < 80:
                continue
            dark_p85 = float(np.percentile(cv2.distanceTransform(dark_fg, cv2.DIST_L2, 5)[dark_fg > 0], 85))
            cond_a = cb['conf'] >= 0.16 and dmax > 0.80 and d50 >= 200 and seg_p85 <= 3.1 and (d50 / max(1, spx)) >= 0.38 and dark_p85 <= 3.2
            cond_b = cb['conf'] >= 0.25 and dmax >= 0.60 and d50 >= 25 and seg_p85 <= 2.3 and dark_p85 <= 1.6 and spx >= 250
            cond_c = cb['conf'] >= 0.065 and ar <= 0.35 and spx >= 5500 and dmax >= 0.85 and d50 >= 500
            cond_d = cb['conf'] >= 0.10 and ar <= 0.55 and spx >= 500 and dmax >= 0.96 and d50 >= 200 and seg_p85 <= 2.2 and dark_p85 <= 1.0
            cond_e = False
            if cb['conf'] >= 0.06 and ar <= 0.55 and 500 <= spx <= 2500 and dmax >= 0.25 and seg_p85 <= 3.8 and dark_p85 <= 1.5:
                dfg_b = (sub_g < 130) & (sub_seg > 0.15)
                ring_halo = (cv2.dilate(dfg_b.astype(np.uint8), k5_h) > 0) & (~dfg_b)
                outer_bg = (cv2.dilate(dfg_b.astype(np.uint8), k11_h) == 0)
                if np.any(ring_halo) and np.any(outer_bg):
                    halo_w = float(np.mean(sub_g[ring_halo] >= 230))
                    outer_med = float(np.median(sub_g[outer_bg]))
                    if 140 <= outer_med <= 232 and halo_w >= 0.40:
                        cond_e = True
            if not (cond_a or cond_b or cond_c or cond_d or cond_e):
                continue
            pad = 8
            _registrar_zona(_procesar_item(
                {'coords': [max(0, bx1 - pad), max(0, by1 - pad), min(w, bx2 + pad), min(h, by2 + pad)],
                 'conf': cb['conf'], 'from_yolo': False}, id_zona))

        # 4c-3. Bloques verticales manuscritos finos omitidos por blk
        seg_u = ((seg_map > 0.30) & (covered == 0)).astype(np.uint8)
        seg_u_dil = cv2.dilate(seg_u, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 19)))
        n_su, su_lbl, su_stats, _ = cv2.connectedComponentsWithStats(seg_u_dil)
        for ui in range(1, n_su):
            ux, uy, uw, uh = [int(v) for v in su_stats[ui][:4]]
            if uh <= uw * 1.3:
                continue
            if float(np.mean(covered[uy:uy+uh, ux:ux+uw])) > 0.35:
                continue
            sub_seg = seg_map[uy:uy+uh, ux:ux+uw]
            sub_det = det_map[uy:uy+uh, ux:ux+uw]
            sub_g = img_gray_full[uy:uy+uh, ux:ux+uw]
            comp_roi = (su_lbl[uy:uy+uh, ux:ux+uw] == ui)
            spx = int(np.count_nonzero((sub_seg > 0.25) & comp_roi))
            if spx < 700:
                continue
            dmax = float(sub_det[comp_roi].max()) if np.any(comp_roi) else 0.0
            d50 = int(np.count_nonzero((sub_det > 0.50) & comp_roi))
            if dmax < 0.65 or d50 < 40:
                continue
            sm = ((sub_seg > 0.35) & comp_roi).astype(np.uint8)
            if int(np.count_nonzero(sm)) == 0:
                continue
            seg_p85 = float(np.percentile(cv2.distanceTransform(sm, cv2.DIST_L2, 5)[sm > 0], 85))
            if seg_p85 > 2.3:
                continue
            dark_fg = ((sub_g < 140) & (sub_seg > 0.15) & comp_roi).astype(np.uint8)
            if int(np.count_nonzero(dark_fg)) == 0:
                continue
            dark_p85 = float(np.percentile(cv2.distanceTransform(dark_fg, cv2.DIST_L2, 5)[dark_fg > 0], 85))
            if dark_p85 > 1.6:
                continue
            pad = 8
            _registrar_zona(_procesar_item(
                {'coords': [max(0, ux - pad), max(0, uy - pad), min(w, ux + uw + pad), min(h, uy + uh + pad)],
                 'conf': 0.25, 'from_yolo': False}, id_zona))

        # 4c-4. Bloques de pizarra/diagrama con DBNet alto sobre fondo oscuro uniforme
        det_u_hi = ((det_map > 0.35) & (covered == 0)).astype(np.uint8)
        det_u_dil = cv2.dilate(det_u_hi, cv2.getStructuringElement(cv2.MORPH_RECT, (35, 25)))
        n_du, _, du_stats, _ = cv2.connectedComponentsWithStats(det_u_dil)
        for di in range(1, n_du):
            dx, dy, dw, dh = [int(v) for v in du_stats[di][:4]]
            if float(np.mean(covered[dy:dy+dh, dx:dx+dw])) > 0.35:
                continue
            sub_d = det_map[dy:dy+dh, dx:dx+dw]
            sub_s = seg_map[dy:dy+dh, dx:dx+dw]
            sub_g = img_gray_full[dy:dy+dh, dx:dx+dw]
            d50 = int(np.count_nonzero((sub_d > 0.50) & (covered[dy:dy+dh, dx:dx+dw] == 0)))
            dmax = float(sub_d.max()) if sub_d.size else 0.0
            spx = int(np.count_nonzero(sub_s > 0.25))
            if dmax < 0.96 or d50 < 400 or spx < 1500:
                continue
            med_g = float(np.median(sub_g)) if sub_g.size else 0.0
            if not (60 <= med_g <= 95):
                continue
            dark_fg = ((sub_g < 140) & (sub_s > 0.15)).astype(np.uint8)
            if not np.any(dark_fg):
                continue
            dark_p85 = float(np.percentile(cv2.distanceTransform(dark_fg, cv2.DIST_L2, 5)[dark_fg > 0], 85))
            if dark_p85 > 2.1:
                continue
            pad = 6
            _registrar_zona(_procesar_item(
                {'coords': [max(0, dx - pad), max(0, dy - pad), min(w, dx + dw + pad), min(h, dy + dh + pad)],
                 'conf': 0.30, 'from_yolo': False}, id_zona))

        # 4d-estricto. Recuperacion quirurgica sin SFX:
        # (a) Titulos horizontales grandes con relleno blanco y contorno negro (ej. 久喜春希 en pág. 03)
        seg_h = ((seg_map > 0.30) & (covered == 0) & (det_map < 0.25)).astype(np.uint8)
        seg_h_dil = cv2.dilate(seg_h, cv2.getStructuringElement(cv2.MORPH_RECT, (49, 11)))
        n_sh, _, sh_stats, _ = cv2.connectedComponentsWithStats(seg_h_dil)
        k5 = np.ones((5, 5), np.uint8)
        for si in range(1, n_sh):
            sx, sy, sw, sh = [int(v) for v in sh_stats[si][:4]]
            if sw < 180 or (sw / max(1, sh)) < 1.55:
                continue
            seg_px = int(np.count_nonzero(seg_h[sy:sy+sh, sx:sx+sw]))
            if seg_px < 2000:
                continue
            if int(np.count_nonzero(det_map[sy:sy+sh, sx:sx+sw] >= 0.35)) >= 40:
                continue
            roi_g = img_gray_full[sy:sy+sh, sx:sx+sw]
            roi_s = seg_h[sy:sy+sh, sx:sx+sw] > 0
            white_ratio = float(np.mean(roi_g[roi_s] > 205)) if np.any(roi_s) else 0.0
            dark_ring = cv2.dilate(roi_s.astype(np.uint8), k5) > 0
            dark_px = int(np.count_nonzero((roi_g < 80) & dark_ring))
            if white_ratio < 0.25 or dark_px < 0.15 * seg_px:
                continue
            above_y1 = max(0, sy - 42)
            if above_y1 >= sy or int(np.count_nonzero(det_map[above_y1:sy, sx:sx+sw] > 0.70)) < 30:
                continue
            main_rect = [int(max(0, sx - 10)), int(max(0, sy - 6)), int(min(w, sx + sw + 10)), int(min(h, sy + sh + 10))]
            rects_title = [main_rect]
            furi_y1 = max(0, sy - 46)
            if furi_y1 < sy:
                ys_f, xs_f = np.where(det_map[furi_y1:sy, sx:sx+sw] > 0.35)
                if len(ys_f) > 0:
                    fy1 = int(max(0, furi_y1 + int(ys_f.min()) - 2))
                    fx1 = int(max(0, sx + int(0.18 * sw)))
                    fx2 = int(min(w, sx + int(xs_f.max()) + 10))
                    fy2 = int(sy)
                    if fx2 > fx1 and fy2 > fy1:
                        rects_title.append([fx1, fy1, fx2, fy2])
            all_x1 = min(r[0] for r in rects_title)
            all_y1 = min(r[1] for r in rects_title)
            all_x2 = max(r[2] for r in rects_title)
            all_y2 = max(r[3] for r in rects_title)
            pad_gen = 12
            _registrar_zona({
                "id": int(id_zona),
                "tipo": "relleno_generativo",
                "origen": "texto_fuera_comic_detector",
                "from_yolo": False,
                "estilo": "contorneado",
                "box_contenedor": [int(max(0, all_x1 - pad_gen)), int(max(0, all_y1 - pad_gen)),
                                   int(min(w, all_x2 + pad_gen)), int(min(h, all_y2 + pad_gen))],
                "rectangulos_texto": [[int(v) for v in r] for r in rects_title],
                "desborda": True,
            })

        # (b) Titulos a color de portada (ej. 元カノだから en pág. 01; inactivo en B&N)
        chroma_full = img.max(axis=2).astype(np.int16) - img.min(axis=2).astype(np.int16)
        if int(np.count_nonzero(chroma_full > 25)) >= 500:
            col_seed = (seg_map > 0.12) & (chroma_full > 22) & (covered == 0)
            col_cand = ((chroma_full > 16) & (covered == 0)).astype(np.uint8)
            col_dil = cv2.dilate(col_cand, np.ones((15, 15), np.uint8))
            n_cm, cm_lbl, cm_stats, _ = cv2.connectedComponentsWithStats(col_dil)
            for ci in range(1, n_cm):
                sx, sy, sw, sh = [int(v) for v in cm_stats[ci][:4]]
                roi_lbl = (cm_lbl[sy:sy+sh, sx:sx+sw] == ci)
                seed_px = int(np.count_nonzero(col_seed[sy:sy+sh, sx:sx+sw] & roi_lbl))
                comp_px = int(np.count_nonzero((col_cand[sy:sy+sh, sx:sx+sw] > 0) & roi_lbl))
                if seed_px < 80 or comp_px < 250 or np.mean(covered[sy:sy+sh, sx:sx+sw]) > 0.45:
                    continue
                rx1, ry1 = int(max(0, sx - 6)), int(max(0, sy - 6))
                rx2, ry2 = int(min(w, sx + sw + 6)), int(min(h, sy + sh + 6))
                pad = 12
                _registrar_zona({
                    "id": int(id_zona),
                    "tipo": "relleno_generativo",
                    "origen": "texto_fuera_comic_detector",
                    "from_yolo": False,
                    "estilo": "color_portada",
                    "box_contenedor": [int(max(0, sx - pad)), int(max(0, sy - pad)),
                                       int(min(w, sx + sw + pad)), int(min(h, sy + sh + pad))],
                    "rectangulos_texto": [[rx1, ry1, rx2, ry2]],
                    "desborda": True,
                })
    else:
        # Compatibilidad con tests unitarios que no devuelven blk
        cnts, _ = cv2.findContours((det_map > .25).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            x, y, cw, ch = cv2.boundingRect(c)
            if cw < 8 or ch < 8 or cv2.contourArea(c) < 80: continue
            if np.mean(covered[y:y+ch, x:x+cw]) > .45: continue
            if np.count_nonzero(seg_map[y:y+ch, x:x+cw] > .1) < 20: continue
            pad = 24
            _registrar_zona(_procesar_item(
                {'coords': [max(0, x-pad), max(0, y-pad), min(w, x+cw+pad), min(h, y+ch+pad)],
                 'conf': .25, 'from_yolo': False}, id_zona))
            
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
