# Traduccion y typeo integrados

El OCR ingles ya forma parte de la limpieza y del contrato de typeo, incluidos carteles y pantallas. Ver [OCR ingles y textos de objetos](OCR_INGLES.md) para la recuperacion de texto inclinado/pequeno, fuentes impresas, geometria automatica y comprobaciones reales en Photoshop.

## Limpieza directa optimizada

Para abrir y limpiar las RAW actuales, sin esperar traduccion ni necesitar la geometria del capitulo anterior:

```powershell
python scripts/ejecutar_todo.py --solo-limpieza
```

El modo completo sigue siendo el comando sin opciones. `--solo-limpieza` termina en la fase de limpieza: no declara traduccion ni typeo completados. Ambos modos usan el mismo motor y guardan un solo PSD por pagina en `09_PSD_FINAL`. `--reemplazar` conserva el nombre; en modo de solo limpieza se bloquea reemplazar un PSD que ya contenga texto editable.

`limpieza_rapida.py` comparte una sola inferencia CTD entre deteccion y segmentacion, carga los modelos una vez y publica las mascaras pagina a pagina. Los dialogos horizontales tambien pueden usar pincel blanco. CTD recupera cartelas/narracion fuera de las cajas del detector de globos. Las mascaras de globos blancos se recortan a su interior, para que los margenes de busqueda no se conviertan en rellenos generativos. Una comprobacion local de textura impide tratar tramas claras de puntos como papel blanco. Los fondos con dibujo siguen usando GenFill en pares de bloques, conservando sus capas independientes.

La ejecucion normal no crea comparativas, trazados de colores, zooms, previews JPEG ni duplicados RAW. Solo necesita mascaras PNG y estados pequenos para pasar el trabajo a Photoshop y verificar su finalizacion. Los diagnosticos experimentales antiguos quedan fuera del recorrido normal; `pipeline_manga.py --diagnostico` conserva su modo explicito de inspeccion. No se eliminan resultados anteriores.

El flujo completo abre las RAW, prepara la limpieza y traduce en paralelo. Cuando una pagina tiene limpieza y traduccion listas, coloca sus textos, hace una segunda revision y guarda un unico PSD final en `09_PSD_FINAL/<pagina>.psd`. Despues continua con el typeo de la siguiente pagina. No necesita PSD de limpieza ni genera PSD intermedios.

## Ejecutar

Desde la carpeta del proyecto:

```powershell
# Abrir, limpiar, traducir, typear, revisar y guardar.
python scripts/ejecutar_todo.py

# Consumir una traduccion corregida.
python scripts/ejecutar_todo.py --guion 03_TRADUCCIONES/guion_traducciones.md

# Volver a trabajar las mismas paginas y reemplazar sus PSD finales.
python scripts/ejecutar_todo.py --reemplazar

# Regenerar las mascaras en lugar de reutilizar las ya verificadas.
python scripts/ejecutar_todo.py --recalcular-mascaras

# Entrada anterior conservada: traduccion y typeo.
python scripts/ejecutar_typer_completo.py

# Validar y preparar sin abrir Photoshop.
python scripts/typear_desde_guion.py --preparar

# Consumir un guion especifico de cualquier proveedor, con dos paginas seleccionadas.
python scripts/typear_desde_guion.py --guion 03_TRADUCCIONES/guion_typeo.json --paginas 001,003
```

`--guion` admite JSON con IDs o tablas Markdown existentes. Sin esta opcion se usa el proveedor local `nativo`, que contiene las traducciones almacenadas de estas cinco paginas. Para usar correcciones manuales se debe indicar su guion expresamente. Las entradas anteriores y los alias `--typeo` y `--traducir-typear` ejecutan ahora el mismo flujo completo.

Para el proveedor Gemini existente se puede indicar `--motor gemini`. Es opcional, requiere sus dependencias y credenciales previas y supone llamadas a ese servicio. Publica cada pagina traducida sin esperar a terminar el capitulo. La integracion no cambia modelos ni credenciales y no lo ejecuta por defecto.

## Limite real del traductor llamado nativo

`traducir_nativo_antigravity.py` contenia una tabla fija para estas cinco paginas; no invocaba un motor multimodal ni un CLI de traduccion. Se conserva como proveedor de traduccion local almacenada, se identifica como tal y rechaza paginas desconocidas en vez de generar `...`. Las RAW deben coincidir con las huellas revisadas. Para paginas nuevas hace falta un guion traducido real o un proveedor configurado, no cambiar solo el nombre del archivo.

Los dos productores existentes exportan `03_TRADUCCIONES/guion_typeo.json` con IDs cuando la correspondencia es valida. El guion textual se conserva para revision. La memoria del proveedor local no vuelve a registrar los mismos lotes en cada ejecucion.

## Contrato de traduccion

