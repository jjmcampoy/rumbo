# -*- coding: utf-8 -*-
"""Pruebas del módulo app.carteras (catálogo de carteras, sin Flask)."""
import json
import os

import pytest

from app import carteras
from app.almacen import CARTERA_VACIA


def _escribe(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def _lee(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _cartera_minima():
    return {
        "version": 1, "titular": "Prueba",
        "productos": [{"id": "accion", "nombre": "Acción Prueba", "corto": "Acción",
                       "tipo": "accion", "fuente": "yahoo", "codigo": "AAA",
                       "moneda": "EUR", "slot": 1, "largoPlazo": True}],
        "movimientos": [{"id": "m1", "fecha": "2024-01-02", "producto": "accion",
                         "tipo": "compra", "unidades": 10, "importe": 1000.0}],
        "valoraciones": [],
        "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True}],
        "hitos": [10000], "objetivo": {"activo": True, "importe": 100000, "etiqueta": "Meta"},
    }


# ---------------------------------------------------------------- migración

def test_migra_en_carpeta_vacia(tmp_path):
    assert carteras.migra_si_hace_falta(str(tmp_path)) is None
    assert not os.path.exists(os.path.join(tmp_path, carteras.CARPETA))
    assert not os.path.exists(os.path.join(tmp_path, carteras.INDICE))


def test_migra_cartera_legada(tmp_path):
    legacy = os.path.join(tmp_path, "cartera.json")
    cfg = _cartera_minima()
    _escribe(legacy, cfg)
    aviso = carteras.migra_si_hace_falta(str(tmp_path))
    assert aviso
    nueva = os.path.join(tmp_path, carteras.CARPETA, "principal.json")
    assert _lee(nueva) == cfg
    idx = _lee(os.path.join(tmp_path, carteras.CARPETA, carteras.INDICE))
    assert idx["activa"] == "principal"
    assert idx["carteras"][0]["id"] == "principal"
    assert not os.path.exists(legacy)
    copias = os.listdir(os.path.join(tmp_path, "copias"))
    assert len(copias) == 1 and copias[0].startswith("cartera_migrada_")
    # Segunda llamada: no-op.
    m1 = os.path.getmtime(nueva)
    i1 = os.path.getmtime(os.path.join(tmp_path, carteras.CARPETA, carteras.INDICE))
    assert carteras.migra_si_hace_falta(str(tmp_path)) is None
    assert os.path.getmtime(nueva) == m1
    assert os.path.getmtime(os.path.join(tmp_path, carteras.CARPETA, carteras.INDICE)) == i1
    assert len(os.listdir(os.path.join(tmp_path, "copias"))) == 1


# ---------------------------------------------------------------- id

def test_id_valido():
    assert carteras.id_valido("principal")
    assert carteras.id_valido("a_1")
    assert carteras.id_valido("../../etc/passwd") is False
    assert carteras.id_valido("Mayus") is False
    assert carteras.id_valido("a" * 31) is False
    assert carteras.id_valido("") is False


# ---------------------------------------------------------------- crear y leer

def test_crea_vacia_y_lista(tmp_path):
    r = carteras.crea(str(tmp_path), "Mi cartera", desde=None)
    assert r["id"] == "mi_cartera"
    assert r["nombre"] == "Mi cartera"
    assert r["creada"]
    cfg = _lee(os.path.join(tmp_path, carteras.CARPETA, "mi_cartera.json"))
    assert cfg == {**CARTERA_VACIA, "titular": "Mi cartera"}
    assert carteras.lista(str(tmp_path)) == [r]
    assert carteras.activa(str(tmp_path)) == "mi_cartera"


def test_crea_ejemplo(tmp_path):
    r = carteras.crea(str(tmp_path), "Copia demo", desde="ejemplo")
    cfg = _lee(os.path.join(tmp_path, carteras.CARPETA, f"{r['id']}.json"))
    assert cfg["titular"] == "Copia demo"
    assert cfg["productos"]


def test_crea_desde_otra(tmp_path):
    a = carteras.crea(str(tmp_path), "Primera")
    b = carteras.crea(str(tmp_path), "Segunda", desde=a["id"])
    assert b["id"] == "segunda"
    ca = _lee(os.path.join(tmp_path, carteras.CARPETA, f"{a['id']}.json"))
    cb = _lee(os.path.join(tmp_path, carteras.CARPETA, f"{b['id']}.json"))
    assert {k: v for k, v in cb.items() if k != "titular"} == \
           {k: v for k, v in ca.items() if k != "titular"}
    assert cb["titular"] == "Segunda" and ca["titular"] == "Primera"


def test_crea_sin_duplicados(tmp_path):
    ids = [carteras.crea(str(tmp_path), "Mi cartera")["id"] for _ in range(3)]
    assert len(set(ids)) == 3
    assert ids[0] == "mi_cartera"


def test_crea_desde_inexistente(tmp_path):
    with pytest.raises(carteras.ErrorCartera):
        carteras.crea(str(tmp_path), "X", desde="no_hay")


# ---------------------------------------------------------------- activa

def test_activa_set(tmp_path):
    a = carteras.crea(str(tmp_path), "Una")
    b = carteras.crea(str(tmp_path), "Dos")
    assert carteras.activa(str(tmp_path)) == a["id"]
    carteras.activa_set(str(tmp_path), b["id"])
    assert carteras.activa(str(tmp_path)) == b["id"]
    with pytest.raises(carteras.ErrorCartera):
        carteras.activa_set(str(tmp_path), "no_hay")


# ---------------------------------------------------------------- renombrar

def test_renombra(tmp_path):
    r = carteras.crea(str(tmp_path), "Antiguo")
    carteras.renombra(str(tmp_path), r["id"], "Nuevo")
    assert carteras.nombre(str(tmp_path), r["id"]) == "Nuevo"
    assert carteras.lista(str(tmp_path))[0]["nombre"] == "Nuevo"
    cfg = _lee(os.path.join(tmp_path, carteras.CARPETA, f"{r['id']}.json"))
    assert cfg["titular"] == "Nuevo"


# ---------------------------------------------------------------- borrar

def test_borra(tmp_path):
    a = carteras.crea(str(tmp_path), "Una")
    b = carteras.crea(str(tmp_path), "Dos")
    carteras.borra(str(tmp_path), a["id"], os.path.join(str(tmp_path), "copias"))
    assert carteras.lista(str(tmp_path)) == [b]
    assert carteras.activa(str(tmp_path)) == b["id"]
    sub = os.listdir(os.path.join(str(tmp_path), "copias", a["id"]))
    assert len(sub) == 1 and sub[0].startswith("borrada_")


def test_borra_activa_cambia(tmp_path):
    a = carteras.crea(str(tmp_path), "Una")
    b = carteras.crea(str(tmp_path), "Dos")
    carteras.activa_set(str(tmp_path), a["id"])
    carteras.borra(str(tmp_path), a["id"], os.path.join(str(tmp_path), "copias"))
    assert carteras.activa(str(tmp_path)) == b["id"]


def test_borra_ultima(tmp_path):
    a = carteras.crea(str(tmp_path), "Única")
    with pytest.raises(carteras.ErrorCartera):
        carteras.borra(str(tmp_path), a["id"], os.path.join(str(tmp_path), "copias"))


def test_borra_inexistente(tmp_path):
    carteras.crea(str(tmp_path), "Una")
    with pytest.raises(carteras.ErrorCartera):
        carteras.borra(str(tmp_path), "no_hay", os.path.join(str(tmp_path), "copias"))
