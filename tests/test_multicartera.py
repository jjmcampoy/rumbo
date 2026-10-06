# -*- coding: utf-8 -*-
"""Pruebas de la cartera multi-cartera (T-31): migración, cartera activa y escrituras."""
import copy
import datetime as dt
import io
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


def _dos_carteras(tmp_path):
    """Siembra dos carteras (a activa) y devuelve sus documentos."""
    a = _copia("Cartera A", "accion", "Acción A")
    b = _copia("Cartera B", "bono", "Bono B")
    escribe_json(os.path.join(tmp_path, "carteras", "a.json"), a)
    escribe_json(os.path.join(tmp_path, "carteras", "b.json"), b)
    escribe_json(os.path.join(tmp_path, "carteras", "indice.json"),
                 {"version": 1, "activa": "a",
                  "carteras": [{"id": "a", "nombre": "Cartera A", "creada": "2024-01-01T00:00:00"},
                               {"id": "b", "nombre": "Cartera B", "creada": "2024-01-01T00:00:00"}]})
    return a, b


def test_catalogo_ciclo_de_vida(cliente, entorno):
    """Crear, renombrar y borrar carteras por HTTP; el orden y la activa se conservan."""
    servidor, tmp_path = entorno
    a, b = _dos_carteras(tmp_path)
    # Crear una tercera (no se activa).
    r = cliente.post("/api/carteras", json={"nombre": "Cartera C", "desde": "vacia"}, headers=CAB)
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["ok"] and cuerpo["cartera"]["nombre"] == "Cartera C"
    assert [c["id"] for c in cuerpo["carteras"]] == ["a", "b", cuerpo["cartera"]["id"]]
    assert not cuerpo["carteras"][-1]["activa"]
    cid_c = cuerpo["cartera"]["id"]
    # Renombrar la nueva.
    r = cliente.post(f"/api/carteras/{cid_c}/renombrar", json={"nombre": "Cartera C2"}, headers=CAB)
    assert r.status_code == 200 and r.get_json()["cartera"]["nombre"] == "Cartera C2"
    # Borrar la nueva: la activa sigue siendo "a".
    r = cliente.delete(f"/api/carteras/{cid_c}", headers=CAB)
    assert r.status_code == 200
    assert [c["id"] for c in r.get_json()["carteras"]] == ["a", "b"]
    assert all(not c["activa"] for c in r.get_json()["carteras"] if c["id"] != "a")
    # GET /api/carteras: orden del índice y la activa.
    r = cliente.get("/api/carteras")
    cuerpo = r.get_json()
    assert [c["id"] for c in cuerpo["carteras"]] == ["a", "b"]
    assert cuerpo["activa"] == "a"
    assert cuerpo["carteras"][0]["activa"] and not cuerpo["carteras"][1]["activa"]
    # Borrar la última cartera: 400.
    cliente.delete("/api/carteras/a", headers=CAB)
    r = cliente.delete("/api/carteras/b", headers=CAB)
    assert r.status_code == 400


def test_activar_cambia_la_cartera(cliente, entorno, monkeypatch):
    """Activar la segunda cartera cambia /api/cartera; una escritura no toca la primera."""
    servidor, tmp_path = entorno
    _cache_sembrada(monkeypatch, tmp_path, ["AAA", "BBB"])
    a, b = _dos_carteras(tmp_path)
    r = cliente.post("/api/carteras/b/activar", headers=CAB)
    assert r.status_code == 200 and r.get_json()["activa"] == "b"
    r = cliente.get("/api/cartera")
    cuerpo = r.get_json()
    assert cuerpo["cartera"]["titular"] == "Cartera B"
    assert cuerpo["carteraActiva"] == {"id": "b", "nombre": "Cartera B"}
    assert cuerpo["carteras"][1]["activa"] and not cuerpo["carteras"][0]["activa"]
    # Una escritura solo toca la cartera activa (b).
    r = cliente.post("/api/productos", json={"nombre": "Nuevo", "tipo": "accion",
                                             "fuente": "manual"}, headers=CAB)
    assert r.status_code == 200
    a2 = json.load(open(os.path.join(tmp_path, "carteras", "a.json"), encoding="utf-8"))
    b2 = json.load(open(os.path.join(tmp_path, "carteras", "b.json"), encoding="utf-8"))
    assert a2["productos"] == a["productos"]
    assert any(p["nombre"] == "Nuevo" for p in b2["productos"])


def test_id_de_url_no_es_ruta(cliente, entorno):
    """Un id con ../ no es un error de ruta: 400/404 con mensaje de id no válido.

    El cliente de pruebas decodifica el %2f antes de enrutar, así que la petición
    codificada se manda por WSGI para que la ruta reciba de verdad el id con ../.
    """
    servidor, tmp_path = entorno
    _dos_carteras(tmp_path)

    def _pide_wsgi(ruta):
        """POST a `ruta` sin decodificar, para simular un servidor WSGI real."""
        entorno_wsgi = {
            "REQUEST_METHOD": "POST", "SCRIPT_NAME": "", "PATH_INFO": ruta,
            "QUERY_STRING": "", "SERVER_NAME": "localhost", "SERVER_PORT": "80",
            "HTTP_HOST": "localhost", "HTTP_X_RUMBO": "1",
            "wsgi.version": (1, 0), "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False, "wsgi.multiprocess": False, "wsgi.run_once": False,
            "CONTENT_LENGTH": "0",
        }
        salida = {}
        cuerpo = b"".join(servidor.app(entorno_wsgi, lambda estado, _cab: salida.update(estado=estado)))
        datos = json.loads(cuerpo) if cuerpo.lstrip().startswith(b"{") else None
        return int(salida["estado"].split()[0]), datos

    estado, cuerpo = _pide_wsgi("/api/carteras/%2e%2e%2f%2e%2e%2fetc%2fpasswd/activar")
    assert estado == 400
    assert cuerpo["ok"] is False
    assert cuerpo["errores"] == ["Identificador de cartera no válido."]
    # La URL con ../ en crudo nunca debe acabar en un error de servidor.
    assert _pide_wsgi("/api/carteras/../../etc/passwd/activar")[0] != 500


def test_borrar_la_ultima_cartera(cliente, entorno):
    """No se puede borrar la única cartera."""
    _dos_carteras(entorno[1])
    cliente.delete("/api/carteras/a", headers=CAB)
    r = cliente.delete("/api/carteras/b", headers=CAB)
    assert r.status_code == 400


def test_crear_en_demo_sale_de_la_demo(cliente, entorno):
    """Crear la primera cartera en modo demo la activa y sale de la demo."""
    servidor, tmp_path = entorno
    r = cliente.get("/api/cartera")
    assert r.get_json()["modo"] == "demo"
    r = cliente.post("/api/carteras", json={"nombre": "Mi cartera", "desde": "vacia"}, headers=CAB)
    assert r.status_code == 200
    cuerpo = r.get_json()
    # La marca de activa va en cada entrada del catálogo, no en la cartera creada.
    assert [c["id"] for c in cuerpo["carteras"]] == [cuerpo["cartera"]["id"]]
    assert cuerpo["carteras"][0]["activa"]
    # La primera cartera en demo también sale de la demo y queda activa.
    r = cliente.get("/api/cartera")
    cuerpo = r.get_json()
    assert cuerpo["modo"] == "propio"
    assert cuerpo["carteraActiva"]["id"] == cuerpo["carteras"][0]["id"]
    # api_empezar sigue funcionando como alias fino.
    r = cliente.post("/api/empezar", headers=CAB)
    assert r.status_code == 400  # ya hay cartera propia
