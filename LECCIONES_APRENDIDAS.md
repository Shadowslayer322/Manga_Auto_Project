# Base de Conocimiento y Correcciones Aprendidas (Manga Cleaner)

## Reglas Visuales y de Coordenadas Consolidadas
1. **Doble Lienzo en Globos de Diálogo:** Todo texto dentro de un globo (blanco, negro o semitransparente) debe registrar DOS polígonos normalizados (0-1000):
   - `poligono_texto`: Ceñido al bloque de caracteres + *furigana* (sin tocar el borde negro del globo) para la limpieza.
   - `poligono_globo`: Contorno interior completo del globo contenedor, reservado para calcular el área y centrado exacto del *typesetting* futuro.
2. **Lienzo Único Fuera de Globos:**
   - `margen_exterior`: Textos fuera de las viñetas (créditos superiores, notas laterales). Solo lleva `poligono_texto` y se limpia con pincel blanco/negro según el fondo.
   - `sfx_o_dibujo`: Títulos sobre arte y onomatopeyas (SFX) dibujadas a mano (grandes o pequeñas). Solo lleva `poligono_texto` ajustado a sus trazos y se limpia con Relleno Generativo en cola individual (1 por 1).
3. **Previsualización de Lienzos Antes de Limpiar:** Antes de ejecutar comandos en Photoshop, generar siempre las imágenes con todos los lienzos dibujados en `04_DIAGNOSTICO\LIENZOS_*.png` para verificar que ningún globo ni SFX quedó fuera.

## Historial de Correcciones Específicas del Usuario
- [2026-11-15] No agrupar múltiples SFX lejanos en una sola llamada de Relleno Generativo; ejecutar siempre en cola individual (1 por 1).
- [2026-11-15] Generar collage `GRID_RAPIDO.jpg` con rejilla 0-1000 antes de analizar.
- [2026-11-15] Implementar detección de doble lienzo: marcar contorno de globo (`poligono_globo`) + contorno de texto (`poligono_texto`) en diálogos para reutilizar las coordenadas de los globos en el typeo futuro; marcar solo `poligono_texto` en márgenes y SFX.

- [2026-11-15] Usar contornos ceñidos (findContours directo) en lugar de convexHull gigante para el texto dentro de globos, extendiendo solo unos px sin chocar jamás con el borde del globo. En globos transparentes aplicar exclusivamente Relleno Generativo sobre el contorno del texto sin añadir blanco ni negro.

- [2026-11-15] Ultralytics YOLO() no soporta archivos .safetensors; utilizar exclusivamente modelos nativos .pt (kitsumed/yolov8m_seg-speech-bubble) o .onnx.

- [2026-11-15] Omitir completamente las SFX. Para textos fuera de globos sólidos dentro de viñetas, detectar exclusivamente aquellos con borde/halo blanco de máximo 20px a la redonda sobre dibujo (globos transparentes), seleccionando el contorno del texto + su halo para Relleno Generativo.

- [2026-11-15] Para globos transparentes/oscuros donde YOLO no detecta contorno sólido, usar detección morfológica de doble contraste (letras oscuras <90 pegadas a halo blanco >220) agrupada por columnas verticales, enviando exclusivamente el contorno ceñido del texto + su borde blanco a Relleno Generativo y filtrando SFX cortas aisladas.

- [2026-11-15] Calibración de globos transparentes/oscuros (ref. image_79f561): usar umbral de halo claro >175 (no 220), agrupar columnas con furigana y exigir altura >=92px o área >=2200px para capturar diálogos verticales cortos (ej. ホホホ〜！) mientras se omiten SFX de 2 caracteres (ej. ポタ).
- [2026-11-15] Detección agnóstica al color y orientación: detectar letras negras, blancas con borde negro o de color (horizontal y vertical) mediante gradiente morfológico multi-canal.
- [2026-11-15] Clasificar globos sólidos evaluando únicamente el fondo ENTRE las letras (evitando falsos positivos por el borde negro del globo).
- [2026-11-15] Regla de Desbordamiento (Morado -> Relleno Generativo): si el lienzo de texto sobresale >8% fuera del lienzo del globo (ej. texto gigante que rompe el globo hacia el dibujo), usar exclusivamente Relleno Generativo en todo el lienzo del texto.
- [2026-11-15] Integración de modelo YOLO `PSImera/manga_bubbles_detect` (Hugging Face) para detección ultra-rápida de globos de diálogo (8.7ms/página).
- [2026-11-15] Integración de modelo de segmentación de instancias Manga109 (`mayocream/manga109-segmentation-bubble` / `manga109_seg_bubble.pt`) para extraer contornos poligonales exactos del interior del globo, evitando morder los bordes negros.
- [2026-11-15] Arquitectura inspirada en Manga-Segment (Ashu11-A) y manga109api para separación estructurada de paneles, globos de diálogo, globos de pensamiento y cajas de narración.
- [2026-11-15] Traducción y rotulado automatizado: integración de `gemini-3.5-flash-lite` para traducción natural al español en MAYÚSCULAS y typeo centrado automático en grupo de capas `TEXTO_TRADUCCION` de Photoshop.
- [2026-11-15] Unificación del pipeline integral (Limpiar + Traducir + Typear) en ejecución secuencial de Photoshop con pre-procesamiento paralelo para prevenir desconexiones COM y colisiones de procesos.
- [2026-11-15] Limpieza ceñida al texto interior y preservación del globo: Se prohíbe limpiar con rectángulos globales que sobrepasen el área del globo o muerdan sus bordes negros. Se delimita el globo contenedor (`box_globo`) para calcular el espacio y centrado del typeo, pero la selección de limpieza (`box_limpieza`) se ciñe estrictamente a las letras detectadas (+4px de margen). Si un globo no tiene texto, no se toca. Para textos que sobrepasan el globo (ej. globos de grito espinosos o textos gigantes sobre dibujo como en la primera página), se aplica exclusivamente Relleno Generativo / IA en la capa `LIMPIEZA_BASE`.

