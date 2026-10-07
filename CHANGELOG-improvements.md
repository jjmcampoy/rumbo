# Historial de mejoras (post 1.1.x)

Resumen de las mejoras añadidas después de la versión 1.1, escrito para el usuario.

## Seguridad

- La app es más segura detrás de un proxy: los nombres de producto y los datos de las importaciones ya no pueden ejecutar código en tu navegador (fijación XSS corregida), y todas las operaciones de cambio exigen una cabecera propia y rechazan peticiones forjadas desde otras webs.
- Validación de `Host` (lista `RUMBO_HOSTS`, por defecto `127.0.0.1` y `localhost`) y límites de tamaño en las cargas (25 MB, 50 archivos, 50 000 filas).
- Las copias de seguridad se validan antes de restaurarlas: un archivo malformado ya no puede tumbar la app.
- Los archivos de `mis_datos` se crean con permisos restringidos (`0600`/`0700`).
- El precio en vivo de la cripto lo da ya nuestro propio servidor, no una web de terceros; la página exportada no sigue consultando a terceros.
- La app sigue siendo **de un solo usuario y sin autenticación**: debe usarse en tu propio equipo o detrás de un proxy que se encargue de la contraseña.

## Nuevo: varias carteras

- Puedes tener varias carteras en la misma instalación: el selector de la cabecera cambia de una a otra, y desde «Carteras» se crean, renombran, borran, y se mueven o copian productos entre carteras.
- El comparador muestra las carteras lado a lado, con métricas combinadas y evolución global.
- Cada cartera vive en su propio archivo en `mis_datos/carteras/`, y las copias automáticas se guardan por cartera. Las versiones anteriores migran solas (tu vieja `cartera.json` pasa a `carteras/`).

## Corregido: participaciones, totales y duplicados de MyInvestor

- Las participaciones de los fondos de MyInvestor ya se calculan bien a partir del extracto (el CSV no las trae): `inversión / VL de la fecha fiscal`, o el valor de mercado del extracto cuando el lote llegó por un traspaso.
- Cada importación substituye lo anterior del mismo fondo, sin duplicados.
- **Si importaste con una versión anterior, importa de nuevo cada fondo una vez**: así se corrigen las participaciones antiguas y cualquier venta fantasma.
- Los totales de la vista previa de importación y la asignación de la tarjeta de importación a su cartera están corregidos.

## Corregido: interfaz

- Al crear una cartera o al extraer productos, el formulario pedía el nombre aunque lo hubieras escrito: los campos se dibujaban con `name` pero el código los buscaba por `id`, así que leía siempre un valor vacío.
- El selector «Origen» (vacía / copia de otra cartera / copia del ejemplo) se ignoraba por el mismo motivo y creaba una cartera vacía.
- Arreglado: los campos ya llevan su `id`, y un test comprueba que cada `$("#id")` del editor tiene su elemento, para que no vuelva a pasar.
- Los selectores segmentados («Distribución», «Rango», «Vista», la tabla y la serie) ahora marcan claramente la opción elegida y siguen al clic: antes el resaltado se quedaba en la opción con la que se había cargado la pestaña —y la opción activa se pintaba además con el propio color de la tarjeta, así que parecía un hueco— y no había forma de saber qué estaba seleccionado.
- El anillo de «Distribución» vuelve a dibujarse cuando solo hay un valor (un producto, o un único grupo/entidad/tipo): antes el centro mostraba el total pero el anillo salía vacío.

## Corregido: rentabilidad

- La rentabilidad por año natural ya no inventa pérdidas en los años en los que entró dinero de un traspaso: lo que entra se valora por el **valor de mercado de las participaciones recibidas**, no por el coste fiscal heredado del fondo de origen. En una cartera real, 2022 pasa de −64,5 % a −9,2 %, que es la rentabilidad que de verdad hizo el fondo en ese periodo.
- El resto de cifras no cambia: lo aportado, la plusvalía y la TIR siguen calculándose sobre el coste fiscal del extracto.

## Interno (tests)

- Suite de tests completa en `tests/`: seguridad (escape y cabeceras), importación MyInvestor, migración de datos, aislamiento entre carteras y flujo HTTP completo. Se ejecuta sin red y en segundos.
