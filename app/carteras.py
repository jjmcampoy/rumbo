# -*- coding: utf-8 -*-
"""
carteras.py  ·  El catálogo de carteras
=======================================
Dueño del layout multi-cartera (ADR-1/ADR-3): la carpeta mis_datos/carteras,
el índice y las operaciones de crear, renombrar, borrar y migrar. No toca
HTTP ni Flask: servidor.py solo le pide rutas y listas.
"""

import copy
import datetime as dt
import json
import os
import re

from .almacen import CARTERA_VACIA, borra_producto, guarda, slug

CARPETA = "carteras"
INDICE = "indice.json"
ID_DEFECTO = "principal"

_ID_RE = re.compile(r"^[a-z0-9_]{1,30}$")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(RAIZ, "demo", "cartera.json")


class ErrorCartera(Exception):
    """Error de catálogo de carteras, con lista de mensajes en .errores."""
    def __init__(self, errores):
        super().__init__("; ".join(errores))
        self.errores = errores


# ---------------------------------------------------------------- rutas

def ruta_carpeta(datos):
    return os.path.join(datos, CARPETA)


def ruta_indice(datos):
    return os.path.join(ruta_carpeta(datos), INDICE)


def ruta(datos, cid):
    if not id_valido(cid):
        raise ErrorCartera(["Identificador de cartera no válido."])
    return os.path.join(ruta_carpeta(datos), f"{cid}.json")


def existe(datos, cid):
    if not id_valido(cid):
        return False
    return os.path.isfile(ruta(datos, cid))


def id_valido(cid):
    """Solo minúsculas, números y guion bajo, de 1 a 30 caracteres."""
    return bool(_ID_RE.fullmatch(str(cid or "")))


# ---------------------------------------------------------------- índice

