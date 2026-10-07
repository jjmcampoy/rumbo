# -*- coding: utf-8 -*-
"""Pruebas de la cartera multi-cartera (T-31): migración, cartera activa y escrituras."""
import copy
import datetime as dt
import hashlib
import importlib
import io
import json
import os
import stat

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


def _cartera_cuatro(tmp_path):
    """Siembra una cartera con cuatro productos (y sus movimientos y valores)."""
    cfg = copy.deepcopy(CARTERA_MINIMA)
    cfg["titular"] = "Principal"
    cfg["productos"] = [
        {"id": "bitcoin", "nombre": "Bitcoin", "corto": "Bitcoin", "tipo": "cripto",
         "fuente": "coingecko", "codigo": "bitcoin", "moneda": "EUR", "slot": 1, "largoPlazo": True},
        {"id": "world", "nombre": "World", "corto": "World", "tipo": "accion",
         "fuente": "yahoo", "codigo": "WLD", "moneda": "EUR", "slot": 2, "largoPlazo": True},
        {"id": "efectivo", "nombre": "Efectivo", "corto": "Efectivo", "tipo": "efectivo",
         "fuente": "manual", "moneda": "EUR", "slot": 3, "largoPlazo": True},
        {"id": "deuda", "nombre": "Deuda", "corto": "Deuda", "tipo": "deuda",
         "fuente": "manual", "moneda": "EUR", "slot": 4, "largoPlazo": True},
    ]
    cfg["movimientos"] = [
        {"id": "m1", "fecha": "2024-01-02", "producto": "bitcoin", "tipo": "compra",
         "unidades": 1, "importe": 50000.0},
        {"id": "m2", "fecha": "2024-01-03", "producto": "world", "tipo": "compra",
         "unidades": 10, "importe": 1000.0},
        {"id": "m3", "fecha": "2024-01-04", "producto": "efectivo", "tipo": "compra",
         "unidades": 0, "importe": 2000.0},
    ]
    cfg["valoraciones"] = [
        {"id": "v1", "fecha": "2024-01-05", "producto": "bitcoin", "valor": 51000.0},
        {"id": "v2", "fecha": "2024-01-05", "producto": "efectivo", "valor": 2000.0},
    ]
    cfg["comparador"] = [
        {"id": "real", "nombre": "Mi cartera real", "real": True},
        {"id": "pesos", "nombre": "Mis pesos", "pesos": {"bitcoin": 50, "world": 30, "efectivo": 20}},
    ]
    escribe_json(os.path.join(tmp_path, "carteras", "principal.json"), cfg)
    escribe_json(os.path.join(tmp_path, "carteras", "indice.json"),
                 {"version": 1, "activa": "principal",
                  "carteras": [{"id": "principal", "nombre": "Principal",
                                "creada": "2024-01-01T00:00:00"}]})
    return cfg


def test_extraer_copia(cliente, entorno, monkeypatch):
    """Extraer dos de cuatro productos (copia): la nueva tiene solo esos dos y el origen no cambia."""
    servidor, tmp_path = entorno
    _cache_sembrada(monkeypatch, tmp_path, ["bitcoin", "WLD"])
    cfg = _cartera_cuatro(tmp_path)
    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Cripto", "productos": ["bitcoin", "world"]}, headers=CAB)
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["ok"] and cuerpo["origen"] == "principal"
    assert cuerpo["movidos"] == 2
    nueva = json.load(open(os.path.join(tmp_path, "carteras", cuerpo["cartera"]["id"] + ".json"),
                           encoding="utf-8"))
    assert [p["id"] for p in nueva["productos"]] == ["bitcoin", "world"]
    assert [m["id"] for m in nueva["movimientos"]] == ["m1", "m2"]
    assert [v["id"] for v in nueva["valoraciones"]] == ["v1"]
    assert nueva["hitos"] == cfg["hitos"] and nueva["objetivo"] == cfg["objetivo"]
    # El comparador conserva la entrada real y solo los pesos de los elegidos.
    assert [c["id"] for c in nueva["comparador"]] == ["real", "pesos"]
    assert nueva["comparador"][1]["pesos"] == {"bitcoin": 50, "world": 30}
    # El origen no cambia.
    a2 = json.load(open(os.path.join(tmp_path, "carteras", "principal.json"), encoding="utf-8"))
    assert a2 == cfg