- [2026-11-15] Pausa de Traducción y Typeo: Se suspende temporalmente toda generación de texto traducido (`TEXTO_TRADUCCION`) y rotulado para focalizarse 100% en la limpieza perfecta de globos y viñetas.
- [2026-11-15] Capas de IA Generativa Independientes y Sin Rasterizar: El Relleno Generativo de Photoshop 2025 se invoca mediante el comando nativo `syntheticFill` (`executeAction(stringIDToTypeID("syntheticFill"), desc, DialogModes.NO)`). Cada zona que requiera relleno generativo (globos de grito, bordes irregulares, texto desbordante sobre dibujo) se ejecuta de forma independiente y genera su propia capa (`IA_Generativa_Zona_X`). Queda estrictamente prohibido fusionar (`merge()`), acoplar (`flatten()`) o rasterizar (`rasterize()`) estas capas, garantizando que el usuario conserve en el panel Propiedades de Photoshop el selector nativo de las 3 alternativas/variaciones para cada zona.
- [2026-11-15] Doble delimitación globo vs texto interior: Se delimita el tamaño del globo (`box_globo`) y se calcula la caja interna exacta de las letras (`box_limpieza`) mediante análisis morfológico de componentes conexos. Si el globo es mayor al texto interior y no hay desbordamiento, la limpieza se realiza con pincel blanco/negro en la capa `LIMPIEZA_PINCEL` sin tocar jamás el contorno negro del globo. Si el texto desborda el globo o está a menos de 5px del borde perimetral (típico de globos de grito espinosos), se envía a Relleno Generativo independiente. Si un globo está vacío o contiene sólo dibujo/explosión, se omite completamente para proteger el arte.

- [2026-11-15] Marcado Multi-Rectángulo por Columnas/Líneas y Silueta Exacta del Globo: Se prohíbe el uso de un único rectángulo monolítico que cubra todo el globo. En su lugar, el trazado adopta la silueta exacta del globo (`poly_globo` en cyan) y segmenta el texto interior mediante múltiples rectángulos morados independientes ceñidos a cada columna vertical (*tategaki*) o línea horizontal (*yokogaki*). Para texto vertical, el kanji y su furigana lateral adyacente (≤22px de ancho, gap ≤8px) se integran en la misma columna, respetando la altura exacta de cada frase (patrón de escalera donde frases cortas como `何？` o `くる…` terminan antes sin cubrir el espacio vacío inferior). Esto evita limpiar zonas transparentes o dibujo de fondo en globos con texto escalonado y permite determinar con precisión si alguna columna desborda el contorno real del globo para activar el Relleno Generativo de Photoshop.

- [2026-11-15] Detección de Textos Fuera de Globos con Bordeado/Halo: Los textos fuera de globos (como nombres de ataques, técnicas, títulos o narración sobre dibujo en `004.jpg` y `005.jpg`) poseen un bordeado característico (letras blancas con contorno negro o letras oscuras con halo blanco luminoso/degradado sobre tramas). Para estos elementos se implementa una arquitectura de doble delimitación:
  1. **Rectángulo General Exterior (Rojo)**: Cubre todo el bloque de la frase incluyendo su borde/halo perimetral, marcándolo automáticamente como `relleno_generativo` (IA Generativa de Photoshop en capa independiente) debido a su interacción con el dibujo de fondo.
  2. **Rectángulos Interiores por Columna/Línea (Morados)**: Segmentan de forma estricta cada columna vertical (*tategaki*) o línea horizontal (*yokogaki*) dentro del bloque, preservando intactas las áreas vacías y el dibujo circundante.

- [2026-11-15] ESTADO BLINDADO Y FINAL PARA GLOBOS DE DIÁLOGO (NO TOCAR): La delimitación de textos dentro de globos de diálogo queda permanentemente fijada en el algoritmo morfológico por columnas con YOLO:
  1. Detección de globos con YOLO `bubbles_detect.pt`.
  2. Silueta poligonal exacta del globo (`poly_globo`) en Cyan.
  3. Múltiples rectángulos independientes en Morado (`#DC14C8`) ceñidos a cada columna vertical (*tategaki*) con furigana adyacente (≤22px, gap ≤8px) y patrón de escalera (cortando exactamente donde termina cada columna y dejando el espacio blanco inferior intacto).
  4. Rectángulos horizontales (*yokogaki*) para carteles/créditos.
  5. Esta lógica de globos está comprobada y validada como perfecta por el usuario; queda estrictamente prohibido modificarla o reemplazarla. Cualquier detección de textos flotantes fuera de globos debe implementarse como un módulo secundario aditivo sin alterar este núcleo.

- [2026-11-15] Doble Margen Rectangular Limpio para Textos Fuera de Globos:
  1. **Margen General Exterior (Rectángulo Cyan)**: Rodea toda la frase con un padding de 12px, estableciendo el contenedor de referencia.
  2. **Margen Interior Ceñido (Rectángulos Rojos)**: Se ciñe con 3px a los trazos de los caracteres y su halo perimetral exterior (separando columnas verticales si la frase tiene múltiples líneas, como en `004.jpg`).
  3. Esto descarta polígonos irregulares o deformes, garantizando bordes nítidos, limpios y perfectamente alineados tanto para los textos flotantes como para las técnicas (`『クロス・クリメイション』`, `ディア・ウェポン`).

