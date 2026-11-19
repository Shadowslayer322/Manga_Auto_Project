import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typeo_core import bind_translation, parse_markdown, read_json, sha256, validate_geometry, write_json, TypeoError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "01_RAW")
TRANS_DIR = os.path.join(BASE_DIR, "03_TRADUCCIONES")
GUION_MD_PATH = os.path.join(TRANS_DIR, "guion_traducciones.md")
GUION_ALT_PATH = os.path.join(TRANS_DIR, "traduccion_capitulo.md")
MEMORIA_PATH = os.path.join(TRANS_DIR, "memoria_contexto.json")

os.makedirs(TRANS_DIR, exist_ok=True)

# ==============================================================================
# Reglas para la traduccion almacenada. Este archivo NO invoca un motor multimodal.
# ==============================================================================
PROMPT_MAESTRO = """
REGLAS OBLIGATORIAS DE TRADUCCIÓN:
1. Lectura estricta manga: De arriba hacia abajo y de derecha a izquierda por cada panel.
2. Identificación de hablante: Analiza colas de globos y escena visual para atribuir género y tono.
3. Extracción total: Diálogos, pensamientos, textos fuera de globo, notas editoriales y SFX.
4. Localización (ES-LA Neutro): Español latinoamericano fluido y natural (sin 'vosotros' ni modismos de España).
5. ESTRICTAMENTE EN MINÚSCULAS: Todo el texto en la columna 'Traducción (ES)' debe ir en minúsculas,
   incluyendo nombres propios e inicios de oraciones.
6. Mapeo tipográfico exacto para Photoshop en la columna 'Ubicación / Panel':
   - Diálogo normal -> Laffayette Comic Pro (19/20) [Keyword: 'Diálogo normal']
   - Grito / Énfasis -> BB Toonacious Italic (22/20) [Keyword: 'Grito']
   - Texto fuera de globo -> CCAstroCityInt Italic (19/20) [Keyword: 'Texto fuera de globo']
   - Susurro -> Neets Hand (21/20) [Keyword: 'Susurro']
   - Globo de miedo / Temblor -> Komika Boo Regular (20/20) [Keyword: 'Globo de miedo']
   - Globo de alegría / Emoción -> Komika Jam Regular (21/20) [Keyword: 'Globo de emoción']
   - Título de capítulo -> Bebas Neue (22/20) [Keyword: 'Título de capítulo']
   - Cuadro de narrador -> DK Snemand (22/20) [Keyword: 'Cuadro de narrador']
   - Nube de pensamiento -> CCSlaphappy (22/20) [Keyword: 'Nube de pensamiento']
"""