def test_extraer_mover(cliente, entorno, monkeypatch):
    """Extraer con mover=true: el origen pierde los productos y sus movimientos/valores."""
    servidor, tmp_path = entorno
    _cache_sembrada(monkeypatch, tmp_path, ["bitcoin", "WLD"])
    cfg = _cartera_cuatro(tmp_path)
    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Cripto", "productos": ["bitcoin", "world"], "mover": True},
                     headers=CAB)
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["ok"] and cuerpo["movidos"] == 2
    nueva = json.load(open(os.path.join(tmp_path, "carteras", cuerpo["cartera"]["id"] + ".json"),
                           encoding="utf-8"))
    assert [p["id"] for p in nueva["productos"]] == ["bitcoin", "world"]
    a2 = json.load(open(os.path.join(tmp_path, "carteras", "principal.json"), encoding="utf-8"))
    assert [p["id"] for p in a2["productos"]] == ["efectivo", "deuda"]
    assert [m["id"] for m in a2["movimientos"]] == ["m3"]
    assert [v["id"] for v in a2["valoraciones"]] == ["v2"]
    # Los pesos del origen solo refieren a productos existentes.
    for c in a2["comparador"]:
        if c.get("pesos"):
            assert set(c["pesos"]) <= {p["id"] for p in a2["productos"]}
    for c in nueva["comparador"]:
        if c.get("pesos"):
            assert set(c["pesos"]) <= {p["id"] for p in nueva["productos"]}


def test_extraer_invalidos(cliente, entorno):
    """Producto desconocido, lista vacía o origen desconocido: 400 y no se crea cartera."""
    servidor, tmp_path = entorno
    _cartera_cuatro(tmp_path)
    antes = [c["id"] for c in carteras_lista(tmp_path)]
    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "X", "productos": ["bitcoin", "noexiste"]}, headers=CAB)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    r = cliente.post("/api/carteras/extraer", json={"nombre": "X", "productos": []}, headers=CAB)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "X", "productos": ["bitcoin"], "desde": "noexiste"}, headers=CAB)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert [c["id"] for c in carteras_lista(tmp_path)] == antes


def carteras_lista(tmp_path):
    """Las carteras del índice, para comprobar que no se creó ninguna de más."""
    idx = json.load(open(os.path.join(tmp_path, "carteras", "indice.json"), encoding="utf-8"))
    return idx["carteras"]


def _texto_importar(pid):
    """Texto pegado con una compra de un producto ya existente."""
    return ("fecha;tipo_movimiento;identificador;importe;unidades\n"
            f"2024-01-05;compra;{pid};500;5\n"
            f"2024-01-06;compra;{pid};700;7")


def test_confirmar_importacion_en_otra_cartera(cliente, entorno):
    """Confirmar con la cartera activa cambiada: 400 y ninguna cartera se toca."""
    servidor, tmp_path = entorno
    a, b = _dos_carteras(tmp_path)
    r = cliente.post("/api/importar/previsualizar",
                     data={"texto": _texto_importar("accion")}, headers=CAB)
    assert r.status_code == 200
    token = r.get_json()["token"]
    # Se activa la cartera B entre la vista previa y la confirmación.
    r = cliente.post("/api/carteras/b/activar", headers=CAB)
    assert r.status_code == 200
    r = cliente.post("/api/importar/confirmar",
                     json={"token": token, "cid": "a"}, headers=CAB)
    assert r.status_code == 400
    assert r.get_json()["errores"] == ["La cartera activa ha cambiado: vuelve a revisar el archivo."]
    # Ni A ni B han cambiado.
    a2 = json.load(open(os.path.join(tmp_path, "carteras", "a.json"), encoding="utf-8"))
    b2 = json.load(open(os.path.join(tmp_path, "carteras", "b.json"), encoding="utf-8"))
    assert a2 == a and b2 == b
    # El token se consume: confirmar otra vez tampoco vale.
    r = cliente.post("/api/importar/confirmar", json={"token": token, "cid": "b"}, headers=CAB)
    assert r.status_code == 400