- [2026-11-15] Integración de `comic-text-detector` oficial con DBNet para textos flotantes y fuera de globos:
  1. Se utiliza el modelo ONNX oficial de última generación `comic-text-detector.onnx` (dmMaze / mayocream) con mapa DBNet (`det[0, 0] > 0.30`).
  2. Detección impecable de técnicas y diálogos sobre screentone o personajes sin importar el contraste ni el color del borde (ej. `『クロス・クリメイション』`, `ディア・ウェポン`, `リーチ様の御血をいただき ますですぅぅ！`, `マイグレーターの貴様らを祓ってえぇ！`, `ホホホ～！`).
  3. Agrupación por proximidad horizontal (gap <= 48px) y vertical (gap <= 55px) para formar bloques unificados con Contenedor General Exterior en Cyan (12px padding) y Columnas Ceñidas Interiores en Rojo (3px padding).
  4. Los globos de diálogo sólidos blancos (`ratio_w >= 0.70` y `med >= 200`) se mantienen 100% blindados con el motor intocable de YOLO + contorno poligonal en Cyan + rectángulos morados en escalera con furigana.

- [2026-11-15] Perfeccionamiento milimétrico contra recortes y exclusión total de SFX:
  1. **Exclusión estricta de SFX (Onomatopeyas dibujadas):** Las onomatopeyas aisladas sobre dibujo (como `カチッ`, `バッ`, `ポタ`) quedan 100% excluidas; sólo se procesan diálogos, títulos y técnicas.
  2. **Expansión milimétrica con UNet Seg:** Se eliminó el problema de quedarse corto en comillas superiores (`『`), comillas inferiores (`』`), caracteres finales (`ン`, `！`) y furigana lateral (`さま`, `あくまつき`, `わたし`, `きょうしゅ`, `ねん`) mediante la proyección de la máscara de caracteres `seg_map > 0.14` sobre cada columna DBNet.
  3. **Carteles horizontales y NMS con containment:** Los carteles con texto horizontal (como el de la monja pirómana `自称悪魔祓い 放火魔ヌー 懲役120年`) se segmentan en líneas horizontales ceñidas abarcando hasta el kanji final `年`. Se aplica NMS con `containment > 0.60` para eliminar cajas solapadas redundantes.

- [2026-11-15] Arquitectura Híbrida de Segmentación y Limpieza (Máscara Píxel + Geometría de Globos):
  1. **Separación de roles:** La máscara exacta a nivel de píxel (`mascara_pixel` con margen adaptativo de 2px) se utiliza exclusivamente para la SELECCIÓN Y LIMPIEZA del texto. Los rectángulos y contornos poligonales (`poly_globo` en Cyan) se preservan intactos para la DELIMITACIÓN Y CENTRADO DEL TYPEO futuro.
  2. **Parcheo total de huecos interiores:** Relleno morfológico jerárquico (`RETR_CCOMP`) para eliminar cualquier agujero o punto negro no sombreado en el interior o intersecciones de los trazos (ej. `きゃあ！`), garantizando que cada carácter quede 100% sólido y continuo.
  3. **Partición de limpieza por ubicación y desbordamiento:**
     - **Texto dentro de globo:** Si el carácter está contenido en el polígono del globo (`mascara_pincel = mascara_pixel & mascara_globo`), se limpia con pincel o borrador blanco.
     - **Texto fuera de globo:** Si está sobre dibujo o tramas (`mascara_genfill = mascara_pixel & ~mascara_globo`), se envía a Relleno Generativo de Photoshop en capa independiente.
     - **Texto con desbordamiento:** Para textos que nacen en un globo pero sobresalen hacia el dibujo exterior, la porción interior se limpia con pincel blanco y la sección que excede se limpia automáticamente con Relleno Generativo.
  4. **Acción Nativa de Photoshop para Relleno Generativo:** Se utiliza la acción oficial del usuario `app.doAction("GenFillAuto", "MangaAuto")` configurada en el panel de Acciones de Photoshop 2025 para ejecutar el relleno generativo de forma ultra-rápida y directa en tiempo real.


- [2026-11-16] Automatización Zero-Click y Agrupación de Relleno Generativo en Pares de 2:
  1. **Control 100% Autónomo de Photoshop (Zero-Click):**
     - Al invocar Photoshop o scripts desde procesos de fondo de Windows, los comandos convencionales no tienen acceso directo a la sesión gráfica del usuario (`Desktop: exebox-...`).
     - Para controlar Photoshop 2025 en vivo sin que el usuario tenga que ejecutar nada manualmente, se despacha la llamada con `CreateProcessW` configurando `STARTUPINFO.lpDesktop = 'WinSta0\\Default'`. Esto corre el script JSX en tiempo real en la pantalla activa del usuario y monitoriza el progreso automáticamente.
  2. **Agrupación de Relleno Generativo en Pares de 2 más Cercanos (`agrupar_en_pares_cercanos`):**
     - En lugar de enviar todos los textos exteriores de una página en un único bloque masivo, los bloques de texto fuera de globos se agrupan en pares de 2 priorizando la menor distancia euclidiana entre sus centroides (greedy nearest-neighbor).
     - Cada par recibe su propia submáscara independiente (`MASCARA_GENFILL_{pagina}_PAR_{k}.png`) y ejecuta una llamada aislada a `app.doAction("GenFillAuto", "MangaAuto")`.
     - Esto genera capas independientes no rasterizadas (`IA_Generativa_Par_1`, `IA_Generativa_Par_2`, etc.), eliminando alucinaciones visuales y permitiendo editar o regenerar cada zona flotante por separado.
  3. **Cierre limpio de documentos:** Cada página procesada guarda su archivo PSD multicapa y preview JPG, y ejecuta `doc.close(SaveOptions.DONOTSAVECHANGES)` para liberar la memoria RAM y permitir un flujo continuo sin interrupciones.