# Cache local del capitulo actual. Para paginas nuevas importar un guion real o usar otro proveedor.
TRADUCCIONES_PAGINAS = {
    "001.jpg": {
        "numero": 1,
        "idioma": "JP",
        "filas": [
            {"ubicacion": "Panel 1 - Título de capítulo", "original": "第16話：乱戦交錯(前編)", "traduccion": "episodio 16: caos cruzado (primera parte)"},
            {"ubicacion": "Panel 1 - Cuadro de narrador", "original": "原作：サク研 作画：渡部タカシ", "traduccion": "historia original: saku-ken / arte: takashi watabe"},
            {"ubicacion": "Panel 1 - Diálogo normal", "original": "シャオ先生に…", "traduccion": "a la doctora shao..."},
            {"ubicacion": "Panel 1 - Diálogo normal", "original": "妹さんが？", "traduccion": "¿tiene una hermana?"},
            {"ubicacion": "Panel 1 - Susurro", "original": "……実は", "traduccion": "...en realidad"},
            {"ubicacion": "Panel 1 - Diálogo normal", "original": "「精神移行実験」というのは…", "traduccion": "el \"experimento de transferencia mental\" es..."},
            {"ubicacion": "Panel 2 - Susurro", "original": "はい…", "traduccion": "sí..."},
            {"ubicacion": "Panel 2 - Diálogo normal", "original": "元々", "traduccion": "originalmente"},
            {"ubicacion": "Panel 2 - Susurro", "original": "私の…", "traduccion": "mi..."},
            {"ubicacion": "Panel 2 - Cuadro de narrador", "original": "◎今回の敵も、くせ者確定。", "traduccion": "definitivamente los enemigos de esta vez también serán difíciles."},
            {"ubicacion": "Panel 3 - Grito", "original": "ぴいっ！", "traduccion": "¡iik!"},
            {"ubicacion": "Panel 3 - Diálogo normal", "original": "なんでしょうか うるさいですね", "traduccion": "¿qué será? qué ruidoso"}
        ],
        "sfx": [
            {"ubicacion": "Panel 3 - Fondo", "original": "マッ / グオオ", "efecto": "rugido estruendoso lejano"},
            {"ubicacion": "Panel 3 - Fondo", "original": "ビクッ", "efecto": "sobresalto súbito"},
            {"ubicacion": "Panel 3 - Suelo", "original": "ザッ ザッ ザッ", "efecto": "multitud de pasos acercándose"}
        ]
    },
    "002.jpg": {
        "numero": 2,
        "idioma": "JP",
        "filas": [
            {"ubicacion": "Panel 2 - Globo de miedo", "original": "何？ この人達", "traduccion": "¿qué pasa con estas personas?"},
            {"ubicacion": "Panel 2 - Globo de miedo", "original": "笑いながら近づいてくる…", "traduccion": "se acercan sonriendo..."}
        ],
        "sfx": [
            {"ubicacion": "Panel 1 - Fondo", "original": "アッハハハ / ハハハハ", "efecto": "risotadas enloquecidas colectivas"},
            {"ubicacion": "Panel 1 - Suelo", "original": "ザッ / ザッ", "efecto": "pasos envolventes rodeándolas"}
        ]
    },
    "003.jpg": {
        "numero": 3,
        "idioma": "JP",
        "filas": [
            {"ubicacion": "Panel 2 - Grito", "original": "きゃあ！", "traduccion": "¡kyaa!"},
            {"ubicacion": "Panel 3 - Globo de miedo", "original": "この臭い…", "traduccion": "este olor..."},
            {"ubicacion": "Panel 3 - Grito", "original": "オイル！？", "traduccion": "¿¡aceite!?"}
        ],
        "sfx": [
            {"ubicacion": "Panel 1 - Mano", "original": "ぐわっ", "efecto": "movimiento violento de la atacante"},
            {"ubicacion": "Panel 2 - Centro", "original": "ビシャッ", "efecto": "salpicadura densa de combustible"},
            {"ubicacion": "Panel 3 - Cuerpo", "original": "ポタ ポタ", "efecto": "goteo de aceite sobre la ropa"}
        ]
    },
    "004.jpg": {
        "numero": 4,
        "idioma": "JP",
        "filas": [
            {"ubicacion": "Panel 1 - Susurro", "original": "浴びましたね 聖水を", "traduccion": "te bañaste en agua bendita, ¿no?"},
            {"ubicacion": "Panel 2 - Grito", "original": "リーチ様の御血をいただき ますですぅぅ！", "traduccion": "¡beberemos la sagrada sangre de lord reach!"},
            {"ubicacion": "Panel 2 - Diálogo normal", "original": "もうおしまいですよ 悪魔憑き", "traduccion": "ya es tu fin, poseída por demonios"},
            {"ubicacion": "Panel 2 - Texto fuera de globo", "original": "私が凶手 マイグレーターの貴様らを祓ってえぇ！", "traduccion": "¡yo soy la ejecutora! ¡exorcizaré a las malditas de migrator!"},
            {"ubicacion": "Panel 2 - Texto fuera de globo", "original": "ホホホホ～！", "traduccion": "¡jojojo!"},
            {"ubicacion": "Panel 2 - Cuadro de narrador", "original": "自称悪魔祓い 放火魔ヌー 懲役120年", "traduccion": "autoproclamada exorcista pirómana nuu condena de 120 años"}
        ],
        "sfx": [
            {"ubicacion": "Panel 1 - Recuadro", "original": "ポタ ポタ", "efecto": "goteo de aceite desde los dedos"},
            {"ubicacion": "Panel 2 - Fondo", "original": "ホ ホ", "efecto": "bocanadas de fuego amenazantes"}
        ]
    },
    "005.jpg": {
        "numero": 5,
        "idioma": "JP",
        "filas": [
            {"ubicacion": "Panel 1 - Diálogo normal", "original": "リーチ？", "traduccion": "¿reach?"},
            {"ubicacion": "Panel 1 - Nube de pensamiento", "original": "まさかこの人達は…", "traduccion": "no me digas que estas personas son..."},
            {"ubicacion": "Panel 2 - Texto fuera de globo", "original": "ディア・ウエポン", "traduccion": "dear weapon"},
            {"ubicacion": "Panel 2 - Texto fuera de globo", "original": "『クロス・クリメイション』", "traduccion": "«cross cremation»"},
            {"ubicacion": "Panel 3 - Grito", "original": "えっ！？", "traduccion": "¿¡eh!?"},
            {"ubicacion": "Panel 3 - Diálogo normal", "original": "ファイヤスターターです", "traduccion": "es un iniciador de fuego"},
            {"ubicacion": "Panel 3 - Grito", "original": "ミミさん避けて", "traduccion": "¡mimi, apártate!"}
        ],
        "sfx": [
            {"ubicacion": "Panel 1 - Mano", "original": "カチャ…", "efecto": "desenfundado de arma cruciforme"},
            {"ubicacion": "Panel 2 - Centro", "original": "ズッ ズッ", "efecto": "fricción de pedernal para encender chispa"},
            {"ubicacion": "Panel 3 - Filo", "original": "ガッ", "efecto": "ignición de chispas ardientes"}
        ]
    }
}

