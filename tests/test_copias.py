# -*- coding: utf-8 -*-
"""Pruebas de validación de copias de seguridad (app/almacen.valida_cartera)."""

import copy
import io
import json
import os
import stat

from app import almacen
from tests.conftest import CARTERA_MINIMA, cartera_en_disco, _jsons_de_datos


def _copia():
    return copy.deepcopy(CARTERA_MINIMA)


def test_copia_valida_no_da_errores():
    assert almacen.valida_cartera(_copia()) == []


def test_falta_la_lista_de_movimientos():
    cfg = _copia()
    del cfg["movimientos"]
    errores = almacen.valida_cartera(cfg)
    assert any("movimientos" in e for e in errores)


def test_producto_sin_identificador():
    cfg = _copia()
    del cfg["productos"][0]["id"]
    assert almacen.valida_cartera(cfg)


def test_movimiento_con_producto_desconocido():
    cfg = _copia()
    cfg["movimientos"][0]["producto"] = "inexistente"
    assert almacen.valida_cartera(cfg)


def test_movimiento_con_fecha_invalida():
    cfg = _copia()
    cfg["movimientos"][0]["fecha"] = "02/01/2024"
    assert almacen.valida_cartera(cfg)


def test_movimiento_con_importe_no_numerico():
    cfg = _copia()
    cfg["movimientos"][0]["importe"] = "mil"
    assert almacen.valida_cartera(cfg)


def test_nombre_con_html_se_guarda_sin_error():
    # El guardado no «sanea» nombres: escapar es cosa del pintado (T-13).
    cfg = _copia()
    cfg["productos"][0]["nombre"] = "<img src=x onerror=alert(1)>"
    assert almacen.valida_cartera(cfg) == []


def test_subir_copia_valida_sustituye_la_cartera(cliente, entorno):
    servidor, tmp_path = entorno
    cartera_en_disco(tmp_path)
    cuerpo = json.dumps(CARTERA_MINIMA).encode("utf-8")
    r = cliente.post("/api/copia/subir",
                     data={"archivo": (io.BytesIO(cuerpo), "copia.json")},
                     content_type="multipart/form-data", headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    cfg = json.load(open(servidor.DATOS + "/cartera.json", encoding="utf-8"))
    assert cfg["titular"] == "Prueba"


def test_subir_copia_mala_no_toca_la_cartera(cliente, entorno):
    servidor, tmp_path = entorno
    cartera_en_disco(tmp_path)
    antes = json.load(open(servidor.DATOS + "/cartera.json", encoding="utf-8"))
    cuerpo = json.dumps({"productos": [], "movimientos": "no"}).encode("utf-8")
    r = cliente.post("/api/copia/subir",
                     data={"archivo": (io.BytesIO(cuerpo), "copia.json")},
                     content_type="multipart/form-data", headers={"X-Rumbo": "1"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    ahora = json.load(open(servidor.DATOS + "/cartera.json", encoding="utf-8"))
    assert ahora == antes


def test_permisos(cliente, entorno):
    servidor, datos = entorno
    r = cliente.post("/api/empezar", json={}, headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    archivos = list(_jsons_de_datos(datos))          # ayuda definida en conftest.py
    assert archivos, "no se ha escrito ningún JSON"
    for p in archivos:
        assert stat.S_IMODE(os.stat(p).st_mode) & 0o077 == 0, p