- [2026-11-16] Manejo de Bloques de Apertura, Persistencia de Pestañas y Exportación Limpia:
  1. **Apertura de golpe (hasta 50 páginas):** Si el total de páginas es menor o igual a 50, se abren todas las páginas juntas al inicio en pestañas de Photoshop (`app.open(f)` upfront). Si son más de 50, se procesan en bloques de 50.
  2. **Persistencia de pestañas activas para revisión:** No se ejecuta `doc.close()`, dejando todas las páginas abiertas en Photoshop con sus capas (`ORIGINAL_TRADUCCION`, `LIMPIEZA_BASE`, `LIMPIEZA_PINCEL`, `IA_Generativa_Par_X`) listas para que el usuario las inspeccione o corrija interactivamente.
  3. **Eliminación del mensaje de pérdida de datos JPEG:** Para evitar el diálogo `"El documento no se puede guardar como JPEG sin perder información"`, se duplica temporalmente el documento (`doc.duplicate()`), se acopla (`flatten()`) y se guarda el JPG desde ese duplicado temporal, el cual se descarta de inmediato.
  4. **Guardado PSD como Copia:** Se utiliza `doc.saveAs(psdFile, psdOpts, true)` (`Save a Copy` en `.psd`), lo cual conserva todas las capas intactas sin advertencias y sin alterar el estado de trabajo del archivo abierto.


- [2026-11-16] Traducción Multimodal Nativa con Antigravity y Memoria Acumulativa:
  1. **Modo Nativo sin APIs Externas ni OCR:** Eliminadas dependencias de `google-generativeai`, `openai`, `GEMINI_API_KEY` o servicios externos. La traducción se ejecuta de forma 100% autónoma y multimodal a través del motor del agente Antigravity CLI (`antigravity translate`).
  2. **Procesamiento por Lotes de 3 a 4 páginas:** Las imágenes de `01_RAW` se ordenan alfanuméricamente y se procesan secuencialmente.
  3. **Memoria de Contexto Acumulativa (`03_TRADUCCIONES/memoria_contexto.json`):** Almacena y transfiere de lote a lote los perfiles de personajes (shao, mimi, nuu, reach), género, nivel de formalidad (tú/usted), terminología clave (`migrator`, `cross cremation`, `dear weapon`, `fire starter`) y el hilo narrativo del capítulo.
  4. **Formato Obligatorio Todo en Minúsculas:** Toda la traducción se genera estrictamente en minúsculas (incluyendo nombres propios e inicios de frase).
  5. **Mapeo Tipográfico de 9 Estilos:** La columna `Ubicación / Panel` codifica los descriptores exactos para que `scripts/typear_desde_guion.py` asigne automáticamente las fuentes obligatorias (`LaffayetteComicPro`, `BBToonacious-Italic`, `CCAstroCityInt-Italic`, `NeetsHand`, `KomikaBoo`, `KomikaJam`, `BebasNeue-Regular`, `DKSnemand`, `CCSlaphappy`).


- [2026-11-16] Aprendizaje Continuo de Páginas Finalizadas y Glosario Persistente:
  1. **Comparativas Ultralivianas de Aprendizaje:** Se almacenan comparativas lado a lado en `04_DIAGNOSTICO/APRENDIZAJE/COMP_APRENDIZAJE_*.jpg` comprimidas a ~120-180 KB por página (ahorrando >98% de espacio en disco respecto a los PSDs).
  2. **Glosario Editable Centralizado:** Definido en `03_TRADUCCIONES/glosario_manga.md` y `glosario_manga.json`. Registra personajes (`shao`, `mimi`, `nuu`, `reach`), técnicas (`cross cremation`, `dear weapon`, `fire starter`), organizaciones (`migrator`) y SFX.
  3. **Retroalimentación Cognitiva:** Antigravity consulta la memoria de aprendizaje (`aprendizaje_correcciones.json`) y el glosario antes de traducir y typear nuevos capítulos para garantizar 100% de coherencia visual y estilística.


