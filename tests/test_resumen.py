# -*- coding: utf-8 -*-
"""Pruebas de GET /api/carteras/resumen (T-40): cifras por cartera y total."""
import json
import os
import re

from app import motor
from tests.conftest import escribe_cache, cartera_en_disco_v2, CARTERA_MINIMA


def _cartera(cid, nombre, codigo):
    """Copia de CARTERA_MINIMA con un producto y un movimiento propios."""
    doc = json.loads(json.dumps(CARTERA_MINIMA))
    doc["titular"] = nombre
    doc["productos"] = [{"id": "p_" + cid, "nombre": nombre, "corto": nombre,
                         "tipo": "accion", "fuente": "yahoo", "codigo": codigo,
                         "moneda": "EUR", "slot": 1, "largoPlazo": True}]
    doc["movimientos"] = [{"id": "m_" + cid, "fecha": "2024-01-02",
                           "producto": "p_" + cid, "tipo": "compra",
                           "unidades": 10, "importe": 1000.0}]
    return doc


def _calc(cid, patrimonio, aportado, plusvalia, rentabilidad, tir,
          fecha="2024-06-30", nprod=1):
    """Cálculo guardado mínimo para una cartera."""
    return {
        "generado": "2024-06-30T12:00:00",
        "fechaExtracto": fecha,
        "productos": [{"id": "p_" + cid, "valor": patrimonio, "aportado": aportado,
                       "plusvalia": plusvalia, "rentabilidad": rentabilidad,
                       "tir": tir,
                       "flujos": [["2024-01-02", -aportado]]}],
        "total": {"patrimonio": patrimonio, "aportado": aportado,
                  "plusvalia": plusvalia, "rentabilidad": rentabilidad, "tir": tir},
    }


def _prepara(entorno, cids):
    """Carteras en disco (índice con todas) + caché de precios para cada código."""
    servidor, datos = entorno
    for cid, nombre, codigo in cids:
        cartera_en_disco_v2(datos, _cartera(cid, nombre, codigo), cid=cid)
        escribe_cache(datos, codigo, {"2024-01-02": 100.0, "2024-06-30": 110.0,
                                      "2026-10-06": 110.0})
    # cartera_en_disco_v2 sobreescribe el índice: se reescribe con todas las carteras.
    from tests.conftest import escribe_json
    idx = {"version": 1, "activa": cids[0][0],
           "carteras": [{"id": cid, "nombre": nombre,
                         "creada": "2024-01-01T00:00:00"} for cid, nombre, _ in cids]}
    escribe_json(os.path.join(str(datos), "carteras", "indice.json"), idx)
    return servidor


def _descarga_de_la_cache(monkeypatch, datos_dir):
    """Descarga simulada que lee la caché ya sembrada, sin salir a la red.

    El fixture autouse `sin_red` deja `motor.descargar_serie` devolviendo {}, y con eso
    el motor no lee la caché: no encuentra precio y `construir` devuelve None. Este
    apaño (mismo patrón que tests/test_motor.py y tests/test_multicartera.py) hace que
    la descarga simulada lea justo el JSON que ha sembrado `_prepara`.
    """
    def _lee(simbolo, anos=None):
        ruta = os.path.join(str(datos_dir), "cache",
                            re.sub(r"[^A-Za-z0-9._-]", "_", simbolo) + ".json")
        return motor.lee_cache(ruta)
    monkeypatch.setattr(motor, "descargar_serie", _lee)


