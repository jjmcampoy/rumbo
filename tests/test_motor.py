# -*- coding: utf-8 -*-
"""Pruebas del motor de cálculo: caché sembrada, FIFO y TIR. Todo sin red."""

import datetime as dt
import os
import re

from app import motor
from tests.conftest import CARTERA_MINIMA, escribe_cache


def _serie_laborables(inicio=dt.date(2024, 1, 2), n=40, base=100.0):
    """{fecha_iso: cierre} con n días laborables y precios crecientes."""
    serie, f = {}, inicio
    while len(serie) < n:
        if f.weekday() < 5:
            serie[f.isoformat()] = base + len(serie)
        f += dt.timedelta(days=1)
    return serie


def _descarga_de_la_cache(monkeypatch, carpeta):
    """Descarga simulada: lee la caché sembrada (equivale a descargar=False)."""
    def _lee(simbolo, anos=None):
        ruta = os.path.join(str(carpeta), "cache",
                            re.sub(r"[^A-Za-z0-9._-]", "_", simbolo) + ".json")
        return motor.lee_cache(ruta)
    monkeypatch.setattr(motor, "descargar_serie", _lee)


def test_construir_con_cache_sembrada(tmp_path, monkeypatch):
    serie = _serie_laborables()
    escribe_cache(tmp_path, "AAA", serie)
    _descarga_de_la_cache(monkeypatch, tmp_path)

    datos = motor.construir(CARTERA_MINIMA, str(tmp_path), descargar=False)

    assert datos is not None
    assert datos["fechas"] == sorted(datos["fechas"])
    assert len(datos["fechas"]) == len(datos["total"]["serie"])
    assert datos["productos"][0]["aportado"] == 1000.0
    assert abs(datos["total"]["patrimonio"] - 10 * max(serie.values())) < 0.01


def test_fifo_al_vender_calcula_la_plusvalia_realizada():
    producto = {"id": "accion", "corto": "Acción"}
    movs = [{"fecha": "2024-01-02", "tipo": "compra", "unidades": 10, "importe": 1000.0},
            {"fecha": "2024-02-01", "tipo": "compra", "unidades": 10, "importe": 2000.0},
            {"fecha": "2024-03-01", "tipo": "venta", "unidades": 10, "importe": 2500.0}]

    mv = motor.aplicar_movimientos(producto, movs)

    assert abs(mv["realizado"] - 1500.0) < 1e-9
    assert abs(sum(e[2] for e in mv["eventos"]) - 2000.0) < 1e-9


def test_xirr_de_un_flujo_anual():
    tir = motor.xirr([(dt.date(2024, 1, 1), -1000), (dt.date(2025, 1, 1), 1100)])
    assert tir is not None
    assert abs(tir - 0.10) < 1e-3
    assert motor.xirr([(dt.date(2024, 1, 1), -1000)]) is None


def test_por_grupo_suma_los_productos_de_cada_grupo(tmp_path, monkeypatch):
    serie_a = _serie_laborables(base=100.0)
    serie_b = _serie_laborables(base=200.0)
    escribe_cache(tmp_path, "AAA", serie_a)
    escribe_cache(tmp_path, "BBB", serie_b)
    _descarga_de_la_cache(monkeypatch, tmp_path)

    cfg = {
        "version": 1, "titular": "Prueba",
        "productos": [
            {"id": "accion", "nombre": "Acción", "corto": "A", "tipo": "accion",
             "fuente": "yahoo", "codigo": "AAA", "moneda": "EUR", "slot": 1,
             "largoPlazo": True, "grupo": "Familia"},
            {"id": "accion2", "nombre": "Acción 2", "corto": "B", "tipo": "accion",
             "fuente": "yahoo", "codigo": "BBB", "moneda": "EUR", "slot": 2,
             "largoPlazo": True, "grupo": "Trabajo"},
        ],
        "movimientos": [
            {"id": "m1", "fecha": "2024-01-02", "producto": "accion",
             "tipo": "compra", "unidades": 10, "importe": 1000.0},
            {"id": "m2", "fecha": "2024-01-09", "producto": "accion2",
             "tipo": "compra", "unidades": 10, "importe": 2000.0},
        ],
        "valoraciones": [],
    }

    datos = motor.construir(cfg, str(tmp_path), descargar=False)

    por_grupo = datos["total"]["porGrupo"]
    assert sorted(g["nombre"] for g in por_grupo) == ["Familia", "Trabajo"]
    por = {g["nombre"]: g for g in por_grupo}
    # El valor de cada grupo es el de su producto; juntos, el patrimonio.
    assert por["Familia"]["valor"] == datos["productos"][0]["valor"]
    assert por["Trabajo"]["valor"] == datos["productos"][1]["valor"]
    assert abs(sum(g["valor"] for g in por_grupo) - datos["total"]["patrimonio"]) < 0.01
    # Aportado y TIR por grupo: float o None, con el aportado de cada producto.
    assert por["Familia"]["aportado"] == 1000.0
    assert por["Familia"]["plusvalia"] is not None
    assert por["Familia"]["rentabilidad"] is not None
    assert por["Familia"]["tir"] is None or isinstance(por["Familia"]["tir"], float)
    assert por["Trabajo"]["tir"] is None or isinstance(por["Trabajo"]["tir"], float)