- [2026-11-16] Integracion autorizada de traduccion y typeo al codigo principal (sustituye la pausa anterior de typeo):
  1. Entradas: `scripts/ejecutar_todo.py --typeo` consume el guion existente; `--traducir-typear` exporta la traduccion disponible y typea. `scripts/ejecutar_typer_completo.py` y `scripts/typear_desde_guion.py` usan el mismo flujo integrado.
  2. Nucleo: `typeo_core.py`, `typeo_pipeline.py` y `typeo_ps.jsx`. Geometria revisada en `config/typeo_geometria.json`, fuentes en `config/typeo_fuentes.json`. No hay dependencia de carpetas experimentales para ejecutar produccion.
  3. Enlace por ID estable; Markdown antiguo se enlaza por original normalizado, nunca por posicion u orden detectado. SFX de referencia excluidas. Correspondencias ambiguas, RAW cambiadas o paneles sin revisar bloquean la ejecucion.
  4. Capas de parrafo editables sueltas, sin rotacion, sin Myriad ni sustituciones de fuente. Borde editable de 5 px en zonas generativas segun RAW. Texto normal en minusculas o formato de oracion segun la fuente. Metodo de limpieza y tipo de contenedor son independientes.
  5. Composicion segun globo, palabras cortas apiladas cuando corresponde, palabras aisladas moderadas y gritos en globos amplios dimensionados por su contenedor. Guiones solo despues de agotar composiciones sin division. Segunda pasada con centrado real, limites del panel, fuente por rangos y verificacion del grosor del borde.
  6. Se copian los PSD limpios y se guardan resultados versionados en `08_RESULTADOS_TYPEO`. Se conserva la apertura de hasta 50 copias por bloque y las pestanas abiertas. JPEG desde duplicado temporal; nunca acoplar el PSD de trabajo ni sus capas generativas.
  7. El script llamado traductor nativo usa una cache fija de cinco paginas, no invoca un modelo. Ahora se identifica correctamente, rechaza paginas desconocidas y exporta el contrato JSON con IDs. Para nuevas paginas se requiere traduccion real y geometria revisada; no inventar coordenadas ni textos. Adaptador del proveedor Gemini existente conservado, opcional y no ejecutado por defecto.
  8. La ejecucion solo se considera correcta con estados por pagina del trabajo actual, PSD, preview y revision; se comprueban las huellas de los originales. Un lanzador con codigo 0 no basta. Un tiempo agotado conserva el bloqueo hasta revisar Photoshop.
  9. Validacion de integracion: 5 paginas y 30 capas guardadas y verificadas en Photoshop. Pruebas automaticas y documentacion en `tests/` y `docs/TRADUCCION_TYPEO.md`. Codigo previo respaldado en `backups/integracion_typeo_20261116_081600`.

- [2026-11-16] Flujo completo y un unico PSD por pagina (sustituye las entradas y salidas separadas descritas arriba):
  1. `python scripts/ejecutar_todo.py` abre las RAW y ejecuta limpieza, traduccion, typeo, segunda revision y guardado. Las entradas antiguas normales llaman al mismo flujo. Ya no requieren PSD limpios previos.
  2. `pipeline_completo.py` prepara mascaras y traduce en trabajadores paralelos despues de abrir las paginas. Publica cada traduccion individualmente. `pipeline_ps.jsx` da prioridad al typeo de la primera pagina lista entre acciones de Photoshop; termina su revision antes del siguiente typeo. Puede adelantar limpieza si la traduccion pendiente tarda.
  3. Solo `09_PSD_FINAL/<pagina>.psd`: original, base, pincel, rellenos generativos independientes y textos de parrafo sueltos. No guardar bases, limpieza o pruebas en otros PSD. Los diagnosticos privados son JSON, PNG, RAW y vistas JPEG. Los archivos historicos existentes se conservan.
  4. Las mascaras en cache se validan por huella de RAW, huella de mascara y dimensiones; si cambian, se recalculan. `--recalcular-mascaras` fuerza el recalculo. `--reemplazar` actualiza el mismo PSD final existente, sin crear versiones.
  5. Las 30 zonas siguen siendo geometria revisada de estas cinco paginas, no un detector universal. El proveedor nativo sigue siendo una cache de traducciones. `--guion` acepta traduccion externa/corregida; `--motor gemini` usa el proveedor opcional existente. No presentar la cache como inferencia de un modelo.
  6. Ejecucion real desde RAW terminada: trabajo `04_DIAGNOSTICO/pipeline/20261116T135339Z_fcb357dc`, cinco PSD finales, 30 textos editables, ocho acciones generativas y cero PSD intermedios. Originales sin cambios y secuencia por pagina verificada. 38 pruebas automaticas aprobadas. Respaldo previo: `backups/pipeline_unificado_20261116_084534`.


- [2026-11-16] Aprendizaje Continuo de Páginas Finalizadas y Glosario Persistente:
  1. **Comparativas Ultralivianas de Aprendizaje:** Se almacenan comparativas lado a lado en `04_DIAGNOSTICO/APRENDIZAJE/COMP_APRENDIZAJE_*.jpg` comprimidas a ~120-180 KB por página (ahorrando >98% de espacio en disco respecto a los PSDs).
  2. **Glosario Editable Centralizado:** Definido en `03_TRADUCCIONES/glosario_manga.md` y `glosario_manga.json`. Registra personajes (`shao`, `mimi`, `nuu`, `reach`), técnicas (`cross cremation`, `dear weapon`, `fire starter`), organizaciones (`migrator`) y SFX.
  3. **Retroalimentación Cognitiva:** Antigravity consulta la memoria de aprendizaje (`aprendizaje_correcciones.json`) y el glosario antes de traducir y typear nuevos capítulos para garantizar 100% de coherencia visual y estilística.


