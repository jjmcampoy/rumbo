# Mejoras de esta versión

Resumen en corto, para quien usa la app, de lo que ha cambiado. El detalle técnico está en los
commits: hay uno por tarea.

## Seguridad

- **El panel ya no habla con terceros desde tu navegador.** El precio en vivo de la cripto lo sirve
  la propia app (`/api/vivo`), así que tu IP y las monedas que sigues dejan de irse cada minuto a
  CoinGecko y Binance. Tampoco desde la página que publiques.
- **Un nombre ya no puede ejecutar código.** Todo lo que se pinta en el panel va escapado, así que
  un producto llamado `<img src=x onerror=…>` se ve tal cual, sin sustos.
- **La app se defiende de una web ajena**: cabeceras de seguridad con `Content-Security-Policy`,
  comprobación de `Host` y de `Origin`, y una cabecera propia obligatoria en las peticiones que
  escriben. Un `Host` que no esté en `RUMBO_HOSTS` recibe un `421`.
- **Límites al subir archivos** (25 MB, 50 archivos, 50 000 filas) y **validación de las copias de
  seguridad** antes de restaurarlas.
- **Tus datos en disco pasan a ser solo tuyos**: archivos `0600` y carpetas `0700`.
- **Dependencias fijadas** y Werkzeug actualizado a 3.1.9 (corrige un aviso de seguridad en Windows).
- La documentación de privacidad ahora dice **exactamente** qué sale del ordenador y qué no.
- Sigue siendo **de un solo usuario y sin autenticación**: si la publicas en tu red, ponla detrás de
  un proxy con contraseña.

## Nuevo: varias carteras

- **Varias carteras en la misma instalación**, con un desplegable arriba para cambiar de una a otra.
- Pantalla **Portfolios**: crear, renombrar, duplicar, borrar y activar carteras. Al borrar se guarda
  una copia antes, y la última no se puede borrar.
- **Extraer productos** de la cartera activa a una cartera nueva, copiándolos o moviéndolos, con sus
  movimientos y sus valores anotados.
- Tabla **Comparar** y **gráfica de evolución conjunta**, con su fila y su línea **TOTAL**.
- **Dos pestañas a la vez**: añade `?cartera=<id>` a la dirección y esa pestaña se queda con esa
  cartera sin cambiar la que tienes activa.
- Tu cartera antigua **se pasa sola a la estructura nueva** la primera vez que abres esta versión, y
  deja el archivo original guardado en `mis_datos/copias/`.

## Arreglado: participaciones de MyInvestor, totales e importaciones duplicadas

- **Las participaciones de los fondos de MyInvestor se calculan bien.** El CSV no las trae: ahora se
  derivan de la **inversión / VL de la fecha fiscal**, y en los lotes que llegaron por **traspaso**
  se usa el **valor de mercado** del extracto.
- **Vuelve a importar cada fondo después de actualizar.** Es lo que corrige las participaciones que
  se guardaron con la fórmula antigua y borra las **ventas fantasma** que esa fórmula podía crear. El
  mismo CSV y el mismo botón: no hay que tocar nada más.
- **Las plusvalías de lo ya vendido no se convierten en ventas.** Se te muestran al importar, para
  cuadrar con tu bróker, y no entran en el panel.
- **Sin duplicados**: reimportar el mismo fondo **sustituye** lo anterior en vez de sumar, y el mismo
  ISIN repetido en dos archivos se detecta y se avisa.
- **Fechas y columnas tolerantes**: fechas en varios formatos, columnas en cualquier orden y el
  separador que traiga la cabecera.
- **Avisos en vez de silencio**: un saldo anotado sobre un producto con precio automático se rechaza
  con un mensaje (antes se perdía) y las unidades que no cuadran con el importe se señalan.
- **Los totales cuadran**: la vista previa enseña la reconciliación fondo por fondo, con el valor del
  extracto y el calculado.

## Interno (pruebas)

- Red de seguridad de **146 pruebas** que corren **sin internet** y en menos de dos segundos, con la
  caché de precios sembrada: API, motor, almacén, importación, seguridad y multi-cartera.
- Guardias de regresión para el escapado, las cabeceras, los límites, las copias y los permisos de
  los datos; cada una se comprobó **rompiendo a propósito** lo que vigila, para que no valga de adorno.
- La disposición de `mis_datos` cambia por dentro (una carpeta `carteras/`, un archivo por cartera),
  pero **no tienes que hacer nada**: la migración es automática y guarda copia.