def inicializar_memoria():
    if os.path.exists(MEMORIA_PATH):
        try:
            with open(MEMORIA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError) as exc:
            raise TypeoError('Memoria de traduccion invalida; no se sobrescribe: '+MEMORIA_PATH) from exc
    return {
        "capitulo": "capítulo 16: caos cruzado",
        "personajes": {
            "shao": {"rol": "doctora / científica", "genero": "femenino", "formalidad": "formal / serena", "honorifico": "shao-sensei"},
            "mimi": {"rol": "hermana menor de shao", "genero": "femenino", "formalidad": "informal / asustadiza", "honorifico": "mimi-san"},
            "nuu": {"rol": "antagonista principal, monja pirómana", "genero": "femenino", "formalidad": "fanática / demente", "condena": "120 años"},
            "reach": {"rol": "líder o figura de adoración de los atacantes", "genero": "masculino", "formalidad": "honorífica (lord reach)"}
        },
        "terminologia": {
            "migrator": "organización o grupo de las protagonistas",
            "cross cremation": "técnica de incineración con cruz de pedernal",
            "dear weapon": "técnica o invocación de arma sagrada",
            "fire starter": "iniciador de fuego / ignición con pedernal"
        },
        "resumen_narrativo": "shao y mimi conversan sobre el experimento de transferencia mental cuando son emboscadas por zombis sonrientes y la monja pirómana nuu, quien rocía a mimi con aceite e intenta quemarla con su técnica cross cremation.",
        "lotes_procesados": []
    }

def actualizar_memoria(memoria, lote_paginas):
    raw_hashes = {name: sha256(Path(RAW_DIR)/name) for name in lote_paginas}
    for lote in memoria.get('lotes_procesados', []):
        if lote.get('paginas') == list(lote_paginas) and lote.get('proveedor') == 'cache_local_validada' and lote.get('raw_sha256') == raw_hashes:
            return
    info_lote = {
        "lote_id": len(memoria["lotes_procesados"]) + 1,
        "paginas": [p for p in lote_paginas],
        "fecha": datetime.now(timezone(timedelta(hours=-5))).date().isoformat(),
        "proveedor": "cache_local_validada",
        "raw_sha256": raw_hashes,
        "estado": "completado"
    }
    memoria["lotes_procesados"].append(info_lote)
    with open(MEMORIA_PATH, "w", encoding="utf-8") as f:
        json.dump(memoria, f, indent=2, ensure_ascii=False)
    print(f"[MEMORIA] Contexto narrativo acumulado actualizado en: {MEMORIA_PATH}")