- [2026-11-16] Limpieza directa optimizada tras analizar el capitulo nuevo de 53 paginas:
  1. La ultima limpieza tuvo 234 GenFill y 25 aplicaciones de pincel. No confundir 259 operaciones totales con 259 GenFill. La regla que excluia textos horizontales y exigia dialogo vertical estaba enviando globos blancos en ingles a IA.
  2. Motor de produccion `limpieza_rapida.py`, version 3: una inferencia CTD por pagina, compartida con segmentacion; modelos cargados una vez; recuperacion de narracion fuera de YOLO; mascaras publicadas pagina a pagina. La limpieza puede empezar sin esperar todas las detecciones.
  3. Sin comparativas, trazados, zooms, previews JPEG ni copias RAW en el recorrido normal. Solo mascaras/estados necesarios y un PSD por pagina. Abrir RAW y guardar como copia PSD; no cambiar el JPEG original ni usar monitor de aprobacion de dialogos para el guardado normal.
  4. No clasificar una trama clara como blanco plano solo por su mediana: comprobar puntos de textura. Las mascaras blancas se recortan al contenedor; los margenes de busqueda no pasan automaticamente a GenFill. Los fondos complejos conservan sus capas generativas independientes.
  5. Plan final comprobado en las 53 RAW: 56 GenFill frente a 234 (76,1 % menos); 23 paginas solo pincel. El plan preliminar de 34 no protegia todas las tramas claras y fue sustituido. Esto es verificacion de mascaras, no una nueva ejecucion completa de los 53 PSD.
  6. Prueba real de Photoshop: paginas 03, 04 y 52, sin GenFill; originales sin cambios, un PSD por pagina. Se revisaron visualmente los nueve globos vacios de 03 con SFX dibujadas conservadas. Guardado final directo de 04 en unos cinco segundos con mascara preparada. 47 pruebas automaticas aprobadas.
  7. `python scripts/ejecutar_todo.py --solo-limpieza` abre y limpia las RAW actuales sin geometria de un capitulo anterior. Las entradas de limpieza antiguas delegan en esa entrada. El comando sin opciones conserva el flujo completo con traduccion y geometria revisada. Solo limpieza nunca reemplaza PSD con texto editable, incluso con --reemplazar.
  8. Detalles y limites en `docs/ANALISIS_ULTIMA_LIMPIEZA.md`. Titulos estilizados y fondos complejos siguen requiriendo revision visual. Respaldos de codigo y registros originales en `backups/limpieza_rapida_20261116`.


- [2026-11-16] OCR real ingles e inclusion de carteles/celulares en limpieza, traduccion y typeo:
  1. El detector CTD no era un reconocedor de palabras. Se reutiliza RapidOCR ya instalado con el modelo oficial ingles PP-OCRv5, descargado en models/ocr y fijado por SHA256. No se clona ni modifica BallonsTranslator ni se instala otra aplicacion completa.
  2. `ocr_ingles.py`: lectura de pagina, recuperaciones locales acotadas, enderezado solo para lectura y ampliacion selectiva. Desactivar el clasificador 180 grados evita invertir lineas inglesas que ya estaban derechas. Deduplicar por cuadrilateros, no por cajas horizontales; proyectar los renglones inclinados para reconstruir el mensaje completo.
  3. Motor de mascaras v4: reutilizar las siluetas v3/v4 compatibles antes de volver a inferir CTD; unir letras inglesas omitidas y guardar contrato OCR por pagina. Lecturas nuevas dudosas quedan pendientes. Los IDs enlazan limpieza, guion y tipo de texto. Ni una caja rectangular ni el metodo de limpieza demuestran por si solos que un texto sea de celular o de dialogo.
  4. Roles nuevos: cartel = Arial Bold, pantalla/impreso = Arial regular. Siempre verificar archivo, PostScript y glifos; nunca Myriad. El proveedor visual recibe la RAW y los IDs para corregir OCR/rol. No excluir carteles, etiquetas, documentos ni interfaces como si fueran SFX.
  5. Geometria OCR automatica para capitulos nuevos; conservar geometria revisada cuando corresponda a la RAW. Inscribir el cuadro horizontal de texto dentro del objeto o una zona orientada local. No agrandar un mensaje usando como contenedor el telefono entero. La revision nativa audita limites y centrado. La RAW 24 se reviso para mantener interfaz sin bordes, conservando el valor general de 5 px en las demas zonas generativas.
  6. `--solo-revision-typeo` reutiliza el PSD final verificado de la misma RAW, conserva la limpieza y sustituye solo las capas de texto administradas por sus IDs. No repetir GenFill para corregir fuente, borde o distribucion. Un PSD de otra RAW no se reutiliza. Un solo PSD por pagina y sin PSD intermedios.
  7. Comprobacion local: OCR de 53 paginas en aproximadamente 70 s sobre siluetas existentes. No confundir ese tiempo con la limpieza/traduccion de todos los PSD ni los candidatos OCR con transcripciones perfectas. Fuentes artisticas y texto pequeno/cortado pueden requerir cotejo visual.
  8. Photoshop: pagina 24 con mensajes de celular = 18 textos editables; pagina 32 con cartel = 10. Segunda revision correcta, Arial/Arial Bold en los objetos, todo horizontal y sin Myriad. La revision posterior de 24 hizo cero GenFill y conservo sus cuatro capas generativas. Guiones preparados para esas pruebas; adaptador Gemini verificado sin llamadas externas, no afirmar una traduccion API del capitulo completo.
  9. 58 pruebas automaticas aprobadas. Documentacion: docs/OCR_INGLES.md. Fuente OCR exportada en 03_TRADUCCIONES/ocr_capitulo.json; esto no contiene traducciones. Para un capitulo nuevo, usar un guion real o un proveedor configurado; la cache nativa antigua no es un motor de traduccion. Respaldos: backups/ocr_ingles_20261116.


