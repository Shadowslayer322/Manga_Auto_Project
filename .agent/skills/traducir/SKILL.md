---
name: traducir
description: Traduce capítulos directamente abriendo las páginas de 01_RAW en Antigravity sin depender del clíneo previo; usa recortes de solo globos únicamente bajo demanda si alguna página es rechazada por políticas, y permite avanzar el typeo en paralelo página por página (--esperar-guion).
---

# Traducción Directa y en Paralelo con Antigravity (Sin Clíneo Previo)

## Regla Principal: Directo desde `01_RAW` (Cero Dependencia de Clíneo Previo)
**NO ejecutes `extraer_globos_traduccion.py` al inicio sobre todo el capítulo.** Traduce abriendo directamente las páginas en `01_RAW/` con `read_file` para no depender de la detección ni perder tiempo esperando recortes innecesarios.

1. **Inicio paralelo (si se ejecuta el flujo completo):**
   - Si el usuario pidió el flujo completo (o limpieza + traducción + typeo), lanza **de inmediato** en segundo plano:
     ```powershell
     python scripts/ejecutar_todo.py --esperar-guion
     ```
   - El proceso abrirá Photoshop, irá limpiando en orden y **pausará el typeo en cada página hasta que su traducción aparezca en `03_TRADUCCIONES/guion_typeo.json`**, avanzando automáticamente en cuanto escribas la página 1, luego la 2, etc., y **no terminará hasta entregar todas las páginas procesadas**.

2. **Traducción página por página (Ruta principal -> Respaldo bajo demanda):**
   - **Ruta principal (directa):** Lee `01_RAW/<archivo>` con `read_file` en orden (desde la primera página) y traduce directamente todos los diálogos, pensamientos, narraciones y rótulos visibles.
   - Incluye para cada bloque su posición aproximada normalizada `"pos": [x, y]` (enteros de `0` a `1000`, donde `[0, 0]` es arriba-izquierda y `[1000, 1000]` abajo-derecha) para que `bind_translation` lo enlace automáticamente con la geometría cuando termine la limpieza de esa página, sin necesitar `id` previo.
   - **Ruta de respaldo (solo si una página falla):** Únicamente si `read_file` sobre `01_RAW/<archivo>` es rechazado o bloqueado por políticas de contenido en una página puntual, ejecuta el extractor **solo para esa página**:
     ```powershell
     python scripts/extraer_globos_traduccion.py --paginas <stem>
     ```
     y lee únicamente su collage `03_TRADUCCIONES/recortes_globos/<stem>_globos.png` (y recortes individuales si hace falta).

3. **Actualización incremental de `03_TRADUCCIONES/guion_typeo.json`:**
   - Ve guardando/actualizando `03_TRADUCCIONES/guion_typeo.json` conforme terminas cada página (o lote pequeño desde la página 1) para desbloquear de inmediato el typeo en Photoshop sin esperar a terminar todo el capítulo:
     ```json
     {
       "version": 1,
       "paginas": [
         {
           "archivo": "01.png",
           "bloques": [
             {
               "pos": [780, 140],
               "texto_original": "...",
               "traduccion_es": "...",
               "rol_fuente": "normal"
             }
           ]
         }
       ]
     }
     ```
   - Roles válidos en `rol_fuente`: `normal`, `grito`, `miedo`, `emocion`, `pensamiento`, `murmullo`, `titulo`, `narrador`, `fuera_globo`, `cartel`, `pantalla`, `impreso`.

4. **Reglas de traducción** (español latinoamericano neutro):
   - Sin modismos de España (`vosotros`, `tío`, `joder`, etc.).
   - Formato de oración / minúsculas según corresponda a las fuentes del proyecto (sin bloques forzados todo en mayúsculas).
   - Mantén coherencia de género, tono, nombres propios y continuidad entre páginas.
   - Omite SFX puras (onomatopeyas dibujadas sobre arte). No inventes texto ilegible.