def test_confirmar_importacion_en_la_misma_cartera(cliente, entorno, monkeypatch):
    """Confirmar sin cambiar de cartera: los movimientos caen solo en esa cartera."""
    servidor, tmp_path = entorno
    _cache_sembrada(monkeypatch, tmp_path, ["AAA"])
    a, b = _dos_carteras(tmp_path)
    r = cliente.post("/api/importar/previsualizar",
                     data={"texto": _texto_importar("AAA")}, headers=CAB)
    assert r.status_code == 200
    token = r.get_json()["token"]
    # La vista previa de verdad produce las dos filas, sin errores.
    informe = r.get_json()["informe"]
    assert informe["añadidos"] == 2
    assert not informe["errores"]
    r = cliente.post("/api/importar/confirmar", json={"token": token, "cid": "a"}, headers=CAB)
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["ok"]
    a2 = json.load(open(os.path.join(tmp_path, "carteras", "a.json"), encoding="utf-8"))
    b2 = json.load(open(os.path.join(tmp_path, "carteras", "b.json"), encoding="utf-8"))
    # Los movimientos importados (2024-01-05 y 2024-01-06) quedan solo en A.
    fechas_a = {m["fecha"] for m in a2["movimientos"]}
    assert {"2024-01-05", "2024-01-06"} <= fechas_a
    assert b2 == b


def test_confirmar_importacion_sin_cid(cliente, entorno, monkeypatch):
    """Confirmar mandando solo el token (como hace la interfaz): funciona si la
    cartera activa no cambió, y los movimientos caen en la cartera del token."""
    servidor, tmp_path = entorno
    _cache_sembrada(monkeypatch, tmp_path, ["AAA"])
    a, b = _dos_carteras(tmp_path)
    r = cliente.post("/api/importar/previsualizar",
                     data={"texto": _texto_importar("AAA")}, headers=CAB)
    assert r.status_code == 200
    token = r.get_json()["token"]
    # La interfaz manda solo el token, sin repetir la cartera.
    r = cliente.post("/api/importar/confirmar", json={"token": token}, headers=CAB)
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["ok"]
    a2 = json.load(open(os.path.join(tmp_path, "carteras", "a.json"), encoding="utf-8"))
    b2 = json.load(open(os.path.join(tmp_path, "carteras", "b.json"), encoding="utf-8"))
    # Los movimientos importados quedan solo en A.
    fechas_a = {m["fecha"] for m in a2["movimientos"]}
    assert {"2024-01-05", "2024-01-06"} <= fechas_a
    assert b2 == b


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


# ---------------------------------------------------------------- T-36: migración y aislamiento

def _sello(datos_dir):
    """sha1 de cada fichero bajo una carpeta -> {ruta relativa: hash}."""
    salida = {}
    for raiz, _dirs, nombres in os.walk(str(datos_dir)):
        for n in nombres:
            p = os.path.join(raiz, n)
            with open(p, "rb") as f:
                salida[os.path.relpath(p, str(datos_dir))] = hashlib.sha1(f.read()).hexdigest()
    return salida


def _cartera_rico():
    """Un documento de la 1.1.1 con todo lo que puede llevar una cartera real."""
    cfg = copy.deepcopy(CARTERA_MINIMA)
    cfg["productos"].append({"id": "bono", "nombre": "Bono Prueba", "corto": "Bono",
                             "tipo": "bono", "fuente": "manual", "codigo": "",
                             "moneda": "EUR", "slot": 2, "largoPlazo": True})
    cfg["movimientos"].append({"id": "m2", "fecha": "2024-02-01", "producto": "bono",
                               "tipo": "compra", "unidades": 5, "importe": 500.0})
    cfg["valoraciones"] = [{"id": "v1", "fecha": "2024-03-01", "producto": "accion",
                            "valor": 1100.0}]
    cfg["comparador"] = [{"id": "real", "nombre": "Mi cartera real", "real": True},
                         {"id": "pesos", "nombre": "Mis pesos",
                          "pesos": {"accion": 60, "bono": 40}}]
    cfg["hitos"] = [10000, 25000]
    cfg["objetivo"] = {"activo": True, "importe": 50000, "etiqueta": "Meta"}
    return cfg


def _recarga(servidor):
    """Recarga el módulo (la migración corre al importar) y devuelve un cliente nuevo."""
    servidor = importlib.reload(servidor)
    servidor.app.config.update(TESTING=True)
    return servidor, servidor.app.test_client()


def test_permisos_de_la_carpeta_carteras(cliente, entorno):
    """F-11 en el layout nuevo: carteras/ es 0700 y los ficheros de dentro, 0600."""
    servidor, tmp_path = entorno
    r = cliente.post("/api/carteras", json={"nombre": "Mi cartera", "desde": "vacia"},
                     headers=CAB)
    assert r.status_code == 200

    carpeta = os.path.join(tmp_path, "carteras")
    modo = stat.S_IMODE(os.stat(carpeta).st_mode)
    assert modo == 0o700, oct(modo)

    dentro = [os.path.join(carpeta, n) for n in os.listdir(carpeta)]
    assert dentro, "no se ha escrito nada en carteras/"
    for p in dentro:
        modo = stat.S_IMODE(os.stat(p).st_mode)
        assert modo == 0o600, f"{p}: {oct(modo)}"


