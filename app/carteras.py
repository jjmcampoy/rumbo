# -*- coding: utf-8 -*-
"""
carteras.py  ·  El catálogo de carteras (layout multicartera, ADR-1/ADR-3)
==========================================================================
Un módulo sin HTTP ni dependencias web: decide dónde viven las carteras y cómo
se crean, renuevan, borran y migran:

    mis_datos/
      carteras/
        indice.json          # {"version":1,"activa":…,"carteras":[{id,nombre,creada}]}
        principal.json       # un documento completo, mismo esquema de cartera.json
        cripto.json
      copias/<id>/borrada_*.json   # donde acaba una cartera borrada

`servidor.py` solo le pide rutas y listas; no decide nada sobre el layout.
"""

import datetime as dt
import json
import os
import re

from . import almacen

CARPETA = "carteras"
INDICE = "indice.json"
ID_DEFECTO = "principal"
_DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "demo", "cartera.json")
_RE_ID = re.compile(r"^[a-z0-9_]{1,30}$")


class ErrorCartera(Exception):
    """Fallo de catálogo (id inválido, cartera inexistente, última cartera…)."""
    def __init__(self, errores):
        super().__init__("; ".join(errores))
        self.errores = errores


# ---------------------------------------------------------------- rutas

def ruta_carteras(datos):
    return os.path.join(str(datos), CARPETA)


def ruta_indice(datos):
    return os.path.join(ruta_carteras(datos), INDICE)


def ruta(datos, cid):
    """Ruta del documento completo de la cartera `cid`."""
    if not id_valido(cid):
        raise ErrorCartera([f"El identificador «{cid}» no es válido."])
    return os.path.join(ruta_carteras(datos), f"{cid}.json")


def existe(datos, cid):
    """True si la cartera `cid` existe (valida el id primero)."""
    if not id_valido(cid):
        return False
    return os.path.exists(ruta(datos, cid))


def id_valido(cid):
    """Id legítimo: sin puntos, barras ni mayúsculas, solo [a-z0-9_] de 1 a 30."""
    return isinstance(cid, str) and bool(_RE_ID.match(cid))


# ---------------------------------------------------------------- índice

def _lee_json(ruta, defecto=None):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def lee_indice(datos):
    """El índice; si no existe (o no se puede leer) devuelve el índice vacío."""
    indice = _lee_json(ruta_indice(datos))
    if not isinstance(indice, dict):
        return {"version": 1, "activa": None, "carteras": []}
    return indice


def escribe_indice(datos, indice):
    """Carpeta, escritura temporal y `os.replace`: no se corrompe a medias."""
    os.makedirs(ruta_carteras(datos), mode=0o700, exist_ok=True)
    tmp = ruta_indice(datos) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta_indice(datos))
    os.chmod(ruta_indice(datos), 0o600)


def _escribe_documento(ruta, doc):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)
    os.chmod(ruta, 0o600)


# ---------------------------------------------------------------- consultas

def lista(datos):
    """La metadata de cada cartera, en el orden que tiene el índice."""
    return list(lee_indice(datos).get("carteras") or [])


def _primera_que_exista(datos):
    """El primer id del índice cuyo documento exista en disco."""
    for c in lista(datos):
        cid = c.get("id") if isinstance(c, dict) else None
        if id_valido(cid) and existe(datos, cid):
            return cid
    return None


def activa(datos):
    """La cartera activa (valida el id antes); si no, la primera; None si no hay."""
    idx = lee_indice(datos)
    cid = idx.get("activa")
    if id_valido(cid) and existe(datos, cid):
        return cid
    return _primera_que_exista(datos)


def activa_set(datos, cid):
    """Guarda `cid` como cartera activa; ErrorCartera si no existe."""
    if not id_valido(cid):
        raise ErrorCartera([f"El identificador «{cid}» no es válido."])
    if not existe(datos, cid):
        raise ErrorCartera([f"La cartera «{cid}» no existe."])
    idx = lee_indice(datos)
    idx["activa"] = cid
    escribe_indice(datos, idx)


def nombre(datos, cid):
    """El nombre de la cartera según el índice; None si no consta."""
    for c in lee_indice(datos).get("carteras") or []:
        if isinstance(c, dict) and c.get("id") == cid:
            return c.get("nombre")
    return None


def _copia_profunda(doc):
    return json.loads(json.dumps(doc))


# ---------------------------------------------------------------- alta y cambio