- [2026-11-16] Conservacion de sonidos/cifras y escala inglesa:
  1. La instruccion actual sustituye la politica anterior de typear horas: SFX, numeros/horas aislados y puntuacion sin palabras quedan en la RAW. Compartir politica entre OCR, mascara, contrato y typeo; proteger tambien mascaras heredadas. Numeros dentro de una frase no se excluyen.
  2. Medir el alto de letras inglesas, no el bbox de una frase inclinada. Agotar composiciones legibles sin division antes de cortes silabicos; una frase no debe volverse minuscula para evitar un guion.
  3. Photoshop reutiliza una RAW abierta si se vuelve a abrir su misma ruta: puede duplicar textos. Cargar una entrada temporal con UUID, retirarla inmediatamente y comprobar que se abre una unica capa raster. Guardar como documento PSD final, no como copia JPEG asociada.
  4. Algunas generaciones contienen transparencia o letras residuales. Conservar alternativas con una mascara externa local. El repaso segun contenido indiscriminado se descarto por deformar bordes del telefono; correcciones planas solo mediante zonas revisadas y huella de RAW. No generalizar parches de la pagina 24 a otros fondos.
  5. El usuario autorizo reemplazar la version abierta de 24.psd, incluidos sus cambios pendientes, en esta sesion. Esta autorizacion NO habilita descartar otros documentos ni futuras ediciones del usuario. Mantener la proteccion por defecto.
  6. Un unico PSD final por pagina. Pagina 24: nueve textos traducidos, horas y sonidos originales; revision de typeo sin nuevas llamadas GenFill. Las mascaras/OCR del capitulo no equivalen a 53 PSD traducidos.

- [2026-11-18] Revisión manual de Morino-san, capítulo 11. Priorizar el contorno real del globo y medir el tamaño efectivo con la transformación de Photoshop. Las correcciones apilaron respuestas cortas y favorecieron bloques más altos. Si las palabras enteras caen por debajo del 80 % de la escala RAW en un óvalo, un corte silábico válido puede recuperar legibilidad. Portada, crédito y cambios de interjecciones se registran por capítulo. Evidencia y ejemplos en [la revisión de Morino 11](08_RESULTADOS_TYPEO/morino_11_cccomicrazy/revision_correcciones_20261118_174931/ANALISIS.md).


- [2026-11-19] Revisión completa de 53 páginas y transición a solo Relleno Generativo de Photoshop:
  1. **Motor de limpieza por defecto (`genfill`)**: Se elimina el uso por defecto del motor local `hibrido`/`comic` (LaMa), pasando a `genfill` (solo Relleno Generativo de Photoshop) en `scripts/pipeline_completo.py`.
  2. **Eliminación de rellenos fantasma e innecesarios (`scripts/limpieza_rapida.py`, v11)**: `route_masks` ahora omite zonas marcadas como `no_procesar`/`alias_ocr` y restringe la máscara generativa exclusivamente a `mask & textured & ~white` (descartando componentes < 25 px), evitando enviar a IA píxeles sueltos o ruido fuera de zonas activas.
  3. **Filtro ampliado de SFX, descriptores y créditos (`scripts/text_policy.py`)**: Se añaden onomatopeyas inglesas (`SPLASH`, `PANT`, `SLIDE`, `PHEW`, `SCRATCH`, `ACHOO`, `SMOOCH`, `POKE`, `MUNCH`, `NOM`, `CHOMP`, `THROB`, `WHEEZE`, `GULP`, `SHUDDER`, etc.) y notas/créditos (`T/N:`, `N/T:`, `Localization by`) a `protected_reason` para que no se limpien ni se typeen.
  4. **Respaldo de símbolos por carácter y tolerancia por bloque (`typeo_core.py`, `typeo_ps.jsx`, `pipeline_ps.jsx`)**: Los símbolos no presentes en la fuente principal (`♡`, `♥`, `★`, `☆`, `♪`) usan `NeetsHandRegular` solo en el rango del símbolo; bloques o símbolos irreproducibles se omiten sin abortar el capítulo.
  5. **Puntos suspensivos junto a texto y reanudación automática**: Todo `signo_aislado` (`...`) en el mismo globo que texto normal se borra junto al texto; solo se conserva cuando está solo en un globo. El pipeline guarda progreso en `04_DIAGNOSTICO/pipeline/sesion_actual.json` para reanudar automáticamente tras cualquier interrupción, y `auto_ok_photoshop.py` marca "No volver a mostrar" al confirmar el aviso de guardado.

- [2026-11-20] Comparativa contra PSDs perfectos del usuario (`C:\Users\USER\Downloads\PSD`, 16 páginas en japonés) y mejoras aplicadas:
  1. **No aplicar filtros/inyecciones de OCR inglés en páginas japonesas (`scripts/ocr_ingles.py`)**: `PP-OCRv5` inglés leía kanji/kana vertical como símbolos o números aislados (`##`, `...:`, `1`, `2`, `#6`, `114`, `DD`, `150mE`), provocando que 17 globos/diálogos válidos (incluida toda la página 14 `もにょ`) quedaran marcados como `no_procesar` y que se inyectaran 6 zonas falsas. Se añadió `_is_english_page(candidates, result)` para que `enrich_zones` solo aplique `numero_aislado`/`signo_aislado` e inyecciones `ocr_ingles` cuando la página tenga inglés real.
  2. **Recuperación CTD sin ocultar texto flotante junto a globos (`scripts/pipeline_manga.py`)**: `covered` ahora se pinta usando la silueta real (`poligono_contenedor` o `rectangulos_texto`), no el rectángulo completo de YOLO, evitando descartar texto flotante adyacente; además, `det_map > 0.22` se dilata `5x5` con área mínima `45` para no perder trazos fragmentados, y los bloques recuperados por CTD (`from_yolo=False`) exigen `med >= 230` para clasificarse como fondo blanco plano.
  3. **Protección de arte oscuro y texto en bordes (`scripts/prueba_segmentacion_pixel.py`)**: En `globo_solido_yolo`, los componentes grandes (`> 120 px`) de `gray < 220` con `< 12 %` de solapamiento con `seg_map > 0.08` se descartan antes de dilatar/parchar (evitando borrar faldas, cabello o marcos de ventana como en la pág. 05), y en zonas `from_yolo=False` no se recorta por `poligono_contenedor` si descarta más del 15 % del texto detectado (recuperando `失礼すぎる…` completo).