def lee_indice(datos):
    """El índice de carteras; si no existe, uno vacío."""
    try:
        with open(ruta_indice(datos), "r", encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return {"version": 1, "activa": None, "carteras": []}
    if not isinstance(idx, dict):
        return {"version": 1, "activa": None, "carteras": []}
    idx.setdefault("version", 1)
    idx.setdefault("activa", None)
    idx.setdefault("carteras", [])
    return idx


def escribe_indice(datos, indice):
    """Escritura atómica (temporal + os.replace) del índice."""
    ruta = ruta_indice(datos)
    # mode explícito: carteras/ se crea al importar, antes del umask de main().
    os.makedirs(os.path.dirname(ruta), mode=0o700, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)
    os.chmod(ruta, 0o600)


def _lee_json(ruta, defecto=None):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def _escribe_json(ruta, datos):
    """Escribe en un archivo temporal y lo renombra: si se corta, no se pierde nada."""
    # mode explícito: carteras/ se crea al importar, antes del umask de main().
    os.makedirs(os.path.dirname(ruta), mode=0o700, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)
    os.chmod(ruta, 0o600)


# ---------------------------------------------------------------- consultas

def lista(datos):
    """[{"id","nombre","creada"}] en el orden del índice."""
    idx = lee_indice(datos)
    return [{"id": c.get("id"), "nombre": c.get("nombre"), "creada": c.get("creada")}
            for c in idx["carteras"] if isinstance(c, dict) and c.get("id")]


def activa(datos):
    """El id activo si es válido; si no, el primero; None si no hay carteras."""
    idx = lee_indice(datos)
    ids = [c.get("id") for c in idx["carteras"] if isinstance(c, dict) and c.get("id")]
    a = idx.get("activa")
    if a in ids:
        return a
    return ids[0] if ids else None


def nombre(datos, cid):
    """El nombre de la cartera con ese id."""
    if not id_valido(cid):
        raise ErrorCartera(["Identificador de cartera no válido."])
    for c in lee_indice(datos)["carteras"]:
        if isinstance(c, dict) and c.get("id") == cid:
            return c.get("nombre")
    raise ErrorCartera(["Esa cartera no existe."])


# ---------------------------------------------------------------- cambios

def crea(datos, nombre, desde=None):
    """Crea una cartera: vacía, copia del ejemplo o copia de otra cartera.
    Devuelve {"id","nombre","creada"}."""
    if not str(nombre or "").strip():
        raise ErrorCartera(["Ponle un nombre a la cartera."])
    nombre = str(nombre).strip()
    idx = lee_indice(datos)
    existentes = {c.get("id") for c in idx["carteras"] if isinstance(c, dict)}
    cid = nuevo_id(datos, nombre)
    if desde is None:
        cfg = copy.deepcopy(CARTERA_VACIA)
    elif desde == "vacia":
        cfg = copy.deepcopy(CARTERA_VACIA)
    elif desde == "ejemplo":
        cfg = copy.deepcopy(_lee_json(DEMO, {}))
        if not cfg:
            raise ErrorCartera(["No encuentro la cartera de ejemplo."])
    else:
        if not id_valido(desde):
            raise ErrorCartera(["La cartera de origen no es válida."])
        if not existe(datos, desde):
            raise ErrorCartera(["La cartera de origen no existe."])
        cfg = copy.deepcopy(_lee_json(ruta(datos, desde), {}))
        if not cfg:
            raise ErrorCartera(["La cartera de origen no se puede leer."])
    cfg["titular"] = nombre
    _escribe_json(ruta(datos, cid), cfg)
    idx["carteras"].append({"id": cid, "nombre": nombre,
                            "creada": dt.datetime.now().replace(microsecond=0).isoformat()})
    if idx.get("activa") is None:
        idx["activa"] = cid
    escribe_indice(datos, idx)
    return {"id": cid, "nombre": nombre, "creada": idx["carteras"][-1]["creada"]}


def activa_set(datos, cid):
    """Marca la cartera como activa y persiste el índice."""
    if not id_valido(cid):
        raise ErrorCartera(["Identificador de cartera no válido."])
    if not existe(datos, cid):
        raise ErrorCartera(["Esa cartera no existe."])
    idx = lee_indice(datos)
    idx["activa"] = cid
    escribe_indice(datos, idx)


def renombra(datos, cid, nombre):
    """Cambia el nombre en el índice y el titular del documento."""
    if not id_valido(cid):
        raise ErrorCartera(["Identificador de cartera no válido."])
    if not str(nombre or "").strip():
        raise ErrorCartera(["Ponle un nombre a la cartera."])
    nombre = str(nombre).strip()
    if not existe(datos, cid):
        raise ErrorCartera(["Esa cartera no existe."])
    idx = lee_indice(datos)
    for c in idx["carteras"]:
        if isinstance(c, dict) and c.get("id") == cid:
            c["nombre"] = nombre
            break
    else:
        raise ErrorCartera(["Esa cartera no existe."])
    cfg = _lee_json(ruta(datos, cid), {})
    if cfg is None:
        raise ErrorCartera(["Esa cartera no se puede leer."])
    cfg["titular"] = nombre
    _escribe_json(ruta(datos, cid), cfg)
    escribe_indice(datos, idx)


def borra(datos, cid, copias_dir):
    """Borra una cartera: su JSON se mueve a copias/<cid>/borrada_<sello>.json."""
    if not id_valido(cid):
        raise ErrorCartera(["Identificador de cartera no válido."])
    if not existe(datos, cid):
        raise ErrorCartera(["Esa cartera no existe."])
    idx = lee_indice(datos)
    restantes = [c for c in idx["carteras"] if isinstance(c, dict) and c.get("id") != cid]
    if not restantes:
        raise ErrorCartera(["No se puede borrar la última cartera."])
    destino = os.path.join(copias_dir, cid)
    os.makedirs(destino, mode=0o700, exist_ok=True)
    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    os.replace(ruta(datos, cid), os.path.join(destino, f"borrada_{sello}.json"))
    idx["carteras"] = restantes
    if idx.get("activa") == cid:
        idx["activa"] = restantes[0]["id"]
    escribe_indice(datos, idx)


def nuevo_id(datos, nombre):
    """Un id único derivado del nombre (reutiliza almacen.slug)."""
    existentes = {c.get("id") for c in lee_indice(datos)["carteras"] if isinstance(c, dict)}
    base = slug(nombre, existentes)
    if base:
        return base
    # El nombre no da base legible: cartera, cartera_2, ...
    i = 1
    while f"cartera_{i}" in existentes:
        i += 1
    return "cartera" if "cartera" not in existentes else f"cartera_{i}"


# ---------------------------------------------------------------- extraer

def extrae(datos, origen_cid, nombre, ids, mover=False):
    """Crea una cartera nueva con los productos `ids` (y sus movimientos y valores).
    Con mover=True los quita también del origen. Devuelve (nueva, origen_actualizado)."""
    if not id_valido(origen_cid):
        raise ErrorCartera(["La cartera de origen no es válida."])
    if not existe(datos, origen_cid):
        raise ErrorCartera(["La cartera de origen no existe."])
    if not str(nombre or "").strip():
        raise ErrorCartera(["Ponle un nombre a la cartera."])
    nombre = str(nombre).strip()
    if not isinstance(ids, list) or not ids:
        raise ErrorCartera(["Elige al menos un producto para extraer."])
    origen = _lee_json(ruta(datos, origen_cid), {})
    if not origen:
        raise ErrorCartera(["La cartera de origen no se puede leer."])
    existentes = {p.get("id") for p in origen.get("productos", []) if isinstance(p, dict)}
    desconocidos = [i for i in ids if i not in existentes]
    if desconocidos:
        raise ErrorCartera([f"Producto desconocido: «{d}»." for d in desconocidos])
    nueva = copy.deepcopy(CARTERA_VACIA)
    nueva["titular"] = nombre
    nueva["productos"] = [copy.deepcopy(p) for p in origen["productos"] if p["id"] in ids]
    nueva["movimientos"] = [copy.deepcopy(m) for m in origen.get("movimientos", [])
                           if m.get("producto") in ids]
    nueva["valoraciones"] = [copy.deepcopy(v) for v in origen.get("valoraciones", [])
                            if v.get("producto") in ids]
    nueva["hitos"] = copy.deepcopy(origen.get("hitos", []))
    nueva["objetivo"] = copy.deepcopy(origen.get("objetivo", {}))
    # El comparador conserva la entrada real y los pesos de los productos elegidos;
    # se descartan las entradas de pesos que quedan vacías (como en borra_producto).
    nueva["comparador"] = []
    for c in origen.get("comparador", []):
        if c.get("real"):
            nueva["comparador"].append(copy.deepcopy(c))
        elif c.get("pesos"):
            pesos = {k: v for k, v in c["pesos"].items() if k in ids}
            if pesos:
                nueva["comparador"].append({**copy.deepcopy(c), "pesos": pesos})
    # Primero se persiste la cartera nueva; solo después se toca el origen.
    cid = nuevo_id(datos, nombre)
    guarda(ruta(datos, cid), nueva, copias=os.path.join(datos, "copias", cid))
    if mover:
        for pid in ids:
            borra_producto(origen, pid)
        guarda(ruta(datos, origen_cid), origen,
               copias=os.path.join(datos, "copias", origen_cid))
    idx = lee_indice(datos)
    idx["carteras"].append({"id": cid, "nombre": nombre,
                            "creada": dt.datetime.now().replace(microsecond=0).isoformat()})
    if idx.get("activa") is None:
        idx["activa"] = cid
    escribe_indice(datos, idx)
    return {"id": cid, "nombre": nombre, "productos": len(nueva["productos"])}, origen


# ---------------------------------------------------------------- migración

def migra_si_hace_falta(datos):
    """Migración ADR-3, idempotente. Devuelve None o un aviso de texto."""
    indice = ruta_indice(datos)
    legacy = os.path.join(datos, "cartera.json")
    if os.path.exists(indice):
        return None
    if not os.path.exists(legacy):
        return None
    idx = {"version": 1, "activa": ID_DEFECTO,
           "carteras": [{"id": ID_DEFECTO, "nombre": "Mi patrimonio",
                         "creada": dt.datetime.now().replace(microsecond=0).isoformat()}]}
    _escribe_json(ruta(datos, ID_DEFECTO), _lee_json(legacy, {}))
    escribe_indice(datos, idx)
    copias = os.path.join(datos, "copias")
    os.makedirs(copias, mode=0o700, exist_ok=True)
    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    os.replace(legacy, os.path.join(copias, f"cartera_migrada_{sello}.json"))
    return "He movido tu cartera a la nueva estructura (mis_datos/carteras)."