```json
{
  "version": 1,
  "paginas": [{
    "archivo": "001.jpg",
    "bloques": [{
      "id": "001_05",
      "texto_original": "シャオ先生に…",
      "traduccion_es": "a la doctora shao..."
    }]
  }]
}
```

`rol_fuente` es opcional. Si no se indica, se conserva el estilo revisado de la geometria. Para una traduccion Markdown antigua, se enlaza por texto original normalizado; si la misma frase aparece en varios globos se exige el ID, nunca se adivina por orden. Una columna adicional `Zona ID` permite indicar esos IDs en Markdown. Las tablas SFX solo de referencia no se typean. No se aceptan zonas duplicadas, traducciones vacias, japones pendiente ni zonas sin correspondencia.

## Geometria y nuevas paginas

`config/typeo_geometria.json` conserva las 30 zonas y los paneles revisados de las cinco RAW actuales. Contiene identificadores, huellas de las imagenes, contornos de globos, areas utiles, poligonos de vineta, estilos y excepciones cotejadas en RAW. No incluye traducciones ni los saltos de linea de una prueba: se recomponen con el guion recibido.

Los limites revisados de este capitulo no son un detector universal de paneles. El flujo de un capitulo nuevo usa las zonas OCR actuales cuando las RAW no corresponden a la geometria guardada. `--geometria-ocr` fuerza esta ruta; requiere un guion traducido o el proveedor configurado. Para exportar una plantilla y revisar manualmente otras paginas:

```powershell
python scripts/preparar_geometria_typeo.py
```

La plantilla pendiente usa las zonas de produccion y el texto OCR actuales; el manifiesto antiguo solo se usa si se solicita expresamente. Cotejar RAW, originales/IDs, contenedores transparentes, paneles, limites de objetos, colores y estilos. Una plantilla pendiente no puede ejecutarse como geometria revisada. Guardar la geometria revisada y pasarla con `--geometria` o actualizar el archivo configurado. Si una RAW cambia, el sistema bloquea las coordenadas antiguas.

El metodo de limpieza no decide si hay globo: el relleno generativo puede haber limpiado un dialogo dentro de un globo transparente. Las excepciones al limite de vineta requieren `permite_fuera_panel_raw` revisado; no se infieren por el color o por la limpieza.

## Reglas preservadas

- Una capa nativa de parrafo por globo, suelta en la raiz; nada de carpetas de typeo ni texto rasterizado.
- Los dialogos conservan su composicion habitual. Pantallas y carteles siguen la rotacion RAW; los mensajes de pantalla se alinean a la izquierda. `alineacion_raw` permite revisar izquierda, centro o derecha. La caja de composicion se calcula en los ejes del objeto y el texto sigue editable.
- Nueve roles de comic y tres roles para carteles, pantallas e impresos, con fuentes verificadas por nombre PostScript y archivo. Las rutas locales se configuran en `config/typeo_fuentes.json`.
- Comprobacion de glifos y equivalentes tipograficos antes de Photoshop. Auditoria de cada rango de texto: Myriad y las sustituciones de fuente producen un error, no un resultado aprobado.
- Texto en minusculas cuando la fuente no distingue ambos casos; de lo contrario, formato de oracion. No se impone todo en mayusculas.
- Borde editable de 5 px en zonas generativas, con el color de la RAW; blanco por defecto. El relleno y borde se configuran por zona.
- Risa y palabras muy cortas apiladas cuando conviene, con tamano acorde al globo. Las palabras aisladas normales no se agrandan indiscriminadamente; los globos de grito amplios tienen una politica de tamano revisada.
- Composiciones rectangulares, ovaladas y triangulares segun el contorno. Se agotan primero las alternativas sin division de palabras. Los cortes admitidos son silabicos y de ultimo recurso; no se parte una palabra arbitrariamente.
- Segunda pasada despues de colocar todos los textos de la pagina: medir, recentrar, comprobar desbordes, paneles, fuentes y bordes. La comprobacion geometrica no sustituye el criterio editorial visual.

## Ejecucion y resultados

`ejecutar_todo.py` es la entrada de control de Photoshop con `Photoshop.exe -r` y `cola_limpieza_ps.jsx`. Un bloqueo exclusivo protege todo el flujo. Se cargan las RAW desde disco en bloques de hasta 50. Una entrada temporal unica, retirada inmediatamente al abrir, evita reutilizar pestañas RAW que ya tengan textos. El documento pasa a ser el PSD final al guardarse; no se conserva una copia PSD adicional. Solo despues de abrirlas arrancan los trabajadores de traduccion y mascaras. Photoshop ejecuta una accion de limpieza a la vez; entre acciones da prioridad al typeo de la primera pagina pendiente que este lista. Si su traduccion tarda, avanza con la limpieza de otras paginas, manteniendo el orden del typeo y su revision.

