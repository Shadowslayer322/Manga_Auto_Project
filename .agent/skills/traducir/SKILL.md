---
name: traducir
description: Traduce capítulos directamente con el modelo actual de Antigravity usando un sistema dual: página completa de 01_RAW para máximo contexto visual y respaldo automático con recortes de solo globos si alguna página es rechazada por políticas, generando 03_TRADUCCIONES/guion_typeo.json sin APIs externas.
---

# Traducción Dual con Antigravity (Sin API Externa)

## Estrategia Dual (Página Completa -> Respaldo Solo Globos)
1. **Primero prepara el índice y los recortes de respaldo** ejecutando:
   ```powershell
   python scripts/extraer_globos_traduccion.py
   ```
   Esto genera `03_TRADUCCIONES/pendiente_traduccion.json`, los collages `03_TRADUCCIONES/recortes_globos/<pagina>_globos.png` y los recortes individuales `03_TRADUCCIONES/recortes_globos/<pagina>/<id>.png`.

2. **Por cada página en `03_TRADUCCIONES/pendiente_traduccion.json`:**
   - **Ruta principal (contexto completo):** Lee la página original en `01_RAW/<archivo>` con `read_file` para tener el contexto visual completo (quién habla, tono, escena, carteles, pantallas).
   - **Ruta de respaldo (solo globos):** Si una página es rechazada o bloqueada al leerla completa por políticas de contenido (escenas subidas de tono, gore, etc.), **cambia inmediatamente** en esa página a leer **únicamente** su collage de globos (`03_TRADUCCIONES/recortes_globos/<pagina>_globos.png`) y, si hace falta detalle en algún texto pequeño, sus recortes individuales (`03_TRADUCCIONES/recortes_globos/<pagina>/<id>.png`), sin volver a intentar abrir la página completa.

3. **Reglas de traducción** (español latinoamericano neutro):
   - Coteja el `texto_ocr` de `pendiente_traduccion.json` contra la imagen (completa o recorte) y corrige errores de OCR en `texto_original`.
   - Mantén coherencia de género, tono, nombres propios y continuidad entre páginas y globos.
   - Sin modismos de España (`vosotros`, `tío`, `joder`, etc.).
   - Formato de oración / minúsculas según corresponda a las fuentes del proyecto (sin bloques forzados todo en mayúsculas).
   - No inventes texto ilegible; si un bloque es realmente ilegible, déjalo vacío para revisión.
   - Respeta o ajusta `rol_fuente` entre los roles válidos: `normal`, `grito`, `miedo`, `emocion`, `pensamiento`, `murmullo`, `titulo`, `narrador`, `fuera_globo`, `cartel`, `pantalla`, `impreso`.

4. **Guarda el resultado** en `03_TRADUCCIONES/guion_typeo.json` con la estructura exacta:
   ```json
   {
     "version": 1,
     "paginas": [
       {
         "archivo": "001.jpg",
         "bloques": [
           {
             "id": "001_01",
             "texto_original": "...",
             "traduccion_es": "...",
             "rol_fuente": "normal"
           }
         ]
       }
     ]
   }
   ```

5. **Valida el contrato** sin abrir Photoshop ejecutando:
   ```powershell
   python scripts/ejecutar_todo.py --guion 03_TRADUCCIONES/guion_typeo.json --preparar
   ```
   Si el usuario pidió ejecutar el flujo completo, lanza `python scripts/ejecutar_todo.py` (detectará automáticamente `03_TRADUCCIONES/guion_typeo.json`).
