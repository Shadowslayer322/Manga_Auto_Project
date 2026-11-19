# OCR ingles y textos de objetos

El flujo de limpieza ahora ejecuta OCR real en ingles con RapidOCR instalado y el modelo oficial `en_PP-OCRv5_rec_mobile.onnx`. La descarga de 7.872.351 bytes se verifico con SHA256 `c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8`, publicado en la [configuracion oficial de RapidOCR](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml). No se ha modificado el repositorio externo BallonsTranslator.

La deteccion CTD y la lectura OCR son tareas distintas. Las siluetas CTD existentes se reutilizan cuando coincide la RAW; se anaden las letras inglesas omitidas y sus coordenadas. No se repite la inferencia CTD solo para mejorar una lectura. Los modelos OCR se cargan una vez. Una lectura de pagina se complementa con un maximo de cuatro recuperaciones locales: enderezado de zonas inclinadas y recortes ampliados de texto pequeno o dudoso. El enderezado solo sirve para leer; las capas de Photoshop permanecen horizontales.

La deduplicacion usa cuadrilateros, no solo cajas horizontales: dos lineas inclinadas pueden tener cajas que se solapan aunque sean renglones diferentes. El orden de lectura del mensaje se reconstruye en su plano enderezado y despues se conservan las coordenadas RAW. No se aplica un corrector que invente nombres propios.

Los carteles, letreros, etiquetas, documentos, mensajes, nombres y textos de interfaces entran en el contrato de traduccion. El tipo de objeto puede venir del contexto OCR, una revision local o el proveedor visual. Una forma rectangular sola no demuestra que sea un celular. Fuentes verificadas: `cartel` usa Arial Bold; `pantalla` e `impreso` usan Arial regular. El proveedor puede conservar los roles de comic para dialogos y gritos. No se usa Myriad para sustituir caracteres ausentes.

Cada bloque tiene un ID estable dentro de sus zonas de limpieza. El proveedor recibe esos IDs, el texto leido, las coordenadas y la RAW; debe cotejar el OCR con la imagen y devolver exactamente una traduccion por ID. Los objetos no se excluyen como si fueran SFX. Una zona existente que el OCR no logra leer queda identificada para que el traductor visual la transcriba. Las nuevas detecciones con confianza insuficiente quedan en pendientes y no generan una nueva zona de borrado por si solas. Una traduccion vacia o un ID perdido impiden aprobar el PSD final.

Los limites de carteles y pantallas se obtienen de contornos o de una zona orientada proxima al texto RAW. Dentro de ella se inscribe el cuadro horizontal de parrafo. No se permite usar la cara completa de un telefono como excusa para agrandar un mensaje sobre los demas. La segunda pasada de Photoshop comprueba centrado, limites, texto editable, fuentes y bordes. En la pagina 24 se cotejo la RAW y se conservaron los textos de interfaz sin borde: los 5 px siguen siendo el valor general para zonas generativas cuando no hay un estilo RAW revisado diferente.

## Uso

```powershell
# Limpieza con deteccion y OCR de las RAW actuales.
python scripts/ejecutar_todo.py --solo-limpieza

# Flujo completo de capitulo nuevo con el proveedor configurado.
python scripts/ejecutar_todo.py --motor gemini --reemplazar

# Flujo completo con guion JSON traducido por ID.
python scripts/ejecutar_todo.py --geometria-ocr --guion ruta/al/guion.json --reemplazar

# Revisar el typeo ya guardado sin repetir los rellenos generativos.
python scripts/ejecutar_todo.py --paginas 24 --geometria-ocr --guion 03_TRADUCCIONES/guion_ocr_24.json --solo-revision-typeo
```

La geometria revisada existente conserva prioridad si coincide con las RAW. Para un capitulo nuevo se prepara geometria OCR automaticamente; `--geometria-ocr` permite solicitarla expresamente. Tambien puede exportarse una plantilla pendiente de revision con `preparar_geometria_typeo.py`. Las geometrias automaticas son propuestas conservadoras, no un detector infalible de paneles u objetos.