Las mascaras se reutilizan solo si coinciden la version del motor, las huellas de RAW y de todos los archivos necesarios; de lo contrario se recalcula esa pagina. Cada PSD final conserva original, base, pincel, capas generativas independientes y, en el modo completo, capas nativas de texto. El guardado directo no exporta JPEG ni acopla el documento.

El codigo de salida del lanzador de Photoshop no se interpreta como exito: cada pagina debe producir un estado con el ID de ejecucion, un PSD y su revision. Un error de fuente, texto, centrado o panel detiene el lote. Un trabajo enviado no se reenvia automaticamente; ante un aviso o tiempo agotado se revisa el trabajo y se prepara una ejecucion nueva.

`09_PSD_FINAL` contiene un solo PSD por pagina, `RESULTADOS.md` y el estado final verificado. Para sobrescribir un PSD existente se exige `--reemplazar`; su nombre sigue siendo el mismo. Los contratos, mascaras PNG, tiempos e informes se guardan en `04_DIAGNOSTICO/pipeline/<ejecucion>/`, sin PSD. Las mascaras reutilizables estan en `04_DIAGNOSTICO/mascaras_produccion/`. Los archivos antiguos de pruebas se conservan; este flujo no los vuelve a generar.

Si vence el tiempo de espera, se conserva `02_TRABAJO_PSD/.typeo_photoshop.lock` porque Photoshop podria seguir ejecutando el lote. Confirmar que Photoshop termino y revisar el trabajo indicado en ese archivo antes de quitar el bloqueo manualmente. No se mata Photoshop ni se reenvia el trabajo automaticamente.

## Verificacion

```powershell
python -m unittest discover -s tests -v
node tests/status_jsx_harness.js
node tests/pipeline_ps_harness.js
```

Las pruebas cubren correspondencia por ID/original, reordenamiento, duplicados, fuentes, SFX, cambios de RAW, comillas de Photoshop, composicion, estados ajenos y conservacion de fuentes. Ademas debe verificarse una ejecucion real en Photoshop, porque un test local no garantiza su comportamiento tipografico.


Los sonidos, cifras/horas aisladas y signos sin palabras se preservan antes de limpiar y antes de traducir/typear. La escala inglesa sirve de referencia. Si un PSD abierto tiene cambios pendientes, el reemplazo se bloquea por defecto; `--reemplazar-version-abierta` solo debe usarse con autorizacion expresa para las paginas seleccionadas. No afecta a documentos ajenos al lote.


## Tipografia proporcional

CC KissAndTell regular para texto normal; italic para otros globos y bold italic para texto exterior. Encabezados de capitulo: Bebas Neue. Murmullos: Neets Hand. Las bases 18/20 y 22/20 son relaciones entre tamano e interlineado, no tamanos finales fijos. Se compone segun el contenedor y la escala de letra RAW, se conserva la alineacion y rotacion y se centra sobre el area revisada. Cada ajuste en Photoshop aplica interlineado = tamano * 20/18 (general) o tamano * 20/22 (capitulo y murmullo). Se mantiene texto editable y se audita la proporcion medida despues de colocar el texto. Se revisan signos de apertura de interrogacion y exclamacion.


## Optimizacion conservando el flujo (16 de noviembre de 2026)

Mascaras y traduccion/composicion siguen ejecutandose en paralelo despues de abrir las RAW. Photoshop conserva una accion a la vez, prioridad al typeo de la primera pagina lista y revision/guardado antes del typeo siguiente. No se amplian permisos de traduccion externa.

Las medidas de palabras se reutilizan dentro de cada tamano de fuente. Se eliminan las comprobaciones duplicadas de una cache valida, copias de mascaras vacias, escritura duplicada del contrato y limites de capas que no se usan en una revision solo de texto. Las RAW no seleccionadas no se abren para consultar dimensiones y huellas.

El contexto OCR (regiones protegidas y repasos) se incorpora desde la misma publicacion atomica que habilita la limpieza, antes de renderizar el texto. Los avisos de apertura de otra ejecucion no desbloquean trabajadores. Las zonas nuevas de baja confianza quedan pendientes, sin limpiar. La version de mascaras invalida las selecciones anteriores a esa correccion. Las capas generativas originales se conservan en revisiones de typeo.

Los ajustes tipograficos usan una correccion proporcional segun las dimensiones medidas, seguida de una nueva medicion; conservan el interlineado proporcional y el minimo. Los eventos `typeo_render_complete`, `psd_save_start` y `psd_save_complete` separan renderizado y guardado para medir futuras ejecuciones.

Validacion sin abrir Photoshop: pruebas unitarias, simuladores JSX y comparacion exacta de la composicion de cinco paginas. La mejora local medida no equivale a una promesa sobre el tiempo completo: los rellenos generativos siguen dependiendo de Photoshop y su servicio.