def crea(datos, nombre, desde=None):
    """Crea una cartera y la añade al índice. `desde`: None|«vacia»|«ejemplo»|<cid>.

    Devuelve {"id", "nombre", "creada"}."""
    nombre = (nombre or "").strip()[:60]
    if not nombre:
        raise ErrorCartera(["Ponle un nombre a la cartera."])
    if desde is None:
        doc = {"vacia": _copia_profunda(almacen.CARTERA_VACIA)}
    elif desde == "ejemplo":
        demo = _lee_json(_DEMO)
        if not isinstance(demo, dict):
            raise ErrorCartera(["El ejemplo no se puede leer."])
        doc = _copia_profunda(demo)
    elif desde == "vacia":
        doc = _copia_profunda(almacen.CARTERA_VACIA)
    else:
        if not id_valido(desde) or not existe(datos, desde):
            raise ErrorCartera([f"La cartera de origen «{desde}» no existe."])
        doc = _lee_json(ruta(datos, desde))
        if not isinstance(doc, dict):
            raise ErrorCartera([f"La cartera «{desde}» no se puede leer."])
        doc = _copia_profunda(doc)
    doc["titular"] = nombre

    idx = lee_indice(datos)
    ids = [c.get("id") for c in idx.get("carteras") or [] if isinstance(c, dict)]
    cid = nuevo_id(datos, nombre)
    while not id_valido(cid) or cid in ids or existe(datos, cid):
        cid = nuevo_id(datos, nombre)
    _escribe_documento(ruta(datos, cid), doc)
    entrada = {"id": cid, "nombre": nombre, "creada": _ahora_iso()}
    idx.setdefault("version", 1)
    idx["carteras"] = list(idx.get("carteras") or [])
    idx["carteras"].append(entrada)
    if not idx.get("activa"):
        idx["activa"] = cid       # la primera cartera creada es la activa
    escribe_indice(datos, idx)
    return entrada


def nuevo_id(datos, nombre):
    """Id único derivado del nombre (almacen.slug); si el slug no da nada,
    cae en `cartera`, `cartera_2`, …"""
    idx = lee_indice(datos)
    existentes = [c.get("id") for c in idx.get("carteras") or []
                  if isinstance(c, dict) and id_valido(c.get("id"))]
    base = almacen.slug(nombre, existentes)
    if not base.startswith("cartera"):          # el slug genérico de la librería
        return base
    cand, i = "cartera", 2
    while cand in existentes or (id_valido(cand) and existe(datos, cand)):
        cand = f"cartera_{i}"
        i += 1
    return cand


def extrae(datos, origen_cid, nombre, ids, mover=False):
    """Crea una cartera nueva con los productos `ids` (y sus movimientos y valores).

    Con `mover=True` los quita también del origen. Primero se persiste la
    cartera nueva (y se añade al índice) y solo después se toca el origen,
    para que un corte nunca deje la selección sin su copia. Devuelve
    (nueva, origen_actualizado).
    """
    if not id_valido(origen_cid) or not existe(datos, origen_cid):
        raise ErrorCartera([f"La cartera de origen «{origen_cid}» no existe."])
    nombre = (nombre or "").strip()[:60]
    if not nombre:
        raise ErrorCartera(["Ponle un nombre a la cartera."])
    if not isinstance(ids, list) or not ids:
        raise ErrorCartera(["Selecciona al menos un producto para extraer."])
    origen = _lee_json(ruta(datos, origen_cid))
    if not isinstance(origen, dict):
        raise ErrorCartera([f"La cartera «{origen_cid}» no se puede leer."])
    pids = {p.get("id") for p in origen.get("productos", []) if isinstance(p, dict)}
    errores = [f"El producto «{i}» no está en la cartera de origen."
               for i in ids if i not in pids]
    if errores:
        raise ErrorCartera(errores)
    seleccion = list(dict.fromkeys(ids))      # sin repetir, en el orden dado
    vivos = set(seleccion)

    nueva = _copia_profunda(almacen.CARTERA_VACIA)
    nueva["titular"] = nombre
    nueva["productos"] = [_copia_profunda(p) for p in origen.get("productos", [])
                          if isinstance(p, dict) and p.get("id") in vivos]
    nueva["movimientos"] = [_copia_profunda(m) for m in origen.get("movimientos", [])
                           if m.get("producto") in vivos]
    nueva["valoraciones"] = [_copia_profunda(v) for v in origen.get("valoraciones", [])
                            if v.get("producto") in vivos]
    nueva["hitos"] = _copia_profunda(origen.get("hitos") or [])
    nueva["objetivo"] = _copia_profunda(origen.get("objetivo") or almacen.CARTERA_VACIA["objetivo"])
    # El comparador se recorta a los productos nuevos: si un peso queda vacío,
    # la entrada se tira, como en almacen.borra_producto.
    comparador = []
    for c in origen.get("comparador", []):
        if not isinstance(c, dict):
            continue
        cc = _copia_profunda(c)
        if cc.get("pesos"):
            cc["pesos"] = {pid: w for pid, w in cc["pesos"].items() if pid in vivos}
        comparador.append(cc)
    nueva["comparador"] = [c for c in comparador if c.get("real") or c.get("pesos")] \
        or _copia_profunda(almacen.CARTERA_VACIA["comparador"])

    idx = lee_indice(datos)
    existentes = [c.get("id") for c in idx.get("carteras") or [] if isinstance(c, dict)]
    cid = nuevo_id(datos, nombre)
    while not id_valido(cid) or cid in existentes or existe(datos, cid):
        cid = nuevo_id(datos, nombre)
    # Primero se persiste la cartera nueva, y solo después se toca el origen.
    almacen.guarda(ruta(datos, cid), nueva, copias=os.path.join(str(datos), "copias", cid))
    idx.setdefault("version", 1)
    idx["carteras"] = list(idx.get("carteras") or [])
    idx["carteras"].append({"id": cid, "nombre": nombre, "creada": _ahora_iso()})
    escribe_indice(datos, idx)
    if mover:
        for pid in seleccion:
            almacen.borra_producto(origen, pid)
        almacen.guarda(ruta(datos, origen_cid), origen,
                       copias=os.path.join(str(datos), "copias", origen_cid))
    return nueva, origen