El modo nativo de traduccion continua siendo una cache del capitulo antiguo. El OCR no traduce: para paginas nuevas se requiere un guion o un proveedor real configurado. Las pruebas de Photoshop de esta integracion utilizaron guiones preparados de las paginas 24 y 32; el adaptador de Gemini se comprobo con pruebas sin llamadas externas y sin cambiar sus modelos. No se ha verificado una traduccion real del capitulo completo mediante ese servicio.

Configuracion: `config/ocr_ingles.json`; modelo: `models/ocr/`; fuentes: `config/typeo_fuentes.json`. Las revisiones por zona se fijan a la huella de su RAW. Los estados y lecturas individuales se guardan junto a sus mascaras; `03_TRADUCCIONES/ocr_capitulo.json` exporta el texto fuente y los pendientes, sin inventar traducciones. `instalar_ocr_ingles.py` permite descargar explicitamente el modelo si falta; no se descarga durante una limpieza. Las dependencias estan en `requirements-ocr.txt`.

## Comprobacion realizada

Se paso OCR por las 53 RAW actuales, reutilizando sus siluetas CTD. El ultimo recorrido tardo aproximadamente 70 segundos en este equipo; ese tiempo es OCR/preparacion sobre mascaras existentes, no limpieza y traduccion de todos los PSD. Se revisaron los mensajes inclinados de la pagina 24 y el cartel de la 32. Photoshop produjo 18 y 10 capas de texto nativas respectivamente, con una segunda revision y un unico PSD por pagina. Una revision posterior de 24 reutilizo las cuatro capas generativas existentes y ejecuto cero GenFill.

58 pruebas automaticas aprobadas. Incluyen lineas inclinadas solapadas, orden de mensajes, recuperacion sin duplicados, fuentes impresas, seleccion localizada, propagacion de IDs, JSON del traductor, reutilizacion de PSD de la misma RAW y conservacion de la limpieza. Las fuentes artisticas, texto cortado, dibujos parecidos a letras y lecturas dudosas siguen necesitando cotejo visual. Los contadores OCR son candidatos aceptados por confianza, no una garantia de transcripcion perfecta.

## Correccion de conservacion y escala (16 noviembre 2026)

Los sonidos (incluidos BRRR/VRRR/TMP), cifras y horas aisladas y signos sin palabras se conservan en la RAW: no se limpian, traducen ni typean. Se excluyen tanto del contrato como de las mascaras, incluso si estas proceden de una ejecucion anterior. Una cifra que forma parte de una frase, como «120 años», permanece con ella. Las zonas semanticamente revisadas como SFX tambien quedan protegidas. El reconocimiento de sonidos nuevos sigue dependiendo de la lectura y del contexto; la lista automatica no es exhaustiva.

El alto de letra inglesa orienta el tamano real de la fuente española. Para dialogos se buscan composiciones sin guion a una escala legible antes de recurrir a cortes silabicos; no se reduce toda una frase a texto diminuto solo para evitar el corte. Los mensajes de objetos conservan sus limites horizontales y pueden necesitar una adaptacion mayor.

Motor de mascaras v6 / contrato OCR v3: las zonas completamente leidas usan trazos OCR locales en lugar de selecciones CTD amplias. Los originales de sonido y cifras se protegen con margen para la expansion nativa de Photoshop. Los rellenos generativos conservan sus alternativas dentro de mascaras externas editables. El repaso de fondo es una correccion local revisada por RAW y zona; no se aplica relleno segun contenido indiscriminadamente a todos los textos.

La pagina 24 ahora contiene nueve textos traducidos editables. Sus horas y sonidos quedan originales. La cifra historica de 18 capas correspondia a la prueba anterior a esta regla. El capitulo dispone de mascaras/OCR actualizados; esto no significa que se hayan traducido o rehecho sus 53 PSD.

Verificacion de esta correccion: 64 pruebas automaticas aprobadas; cache de mascaras valida para las 53 RAW actuales; 55 elementos protegidos detectados y cero pixeles seleccionados en sus cuadrilateros. En el compuesto PSD de 24, los elementos protegidos coinciden con la RAW con diferencia maxima de un nivel RGB de 8 bits. Esta medida comprueba conservacion, no exhaustividad del OCR ni calidad editorial de todas las paginas. La correccion final de 24 no ejecuto nuevos rellenos generativos.
