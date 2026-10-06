# -*- coding: utf-8 -*-
"""
servidor.py  ·  La app local
============================
Arranca un pequeño servidor web en tu propio ordenador (solo accesible desde él,
en 127.0.0.1) y abre el navegador. Tus datos nunca salen de la carpeta mis_datos;
a internet solo se sale para descargar precios.
"""

import datetime as dt
import json
import logging
import os
import re
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.serving import make_server

from . import almacen, buscar, carteras, exportar, importar, motor, plantilla

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RAIZ, "app", "web")
# Otra carpeta de datos, solo para pruebas o capturas: PATRIMONIO_DATOS=ruta
DATOS = os.environ.get("PATRIMONIO_DATOS") or os.path.join(RAIZ, "mis_datos")
DEMO = os.path.join(RAIZ, "demo", "cartera.json")
PUERTO = int(os.environ.get("PATRIMONIO_PUERTO") or 8765)

# Migración ADR-3 (idempotente): la cartera antigua pasa a mis_datos/carteras.
carteras.migra_si_hace_falta(DATOS)
HORAS_PRECIOS = 6          # al arrancar, se actualizan si tienen más de esto

app = Flask(__name__, static_folder=None)
app.json.sort_keys = False   # respeta el orden de tipos y listas al mandarlos al navegador
cerrojo = threading.RLock()  # el motor no admite dos cálculos (ni dos escrituras) a la vez

# Cabeceras de seguridad para todas las respuestas (ver 01-security-analysis.md).
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

@app.after_request
def cabeceras_seguridad(resp):
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    return resp

app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024      # 25 MB por petición
MAX_ARCHIVOS = 50
MAX_FILAS = 50000


@app.errorhandler(413)
def demasiado_grande(_e):
    return jsonify(ok=False, errores=["El archivo es demasiado grande (máximo 25 MB)."]), 413


@app.errorhandler(carteras.ErrorCartera)
def _error_cartera(e):
    return jsonify(ok=False, errores=e.errores), 400

# Hosts y orígenes permitidos. En Docker hay que añadir el nombre del NAS:
#   RUMBO_HOSTS=rumbo.lan,127.0.0.1,localhost
HOSTS = tuple(h.strip().lower() for h in
              (os.environ.get("RUMBO_HOSTS") or "127.0.0.1,localhost").split(",") if h.strip())
CABECERA_ANTICSRF = "X-Rumbo"
MUTANTES = ("POST", "PUT", "PATCH", "DELETE")

def _host_de(valor):
    """'rumbo.lan:8765' -> 'rumbo.lan'; '[::1]:8765' -> '::1'."""
    v = (valor or "").strip().lower()
    if v.startswith("["):
        return v[1:].split("]")[0]
    return v.split(":")[0]

@app.before_request
def guardia_peticion():
    # 1) Host permitido: evita DNS rebinding.
    if _host_de(request.host) not in HOSTS:
        return jsonify(ok=False, errores=["Host no permitido."]), 421
    # 2) Peticiones de navegador de otro sitio: fuera (CSRF).
    if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        return jsonify(ok=False, errores=["Origen no permitido."]), 403
    origen = request.headers.get("Origin")
    if origen and _host_de(urllib.parse.urlsplit(origen).netloc) not in HOSTS:
        return jsonify(ok=False, errores=["Origen no permitido."]), 403
    # 3) Las rutas que escriben exigen una cabecera que un formulario cross-site
    #    no puede poner (multipart/form-data sigue siendo "simple" para CORS).
    if request.method in MUTANTES and request.path.startswith("/api/"):
        if request.headers.get(CABECERA_ANTICSRF) != "1":
            return jsonify(ok=False, errores=["Falta la cabecera %s." % CABECERA_ANTICSRF]), 403
    return None


# ---------------------------------------------------------------- archivos

def lee_json(ruta, defecto=None):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def escribe_json(ruta, datos):
    """Escribe en un archivo temporal y lo renombra: si se corta, no se pierde nada."""
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)
    os.chmod(ruta, 0o600)


