# Seguridad de Rumbo

**Versión soportada: 1.1.x.** Las versiones anteriores no reciben parches de seguridad.

## Diseño local, de un solo usuario

Rumbo está pensado para correr **solo en tu propio ordenador**: el servidor escucha por defecto en `127.0.0.1` y `localhost`, no hay cuentas ni autenticación, y los datos viven en la carpeta `mis_datos` sin cifrar.

**Por eso la app no debe exponerse a internet.** Si quieres abrirla desde otros equipos de tu red (por ejemplo, desde un NAS), ponla detrás de un proxy con autenticación y fija la variable de entorno **`RUMBO_HOSTS`** con los nombres por los que se podrá abrir, por ejemplo:

```
RUMBO_HOSTS=rumbo.lan,127.0.0.1,localhost
```

Sin esa variable, cualquier petición con otro `Host` se rechaza (421).

## Protecciones incluidas

- Cabeceras de seguridad en todas las respuestas: `Content-Security-Policy` (solo recursos propios), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy` y `Cross-Origin-Resource-Policy` en `same-origin`.
- **CSRF**: las peticiones que escriben (`POST`, `PUT`, `PATCH`, `DELETE` a `/api/…`) exigen la cabecera `X-Rumbo: 1`, que un formulario de otro sitio no puede poner; además se rechazan las peticiones `cross-site` y los `Origin` ajenos a `RUMBO_HOSTS`.
- **Límite de subida**: 25 MB por petición (413 si se supera).
- **Validación de las copias de seguridad** al subirlas: el archivo debe ser un JSON con el esquema de Rumbo.
- Los archivos de `mis_datos` se crean con permisos `0600`.
- El precio en vivo de la cripto lo sirve **nuestro propio servidor** (`GET /api/vivo`): el navegador no habla directamente con CoinGecko ni con Binance.

## Limitaciones conocidas

- **Sin autenticación**: no es apta para internet abierto; solo para uso local o detrás de un proxy que la proteja.
- **Sin cifrado en reposo**: `mis_datos` es legible por quien tenga acceso al disco.
- **Un solo usuario**: no hay cuentas ni roles.

## ¿Cómo reportar una vulnerabilidad?

1. **Preferido, en privado**: escríbenos por el canal privado del proyecto (ver la sección de contacto del README o el perfil del autor) con el detalle del problema.
2. **Alternativa**: abre una [incidencia en GitHub](../../issues) **sin detalles sensibles** (sin código que revele el exploit ni datos reales): describe el problema de forma general y te contactaremos para los detalles.

No publiques el detalle de una vulnerabilidad sin antes avisarnos: da tiempo a preparar un parche.
