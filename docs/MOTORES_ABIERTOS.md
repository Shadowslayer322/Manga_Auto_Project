# Motores abiertos: integracion y pruebas

## Estado comprobado el 18 de noviembre de 2026

Se conservaron las RAW y los PSD finales existentes. Las pruebas estan en `04_DIAGNOSTICO`.
Los motores nuevos son opcionales: el comando habitual conserva su comportamiento.

| Proyecto | Integracion disponible | Comprobacion |
|---|---|---|
| BallonsTranslator, GPL-3.0 | Motor OpenCV local mediante su clase oficial | 3 recortes reales y 1 caso sintetico |
| Comic Translate, Apache-2.0 | LaMa ONNX mediante su modulo oficial, entorno Python separado | 3 recortes reales y 1 caso sintetico; pagina 32 guardada en Photoshop con 3 capas locales independientes |
| Manga Image Translator, GPL-3.0 | LaMa Large mediante su interfaz asincrona oficial, Python 3.13 separado | 3 recortes reales y 1 caso sintetico |
| Manga OCR, Apache-2.0 | Lectura japonesa por recortes con IDs y huella de RAW | 12/12 ejemplos oficiales coinciden exactamente |
| Koharu, MIT/Apache-2.0 | Omitido por indicacion del usuario | Se habia comprobado version y conexion; no se integra al flujo |

Magi queda fuera de la integracion de produccion: sus modelos y datos se ofrecen solo para investigacion academica.
Las licencias de modelos y proveedores se revisan por separado de las del codigo.

## Comparacion de limpieza

Misma imagen y mascara para cada motor: recortes de 512 x 512 de paginas 01, 24 y 32, y un caso sintetico de 384 x 384 con imagen original conocida.
Los tiempos son la suma de cuatro inferencias, excluyen carga, descargas, Photoshop, OCR, traduccion y guardado PSD. Son pruebas de CPU; no predicen el tiempo de un capitulo completo.

| Motor probado | Inferencia total | Error absoluto medio en region sintetica (menor es mejor) | Pixeles cambiados fuera de mascara |
|---|---:|---:|---:|
| Ballons / OpenCV | 0,06 s | 26,36 | 0 |
| Comic / LaMa ONNX | 4,81 s | 18,96 | 0 |
| MIT / LaMa Large | 6,59 s | 17,79 | 0 |

El error de la imagen danada antes de reconstruir era 112,39. Es un unico caso sintetico, no una clasificacion general de calidad.
La comparativa visual `04_DIAGNOSTICO/comparativa_motores_abiertos.jpg` muestra mejor conservacion de tramas con ambos LaMa que con OpenCV, que introduce manchas y arrastre. La pagina 24 conserva imperfecciones de textura incluso con LaMa; requiere revision editorial.
No se probaron aqui todos los algoritmos de BallonsTranslator ni traductores remotos. Estos resultados no demuestran calidad de traduccion o typeo.

Prueba real de Photoshop: `04_DIAGNOSTICO/prueba_psd_motores_abiertos/32.psd`, 1448 x 2100, conserva ORIGINAL_TRADUCCION, LIMPIEZA_BASE, LIMPIEZA_PINCEL y tres grupos con capas locales. Se inspecciono la imagen compuesta y la estructura PSD. La capa original difiere como maximo un nivel RGB respecto de la RAW decodificada; no se modifico el archivo RAW. Informe: `verificacion_capas.json` en esa misma carpeta.

Prueba completa: `04_DIAGNOSTICO/prueba_completa_motores_abiertos/32.psd`, con 10 capas de texto nativas y tres capas de limpieza local. Se uso un guion preparado de prueba, sin llamar un traductor remoto. Se corrigieron visualmente el limite del globo 32_07 y la geometria del cartel 32_09 en `04_DIAGNOSTICO/geometria32_motores_revisada.json`; la revision de typeo conservo las mismas capas de limpieza. El limite automatico original del globo era demasiado amplio: las comprobaciones geometricas no sustituyen la revision visual. La muestra final se volvio a inspeccionar. Su imagen es `32_preview.jpg` y el informe estructural es `verificacion_capas.json` en la carpeta del PSD.

La prueba detecto una mascara antigua (motor 6 frente al motor 8 actual). Se corrigio la preparacion para actualizar mascaras antes de generar capas locales y rechazar mascaras antiguas antes de abrir Photoshop. No se permite recalcularlas a mitad de una ejecucion con capas externas.

Informes de inferencia:

- `04_DIAGNOSTICO/motores_abiertos/20261118_091750_651900/ballons.json`
- `04_DIAGNOSTICO/motores_abiertos/20261118_091750_651900/comic.json`
- `04_DIAGNOSTICO/motores_abiertos/20261118_092027_ab7d9b/mit.json`
- `04_DIAGNOSTICO/manga_ocr_prueba_oficial.json`
- `04_DIAGNOSTICO/koharu_herramientas.json`

## Repetir las pruebas

```powershell
python scripts/motores_abiertos.py pruebas
python scripts/motores_abiertos.py pruebas --motor comic --paginas 01,24,32
python scripts/ocr_japones.py --prueba-oficial --salida 04_DIAGNOSTICO/otra_prueba_ocr.json
```

Cada prueba de limpieza crea una carpeta nueva con entradas, mascaras, resultados, tiempos y errores individuales. La inferencia es local y no llama servicios de traduccion. No confundir un estado de prueba tecnica con aceptacion visual.

