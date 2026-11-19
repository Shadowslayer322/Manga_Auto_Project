import os
import sys
import json
import time
from pathlib import Path
from PIL import Image
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts"))

from typeo_core import read_json, write_json, parse_markdown, load_translation

RAW_DIR = BASE_DIR / "01_RAW"
TRANS_DIR = BASE_DIR / "03_TRADUCCIONES"
CACHE_FILE = TRANS_DIR / "cache_traduccion_capitulo.json"
MD_FILE = TRANS_DIR / "traduccion_capitulo.md"
MD_GUION = TRANS_DIR / "guion_traducciones.md"
JSON_GUION = TRANS_DIR / "guion_typeo.json"
OCR_FILE = TRANS_DIR / "ocr_capitulo.json"

load_dotenv()
from google import genai
from google.genai import types

SYSTEM_INSTRUCTION = '''Actúa como un traductor profesional de manga, experto en localización y adaptación cultural al español latinoamericano.
Traduce el texto del manga al español latinoamericano natural, fluido y moderno.
Responde únicamente JSON válido con esta estructura:
{
  "version": 1,
  "paginas": [
    {
      "archivo": "nombre_exacto.jpg",
      "bloques": [
        {
          "id": "ID_exacto",
          "texto_original": "texto cotejado con la imagen",
          "traduccion_es": "traducción en español latino neutro en minúsculas/oración",
          "rol_fuente": "rol (normal, grito, pensamiento, murmullo, cartel, pantalla, impreso)"
        }
      ],
      "sfx": [
        {
          "ubicacion": "descripción",
          "original": "SFX en la RAW",
          "significado": "efecto en español (solo referencia)"
        }
      ]
    }
  ]
}

Reglas estrictas:
1. Devuelve exactamente una traducción para cada ID de bloque provisto en el OCR.
2. Si el bloque es diálogo o narración, tradúcelo fielmente en minúsculas (usando mayúsculas solo al inicio o en nombres propios).
3. Coteja la imagen RAW: el OCR puede tener erratas o espacios rotos; corrígelos según lo que se ve en la imagen.
4. NO traduzcas sonidos/onomatopeyas ni números u horas aislados como texto de diálogo: esos van en la sección "sfx" solo como referencia visual si son relevantes. Si un número o signo forma parte de una frase, permanece en la frase.
5. Carteles, letreros, menús y pantallas de celulares son textos válidos con roles "cartel", "impreso" o "pantalla".
6. Nombres de personajes: Tokimasa (apodo Tokirin), Airin. Serie: Evershifting Girlfriends.
7. Si una zona no contiene texto legible o es sólo un fondo/dibujo o SFX, pon "traduccion_es": "".
'''

def cargar_cache():
    if CACHE_FILE.exists():
        try:
            return read_json(CACHE_FILE)
        except Exception:
            return {}
    return {}

def guardar_cache(cache):
    write_json(CACHE_FILE, cache)

def traducir_pagina_api(client, archivo, info_ocr):
    img_path = RAW_DIR / archivo
    with Image.open(img_path) as source:
        img = source.copy()
        
    prompt = f"Página: {archivo}\nDatos OCR de la página:\n" + json.dumps(info_ocr, ensure_ascii=False)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
        response_mime_type="application/json"
    )
    
    models = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.5-flash"]
    for m in models:
        for intento in range(3):
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=[img, prompt],
                    config=config
                )
                text = resp.text.strip()
                parsed = json.loads(text)
                if "paginas" in parsed and len(parsed["paginas"]) > 0:
                    res = parsed["paginas"][0]
                elif "bloques" in parsed:
                    res = {"archivo": archivo, "bloques": parsed["bloques"], "sfx": parsed.get("sfx", [])}
                else:
                    raise ValueError("Formato de JSON inesperado")
                res["archivo"] = archivo
                return res
            except Exception as e:
                err = str(e)
                print(f"  [Reintento] {archivo} en {m} (intento {intento+1}): {err[:80]}", flush=True)
                time.sleep(2 * (intento + 1))
    raise RuntimeError(f"Error fatal traduciendo {archivo} tras agotar modelos y reintentos")

def construir_markdown_pagina(num_pagina, arch, bloques, sfx_list):
    md_lines = [
        f"Página {num_pagina} - Archivo: {arch} (Idioma detectado: EN)\n",
        "| Ubicación / Panel | Texto Original (JP/EN) | Traducción (ES) | ID / Zona |",
        "| :--- | :--- | :--- | :--- |"
    ]
    
    bloques_validos = [b for b in bloques if b.get("traduccion_es")]
    if not bloques_validos:
        md_lines.append("| Toda la página | Sin texto | Sin texto | - |")
    else:
        for b in bloques:
            orig = (b.get("texto_original") or "").replace("\n", " ").replace("|", "\\|").strip()
            trad = (b.get("traduccion_es") or "").replace("\n", " ").replace("|", "\\|").strip()
            if not trad:
                continue
            rol = b.get("rol_fuente", "normal")
            ubicacion = f"Panel - {rol.capitalize()}"
            zid = b.get("id", "")
            md_lines.append(f"| {ubicacion} | {orig} | {trad} | {zid} |")
            
    md_lines.append("\n#### Onomatopeyas / SFX (Solo Referencia)")
    md_lines.append("| Ubicación | SFX Original | Significado / Efecto (ES) |")
    md_lines.append("| :--- | :--- | :--- |")
    if sfx_list:
        for s in sfx_list:
            ub = s.get("ubicacion", "Fondo / Viñeta").replace("|", "\\|")
            orig = s.get("original", "").replace("|", "\\|")
            sig = s.get("significado", "").replace("|", "\\|")
            md_lines.append(f"| {ub} | {orig} | {sig} |")
    else:
        md_lines.append("| Fondo | - | - |")
        
    return "\n".join(md_lines)