def renombra(datos, cid, nombre):
    """Cambia el nombre en el índice y el `titular` del documento."""
    if not id_valido(cid) or not existe(datos, cid):
        raise ErrorCartera([f"La cartera «{cid}» no existe."])
    nombre = (nombre or "").strip()[:60]
    if not nombre:
        raise ErrorCartera(["Ponle un nombre a la cartera."])
    idx = lee_indice(datos)
    for c in idx.get("carteras") or []:
        if isinstance(c, dict) and c.get("id") == cid:
            c["nombre"] = nombre
            break
    else:
        raise ErrorCartera([f"La cartera «{cid}» no está en el índice."])
    escribe_indice(datos, idx)
    doc = _lee_json(ruta(datos, cid))
    doc["titular"] = nombre
    _escribe_documento(ruta(datos, cid), doc)


def borra(datos, cid, copias_dir):
    """Pasa la cartera a `copias_dir/<cid>/borrada_<sello>.json` y la quita del índice.

    Se niega a borrar la última cartera; si la que se borra era la activa,
    la activa pasa a ser la primera de las que quedan."""
    if not id_valido(cid):
        raise ErrorCartera([f"El identificador «{cid}» no es válido."])
    doc_ruta = ruta(datos, cid)
    if not os.path.exists(doc_ruta):
        raise ErrorCartera([f"La cartera «{cid}» no existe."])
    idx = lee_indice(datos)
    quedantes = [c.get("id") for c in idx.get("carteras") or []
                 if isinstance(c, dict) and c.get("id") != cid]
    if not quedantes:
        raise ErrorCartera(["No puedes borrar la última cartera."])
    destino_dir = os.path.join(str(copias_dir), cid)
    os.makedirs(destino_dir, mode=0o700, exist_ok=True)
    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    with open(doc_ruta, "rb") as f, open(os.path.join(destino_dir, f"borrada_{sello}.json"), "wb") as g:
        g.write(f.read())
    os.remove(doc_ruta)
    idx["carteras"] = [c for c in idx.get("carteras") or []
                       if not (isinstance(c, dict) and c.get("id") == cid)]
    if idx.get("activa") == cid or not idx.get("activa"):
        for c in idx["carteras"]:                 # la primera de las que quedan
            if isinstance(c, dict) and id_valido(c.get("id")):
                idx["activa"] = c["id"]
                break
    escribe_indice(datos, idx)


# ---------------------------------------------------------------- migración (ADR-3)

def _ahora_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def migra_si_hace_falta(datos):
    """Migra la cartera heredada al layout multicartera (ADR-3).

    Idempotente: si hay índice no hace nada; si no hay índice ni
    `cartera.json` (instalación nueva) tampoco. Tras migrar devuelve un
    aviso en español; en los casos de no-op deviene None.
    """
    if os.path.exists(ruta_indice(datos)):
        return None
    legado = os.path.join(str(datos), "cartera.json")
    if not os.path.exists(legado):
        return None
    doc = _lee_json(legado)
    if not isinstance(doc, dict):
        raise ErrorCartera(["La cartera heredada no se puede leer."])
    copias = os.path.join(str(datos), "copias")
    os.makedirs(copias, mode=0o700, exist_ok=True)
    _escribe_documento(ruta(datos, ID_DEFECTO), doc)
    indice = {"version": 1, "activa": ID_DEFECTO, "carteras": [
        {"id": ID_DEFECTO,
         "nombre": (doc.get("titular") or "Mi cartera").strip()[:60],
         "creada": _ahora_iso()}]}
    escribe_indice(datos, indice)
    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.replace(legado, os.path.join(copias, f"migrada_{sello}_cartera.json"))
    return "He migrado tu cartera al formato multicartera"
