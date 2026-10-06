# -*- coding: utf-8 -*-
"""
Pruebas de la vista previa de la importación (I-06): la reconciliación por fondo
se muestra en el editor y el informe de aplicar() la incluye.
"""
import os

from app import importar
from tests.conftest import escribe_cache

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RAIZ, "app", "web")
HOY = "2025-01-01"  # se fija en el módulo de tests; aquí solo se usa la serie
VL_HOY = 40.0
ISIN = "TEST12345678"
ARCHIVO = "TEST123456789.csv"
# Caso I-A de la tabla de auditoría: coste 10.000, valor 24.000, VL 18,00 el
# 2019-03-01 y 40,00 hoy.
EXTRACTO_IA = ("Fecha fiscal;Inversión;Valor de mercado;Resultado fiscal\n"
               "01/03/2019;10.000,00;24.000,00;\n")


def test_preview_muestra_reconciliacion():
    src = open(os.path.join(WEB, "editor.js"), encoding="utf-8").read()
    for aguja in ("reconciliacion", "valorExtracto", "valorCalculado", "esc("):
        assert aguja in src
    # El desvío es una proporción (k - 1): se muestra en porcentaje, no en euros.
    assert "desvio) * 100" in src
    assert "eur(r.desvio)" not in src


def test_preview_muestra_plusvalias_realizadas():
    """La vista previa avisa de las plusvalías ya realizadas del extracto (I-08)."""
    src = open(os.path.join(WEB, "editor.js"), encoding="utf-8").read()
    # Se lee del informe y solo se pinta cuando hay alguna (n > 0).
    assert "r.plusvaliasRealizadas" in src
    assert "pr.n > 0" in src
    assert "plusvalías ya realizadas del extracto" in src
    assert "no se importan (MyInvestor no da la fecha de venta)" in src


def test_aplicar_devuelve_reconciliacion(entorno, monkeypatch):
    """aplicar() incluye la reconciliación del plan y el caso I-A cuadra a <1 %."""
    _, datos_dir = entorno
    import re
    from app import motor

    def _lee(simbolo, anos=None):
        ruta = os.path.join(str(datos_dir), "cache",
                            re.sub(r"[^A-Za-z0-9._-]", "_", simbolo) + ".json")
        return motor.lee_cache(ruta)
    monkeypatch.setattr(motor, "descargar_serie", _lee)

    cfg = {"productos": [{"id": "fondo", "nombre": "Fondo Test", "corto": "Fondo Test",
                          "tipo": "fondo", "fuente": "yahoo", "codigo": ISIN, "moneda": "EUR"}],
           "movimientos": [], "valoraciones": []}
    escribe_cache(datos_dir, ISIN, {"2019-03-01": 18.0, motor.hoy().isoformat(): VL_HOY})
    plan = importar.preparar_myinvestor(cfg, [(ARCHIVO, EXTRACTO_IA.encode("utf-8"))], str(datos_dir))
    informe = importar.aplicar(cfg, plan)
    assert len(informe["reconciliacion"]) == 1
    r = informe["reconciliacion"][0]
    assert r["isin"] == ISIN
    assert r["valorExtracto"] == 24000.0
    assert r["valorCalculado"] == 24000.0
    assert abs(r["desvio"]) <= 0.01
