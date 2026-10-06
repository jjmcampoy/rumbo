# -*- coding: utf-8 -*-
"""Utilidades comunes de las pruebas: datos aislados y SIN RED."""
import importlib
import json
import os
import re
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

def _falso_get(url, timeout=15):
    raise OSError("pruebas: sin red")

@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    """Ninguna prueba sale a internet; tampoco duerme en los reintentos."""
    from app import buscar, motor

    monkeypatch.setattr(buscar, "_get", _falso_get)
    monkeypatch.setattr(buscar.time, "sleep", lambda *_: None)
    monkeypatch.setattr(motor, "descargar_serie", lambda simbolo, anos=None: {})
    monkeypatch.setattr(motor, "descargar_morningstar",
                        lambda secid, universo="]2]0]FOESP$$ALL", anos=30: {})
    monkeypatch.setattr(motor, "descargar_coingecko", lambda coin, dias=365: {})

@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    """Servidor recargado con PATRIMONIO_DATOS apuntando a una carpeta temporal."""
    monkeypatch.setenv("PATRIMONIO_DATOS", str(tmp_path))
    monkeypatch.setenv("PATRIMONIO_PUERTO", "8799")
    monkeypatch.setenv("PATRIMONIO_NO_ABRIR", "1")
    import app.servidor as servidor
    servidor = importlib.reload(servidor)      # DATOS se lee al importar
    servidor.app.config.update(TESTING=True)
    return servidor, tmp_path

@pytest.fixture()
def cliente(entorno):
    servidor, _ = entorno
    return servidor.app.test_client()

# ---------------------------------------------------------------- ayudas
CARTERA_MINIMA = {
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

def escribe_json(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)

def escribe_cache(datos_dir, simbolo, serie):
    """Serie {fecha_iso: cierre} en la caché, para calcular sin red."""
    escribe_json(os.path.join(datos_dir, "cache",
                              re.sub(r"[^A-Za-z0-9._-]", "_", simbolo) + ".json"), serie)

def cartera_en_disco(datos_dir, datos=None):
    """Escribe la cartera propia y devuelve la ruta (layout de la 1.1.1)."""
    ruta = os.path.join(str(datos_dir), "cartera.json")
    escribe_json(ruta, datos or CARTERA_MINIMA)
    return ruta

def cartera_en_disco_v2(datos_dir, datos=None, cid="principal"):
    """Escribe la cartera en el layout nuevo (carteras/indice.json + carteras/<cid>.json)."""
    datos_dir = str(datos_dir)
    indice = {"version": 1, "activa": cid,
              "carteras": [{"id": cid, "nombre": "Prueba",
                            "creada": "2024-01-01T00:00:00"}]}
    escribe_json(os.path.join(datos_dir, "carteras", "indice.json"), indice)
    ruta = os.path.join(datos_dir, "carteras", cid + ".json")
    escribe_json(ruta, datos or CARTERA_MINIMA)
    return ruta

def _jsons_de_datos(datos_dir):
    """Todos los *.json bajo la carpeta de datos, en cualquier profundidad."""
    for raiz, _dirs, nombres in os.walk(str(datos_dir)):
        for n in nombres:
            if n.endswith(".json"):
                yield os.path.join(raiz, n)
