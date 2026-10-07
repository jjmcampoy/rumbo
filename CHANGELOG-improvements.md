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

## Interno (tests)

- Suite de tests completa en `tests/`: seguridad (escape y cabeceras), importación MyInvestor, migración de datos, aislamiento entre carteras y flujo HTTP completo. Se ejecuta sin red y en segundos.