## Usar limpieza local en Photoshop

El modo predeterminado es `hibrido`: pincel para fondos lisos, LaMa local para los demas rellenos y GenFill de Photoshop para zonas de personaje revisadas. La primera zona revisada es el titulo que tapa la mano y la manga de la pagina 01.

`config/zonas_genfill.json` asocia cada RAW revisada con su SHA-256 y rectangulos `[izquierda, arriba, derecha, abajo]` en pixeles. Agrega un motivo a cada rectangulo. La regla toma solamente los pixeles de las mascaras existentes dentro de la zona, incluidos los que habian quedado asignados al pincel. El recuadro completo no se borra. Si cambia la RAW, la regla deja de aplicarse. En paginas nuevas se necesita revisar y marcar las zonas de personaje, ya que el modo no reconoce anatomia automaticamente. Si Firefly falla en una zona reservada, la ejecucion informa del error para revision.

Usa `--motor-limpieza comic` para una ejecucion exclusivamente local o `--motor-limpieza genfill` para usar Photoshop en todos los rellenos complejos.

Puedes preparar la limpieza local y guardar los PSD en un solo comando, con pincel blanco para fondos lisos y LaMa de Comic Translate en los pares restantes.

```powershell
python scripts/ejecutar_todo.py --solo-limpieza --motor-limpieza comic --paginas 01,24,32 --salida 04_DIAGNOSTICO/prueba_local
```

El [informe de la prueba final](../04_DIAGNOSTICO/comparativa_final_20261118/RESULTADOS.md) incluye tiempos, detalles visuales y los tres PSD de prueba.

```powershell
python scripts/motores_abiertos.py limpieza --motor comic --paginas 32
```

El comando imprime una ruta nueva `capas.json`. Genera una capa RGBA por cada par de mascara generativa. Conserva la limpieza blanca y las protecciones del flujo existente.
Antes de inferir comprueba que las mascaras pertenecen al motor actual; si es necesario, las regenera mediante el motor existente. El cache del flujo adopta despues esas mismas mascaras verificadas.

Usar la ruta impresa en una salida de prueba:

```powershell
python scripts/ejecutar_todo.py --solo-limpieza --paginas 32 --limpieza-externa RUTA_A_CAPAS_JSON --salida 04_DIAGNOSTICO/prueba_psd_local
```

`--limpieza-externa` tambien se admite en el flujo completo con `--guion` o el proveedor ya configurado. Antes de abrir Photoshop se comprueban huellas de RAW, mascaras y capas, dimensiones y transparencia exacta fuera de las mascaras. Se repite la comprobacion al publicar cada pagina. Photoshop coloca las capas locales en lugar de pedir nuevos rellenos generativos; original, base, pincel y texto siguen separados. La segunda revision del typeo sigue vigente.

No usar `--solo-revision-typeo` ni `--documento-preparado` con limpieza externa. Si se recalculan las mascaras y cambian, las capas antiguas se rechazan y deben regenerarse.

## Manga OCR para originales japoneses

```powershell
python scripts/ocr_japones.py --geometria geometria_japonesa.json --salida 04_DIAGNOSTICO/ocr_japones.json
```

La geometria contiene `paginas`, cada una con `archivo`, `raw_sha256` y `zonas`; cada zona necesita `id` y `box_ocr` o `box_contenedor` en coordenadas RAW. El modelo local se carga una sola vez. La salida conserva IDs y transcripciones; no inventa traducciones al espanol ni reemplaza el OCR ingles.
La salida no sobrescribe archivos existentes. `--modelo` permite seleccionar una carpeta de modelo local.
Se probo tambien el cartel japones real de la pagina 32, zona 32_09, que el OCR ingles dejo pendiente. Manga OCR devolvio `全商通行止`; la lectura cotejada visualmente es `全面通行止`. Este error queda registrado: acertar los 12 ejemplos oficiales no garantiza transcripcion perfecta de las RAW actuales. La traduccion de prueba del cartel se preparo despues del cotejo visual.

## Koharu

Omitido por indicacion del usuario. Se conservan las descargas y el cliente de conexion preparados durante la investigacion; no se activa en el flujo ni se declara probada su inferencia.

## Dependencias

- El Python 3.11 existente y sus paquetes no se actualizaron.
- Comic: `motores_externos/entornos/comic`, dependencias oficiales.
- MIT: `motores_externos/entornos/mit313`, Python 3.13 local en `motores_externos/python` y dependencias oficiales. Se necesitaron ambos indices indicados por el proyecto para resolver `rusty-manga-image-translator`.
- Datos/modelos Comic: `motores_externos/datos/ComicTranslate`. El SHA256 de LaMa ONNX se verifico con el catalogo oficial.
- MIT: modelo `lama_large_512px.ckpt`, SHA256 verificado `11d30fbb3000fb2eceae318b75d9ced9229d99ae990a7f8b3ac35c8d31f2c935`.
- Manga OCR reutiliza el modelo local existente. Los ejemplos oficiales estan en `motores_externos/manga-ocr/tests/data`.

Pruebas de regresion: `python -m pytest tests -q`, 91 aprobadas. Incluyen rechazo de RAW cambiada, mascara distinta, capa modificada, pagina duplicada y pixeles visibles fuera de la mascara.
