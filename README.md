# Manga Auto Project

Pipeline automatizado para detección, limpieza híbrida (pincel + Relleno Generativo en Adobe Photoshop), traducción asistida con Antigravity (sistema dual) y typeo tipográfico en PSD editables.

---

## Requisitos Previos

1. **Windows 10/11** con **Adobe Photoshop 2024/2025/2026** instalado.
   - El sistema detecta `Photoshop.exe` automáticamente en `Program Files\Adobe\`.
   - Si lo tienes en otra ruta, define la variable de entorno `PHOTOSHOP_EXE` apuntando a tu ejecutable.
2. **Python 3.11+** instalado.
3. **Antigravity IDE** (para traducir capítulos directamente con el skill `.agent/skills/traducir/SKILL.md` sin APIs externas).
4. **Fuentes tipográficas instaladas en Windows** (en `%LOCALAPPDATA%\Microsoft\Windows\Fonts` o `C:\Windows\Fonts`):
   - `CC-KISSANDTELL-REGULAR.TTF` (`normal`)
   - `CC-KISSANDTELL-ITALIC.TTF` (`grito`, `miedo`, `emocion`, `narrador`, `pensamiento`)
   - `CC-KISSANDTELL-BOLD-ITALIC.TTF` (`fuera_globo`, `cartel`, `pantalla`, `impreso`)
   - `Bebas Neue.otf` (`titulo`)
   - `NeetsHand-Modificado.otf` (`murmullo`)
   - Configuradas de forma portable en `config/typeo_fuentes.json` usando `%LOCALAPPDATA%`.

---

## Instalación Inicial (Nueva PC)

1. **Clonar el repositorio:**
   ```powershell
   git clone <URL_DEL_REPOSITORIO>
   cd Manga_Auto_Project
   ```

2. **Crear entorno virtual e instalar dependencias:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements-ocr.txt -r requirements-typeo.txt
   pip install ultralytics pywin32
   ```
   *(Si usarás el motor opcional `--motor gemini`, instala también `google-genai` y `python-dotenv`, y configura `GEMINI_API_KEY` en `.env`.)*

3. **Colocar los modelos de detección en `models/`:**
   Los pesos (`.pt` / `.onnx`) no se incluyen en Git por su tamaño. Debes colocar en `models/`:
   - Modelo YOLO de detección de globos (`bubbles_detect.pt` / `manga109_seg_bubble.pt`)
   - `comic-text-detector.onnx`

4. **Crear las carpetas de trabajo** (si aún no existen):
   ```powershell
   mkdir 01_RAW, 02_TRABAJO_PSD, 03_TRADUCCIONES, 04_DIAGNOSTICO, 09_PSD_FINAL -Force
   ```

---

## Manual de Ejecución (Flujo Diario)

### Paso 1: Colocar las páginas RAW
Copia las imágenes del capítulo (`.jpg`, `.png`, `.webp`) en `01_RAW/`.

### Paso 2: Traducir con Antigravity (Sistema Dual, Sin API Externa)
Abre el proyecto en Antigravity y pide en el chat:
> **"Traduce el capítulo actual"**

El skill `.agent/skills/traducir/SKILL.md` hará automáticamente:
1. Extraer solo los recortes de globos (`python scripts/extraer_globos_traduccion.py`) en `03_TRADUCCIONES/recortes_globos/` y el índice `03_TRADUCCIONES/pendiente_traduccion.json`.
2. Traducir cada página usando **la página completa** para máximo contexto visual y, si alguna página es rechazada por políticas de contenido, usar automáticamente **solo los recortes de globos** de esa página.
3. Guardar el guion listo en `03_TRADUCCIONES/guion_typeo.json`.

*(También puedes correr `python scripts/extraer_globos_traduccion.py` manualmente en PowerShell antes de pedir la traducción.)*

### Paso 3: Limpiar, Typear y Guardar PSDs en Photoshop
*(Opcional: abre Adobe Photoshop antes para ver el proceso en vivo en pantalla.)*

Ejecuta en PowerShell:
```powershell
python scripts/ejecutar_todo.py
```

El pipeline tomará automáticamente `03_TRADUCCIONES/guion_typeo.json`, limpiará las páginas en Photoshop (conservando capas independientes de Relleno Generativo), colocará las capas nativas de texto editable, hará la segunda pasada de revisión y guardará **un único PSD final por página** en `09_PSD_FINAL/`.

---

## Comandos Útiles

| Comando | Qué hace |
| :--- | :--- |
| `python scripts/ejecutar_todo.py` | Flujo completo: limpia, typea con `03_TRADUCCIONES/guion_typeo.json` y guarda en `09_PSD_FINAL/` |
| `python scripts/ejecutar_todo.py --solo-limpieza` | Solo abre y limpia las RAW sin traducir ni typear |
| `python scripts/ejecutar_todo.py --guion ruta/al/guion.json` | Usa un guion específico (JSON o Markdown) |
| `python scripts/ejecutar_todo.py --reemplazar` | Vuelve a procesar y sobrescribe PSDs ya existentes en `09_PSD_FINAL/` |
| `python scripts/ejecutar_todo.py --recalcular-mascaras` | Recalcula máscaras en vez de reutilizar caché |
| `python scripts/extraer_globos_traduccion.py` | Extrae únicamente los recortes y collages de globos para traducción segura |

---

## Verificación y Pruebas

```powershell
python -m unittest discover -s tests -v
node tests/status_jsx_harness.js
node tests/pipeline_ps_harness.js
```

Para más detalles técnicos de limpieza, OCR y reglas tipográficas, consulta `docs/TRADUCCION_TYPEO.md` y `docs/OCR_INGLES.md`.
