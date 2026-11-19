import os
import glob
import json
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG_DIR = os.path.join(BASE_DIR, "04_DIAGNOSTICO")
RAW_DIR = os.path.join(BASE_DIR, "01_RAW")

def agrupar_en_pares_cercanos(bloques):
    """
    bloques: lista de dict con {'id': int, 'centroid': (cx, cy), 'label_indices': [int], 'bbox': (x, y, w, h)}
    Retorna lista de pares (o grupo de 1 si es impar), emparejando greedy por menor distancia euclidiana.
    """
    unpaired = list(range(len(bloques)))
    grupos = []
    
    while len(unpaired) > 1:
        best_d = float('inf')
        best_pair = (None, None)
        best_indices = (0, 1)
        
        for i in range(len(unpaired)):
            idx_i = unpaired[i]
            c1 = bloques[idx_i]['centroid']
            for j in range(i + 1, len(unpaired)):
                idx_j = unpaired[j]
                c2 = bloques[idx_j]['centroid']
                d = np.hypot(c1[0] - c2[0], c1[1] - c2[1])
                if d < best_d:
                    best_d = d
                    best_pair = (idx_i, idx_j)
                    best_indices = (i, j)
        
        grupos.append([best_pair[0], best_pair[1]])
        # Remove higher index first
        i_rem, j_rem = best_indices
        del unpaired[max(i_rem, j_rem)]
        del unpaired[min(i_rem, j_rem)]
        
    if len(unpaired) == 1:
        grupos.append([unpaired[0]])
        
    return grupos

def procesar_particion_genfill_pares():
    archivos = sorted([f for f in os.listdir(RAW_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    paginas = archivos if archivos else ["001.jpg", "002.jpg", "003.jpg", "004.jpg", "005.jpg"]
    manifiesto_pares = {}
    
    for nom in paginas:
        nombre_base = os.path.splitext(nom)[0]
        ruta_mask_genfill = os.path.join(DIAG_DIR, f"MASCARA_GENFILL_{nombre_base}.png")
        if not os.path.exists(ruta_mask_genfill):
            print(f"[{nom}] Mascara no encontrada: {ruta_mask_genfill}")
            continue
            
        mask_gf = cv2.imread(ruta_mask_genfill, cv2.IMREAD_GRAYSCALE)
        if mask_gf is None or np.count_nonzero(mask_gf) == 0:
            print(f"[{nom}] Mascara GenFill VACIA (solo requiere pincel)")
            manifiesto_pares[nom] = []
            continue
            
        h, w = mask_gf.shape
        # Dilatacion vertical para agrupar caracteres de una misma columna en un solo bloque
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 55))
        dilated = cv2.dilate(mask_gf, kernel, iterations=1)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(dilated)
        
        bloques = []
        for i in range(1, num_labels):
            bx, by, bw, bh, area = stats[i]
            if area > 100:
                bloques.append({
                    'id': i,
                    'centroid': (centroids[i][0], centroids[i][1]),
                    'bbox': (bx, by, bw, bh),
                    'label_id': i
                })
                
        if not bloques:
            print(f"[{nom}] No se encontraron bloques significativos en GenFill")
            manifiesto_pares[nom] = []
            continue
            
        grupos_indices = agrupar_en_pares_cercanos(bloques)
        print(f"[{nom}] Total bloques: {len(bloques)} -> Agrupados en {len(grupos_indices)} pares/grupos:")
        
        submascaras = []
        raw_img = cv2.imread(os.path.join(RAW_DIR, nom))
        vis_pares = raw_img.copy() if raw_img is not None else np.zeros((h, w, 3), dtype=np.uint8)
        
        COLORES_PARES = [
            (255, 0, 0),    # Azul
            (0, 255, 0),    # Verde
            (0, 0, 255),    # Rojo
            (255, 255, 0),  # Cyan
            (255, 0, 255),  # Magenta
            (0, 255, 255),  # Amarillo
            (128, 0, 255),  # Violeta
            (0, 165, 255)   # Naranja
        ]
        
        for g_idx, g_bloques in enumerate(grupos_indices):
            par_num = g_idx + 1
            mask_par = np.zeros((h, w), dtype=np.uint8)
            color = COLORES_PARES[g_idx % len(COLORES_PARES)]
            
            for b_idx in g_bloques:
                b = bloques[b_idx]
                lid = b['label_id']
                # Extraer pixeles originales de mask_gf que coinciden con este bloque dilatado
                componente_pixels = (labels == lid) & (mask_gf > 0)
                mask_par[componente_pixels] = 255
                
                # Dibujar en visualizacion
                bx, by, bw, bh = b['bbox']
                cv2.rectangle(vis_pares, (bx, by), (bx + bw, by + bh), color, 3)
                cv2.putText(vis_pares, f"PAR {par_num}", (bx, max(25, by - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                            
            out_par_png = os.path.join(DIAG_DIR, f"MASCARA_GENFILL_{nombre_base}_PAR_{par_num}.png").replace("\\", "/")
            cv2.imwrite(out_par_png, mask_par)
            px_count = np.count_nonzero(mask_par)
            print(f"   -> Par {par_num}: {len(g_bloques)} textos, {px_count} px -> {out_par_png}")
            
            submascaras.append({
                "par_num": par_num,
                "mascara_png": out_par_png,
                "num_textos": len(g_bloques),
                "px": px_count
            })
            
        manifiesto_pares[nom] = submascaras
        
        # Guardar visualizacion de diagnostico
        out_vis_pares = os.path.join(DIAG_DIR, f"DIAGNOSTICO_PARES_GENFILL_{nombre_base}.jpg")
        cv2.imwrite(out_vis_pares, vis_pares)
        
    out_json = os.path.join(BASE_DIR, "02_TRABAJO_PSD", "manifiesto_genfill_pares.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(manifiesto_pares, f, indent=2, ensure_ascii=False)
    print("\nParticion de Relleno Generativo en pares de 2 completada exitosamente!")

if __name__ == "__main__":
    procesar_particion_genfill_pares()