def test_resumen_dos_carteras_con_cache(entorno):
    servidor = _prepara(entorno, [("a", "Cartera A", "AAA"), ("b", "Cartera B", "BBB")])
    datos = entorno[1]
    from app import servidor as srv
    srv.escribe_json(os.path.join(str(datos), "calculado", "a.json"),
                     _calc("a", 1100.0, 1000.0, 100.0, 0.1, 0.2))
    srv.escribe_json(os.path.join(str(datos), "calculado", "b.json"),
                     _calc("b", 2200.0, 2000.0, 200.0, 0.1, 0.3))
    r = servidor.app.test_client().get("/api/carteras/resumen")
    assert r.status_code == 200
    j = r.get_json()
    assert len(j["carteras"]) == 2
    a = next(c for c in j["carteras"] if c["id"] == "a")
    b = next(c for c in j["carteras"] if c["id"] == "b")
    for c in (a, b):
        for k in ("id", "nombre", "activa", "patrimonio", "aportado", "plusvalia",
                  "rentabilidad", "tir", "fechaExtracto", "generado", "nProductos"):
            assert k in c
    assert abs(j["total"]["patrimonio"] - (a["patrimonio"] + b["patrimonio"])) < 0.01
    assert abs(j["total"]["aportado"] - (a["aportado"] + b["aportado"])) < 0.01
    assert abs(j["total"]["plusvalia"] - (a["plusvalia"] + b["plusvalia"])) < 0.01
    assert j["total"]["rentabilidad"] is not None
    # Con flujos de signo mixto y una fecha de extracto, la TIR del total debe salir
    # de verdad: si motor.xirr recibe las fechas guardadas como texto devolvería None,
    # y la aserción permisiva («float o None») pasaba sin comprobar nada.
    assert isinstance(j["total"]["tir"], float)


def test_resumen_sin_cache_calcula_sin_red(entorno, monkeypatch):
    _prepara(entorno, [("a", "Cartera A", "AAA")])
    # Sembrar la caché no basta: hay que impedir que `sin_red` la deje inservible.
    _descarga_de_la_cache(monkeypatch, entorno[1])
    r = entorno[0].app.test_client().get("/api/carteras/resumen")
    assert r.status_code == 200
    j = r.get_json()
    a = j["carteras"][0]
    assert "error" not in a
    assert a["patrimonio"] is not None
    assert a["nProductos"] == 1
    # el cálculo queda guardado para la próxima vez
    assert os.path.exists(os.path.join(str(entorno[1]), "calculado", "a.json"))


def test_resumen_cartera_brota_da_error_y_200(entorno):
    _prepara(entorno, [("a", "Cartera A", "AAA"), ("b", "Cartera B", "BBB")])
    datos = entorno[1]
    from app import servidor as srv
    srv.escribe_json(os.path.join(str(datos), "calculado", "a.json"),
                     _calc("a", 1100.0, 1000.0, 100.0, 0.1, 0.2))
    # documento de la cartera b roto: JSON inválido
    with open(os.path.join(str(datos), "carteras", "b.json"), "w", encoding="utf-8") as f:
        f.write("{esto no es json")
    r = entorno[0].app.test_client().get("/api/carteras/resumen")
    assert r.status_code == 200
    j = r.get_json()
    a = next(c for c in j["carteras"] if c["id"] == "a")
    b = next(c for c in j["carteras"] if c["id"] == "b")
    assert "error" in b
    assert "error" not in a
    # el total excluye la cartera rota
    assert abs(j["total"]["patrimonio"] - a["patrimonio"]) < 0.01
    assert j["total"]["tir"] is None or isinstance(j["total"]["tir"], float)


def test_resumen_cartera_sin_precio_sale_con_error_y_200(entorno):
    """Si el motor no puede valorarla (ni precio en la caché ni cálculo guardado),
    `construir` devuelve None sin lanzar: la entrada debe llevar `error`, quedar fuera
    del total y la respuesta seguir siendo 200."""
    servidor, datos = entorno
    cartera_en_disco_v2(datos, _cartera("a", "Cartera A", "AAA"), cid="a")   # sin caché
    r = servidor.app.test_client().get("/api/carteras/resumen")
    assert r.status_code == 200
    j = r.get_json()
    a = j["carteras"][0]
    assert a["id"] == "a"
    assert "error" in a
    assert "patrimonio" not in a
    assert j["total"]["patrimonio"] == 0.0
    assert j["total"]["tir"] is None or isinstance(j["total"]["tir"], float)