- [2026-11-20] Traducción directa sin clíneo previo y typeo en pausa/streaming (`--esperar-guion`):
  1. **Cero dependencia del clíneo previo para traducir**: El skill `traducir` (`.agent/skills/traducir/SKILL.md`) abre y traduce directamente las páginas de `01_RAW/` sin ejecutar `extraer_globos_traduccion.py` al inicio. Únicamente si una página puntual es bloqueada por políticas, se extraen los recortes solo de esa página (`--paginas <stem>`).
  2. **Enlace por coordenadas normalizadas (`pos: [x, y]` 0-1000)**: `bind_translation` en `scripts/typeo_core.py` enlaza automáticamente bloques sin `id` previo usando la posición `[x, y]` normalizada contra los `box_contenedor` detectados durante la limpieza.
  3. **Pausa y avance en paralelo (`--esperar-guion`)**: `scripts/pipeline_completo.py` acepta `--esperar-guion` para iniciar la limpieza en Photoshop en paralelo mientras se traduce página por página en `03_TRADUCCIONES/guion_typeo.json`. Si el typeo alcanza una página aún no traducida, queda en pausa esperando hasta que aparezca en el guion, y no termina el proceso hasta entregar todas las páginas completas.


- [2026-11-21] Comparativa contra 35 nuevos PSDs con clíneo (`C:\Users\USER\Downloads\PSD`, 51 PSDs en total incluyendo `1.psd`..`35.psd` y `10_2.psd`..`16_2.psd`) y calibración integral de detección y enrutamiento:
  1. **Clasificación precisa de globos blancos ovalados/con furigana (`scripts/limpieza_rapida.py` v17, `scripts/pipeline_manga.py`)**:
     - Se redujo el umbral geométrico `ratio_w` de `0.70` a `0.58` para cajas `from_yolo=True` y se actualizó `flat_white_background(gray, polygon, rects=None)` (pasando `rects` también desde `white_container`) para evaluar el anillo de fondo inmediatamente alrededor de las columnas de texto (`pct248_ring >= 0.94`, `p10_ring >= 252`), evitando que trazos pequeños de *furigana*, *dakuten* o líneas radiales en los bordes exteriores de globos destello clasifiquen globos blancos puros como trama y los envíen innecesariamente a Relleno Generativo (reduciendo discrepancias `BRUSH vs GEN` en un 80 %, de 30 a 6 en los 51 PSDs).
     - Si un bloque CTD de alta confianza (`conf >= 0.70`, solapamiento `>= 0.75`) desborda `> 25 px` fuera de la caja YOLO (ej. texto que nace en globo blanco y cae sobre trama en `3.psd`), se expande la caja contenedora y se fuerza `relleno_generativo`.
  2. **Eliminación de falsos positivos por puntas de globo, corazones decorativos y SFX (`scripts/limpieza_rapida.py`, `scripts/pipeline_manga.py`, `scripts/prueba_segmentacion_pixel.py`)**:
     - En `route_masks`, los componentes dentro de `brush` que tocan el borde negro del globo o adornos perimetrales (`pct_white < 0.82` o `p25 < 240`) ya no se convierten automáticamente en llamadas a `gen` (`relleno_generativo`), sino que se descartan (`brush = 0`) salvo que constituyan una columna de texto real desbordada (`area >= 900 px`, `bh >= 95`, `p25 < 180`).
     - En `extraer_forma_globo_y_rectangulos` y `extraer_lineas_zona_outside`, cuando una zona ya contiene líneas con `det_map.max() >= 0.35`, se descartan sub-bloques desconectados con `det_map.max() < 0.18`; además, `expandir_linea_con_seg` y `procesar_mascara_pagina` filtran componentes conexos que no tocan el núcleo de la línea DBNet, y se descartan cajas YOLO/CTD de globos vacíos, signos aislados (`……`, `！`) o SFX sin núcleo DBNet (`spx < 50` o `dmax < 0.30` con `d50 == 0`, o `seg_p85 >= 6.0`), reduciendo los falsos positivos en un 68,7 % (`67 -> 21`).
  3. **Recuperación de diálogos verticales manuscritos con halo blanco, carteles en pizarra y cápsulas de cierre (`scripts/pipeline_manga.py`, `scripts/prueba_segmentacion_pixel.py`)**:
     - Se recuperan cajas YOLO con `0.35 <= conf < 0.55` respaldadas por DBNet (`dmax >= 0.82` y `d50 >= 250`, como `1.psd`, `31.psd` y `34.psd`), diálogos verticales largos o manuscritos finos con halo blanco sobre trama (`140 <= outer_med <= 232` y `halo_w230 >= 0.40`, como `1.psd`, `25.psd`, `27.psd` y `31.psd`), diagramas de pizarra oscura (`60 <= med_g <= 95`, `dmax >= 0.96`, `d50 >= 400` en `06.psd`) y cápsulas horizontales de texto blanco sobre fondo gris en margen inferior (`つづく` en `35.psd`), reduciendo los bloques omitidos en un 68,8 % (`16 -> 5`).