def generar_tablas_markdown(archivos, memoria):
    bloques_md = []
    
    for arch in archivos:
        datos = TRADUCCIONES_PAGINAS.get(arch)
        if not datos:
            raise TypeoError('No hay traduccion local para '+arch+'. Importar un guion traducido; no se inventan textos.')
            
        num = datos["numero"]
        idioma = datos["idioma"]
        
        md = []
        md.append(f"Página {num} - Archivo: {arch} (Idioma detectado: {idioma})")
        md.append("")
        md.append("| Ubicación / Panel | Texto Original (JP/EN) | Traducción (ES) |")
        md.append("| :--- | :--- | :--- |")
        
        for fila in datos["filas"]:
            ub = fila["ubicacion"]
            orig = fila["original"]
            trad = fila["traduccion"].strip().lower()
            md.append(f"| {ub} | {orig} | {trad} |")
            
        if datos.get("sfx"):
            md.append("")
            md.append("#### Onomatopeyas / SFX (Solo Referencia)")
            md.append("| Ubicación | SFX Original | Significado / Efecto (ES) |")
            md.append("| :--- | :--- | :--- |")
            for s in datos["sfx"]:
                md.append(f"| {s['ubicacion']} | {s['original']} | {s['efecto'].lower()} |")
                
        bloques_md.append("\n".join(md))
        
    return "\n\n---\n\n".join(bloques_md)

def traducir_por_lotes(batch_size=4):
    if not 1 <= batch_size <= 50:
        raise TypeoError('El tamano de lote debe estar entre 1 y 50')
    print("="*70)
    print("EXPORTANDO TRADUCCION LOCAL ALMACENADA DEL CAPITULO")
    print("Sin llamadas a modelos ni APIs. Paginas nuevas requieren una traduccion real.")
    print("="*70)
    
    archivos = sorted([f for f in os.listdir(RAW_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
    if not archivos:
        print("No se encontraron páginas en 01_RAW.")
        return
        
    memoria = inicializar_memoria()
    geometry = read_json(Path(BASE_DIR)/'config/typeo_geometria.json')
    validate_geometry(geometry, Path(BASE_DIR))
    # Validar todas las correspondencias antes de modificar memoria o guiones.
    guion_final = generar_tablas_markdown(archivos, memoria)
    contrato = bind_translation(parse_markdown(guion_final), geometry, Path(BASE_DIR))
    print(f"\nTotal páginas encontradas en 01_RAW: {len(archivos)}")
    print(f"Tamaño de lote configurado: {batch_size} páginas por tanda\n")
    
    total_lotes = (len(archivos) + batch_size - 1) // batch_size
    todas_las_paginas = []
    
    for l_idx in range(total_lotes):
        ini = l_idx * batch_size
        fin = min(ini + batch_size, len(archivos))
        lote_actual = archivos[ini:fin]
        
        print(f"--- Procesando Lote {l_idx + 1}/{total_lotes}: Páginas {ini + 1} a {fin} ({', '.join(lote_actual)}) ---")
        for arch in lote_actual:
            info = TRADUCCIONES_PAGINAS.get(arch, {})
            n_filas = len(info.get("filas", []))
            n_sfx = len(info.get("sfx", []))
            print(f"  [Página {arch}] -> Cache: {n_filas} textos y {n_sfx} SFX solo de referencia.")
            
        actualizar_memoria(memoria, lote_actual)
        todas_las_paginas.extend(lote_actual)
        
    # Generar guion de traducción final
    write_json(Path(TRANS_DIR)/'guion_typeo.json', contrato)
    
    with open(GUION_MD_PATH, "w", encoding="utf-8") as f:
        f.write(guion_final)
    with open(GUION_ALT_PATH, "w", encoding="utf-8") as f:
        f.write(guion_final)
        
    print("\n" + "="*70)
    print("GUION DE TRADUCCIÓN GENERADO CON ÉXITO")
    print(f"Archivo primario:   {GUION_MD_PATH}")
    print(f"Archivo secundario: {GUION_ALT_PATH}")
    print("="*70)
    return guion_final

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Antigravity Native Multimodal Manga Translator")
    parser.add_argument("--batch-size", type=int, default=4, help="Tamaño de lote (3 o 4)")
    args, _ = parser.parse_known_args()
    traducir_por_lotes(batch_size=args.batch_size)
