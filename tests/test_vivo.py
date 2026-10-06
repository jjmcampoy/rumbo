# -*- coding: utf-8 -*-
"""Pruebas de /api/vivo: el precio en vivo lo sirve nuestro propio servidor."""
import json
import os

from app import exportar, buscar

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "web")

DATOS_MINIMOS = {
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


def _escribe_calculado(servidor, datos):
    os.makedirs(os.path.dirname(servidor.ruta_calculado()), exist_ok=True)
    with open(servidor.ruta_calculado(), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def test_vivo_devuelve_el_precio(cliente, monkeypatch):
    import app.servidor as srv
    _escribe_calculado(srv, {"vivo": {"coin": "bitcoin"}})
    monkeypatch.setattr(buscar, "probar",
                        lambda fuente, codigo: {"precio": 50000.0,
                                                "fecha": "2026-01-01", "moneda": "EUR"})
    r = cliente.get("/api/vivo")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert j["precio"] == 50000.0
    assert j["coin"] == "bitcoin"
    assert j["moneda"] == "EUR"


def test_vivo_sin_producto_da_404(cliente):
    import app.servidor as srv
    _escribe_calculado(srv, {"vivo": {}})
    r = cliente.get("/api/vivo")
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_vivo_sin_precio_da_502(cliente, monkeypatch):
    import app.servidor as srv
    _escribe_calculado(srv, {"vivo": {"coin": "bitcoin"}})
    monkeypatch.setattr(buscar, "probar", lambda fuente, codigo: None)
    r = cliente.get("/api/vivo")
    assert r.status_code == 502
    assert r.get_json()["ok"] is False


def test_vivo_cross_site_da_403(cliente):
    import app.servidor as srv
    _escribe_calculado(srv, {"vivo": {"coin": "bitcoin"}})
    r = cliente.get("/api/vivo", headers={"Origin": "https://otro-sitio.example"})
    assert r.status_code == 403


def test_exportacion_borra_el_bloque_vivo():
    html = exportar.pagina(WEB, dict(DATOS_MINIMOS, vivo={"coin": "bitcoin"}))
    assert '"vivo":null' in html
    assert "binance" not in html