def test_migracion_legada_conserva_todo(cliente, entorno):
    """Un mis_datos rico de la 1.1.1 se migra sin perder nada y sin borrar lo demás."""
    servidor, tmp_path = entorno
    cfg = _cartera_rico()
    escribe_json(os.path.join(tmp_path, "cartera.json"), cfg)
    escribe_json(os.path.join(tmp_path, "copias", "auto_x.json"), CARTERA_MINIMA)
    escribe_cache(tmp_path, "AAA", {"2024-01-02": 100.0, "2024-01-03": 101.0})
    escribe_json(os.path.join(tmp_path, "estado.json"),
                 {"preciosActualizados": "2024-01-01T00:00:00"})
    escribe_json(os.path.join(tmp_path, "calculado_propio.json"), {"patrimonio": 1234.0})

    servidor, cliente = _recarga(servidor)

    r = cliente.get("/api/cartera")
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["modo"] == "propio"
    assert cuerpo["cartera"] == cfg, "la cartera migrada no es idéntica a la antigua"

    # Nada de lo demás se toca: la caché compartida y los derivados siguen donde estaban.
    assert os.path.exists(os.path.join(tmp_path, "cache", "AAA.json"))
    assert os.path.exists(os.path.join(tmp_path, "copias", "auto_x.json"))
    assert os.path.exists(os.path.join(tmp_path, "estado.json"))
    assert os.path.exists(os.path.join(tmp_path, "calculado_propio.json"))

    # La cartera antigua se movió a copias/ con una copia de seguridad intacta.
    assert not os.path.exists(os.path.join(tmp_path, "cartera.json"))
    respaldos = [n for n in os.listdir(os.path.join(tmp_path, "copias"))
                 if n.startswith("cartera_migrada_")]
    assert len(respaldos) == 1
    with open(os.path.join(tmp_path, "copias", respaldos[0]), encoding="utf-8") as f:
        assert json.load(f) == cfg


def test_aislamiento_entre_carteras(cliente, entorno):
    """Escribir en una cartera, y borrarla, no toca el fichero de la otra."""
    servidor, tmp_path = entorno
    _dos_carteras(tmp_path)
    rb = os.path.join(tmp_path, "carteras", "b.json")
    with open(rb, "rb") as f:
        b_antes = f.read()

    r = cliente.post("/api/productos", json={"nombre": "Nuevo", "tipo": "accion",
                                            "fuente": "manual"}, headers=CAB)
    assert r.status_code == 200
    with open(rb, "rb") as f:
        assert f.read() == b_antes, "escribir en A ha modificado B"

    r = cliente.delete("/api/carteras/a", headers=CAB)
    assert r.status_code == 200
    with open(rb, "rb") as f:
        assert f.read() == b_antes, "borrar A ha modificado B"
    assert os.path.exists(rb)


def test_dos_escrituras_no_tocan_el_mismo_fichero(cliente, entorno):
    """Dos POST /api/productos seguidos, en carteras distintas, van a ficheros distintos."""
    servidor, tmp_path = entorno
    _dos_carteras(tmp_path)
    ra = os.path.join(tmp_path, "carteras", "a.json")
    rb = os.path.join(tmp_path, "carteras", "b.json")

    r = cliente.post("/api/productos", json={"nombre": "En A", "tipo": "accion",
                                            "fuente": "manual"}, headers=CAB)
    assert r.status_code == 200
    a1, b1 = os.stat(ra).st_mtime_ns, os.stat(rb).st_mtime_ns

    r = cliente.post("/api/carteras/b/activar", headers=CAB)
    assert r.status_code == 200
    r = cliente.post("/api/productos", json={"nombre": "En B", "tipo": "accion",
                                            "fuente": "manual"}, headers=CAB)
    assert r.status_code == 200
    a2, b2 = os.stat(ra).st_mtime_ns, os.stat(rb).st_mtime_ns

    assert a2 == a1, "la escritura en B ha tocado la cartera A"
    assert b2 > b1, "la escritura en B no ha llegado a su fichero"