def _cid():
    """El id de la cartera activa (o el defecto si no hay índice)."""
    return carteras.activa(DATOS) or carteras.ID_DEFECTO


def ruta_cartera(cid=None):
    return carteras.ruta(DATOS, cid or _cid())


def ruta_copias(cid=None):
    return os.path.join(DATOS, "copias", cid or _cid())


def ruta_calculado(cid=None):
    return os.path.join(DATOS, "calculado", (cid or _cid()) + ".json")


def ruta_estado(cid=None):
    return os.path.join(DATOS, "estado", (cid or _cid()) + ".json")


def ruta_historico(cid=None):
    return os.path.join(DATOS, "historico", (cid or _cid()) + ".json")


def modo():
    """'propio' si ya hay alguna cartera en mis_datos; si no, 'demo'."""
    return "propio" if carteras.lista(DATOS) else "demo"


def cartera(cid=None):
    """El documento de la cartera activa; {} si no existe (nunca lanza)."""
    if modo() == "demo":
        return lee_json(DEMO, {})
    return lee_json(ruta_cartera(cid), {})


def estado():
    return lee_json(ruta_estado(), {})


# ---------------------------------------------------------------- cálculo

def recalcula(descargar):
    """Recalcula el panel. Con descargar=True baja antes los precios nuevos;
    con "faltan", solo los de productos que aún no tienen precios guardados."""
    with cerrojo:
        datos = motor.construir(cartera(), DATOS, descargar=descargar,
                                historico=ruta_historico())
        est = estado()
        if descargar is True:
            est["preciosActualizados"] = dt.datetime.now().replace(microsecond=0).isoformat()
            escribe_json(ruta_estado(), est)
        if datos is not None:
            datos["modo"] = modo()
            datos["preciosActualizados"] = est.get("preciosActualizados")
        escribe_json(ruta_calculado(), datos)
        return datos


def precios_viejos():
    ultima = estado().get("preciosActualizados")
    if not ultima or not os.path.exists(ruta_calculado()):
        return True
    return dt.datetime.now() - dt.datetime.fromisoformat(ultima) > dt.timedelta(hours=HORAS_PRECIOS)


# ---------------------------------------------------------------- rutas

@app.get("/")
def inicio():
    return send_from_directory(WEB, "index.html")


@app.get("/datos.js")
def datos_js():
    datos = lee_json(ruta_calculado())
    if datos is None and not os.path.exists(ruta_calculado()):
        datos = recalcula(descargar=False)
    cuerpo = "window.DATOS = " + json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + ";\n"
    return Response(cuerpo, mimetype="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/actualizar")
def api_actualizar():
    try:
        datos = recalcula(descargar=True)
    except Exception as e:  # que la app no se caiga nunca por un precio
        logging.exception("Fallo al actualizar")
        return jsonify(ok=False, error=f"No he podido actualizar: {e}"), 500
    return jsonify(ok=True, avisos=(datos or {}).get("avisos", []))


@app.get("/api/cartera")
def api_cartera():
    return jsonify(modo=modo(), cartera=cartera(), tipos=motor.TIPOS, fuentes=motor.FUENTES,
                   tiposMovimiento=almacen.TIPOS_MOV,
                   carteraActiva={"id": _cid(), "nombre": carteras.nombre(DATOS, _cid())}
                   if modo() == "propio" else None,
                   carteras=[{**c, "activa": c["id"] == _cid()} for c in carteras.lista(DATOS)])


@app.get("/api/buscar")
def api_buscar():
    n = len(buscar.FALLOS)
    res = buscar.buscar(request.args.get("q", ""))
    return jsonify(resultados=res, sinConexion=(not res and bool(buscar.hubo_fallos_desde(n))))


