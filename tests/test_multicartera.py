# -*- coding: utf-8 -*-
"""Pruebas de la cartera multi-cartera (T-31): migración, cartera activa y escrituras."""
import copy
import datetime as dt
import json
import os

from app import motor
from tests.conftest import (CARTERA_MINIMA, cartera_en_disco, cartera_en_disco_v2,
                            escribe_cache, escribe_json)

CAB = {"X-Rumbo": "1"}


def _serie_laborables(inicio=dt.date(2024, 1, 2), n=40, base=100.0):
    """{fecha_iso: cierre} con n días laborables y precios crecientes (sin red)."""
    serie, f = {}, inicio
    while len(serie) < n:
        if f.weekday() < 5:
            serie[f.isoformat()] = base + len(serie)
        f += dt.timedelta(days=1)
    return serie


def _cache_sembrada(monkeypatch, datos_dir, simbolos):
    """Siembra la caché de precios y hace que la descarga simulada la lea.

    El fixture autouse `sin_red` devuelve {} en descargar_serie, así que sin este
    apaño el motor no encuentra precio y devuelve None (y /datos.js sirve null).
    """
    serie = _serie_laborables()
    for simbolo in simbolos:
        escribe_cache(datos_dir, simbolo, serie)

    def _lee(simbolo, anos=None):
        ruta = os.path.join(str(datos_dir), "cache",
                            motor.re.sub(r"[^A-Za-z0-9._-]", "_", simbolo) + ".json")
        return motor.lee_cache(ruta)

    monkeypatch.setattr(motor, "descargar_serie", _lee)


def _copia(titular, pid, nombre):
    cfg = copy.deepcopy(CARTERA_MINIMA)
    cfg["titular"] = titular
    cfg["productos"] = [{"id": pid, "nombre": nombre, "corto": nombre,
                         "tipo": "accion", "fuente": "yahoo", "codigo": "AAA",
                         "moneda": "EUR", "slot": 1, "largoPlazo": True}]
    cfg["movimientos"] = [{"id": "m1", "fecha": "2024-01-02", "producto": pid,
                           "tipo": "compra", "unidades": 10, "importe": 1000.0}]
    return cfg


def test_migracion_de_la_cartera_legada(cliente, entorno):
    """Con una cartera.json antigua en disco, al recargar el módulo se migra sola."""
    servidor, tmp_path = entorno
    cartera_en_disco(tmp_path)
    import importlib
    servidor = importlib.reload(servidor)
    cliente = servidor.app.test_client()
    r = cliente.get("/api/cartera")
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["modo"] == "propio"
    assert cuerpo["cartera"]["titular"] == "Prueba"
    assert not os.path.exists(os.path.join(tmp_path, "cartera.json"))
    assert os.path.exists(os.path.join(tmp_path, "carteras", "principal.json"))


def test_cambiar_la_cartera_activa(cliente, entorno, monkeypatch):
    """Activar una cartera cambia lo que devuelven /api/cartera, /datos.js y /api/copias."""
    servidor, tmp_path = entorno
    # Sin precios en la caché el motor no puede valorar las carteras.
    _cache_sembrada(monkeypatch, tmp_path, ["AAA"])
    a = _copia("Cartera A", "accion", "Acción A")
    b = _copia("Cartera B", "bono", "Bono B")
    escribe_json(os.path.join(tmp_path, "carteras", "a.json"), a)
    escribe_json(os.path.join(tmp_path, "carteras", "b.json"), b)
    escribe_json(os.path.join(tmp_path, "carteras", "indice.json"),
                 {"version": 1, "activa": "a",
                  "carteras": [{"id": "a", "nombre": "Cartera A", "creada": "2024-01-01T00:00:00"},
                               {"id": "b", "nombre": "Cartera B", "creada": "2024-01-01T00:00:00"}]})
    # Una copia por cartera, para que /api/copias cambie al activar.
    os.makedirs(os.path.join(tmp_path, "copias", "a"), exist_ok=True)
    os.makedirs(os.path.join(tmp_path, "copias", "b"), exist_ok=True)
    escribe_json(os.path.join(tmp_path, "copias", "a", "auto_20240101_000000_000000.json"), a)
    escribe_json(os.path.join(tmp_path, "copias", "b", "auto_20240102_000000_000000.json"), b)

    r = cliente.get("/api/cartera")
    assert r.get_json()["cartera"]["titular"] == "Cartera A"
    assert "Cartera A" in cliente.get("/datos.js").get_data(as_text=True)
    assert [c["archivo"] for c in cliente.get("/api/copias").get_json()["copias"]] == \
           ["auto_20240101_000000_000000.json"]

    servidor.carteras.activa_set(servidor.DATOS, "b")
    r = cliente.get("/api/cartera")
    assert r.get_json()["cartera"]["titular"] == "Cartera B"
    assert "Cartera B" in cliente.get("/datos.js").get_data(as_text=True)
    assert [c["archivo"] for c in cliente.get("/api/copias").get_json()["copias"]] == \
           ["auto_20240102_000000_000000.json"]


def test_escribir_toca_solo_la_cartera_activa(cliente, entorno):
    """Un POST /api/productos solo modifica el JSON de la cartera activa."""
    servidor, tmp_path = entorno
    a = _copia("Cartera A", "accion", "Acción A")
    b = _copia("Cartera B", "bono", "Bono B")
    escribe_json(os.path.join(tmp_path, "carteras", "a.json"), a)
    escribe_json(os.path.join(tmp_path, "carteras", "b.json"), b)
    escribe_json(os.path.join(tmp_path, "carteras", "indice.json"),
                 {"version": 1, "activa": "a",
                  "carteras": [{"id": "a", "nombre": "Cartera A", "creada": "2024-01-01T00:00:00"},
                               {"id": "b", "nombre": "Cartera B", "creada": "2024-01-01T00:00:00"}]})
    r = cliente.post("/api/productos", json={"nombre": "Nuevo", "tipo": "accion",
                                             "fuente": "manual"}, headers=CAB)
    assert r.status_code == 200
    a2 = json.load(open(os.path.join(tmp_path, "carteras", "a.json"), encoding="utf-8"))
    b2 = json.load(open(os.path.join(tmp_path, "carteras", "b.json"), encoding="utf-8"))
    assert any(p["nombre"] == "Nuevo" for p in a2["productos"])
    assert b2["productos"] == b["productos"]
