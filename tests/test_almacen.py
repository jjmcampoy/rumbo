# -*- coding: utf-8 -*-
"""Pruebas de validación de app/almacen.py: productos, movimientos y valoraciones."""

import pytest

from app import almacen

PRODUCTO = {"nombre": "Fondo prueba", "corto": "Fondo", "tipo": "fondo",
            "fuente": "manual", "moneda": "EUR"}


def _cfg():
    return {"productos": [], "movimientos": [], "valoraciones": []}


def _con_producto(datos=None):
    cfg = _cfg()
    almacen.guarda_producto(cfg, dict(datos or PRODUCTO))
    return cfg, cfg["productos"][0]["id"]


def _rechaza_producto(datos):
    with pytest.raises(almacen.ErrorValidacion) as exc:
        almacen.guarda_producto(_cfg(), datos)
    return exc.value.errores


@pytest.mark.parametrize("datos", [
    {"tipo": "fondo", "fuente": "manual"},                                     # sin nombre
    {"nombre": "X", "tipo": "inventado", "fuente": "manual"},                  # tipo raro
    {"nombre": "X", "tipo": "accion", "fuente": "yahoo"},                      # sin código
    {"nombre": "X", "tipo": "fondo", "fuente": "manual", "moneda": "EURO"},    # moneda mala
    {"nombre": "X", "tipo": "fondo", "fuente": "manual", "riesgo": 9},         # riesgo > 7
    {"nombre": "X", "tipo": "fondo", "fuente": "manual", "ter": -1},           # ter negativo
])
def test_guarda_producto_rechaza_datos_invalidos(datos):
    assert _rechaza_producto(datos)


def test_guarda_producto_acepta_nombre_html_tal_cual():
    # Hoy el nombre se guarda literal: T-13 arregla el pintado, no el guardado.
    prod, _ = almacen.guarda_producto(
        _cfg(), dict(PRODUCTO, nombre="<img src=x onerror=alert(1)>"))
    assert prod["nombre"] == "<img src=x onerror=alert(1)>"


def test_movimiento_importe_tiene_que_ser_positivo():
    cfg, pid = _con_producto()
    with pytest.raises(almacen.ErrorValidacion) as exc:
        almacen.guarda_movimiento(cfg, {"producto": pid, "tipo": "compra",
                                        "fecha": "2024-01-02", "importe": 0, "unidades": 1})
    assert exc.value.errores


def test_movimiento_comision_menor_que_el_importe():
    cfg, pid = _con_producto()
    with pytest.raises(almacen.ErrorValidacion) as exc:
        almacen.guarda_movimiento(cfg, {"producto": pid, "tipo": "compra",
                                        "fecha": "2024-01-02", "importe": 100,
                                        "unidades": 1, "comision": 100})
    assert exc.value.errores


def test_no_se_puede_vender_mas_unidades_de_las_que_tienes():
    cfg, pid = _con_producto(dict(PRODUCTO, fuente="yahoo", codigo="AAA"))
    almacen.guarda_movimiento(cfg, {"producto": pid, "tipo": "compra",
                                    "fecha": "2024-01-02", "importe": 1000, "unidades": 10})
    with pytest.raises(almacen.ErrorValidacion) as exc:
        almacen.guarda_movimiento(cfg, {"producto": pid, "tipo": "venta",
                                        "fecha": "2024-01-03", "importe": 1100, "unidades": 11})
    assert exc.value.errores


def test_borra_producto_arrastra_movimientos_valores_y_pesos():
    cfg, pid = _con_producto(dict(PRODUCTO, fuente="yahoo", codigo="AAA"))
    almacen.guarda_movimiento(cfg, {"producto": pid, "tipo": "compra",
                                    "fecha": "2024-01-02", "importe": 1000, "unidades": 10})
    almacen.guarda_valoracion(cfg, {"producto": pid, "fecha": "2024-01-02", "valor": 1000})
    cfg["comparador"] = [{"id": "real", "real": True, "pesos": {pid: 1.0, "otro": 1.0}},
                         {"id": "solo-pesos", "pesos": {pid: 1.0}}]

    almacen.borra_producto(cfg, pid)

    assert cfg["productos"] == []
    assert cfg["movimientos"] == []
    assert cfg["valoraciones"] == []
    assert pid not in cfg["comparador"][0]["pesos"]
    assert [c["id"] for c in cfg["comparador"]] == ["real"]


def test_guarda_valoracion_sustituye_mismo_producto_y_fecha():
    cfg, pid = _con_producto()
    almacen.guarda_valoracion(cfg, {"producto": pid, "fecha": "2024-01-02", "valor": 1000})
    almacen.guarda_valoracion(cfg, {"producto": pid, "fecha": "2024-01-02", "valor": 1200})
    assert len(cfg["valoraciones"]) == 1
    assert cfg["valoraciones"][0]["valor"] == 1200


def test_guarda_producto_admite_grupo_opcional():
    # El grupo es una etiqueta libre para comparar trozos de una misma cartera.
    prod, _ = almacen.guarda_producto(_cfg(), dict(PRODUCTO, grupo="Familia"))
    assert prod["grupo"] == "Familia"


def test_producto_sin_grupo_no_guarda_el_campo():
    prod, _ = almacen.guarda_producto(_cfg(), PRODUCTO)
    assert "grupo" not in prod


def test_grupo_vacio_quita_el_campo():
    cfg, pid = _con_producto(dict(PRODUCTO, grupo="Familia"))
    prod, _ = almacen.guarda_producto(cfg, {**PRODUCTO, "id": pid, "grupo": ""})
    assert "grupo" not in prod
    assert "grupo" not in cfg["productos"][0]


def test_grupo_se_recorta_a_cuarenta_caracteres():
    prod, _ = almacen.guarda_producto(_cfg(), dict(PRODUCTO, grupo="x" * 60))
    assert prod["grupo"] == "x" * 40