@app.get("/api/vivo")
def api_vivo():
    """Precio actual de la cripto del producto en vivo; lo pide el panel a nuestro
    propio servidor (antes el navegador llamaba a CoinGecko y Binance)."""
    calc = lee_json(ruta_calculado()) or {}
    vivo = calc.get("vivo") or {}
    coin = vivo.get("coin")
    if not coin:
        return jsonify(ok=False, errores=["No hay ningún producto en vivo."]), 404
    with cerrojo:
        p = buscar.probar("coingecko", coin)
    if not p or not p.get("precio"):
        return jsonify(ok=False, errores=["Sin precio en vivo ahora mismo."]), 502
    return jsonify(ok=True, coin=coin, precio=p["precio"], fecha=p.get("fecha"),
                   moneda=p.get("moneda") or "EUR")


GUARDAR = {"productos": almacen.guarda_producto, "movimientos": almacen.guarda_movimiento,
           "valoraciones": almacen.guarda_valoracion}
BORRAR = {"productos": almacen.borra_producto, "movimientos": almacen.borra_movimiento,
          "valoraciones": almacen.borra_valoracion}
AVISO_DEMO = ("Estás viendo la cartera de ejemplo. Pulsa «Empezar con mis datos» "
              "para crear la tuya y poder guardar cambios.")