def test_migracion_idempotente(cliente, entorno):
    """Recargar el servidor tres veces más no vuelve a escribir en carteras/."""
    servidor, tmp_path = entorno
    cartera_en_disco(tmp_path)
    servidor, cliente = _recarga(servidor)          # primera migración
    assert os.path.exists(os.path.join(tmp_path, "carteras", "indice.json"))

    antes = _sello(os.path.join(tmp_path, "carteras"))
    for _ in range(3):
        servidor, cliente = _recarga(servidor)
    assert _sello(os.path.join(tmp_path, "carteras")) == antes
    assert cliente.get("/api/cartera").get_json()["cartera"]["titular"] == "Prueba"


def test_instalacion_limpia_no_crea_nada(cliente, entorno):
    """En una carpeta vacía la app está en demo y no ha creado ni un fichero."""
    servidor, tmp_path = entorno
    r = cliente.get("/api/cartera")
    assert r.get_json()["modo"] == "demo"
    assert os.listdir(tmp_path) == [], os.listdir(tmp_path)


# ---------------------------------------------------------------- cartera anclada (T-51)

def _calculado(tmp_path, cid, titular, patrimonio):
    """Cálculo guardado, mínimo y distinguible, para una cartera."""
    escribe_json(os.path.join(tmp_path, "calculado", cid + ".json"),
                 {"generado": "2024-06-30T12:00:00", "fechaExtracto": "2024-06-30",
                  "titular": titular, "productos": [],
                  "total": {"patrimonio": patrimonio, "aportado": patrimonio,
                            "plusvalia": 0.0, "rentabilidad": 0.0, "tir": None}})


def test_anclaje_de_cartera_por_peticion(cliente, entorno):
    """?cartera= y X-Rumbo-Cartera eligen la cartera de ESTA petición sin cambiar la activa."""
    servidor, tmp_path = entorno
    _dos_carteras(tmp_path)                       # la activa es «a»
    _calculado(tmp_path, "a", "Cartera A", 100.0)
    _calculado(tmp_path, "b", "Cartera B", 200.0)

    # Sin anclaje, todo igual que siempre: manda la activa.
    assert "Cartera A" in cliente.get("/datos.js").get_data(as_text=True)

    # Con ?cartera=b esta petición sirve la otra cartera...
    assert "Cartera B" in cliente.get("/datos.js?cartera=b").get_data(as_text=True)
    # ...y la activa no se ha tocado.
    assert servidor.carteras.activa(servidor.DATOS) == "a"

    # La cabecera es el otro canal y hace exactamente lo mismo.
    r = cliente.get("/datos.js", headers={"X-Rumbo-Cartera": "b"})
    assert r.status_code == 200
    assert "Cartera B" in r.get_data(as_text=True)

    # El anclaje llega también a las rutas de datos.
    j = cliente.get("/api/cartera?cartera=b").get_json()
    assert j["cartera"]["titular"] == "Cartera B"
    assert j["carteraActiva"]["id"] == "b"
    assert cliente.get("/api/cartera").get_json()["cartera"]["titular"] == "Cartera A"
    assert servidor.carteras.activa(servidor.DATOS) == "a"


def test_anclaje_invalido_o_desconocido_cae_a_la_activa(cliente, entorno):
    """Un id inválido o inexistente se ignora: se sirve la activa y nunca hay error."""
    servidor, tmp_path = entorno
    _dos_carteras(tmp_path)
    _calculado(tmp_path, "a", "Cartera A", 100.0)
    _calculado(tmp_path, "b", "Cartera B", 200.0)

    for malo in ("../../etc/passwd", "no_existe", "MAYUS", "a" * 31, ""):
        r = cliente.get("/datos.js", query_string={"cartera": malo})
        assert r.status_code == 200, malo
        assert "Cartera A" in r.get_data(as_text=True), malo
        assert servidor.carteras.activa(servidor.DATOS) == "a"


def test_anclaje_no_salta_la_guardia_csrf(cliente, entorno):
    """Anclar la cartera no exime de la cabecera CSRF de T-16."""
    servidor, tmp_path = entorno
    _dos_carteras(tmp_path)
    assert cliente.post("/api/carteras/b/activar?cartera=b").status_code == 403
    assert cliente.post("/api/carteras/b/activar",
                        headers={"X-Rumbo-Cartera": "b"}).status_code == 403
    # Y la activa sigue siendo la de antes.
    assert servidor.carteras.activa(servidor.DATOS) == "a"
