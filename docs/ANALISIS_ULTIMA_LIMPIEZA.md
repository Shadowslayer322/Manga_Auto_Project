# Revision de la limpieza de 53 paginas

La ultima limpieza ejecutada entre las 09:46:32 y las 10:44:02 del 16 de noviembre de 2026 realizo 234 rellenos generativos y 25 aplicaciones de pincel. El recuento inicial de 259 mezclaba ambas operaciones. Los datos originales quedaron respaldados en `backups/limpieza_rapida_20261116/`.

El problema principal era la clasificacion: un texto horizontal quedaba excluido de la ruta blanca, aunque estuviera dentro de un globo blanco. El detector solo aceptaba dialogos verticales en esa ruta. Ademas, no buscaba narracion fuera de las cajas YOLO y el segmentador podia convertir margenes exteriores de globos blancos en seleccion generativa. Por eso las paginas 01 y 52 quedaron sin zonas detectadas.

El recorrido anterior tambien inferia CTD dos veces por pagina, esperaba al capitulo entero y producia comparativas, trazados, zooms y JPEG. El recorrido de produccion usa una inferencia, publica cada pagina inmediatamente y guarda solo mascaras/estados necesarios y el PSD de resultado. Abre directamente las RAW, sin duplicarlas en disco; las guarda unicamente como copia PSD final.

La comprobacion nueva de las 53 RAW termino en 588,484 segundos de preparacion de mascaras en CPU. Una revision local adicional de fondos tarda unos seis segundos, sin repetir la inferencia: detecta las tramas claras que una simple mediana blanca puede confundir con papel blanco. El plan final contiene 56 llamadas generativas frente a 234: una reduccion del 76,1 %. Son 30 paginas con seleccion generativa y 23 que se resuelven con pincel. Se recuperaron zonas en las paginas 01 y 52. El recuento preliminar de 34 no incluia esta proteccion de las tramas. Las cifras describen mascaras y llamadas previstas; no equivalen a una nueva ejecucion completa del capitulo en Photoshop ni a una revision visual exhaustiva de todas las detecciones.

Se verifico en Photoshop la limpieza de las paginas 03, 04 y 52: cero llamadas generativas en esas paginas, RAW sin cambios y un PSD por pagina. En la 03 se revisaron visualmente los nueve globos vacios y la conservacion de las onomatopeyas dibujadas. La 52 recupera la narracion horizontal omitida. El recorrido final de guardado directo de la 04 termino en aproximadamente cinco segundos con las mascaras ya preparadas, sin JPEG, copias RAW ni monitor de aprobacion de dialogos.

Pruebas automaticas: 47 aprobadas. Cubren dialogo horizontal, narracion omitida por YOLO, una sola inferencia, recorte al globo blanco, rechazo de tramas claras como fondo plano, particion sin perder pixeles, publicacion temprana de la primera pagina y proteccion de PSD que ya contienen typeo. Los fondos complejos conservan relleno generativo por pares; los titulos estilizados y las detecciones automaticas siguen requiriendo revision visual.

Comando de limpieza directa:

```powershell
python scripts/ejecutar_todo.py --solo-limpieza
```

Para actualizar resultados de limpieza existentes se agrega `--reemplazar`. Este modo bloquea sustituir un PSD con texto editable por una version de solo limpieza. El comando sin opciones conserva el flujo completo de traduccion y typeo, que requiere guion/proveedor y geometria revisada del capitulo correspondiente.