def cambia(fn):
    """Aplica un cambio a la cartera, la guarda (con copia automática) y recalcula."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    with cerrojo:
        ruta = ruta_cartera()
        cfg = almacen.carga(ruta)
        try:
            item = fn(cfg)
        except almacen.ErrorValidacion as e:
            return jsonify(ok=False, errores=e.errores), 400
        almacen.guarda(ruta, cfg, copias=ruta_copias())
        datos = recalcula(descargar="faltan")
    return jsonify(ok=True, item=item, cartera=cfg, avisos=(datos or {}).get("avisos", []))


@app.post("/api/<coleccion>")
def api_guardar(coleccion):
    if coleccion not in GUARDAR:
        return jsonify(ok=False, errores=["No sé guardar eso."]), 404
    datos = request.get_json(silent=True) or {}

    def fn(cfg):
        if coleccion != "productos":
            return GUARDAR[coleccion](cfg, datos)
        prod, cambio = almacen.guarda_producto(cfg, datos)
        # Antes de guardar un producto con precio online, se comprueba que lo hay.
        if cambio and prod["fuente"] != "manual" and not buscar.probar(prod["fuente"], prod["codigo"]):
            raise almacen.ErrorValidacion([
                f"No encuentro precio para «{prod['codigo']}» en {motor.FUENTES[prod['fuente']]}. "
                "Revisa el código con el buscador o elige «a mano» y anota tú su valor."])
        return prod
    return cambia(fn)


@app.delete("/api/<coleccion>/<ident>")
def api_borrar(coleccion, ident):
    if coleccion not in BORRAR:
        return jsonify(ok=False, errores=["No sé borrar eso."]), 404
    return cambia(lambda cfg: BORRAR[coleccion](cfg, ident))


@app.post("/api/repartir-colores")
def api_repartir_colores():
    calc = lee_json(ruta_calculado()) or {}
    grandes = [p["id"] for p in sorted(calc.get("productos", []) + calc.get("otrosActivos", []),
                                       key=lambda p: -(p.get("valor") or 0))]
    return cambia(lambda cfg: almacen.reparte_colores(cfg, grandes))


@app.post("/api/empezar")
def api_empezar():
    """Sale de la demo: crea tu cartera, vacía o como copia del ejemplo para practicar."""
    if modo() != "demo":
        return jsonify(ok=False, errores=["Ya tienes tu propia cartera."]), 400
    # Alias fino del catálogo: conserva el contrato de T-31 para la UI actual.
    desde = (request.get_json(silent=True) or {}).get("desde")
    nombre = "Mi patrimonio (copia del ejemplo)" if desde == "ejemplo" else "Mi patrimonio"
    with cerrojo:
        info = carteras.crea(DATOS, nombre, desde=desde)
        carteras.activa_set(DATOS, info["id"])
    recalcula(descargar="faltan")
    return jsonify(ok=True)


# ---------------------------------------------------------------- catálogo de carteras

def _cartera_meta(cid):
    """Metadatos de una cartera (sin el documento, que puede ser grande)."""
    return {"id": cid, "nombre": carteras.nombre(DATOS, cid),
            "creada": next((c["creada"] for c in carteras.lista(DATOS) if c["id"] == cid), None)}


@app.get("/api/carteras")
def api_carteras():
    """Lista de carteras (solo metadatos) y cuál está activa."""
    return jsonify(carteras=[{**c, "activa": c["id"] == _cid()} for c in carteras.lista(DATOS)],
                   activa=_cid() if modo() == "propio" else None)


@app.post("/api/carteras")
def api_crear_cartera():
    """Crea una cartera: vacía, copia del ejemplo o copia de otra cartera.
    No la activa (la UI lo pide expresamente), salvo en demo: la primera
    cartera sale de la demo y queda activa."""
    datos = request.get_json(silent=True) or {}
    nombre = str(datos.get("nombre") or "").strip()
    if not nombre:
        return jsonify(ok=False, errores=["Ponle un nombre a la cartera."]), 400
    if len(nombre) > 60:
        return jsonify(ok=False, errores=["El nombre es demasiado largo (máximo 60)."]), 400
    desde = datos.get("desde")
    if desde not in (None, "vacia", "ejemplo") and not carteras.id_valido(desde):
        return jsonify(ok=False, errores=["La cartera de origen no es válida."]), 400
    # Hay que mirar el modo ANTES de crear: crea() ya escribe el índice y deja
    # de haber demo, así que después el modo siempre sería "propio".
    era_demo = modo() == "demo"
    with cerrojo:
        info = carteras.crea(DATOS, nombre, desde=desde)
        if era_demo:
            # La primera cartera sale de la demo y queda activa.
            carteras.activa_set(DATOS, info["id"])
            recalcula(descargar="faltan")
    return jsonify(ok=True, cartera=info,
                   carteras=[{**c, "activa": c["id"] == _cid()} for c in carteras.lista(DATOS)])


@app.post("/api/carteras/<cid>/activar")
def api_activar_cartera(cid):
    """Cambia la cartera activa; si su cálculo derivado está viejo, se limpia."""
    if not carteras.id_valido(cid):
        return jsonify(ok=False, errores=["Identificador de cartera no válido."]), 400
    if not carteras.existe(DATOS, cid):
        return jsonify(ok=False, errores=["Esa cartera no existe."]), 404
    with cerrojo:
        carteras.activa_set(DATOS, cid)
        # Si el cálculo de la cartera nueva es anterior a su documento, se recalcula.
        ruta_cfg = carteras.ruta(DATOS, cid)
        ruta_calc = ruta_calculado(cid)
        if os.path.exists(ruta_calc) and os.path.getmtime(ruta_calc) < os.path.getmtime(ruta_cfg):
            os.remove(ruta_calc)
    return jsonify(ok=True, activa=cid)


@app.post("/api/carteras/<cid>/renombrar")
def api_renombrar_cartera(cid):
    """Cambia el nombre de una cartera (índice y titular del documento)."""
    if not carteras.id_valido(cid):
        return jsonify(ok=False, errores=["Identificador de cartera no válido."]), 400
    if not carteras.existe(DATOS, cid):
        return jsonify(ok=False, errores=["Esa cartera no existe."]), 404
    nombre = str((request.get_json(silent=True) or {}).get("nombre") or "").strip()
    if not nombre:
        return jsonify(ok=False, errores=["Ponle un nombre a la cartera."]), 400
    if len(nombre) > 60:
        return jsonify(ok=False, errores=["El nombre es demasiado largo (máximo 60)."]), 400
    with cerrojo:
        carteras.renombra(DATOS, cid, nombre)
    return jsonify(ok=True, cartera=_cartera_meta(cid))


@app.delete("/api/carteras/<cid>")
def api_borrar_cartera(cid):
    """Borra una cartera: su JSON se mueve a copias/<cid>/borrada_<sello>.json."""
    if not carteras.id_valido(cid):
        return jsonify(ok=False, errores=["Identificador de cartera no válido."]), 400
    if not carteras.existe(DATOS, cid):
        return jsonify(ok=False, errores=["Esa cartera no existe."]), 404
    if len(carteras.lista(DATOS)) <= 1:
        return jsonify(ok=False, errores=["No se puede borrar la última cartera."]), 400
    with cerrojo:
        carteras.borra(DATOS, cid, ruta_copias())
    return jsonify(ok=True, carteras=[{**c, "activa": c["id"] == _cid()} for c in carteras.lista(DATOS)])


# ---------------------------------------------------------------- importar

PLANES = {}   # vista previa pendiente de confirmar: {token: plan}


@app.post("/api/importar/previsualizar")
def api_importar_previsualizar():
    """Lee lo que se quiere importar y devuelve la vista previa, sin guardar nada."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    origen = request.form.get("origen")
    archivos = [(f.filename, f.read()) for f in request.files.getlist("archivos") if f.filename]
    if len(archivos) > MAX_ARCHIVOS:
        return jsonify(ok=False, errores=[f"Demasiados archivos (máximo {MAX_ARCHIVOS})."]), 400
    texto = (request.form.get("texto") or "").strip()
    with cerrojo:
        cfg = almacen.carga(ruta_cartera())
        if origen == "myinvestor":
            if not archivos:
                return jsonify(ok=False, errores=["Elige los archivos CSV que has descargado de MyInvestor."]), 400
            plan = importar.preparar_myinvestor(cfg, archivos, DATOS)
        else:
            if not archivos and not texto:
                return jsonify(ok=False, errores=["Elige un archivo o pega el texto que te ha dado la IA."]), 400
            filas, error = [], None
            for nombre, contenido in archivos or [("pegado.csv", texto)]:
                leidas, error = importar.leer_tabla(nombre, contenido)
                if error:
                    return jsonify(ok=False, errores=[f"{nombre}: {error}" if archivos else error]), 400
                filas += leidas
            plan = importar.preparar_tabla(cfg, filas, DATOS)
        informe = importar.vista_previa(cfg, plan)
    token = secrets.token_hex(8)
    PLANES.clear()   # solo una importación pendiente a la vez
    PLANES[token] = plan
    return jsonify(ok=True, token=token, informe=informe)


