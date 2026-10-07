# -*- coding: utf-8 -*-
"""Pruebas de app/carteras.py: catálogo, ids, ciclo de vida y migración (ADR-3)."""

import json
import os

import pytest

from tests.conftest import escribe_json
from app import carteras
from app.almacen import CARTERA_VACIA


CARTERA_LEGADA = {
    "version": 1, "titular": "Mi cartera heredada",
    "productos": [{"id": "accion", "nombre": "Acción Prueba", "corto": "Acción",
                   "tipo": "accion", "fuente": "yahoo", "codigo": "AAA",
                   "moneda": "EUR", "slot": 1, "largoPlazo": True}],
    "movimientos": [{"id": "m1", "fecha": "2024-01-02", "producto": "accion",
                     "tipo": "compra", "unidades": 10, "importe": 1000.0}],
    "valoraciones": [],
    "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True}],
    "hitos": [10000], "objetivo": {"activo": True, "importe": 100000, "etiqueta": "Meta"},
}


def _lee(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- migración

def test_migracion_directorio_vacio_no_crea_nada(tmp_path):
    assert carteras.migra_si_hace_falta(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_migracion_con_cartera_legada(tmp_path):
    ruta = os.path.join(str(tmp_path), "cartera.json")
    escribe_json(ruta, CARTERA_LEGADA)

    aviso = carteras.migra_si_hace_falta(tmp_path)
    assert isinstance(aviso, str)

    # El documento nuevo tiene contenido idéntico y el histórico quedó en copias/
    nuevo = _lee(os.path.join(str(tmp_path), "carteras", "principal.json"))
    assert nuevo == CARTERA_LEGADA
    assert not os.path.exists(ruta)
    copias = list(os.listdir(os.path.join(str(tmp_path), "copias")))
    assert len(copias) == 1 and copias[0].startswith("migrada_")
    assert copias[0].endswith("_cartera.json")
    assert _lee(os.path.join(str(tmp_path), "copias", copias[0])) == CARTERA_LEGADA

    # El índice apunta a `principal` y la activa resuelve bien
    indice = _lee(os.path.join(str(tmp_path), "carteras", "indice.json"))
    assert indice["version"] == 1 and indice["activa"] == "principal"
    assert indice["carteras"] == [{"id": "principal",
                                   "nombre": "Mi cartera heredada",
                                   "creada": indice["carteras"][0]["creada"]}]
    assert isinstance(indice["carteras"][0]["creada"], str)
    assert carteras.activa(tmp_path) == "principal"
    assert carteras.nombre(tmp_path, "principal") == "Mi cartera heredada"

    # Segunda llamada: no-op (mismo mtime del índice y el de principal)
    antes_idx = os.stat(os.path.join(str(tmp_path), "carteras", "indice.json")).st_mtime_ns
    antes_principal = os.stat(os.path.join(str(tmp_path), "carteras", "principal.json")).st_mtime_ns
    assert carteras.migra_si_hace_falta(tmp_path) is None
    assert os.stat(os.path.join(str(tmp_path), "carteras", "indice.json")).st_mtime_ns == antes_idx
    assert os.stat(os.path.join(str(tmp_path), "carteras", "principal.json")).st_mtime_ns == antes_principal
    assert _lee(os.path.join(str(tmp_path), "carteras", "principal.json")) == nuevo


# ---------------------------------------------------------------- ids

def test_id_valido():
    assert carteras.id_valido("principal")
    assert carteras.id_valido("a_b_2")
    assert not carteras.id_valido("../../etc/passwd")
    assert not carteras.id_valido("Mayusculas")
    assert not carteras.id_valido("con punto")
    assert not carteras.id_valido("")
    assert not carteras.id_valido("x" * 31)
    assert not carteras.id_valido(None)
    assert not carteras.id_valido("/abs")


def test_existe_valida_el_id(tmp_path):
    assert carteras.existe(tmp_path, "../../etc/passwd") is False


# ---------------------------------------------------------------- ciclo de vida

def test_ciclo_de_vida(tmp_path):
    copias = os.path.join(str(tmp_path), "copias")
    e1 = carteras.crea(tmp_path, "Mi cartera", desde=None)
    assert set(e1) == {"id", "nombre", "creada"}
    doc1 = _lee(os.path.join(str(tmp_path), "carteras", f"{e1['id']}.json"))
    assert doc1["vacia"] == CARTERA_VACIA     # desde=None -> {"vacia": CARTERA_VACIA}
    assert doc1["titular"] == "Mi cartera"
    assert carteras.activa(tmp_path) == e1["id"]            # la primera es la activa

    e2 = carteras.crea(tmp_path, "Cartera cripto", desde=e1["id"])
    doc2 = _lee(os.path.join(str(tmp_path), "carteras", f"{e2['id']}.json"))
    assert doc2["vacia"]["hitos"] == CARTERA_VACIA["hitos"]  # copia profunda
    assert doc2["titular"] == "Cartera cripto"
    doc2["vacia"]["hitos"].append(999999)                   # no toca la original
    doc1b = _lee(os.path.join(str(tmp_path), "carteras", f"{e1['id']}.json"))
    assert doc1b["vacia"]["hitos"] == CARTERA_VACIA["hitos"]

    # lista respeta el orden del índice
    assert carteras.lista(tmp_path) == [{"id": e1["id"], "nombre": "Mi cartera",
                                         "creada": e1["creada"]},
                                        {"id": e2["id"], "nombre": "Cartera cripto",
                                         "creada": e2["creada"]}]

    # activa_set valida
    carteras.activa_set(tmp_path, e2["id"])
    assert carteras.activa(tmp_path) == e2["id"]
    with pytest.raises(carteras.ErrorCartera):
        carteras.activa_set(tmp_path, "../../etc/passwd")
    with pytest.raises(carteras.ErrorCartera):
        carteras.activa_set(tmp_path, "noexiste")

    # renombra actualiza índice y titular
    carteras.renombra(tmp_path, e2["id"], "Cripto y metales")
    assert carteras.nombre(tmp_path, e2["id"]) == "Cripto y metales"
    doc3 = _lee(os.path.join(str(tmp_path), "carteras", f"{e2['id']}.json"))
    assert doc3["titular"] == "Cripto y metales"

    # borrar la activa: la activa pasa a la primera
    carteras.borra(tmp_path, e2["id"], copias)
    assert carteras.activa(tmp_path) == e1["id"]
    assert carteras.lista(tmp_path) == [{"id": e1["id"], "nombre": "Mi cartera",
                                         "creada": e1["creada"]}]
    borrar = os.listdir(os.path.join(copias, e2["id"]))
    assert len(borrar) == 1 and borrar[0].startswith("borrada_")
    assert not os.path.exists(os.path.join(str(tmp_path), "carteras", f"{e2['id']}.json"))

    # no se puede borrar la última
    with pytest.raises(carteras.ErrorCartera) as e:
        carteras.borra(tmp_path, e1["id"], copias)
    assert "última" in " ".join(e.value.errores)
    assert carteras.existe(tmp_path, e1["id"])


def test_crea_no_produce_duplicados(tmp_path):
    ids = [carteras.crea(tmp_path, "Crypto") for _ in range(4)]
    assert len({x["id"] for x in ids}) == 4
    assert all(carteras.existe(tmp_path, x["id"]) for x in ids)
    # el índice no repite
    assert len({c["id"] for c in carteras.lista(tmp_path)}) == 4


def test_nuevo_id_siempres_valido(tmp_path):
    # nombre cuyo slug empieza por "cartera": el id cae en cartera, cartera_2…
    e1 = carteras.crea(tmp_path, "Cartera una")
    e2 = carteras.crea(tmp_path, "Cartera dos")
    assert (e1["id"], e2["id"]) == ("cartera", "cartera_2")


def test_ejemplo_pone_el_titular(tmp_path):
    e = carteras.crea(tmp_path, "Mi copia del ejemplo", desde="ejemplo")
    doc = _lee(os.path.join(str(tmp_path), "carteras", f"{e['id']}.json"))
    assert doc["titular"] == "Mi copia del ejemplo"
    assert doc["productos"]                    # el demo trae productos
    demo = _lee(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "demo", "cartera.json"))
    assert doc["productos"][0]["id"] == demo["productos"][0]["id"]


def test_errores_tienen_lista_de_mensajes(tmp_path):
    with pytest.raises(carteras.ErrorCartera) as e:
        carteras.activa_set(tmp_path, "noexiste")
    assert isinstance(e.value.errores, list) and e.value.errores


def test_modulo_sin_flask():
    import app.carteras as m
    codigo = (m.__file__ or "").lower()
    assert os.path.exists(m.__file__) or codigo
    src = open(m.__file__, "r", encoding="utf-8").read()
    assert "flask" not in src.lower() and "import servidor" not in src and "servidor" not in vars(m)