def ejecutar():
    print("=== INICIANDO TRADUCCIÓN DEL CAPÍTULO COMPLETO (53 PÁGINAS) ===", flush=True)
    ocr_data = read_json(OCR_FILE)
    paginas_ocr = {p["archivo"]: p for p in ocr_data["paginas"]}
    archivos = sorted(paginas_ocr.keys())
    print(f"Total páginas detectadas: {len(archivos)}", flush=True)
    
    cache = cargar_cache()
    
    # Pre-cargar guiones revisados existentes (24 y 32)
    for num in [24, 32]:
        pfile = TRANS_DIR / f"guion_ocr_{num}.json"
        arch = f"{num:02d}.jpg"
        if pfile.exists() and arch not in cache:
            gdata = read_json(pfile)
            p_data = gdata["paginas"][0]
            cache[arch] = {
                "archivo": arch,
                "raw_sha256": p_data.get("raw_sha256", ""),
                "bloques": p_data.get("bloques", []),
                "sfx": []
            }
            guardar_cache(cache)
            print(f"  -> Pre-cargada traducción validada existente para {arch}", flush=True)

    client = genai.Client()
    
    for idx, arch in enumerate(archivos, 1):
        if arch in cache and len(cache[arch].get("bloques", [])) > 0:
            print(f"[{idx}/{len(archivos)}] {arch} ya está en caché ({len(cache[arch]['bloques'])} bloques). Saltando.", flush=True)
            continue
            
        print(f"[{idx}/{len(archivos)}] Traduciendo {arch}...", flush=True)
        info_ocr = paginas_ocr[arch]
        t0 = time.time()
        res = traducir_pagina_api(client, arch, info_ocr)
        res["raw_sha256"] = info_ocr.get("raw_sha256", "")
        cache[arch] = res
        guardar_cache(cache)
        dt = time.time() - t0
        print(f"  -> {arch} completado en {dt:.2f}s ({len(res.get('bloques', []))} bloques)", flush=True)
        time.sleep(0.3)

    print("\n=== TODAS LAS 53 PÁGINAS HAN SIDO TRADUCIDAS EXITOSAMENTE ===", flush=True)
    
    # Construir contrato JSON final
    paginas_json = []
    tablas_md = []
    
    for idx, arch in enumerate(archivos, 1):
        p_data = cache[arch]
        raw_sha = paginas_ocr[arch].get("raw_sha256", "")
        bloques = p_data.get("bloques", [])
        sfx = p_data.get("sfx", [])
        
        paginas_json.append({
            "archivo": arch,
            "raw_sha256": raw_sha,
            "bloques": bloques
        })
        
        md_pag = construir_markdown_pagina(idx, arch, bloques, sfx)
        tablas_md.append(md_pag)

    contrato_final = {
        "version": 1,
        "idioma_origen": "EN",
        "idioma_destino": "ES",
        "capitulo": "Evershifting Girlfriends - Chapter 2",
        "paginas": paginas_json
    }
    
    write_json(JSON_GUION, contrato_final)
    print(f"Guión JSON guardado en: {JSON_GUION}", flush=True)
    
    markdown_final = "\n\n---\n\n".join(tablas_md)
    MD_FILE.write_text(markdown_final, encoding="utf-8")
    MD_GUION.write_text(markdown_final, encoding="utf-8")
    print(f"Guión Markdown guardado en: {MD_FILE}", flush=True)
    print(f"Guión Markdown sincronizado en: {MD_GUION}", flush=True)
    
    # Actualizar glosario
    glosario = {
        "manga": "Evershifting Girlfriends",
        "capitulo_actual": "Capítulo 2: La determinación de Airin",
        "personajes": [
            {
                "original": "Tokimasa / Tokirin",
                "traduccion": "Tokimasa / Tokirin",
                "rol": "protagonista masculino",
                "formalidad": "informal"
            },
            {
                "original": "Airin",
                "traduccion": "Airin",
                "rol": "protagonista femenina",
                "formalidad": "informal"
            }
        ]
    }
    write_json(TRANS_DIR / "glosario_manga.json", glosario)
    
    # Validar formato con typeo_core
    try:
        val_json = load_translation(JSON_GUION)
        print(f"Validación JSON exitosa: {len(val_json['paginas'])} páginas reconocidas.", flush=True)
        val_md = parse_markdown(markdown_final)
        print(f"Validación Markdown exitosa: {len(val_md['paginas'])} páginas reconocidas.", flush=True)
    except Exception as e:
        print(f"Advertencia en validación de contrato: {e}", flush=True)

if __name__ == "__main__":
    ejecutar()