@app.post("/api/importar/confirmar")
def api_importar_confirmar():
    plan = PLANES.pop((request.get_json(silent=True) or {}).get("token"), None)
    if plan is None:
        return jsonify(ok=False, errores=["Esa vista previa ya no vale: vuelve a revisar el archivo."]), 400
    informe = {}

    def fn(cfg):
        informe.update(importar.aplicar(cfg, plan))
        return None
    respuesta = cambia(fn)
    if isinstance(respuesta, tuple):
        return respuesta
    datos = respuesta.get_json()
    datos["informe"] = {k: informe[k] for k in ("añadidos", "repetidos", "saldos", "sustituidos")}
    return jsonify(datos)


@app.get("/api/plantilla.xlsx")
def api_plantilla_xlsx():
    return Response(plantilla.excel(), headers={"Content-Disposition": 'attachment; filename="plantilla_patrimonio.xlsx"'},
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/plantilla.csv")
def api_plantilla_csv():
    return Response(plantilla.csv_vacio(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="plantilla_patrimonio.csv"'})


@app.get("/api/prompt")
def api_prompt():
    with open(os.path.join(RAIZ, "app", "prompt_ia.txt"), encoding="utf-8") as f:
        return jsonify(texto=f.read())


# ---------------------------------------------------------------- copias de seguridad

def valida_copia(cfg):
    """Comprueba que un JSON tiene pinta de cartera de esta app."""
    errores = almacen.valida_cartera(cfg)
    if errores:
        raise almacen.ErrorValidacion(errores)
    return cfg


def restaura(cfg):
    """Pone cfg como cartera. Lo que hubiera antes queda en las copias automáticas."""
    with cerrojo:
        almacen.guarda(ruta_cartera(), cfg, copias=ruta_copias())
        for viejo in (ruta_calculado(), ruta_historico()):
            if os.path.exists(viejo):
                os.remove(viejo)
        recalcula(descargar="faltan")


@app.get("/api/copias")
def api_copias():
    lista = []
    if os.path.isdir(ruta_copias()):
        for n in os.listdir(ruta_copias()):
            if not n.endswith(".json"):
                continue
            ruta = os.path.join(ruta_copias(), n)
            cfg = lee_json(ruta, {}) or {}
            lista.append({"archivo": n,
                          "fecha": dt.datetime.fromtimestamp(os.path.getmtime(ruta)).isoformat(timespec="minutes"),
                          "motivo": "Antes de empezar de nuevo" if n.startswith("antes_de_reiniciar")
                          else "Antes de recuperar una copia" if n.startswith("antes_de_recuperar")
                          else "Automática",
                          "productos": len(cfg.get("productos", [])),
                          "movimientos": len(cfg.get("movimientos", []))})
    lista.sort(key=lambda c: c["fecha"], reverse=True)
    return jsonify(copias=lista)


@app.get("/api/copia/descargar")
def api_copia_descargar():
    if modo() != "propio":
        return jsonify(ok=False, errores=["Todavía no tienes una cartera propia que guardar."]), 400
    with open(ruta_cartera(), "rb") as f:
        contenido = f.read()
    nombre = f"copia_patrimonio_{dt.date.today().isoformat()}.json"
    return Response(contenido, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.post("/api/copia/subir")
def api_copia_subir():
    """Importa una copia descargada antes (por ejemplo, al cambiar de ordenador)."""
    f = request.files.get("archivo")
    if not f:
        return jsonify(ok=False, errores=["Elige el archivo de la copia (termina en .json)."]), 400
    try:
        cfg = valida_copia(json.loads(importar.decodifica(f.read())))
    except ValueError:
        return jsonify(ok=False, errores=["Ese archivo no es una copia de seguridad de esta app."]), 400
    except almacen.ErrorValidacion as e:
        return jsonify(ok=False, errores=e.errores), 400
    restaura(cfg)
    return jsonify(ok=True)


@app.post("/api/copia/recuperar")
def api_copia_recuperar():
    nombre = os.path.basename((request.get_json(silent=True) or {}).get("archivo") or "")
    ruta = os.path.join(ruta_copias(), nombre)
    if not nombre.endswith(".json") or not os.path.exists(ruta):
        return jsonify(ok=False, errores=["Esa copia ya no existe."]), 400
    try:
        cfg = valida_copia(lee_json(ruta))
    except almacen.ErrorValidacion as e:
        return jsonify(ok=False, errores=e.errores), 400
    if modo() == "propio":
        # Además de la copia automática, una con nombre propio que no se borra sola.
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(ruta_cartera(), "rb") as a, \
                open(os.path.join(ruta_copias(), f"antes_de_recuperar_{sello}.json"), "wb") as b:
            b.write(a.read())
    restaura(cfg)
    return jsonify(ok=True)


# ---------------------------------------------------------------- web estática y versión

@app.get("/api/exportar-web")
def api_exportar_web():
    datos = lee_json(ruta_calculado())
    if not datos:
        return jsonify(ok=False, errores=["Todavía no hay nada que exportar."]), 400
    ocultar = request.args.get("ocultar") == "1"
    html = exportar.pagina(WEB, datos, ocultar=ocultar, titulo=datos.get("titular") or "Mi patrimonio")
    nombre = "patrimonio_sin_importes.html" if ocultar else "patrimonio.html"
    return Response(html.encode("utf-8"), mimetype="text/html",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


REPO = "https://github.com/danidm98/rumbo"
_VERSION = {}


def version_actual():
    with open(os.path.join(RAIZ, "app", "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


@app.get("/api/version")
def api_version():
    """Compara esta versión con la publicada en GitHub (se consulta como mucho una vez al día)."""
    actual = version_actual()
    if not _VERSION or dt.datetime.now() - _VERSION["cuando"] > dt.timedelta(hours=24):
        try:
            url = REPO.replace("github.com", "raw.githubusercontent.com") + "/main/app/VERSION"
            with urllib.request.urlopen(urllib.request.Request(url, headers=motor.UA), timeout=5) as r:
                _VERSION.update(ultima=r.read().decode().strip(), cuando=dt.datetime.now())
        except Exception:
            _VERSION.update(ultima=None, cuando=dt.datetime.now())
    ultima = _VERSION.get("ultima")
    como_tupla = lambda v: tuple(int(x) for x in re.findall(r"\d+", v or "0"))
    return jsonify(actual=actual, ultima=ultima, repo=REPO,
                   hayNueva=bool(ultima) and como_tupla(ultima) > como_tupla(actual))


@app.post("/api/reiniciar")
def api_reiniciar():
    """Empieza de cero o vuelve a la demo. Lo que había se guarda antes en mis_datos/copias."""
    if modo() != "propio":
        return jsonify(ok=False, errores=["Ahora mismo no tienes ninguna cartera propia."]), 400
    a = (request.get_json(silent=True) or {}).get("a")
    with cerrojo:
        ruta = ruta_cartera()
        copias = ruta_copias()
        os.makedirs(copias, exist_ok=True)
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.replace(ruta, os.path.join(copias, f"antes_de_reiniciar_{sello}.json"))
        for viejo in (ruta_calculado(), ruta_historico()):
            if os.path.exists(viejo):
                os.remove(viejo)
        if a == "vacia":
            almacen.guarda(ruta, json.loads(json.dumps(almacen.CARTERA_VACIA)), copias=copias)
        recalcula(descargar="faltan")
    return jsonify(ok=True)


@app.get("/api/ping")
def api_ping():
    return jsonify(app="patrimonio")


@app.get("/<path:archivo>")
def estaticos(archivo):
    return send_from_directory(WEB, archivo)


# ---------------------------------------------------------------- arranque

def ya_abierta(puerto):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/ping", timeout=1) as r:
            return json.load(r).get("app") == "patrimonio"
    except Exception:
        return False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # Los archivos nuevos (caché, histórico) heredan permisos restrictivos.
    os.umask(0o077)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Si la app ya está abierta (otra ventana), basta con enseñarla.
    if ya_abierta(PUERTO):
        print("La app ya estaba abierta: te la enseño en el navegador.")
        if not os.environ.get("PATRIMONIO_NO_ABRIR"):
            webbrowser.open(f"http://127.0.0.1:{PUERTO}/")
        return

    print("\n  RUMBO  ·  tu patrimonio neto")
    print("  " + "-" * 40)
    if modo() == "demo":
        print("  Modo demostración: estás viendo una cartera de ejemplo.")
    # Siempre se recalcula al arrancar (sin internet es un momento): así, tras
    # actualizar la app a una versión nueva, el panel nunca usa cálculos viejos.
    viejos = precios_viejos()
    if viejos:
        print("  Actualizando precios (tarda unos segundos)...")
    try:
        recalcula(descargar=viejos or "faltan")
    except Exception as e:
        print(f"\n  [!] No he podido actualizar los precios: {e}")
        print("      Abro la app con los últimos datos guardados.")

    srv = None
    for puerto in range(PUERTO, PUERTO + 10):
        try:
            srv = make_server("127.0.0.1", puerto, app, threaded=True)
            break
        except OSError:
            continue
    if srv is None:
        print("  [!] No encuentro ningún puerto libre para abrir la app.")
        return
    url = f"http://127.0.0.1:{srv.server_port}/"
    if not os.environ.get("PATRIMONIO_NO_ABRIR"):   # para pruebas: no abre el navegador
        threading.Timer(0.8, webbrowser.open, [url]).start()
    print(f"\n  App abierta en {url}")
    print("  Deja esta ventana abierta mientras la uses. Para salir, ciérrala.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
