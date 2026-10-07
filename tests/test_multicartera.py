# -*- coding: utf-8 -*-
"""Pruebas de multicartera: migración transparente, activación y aislamiento.

Cada cartera tiene su propio `carteras/<cid>.json`; el motor, el estado y los
historicos van a rutas que dependen del `cid` activo.
"""
import hashlib
import importlib
import json
import os
import re
import stat

from app import carteras
from tests.conftest import cartera_en_disco, cartera_en_disco_v2, escribe_json

CARPETA_A = {
    "version": 1, "titular": "Cartera A",
    "productos": [{"id": "prod_a", "nombre": "Producto A", "corto": "PA",
                   "tipo": "accion", "fuente": "manual", "codigo": "AAA",
                   "moneda": "EUR", "slot": 1, "largoPlazo": False}],
    "movimientos": [{"id": "m1", "fecha": "2024-01-02", "producto": "prod_a",
                     "tipo": "compra", "unidades": 1, "importe": 100.0}],
    "valoraciones": [{"id": "v1", "fecha": "2024-01-03", "producto": "prod_a",
                      "valor": 120.0}],
    "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True}],
    "hitos": [10000],
    "objetivo": {"activo": True, "importe": 100000, "etiqueta": "Meta"},
}

CARPETA_B = {
    "version": 1, "titular": "Cartera B",
    "productos": [{"id": "prod_b", "nombre": "Producto B", "corto": "PB",
                   "tipo": "fondo", "fuente": "manual", "codigo": "BBB",
                   "moneda": "EUR", "slot": 1, "largoPlazo": False}],
    "movimientos": [{"id": "m1", "fecha": "2024-01-02", "producto": "prod_b",
                     "tipo": "compra", "unidades": 2, "importe": 200.0}],
    "valoraciones": [{"id": "v1", "fecha": "2024-01-03", "producto": "prod_b",
                      "valor": 150.0}],
    "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True}],
    "hitos": [10000],
    "objetivo": {"activo": True, "importe": 200000, "etiqueta": "Meta"},
}


def _escribe_doc(ruta, doc):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def _escribir_dos_carteras(tmp_path):
    """Escribe alfa y beta (alfa activa) en el layout multicartera."""
    carteras.escribe_indice(tmp_path, {
        "version": 1, "activa": "alfa",
        "carteras": [
            {"id": "alfa", "nombre": "Cartera A", "creada": "2024-01-01T00:00:00"},
            {"id": "beta", "nombre": "Cartera B", "creada": "2024-01-01T00:00:00"},
        ],
    })
    _escribe_doc(carteras.ruta(tmp_path, "alfa"), CARPETA_A)
    _escribe_doc(carteras.ruta(tmp_path, "beta"), CARPETA_B)


# ---------------------------------------------------------------- migración

def test_migracion_transparente(entorno):
    """Cartera heredada → módulo migra → API sirve el contenido migrado."""
    servidor, tmp_path = entorno
    cartera_en_disco(tmp_path)                # layout legacy 1.1.1
    servidor = importlib.reload(servidor)     # dispara migra_si_hace_falta
    cliente = servidor.app.test_client()
    j = cliente.get("/api/cartera").get_json()
    assert j["modo"] == "propio"
    assert j["cartera"]["productos"][0]["id"] == "accion"
    # El archivo heredado ya no está en la raíz de datos
    assert not os.path.exists(os.path.join(str(tmp_path), "cartera.json"))
    # El documento nuevo está en carteras/principal.json
    assert os.path.exists(os.path.join(str(tmp_path), "carteras", "principal.json"))


# ---------------------------------------------------------------- activación

def test_cada_cartera_siria_sus_datos(entorno):
    """Al cambiar la cartera activa, /api/cartera y /datos.js sirven la correcta."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    # Alfa es la activa: el API y datos.js la sirven
    j = cliente.get("/api/cartera").get_json()
    assert j["cartera"]["titular"] == "Cartera A"
    assert j["cartera"]["productos"][0]["id"] == "prod_a"
    txt = cliente.get("/datos.js").get_data(as_text=True)
    assert '"prod_a"' in txt and '"prod_b"' not in txt

    # Activar beta
    carteras.activa_set(tmp_path, "beta")

    # Ahora /api/cartera y /datos.js sirven beta
    j = cliente.get("/api/cartera").get_json()
    assert j["cartera"]["titular"] == "Cartera B"
    assert j["cartera"]["productos"][0]["id"] == "prod_b"
    txt = cliente.get("/datos.js").get_data(as_text=True)
    assert '"prod_b"' in txt and '"prod_a"' not in txt


def test_escribir_no_toca_la_otra(entorno):
    """Un POST /api/productos solo afecta al JSON de la cartera activa."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    r = cliente.post("/api/productos",
                     json={"nombre": "Nuevo", "tipo": "fondo", "fuente": "manual"},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200

    # Beta no tiene el nuevo producto
    doc_beta = json.load(open(carteras.ruta(tmp_path, "beta"), encoding="utf-8"))
    assert all(p.get("nombre") != "Nuevo" for p in doc_beta["productos"])

    # Alfa sí lo tiene
    doc_alfa = json.load(open(carteras.ruta(tmp_path, "alfa"), encoding="utf-8"))
    assert any(p.get("nombre") == "Nuevo" for p in doc_alfa["productos"])


# ---------------------------------------------------------------- copias

def test_copias_cartera_activa(entorno):
    """/api/copias lista solo las copias de la cartera activa (copias/<cid>/)."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    for cid, nombre in (("alfa", "copia_alfa.json"), ("beta", "copia_beta.json")):
        carpeta = os.path.join(str(tmp_path), "copias", cid)
        os.makedirs(carpeta, exist_ok=True)
        _escribe_doc(os.path.join(carpeta, nombre), CARPETA_A)

    # Alfa activa: solo su copia aparece
    carteras.activa_set(tmp_path, "alfa")
    j = cliente.get("/api/copias").get_json()
    nombres = [c["archivo"] for c in j["copias"]]
    assert nombres == ["copia_alfa.json"]

    # Beta activa: solo su copia aparece
    carteras.activa_set(tmp_path, "beta")
    j = cliente.get("/api/copias").get_json()
    nombres = [c["archivo"] for c in j["copias"]]
    assert nombres == ["copia_beta.json"]


# ---------------------------------------------------------------- catálogo HTTP

def test_cred_renombrar_borrar(entorno):
    """Crear, renombrar y borrar por HTTP: orden del índice y cartera activa."""
    servidor, tmp_path = entorno
    cartera_en_disco_v2(tmp_path, CARPETA_A, cid="alfa")
    cliente = servidor.app.test_client()
    h = {"X-Rumbo": "1"}

    # Crear dos (la primera ya existe: alfa)
    r = cliente.post("/api/carteras", json={"nombre": "Segunda", "desde": "vacia"}, headers=h)
    assert r.status_code == 200
    nueva = r.get_json()["cartera"]
    # No se activa al crear
    assert r.get_json()["activa"] == "alfa"
    r = cliente.post("/api/carteras", json={"nombre": "Tercera"}, headers=h)
    assert r.status_code == 200
    otra = r.get_json()["cartera"]

    # GET /api/carteras: solo metadata, en el orden del índice, con la activa
    j = cliente.get("/api/carteras").get_json()
    ids = [c["id"] for c in j["carteras"]]
    assert ids == ["alfa", nueva["id"], otra["id"]]
    assert j["activa"] == "alfa"
    assert [c["activa"] for c in j["carteras"]] == [True, False, False]
    assert set(j["carteras"][0]) == {"id", "nombre", "creada", "activa", "productos"}   # solo metadata

    # Renombrar a una: cambia el índice y el titular
    r = cliente.post(f"/api/carteras/{nueva['id']}/renombrar",
                     json={"nombre": "Segunda (renombrada)"}, headers=h)
    assert r.status_code == 200 and r.get_json()["ok"]
    doc = json.load(open(carteras.ruta(tmp_path, nueva["id"]), encoding="utf-8"))
    assert doc["titular"] == "Segunda (renombrada)"

    # Borrar una que no es la activa: la activa no cambia
    r = cliente.delete(f"/api/carteras/{otra['id']}", headers=h)
    assert r.status_code == 200
    assert r.get_json()["activa"] == "alfa"
    j = cliente.get("/api/carteras").get_json()
    assert [c["id"] for c in j["carteras"]] == ["alfa", nueva["id"]]
    # La borrada pasó a copias/<cid>/
    borradas = []
    copia_dir = os.path.join(str(tmp_path), "copias", otra["id"])
    if os.path.isdir(copia_dir):
        borradas = [n for n in os.listdir(copia_dir) if n.startswith("borrada_")]
    assert borradas and borradas[0].endswith(".json")


def test_activar_por_http(entorno):
    """Activar por HTTP: /api/cartera sirve los productos de la nueva activa;
    escribir no toca la otra."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    r = cliente.post("/api/carteras/beta/activar", headers={"X-Rumbo": "1"})
    assert r.status_code == 200 and r.get_json()["activa"] == "beta"

    j = cliente.get("/api/cartera").get_json()
    assert j["cartera"]["productos"][0]["id"] == "prod_b"
    assert j["carteraActiva"] == {"id": "beta", "nombre": "Cartera B"}
    assert [c["activa"] for c in j["carteras"]] == [False, True]

    # Escribir en la activa (beta): alfa no se toca
    r = cliente.post("/api/productos",
                     json={"nombre": "Nueva en beta", "tipo": "fondo", "fuente": "manual"},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    doc_alfa = json.load(open(carteras.ruta(tmp_path, "alfa"), encoding="utf-8"))
    assert all(p["nombre"] != "Nueva en beta" for p in doc_alfa["productos"])


def test_ids_de_url_se_validan(entorno):
    """Todo id de URL se valida: 400 si no es legítimo, 404 si no existe,
    y una URL con `..` nunca provoca un error de ruta (5xx)."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()
    h = {"X-Rumbo": "1"}
    # URL trampa: o se valida o se normaliza; nunca un error de ruta
    r = cliente.get("/api/carteras/../../etc/passwd/activar")
    assert r.status_code in (200, 400, 404)      # nunca un 5xx
    # Id inválido (mayúsculas) → 400 con mensaje en español
    r = cliente.post("/api/carteras/MAYUSCULA/activar", headers=h)
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    # Id legítimo pero inexistente → 404
    r = cliente.delete("/api/carteras/no_existe", headers=h)
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_no_se_puede_borrar_la_ultima(entorno):
    """Borrar la única cartera → 400."""
    servidor, tmp_path = entorno
    cartera_en_disco_v2(tmp_path, CARPETA_A, cid="solo")
    cliente = servidor.app.test_client()
    r = cliente.delete("/api/carteras/solo", headers={"X-Rumbo": "1"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert os.path.exists(carteras.ruta(tmp_path, "solo"))


def test_crear_en_demo_sale_de_la_demo(entorno):
    """En modo demo, crear la primera cartera la activa y deja el modo demo."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    h = {"X-Rumbo": "1"}
    assert cliente.get("/api/cartera").get_json()["modo"] == "demo"

    r = cliente.post("/api/carteras", json={"nombre": "La mía", "desde": "vacia"}, headers=h)
    assert r.status_code == 200
    j = r.get_json()
    assert j["activa"] == j["cartera"]["id"]

    j = cliente.get("/api/cartera").get_json()
    assert j["modo"] == "propio"
    assert j["carteraActiva"]["nombre"] == "La mía"
    assert j["carteras"][0]["activa"] is True


# ---------------------------------------------------------------- extraer
def _carta_cuatro(tmp_path, cid="origen"):
    """Cartera `origen` con 4 productos (cada uno con un movimiento y una
    valoración) y dos comparadores con pesos; la deja activa en el índice."""
    def _pro(id_, nombre, corto, tipo):
        return {"id": id_, "nombre": nombre, "corto": corto, "tipo": tipo,
                "fuente": "manual", "codigo": "", "moneda": "EUR", "slot": 1,
                "largoPlazo": True}
    doc = {
        "version": 1, "titular": "Principal",
        "productos": [_pro("prod1", "Uno", "Uno", "fondo"),
                      _pro("prod2", "Dos", "Dos", "etf"),
                      _pro("prod3", "Tres", "Tres", "accion"),
                      _pro("prod4", "Cuatro", "Cuatro", "cripto")],
        "movimientos": [
            {"id": "m1", "fecha": "2024-01-01", "producto": "prod1", "tipo": "compra",
             "unidades": 1, "importe": 100.0},
            {"id": "m2", "fecha": "2024-01-01", "producto": "prod2", "tipo": "compra",
             "unidades": 2, "importe": 200.0},
            {"id": "m3", "fecha": "2024-01-01", "producto": "prod3", "tipo": "compra",
             "unidades": 3, "importe": 300.0},
            {"id": "m4", "fecha": "2024-01-01", "producto": "prod4", "tipo": "compra",
             "unidades": 4, "importe": 400.0}],
        "valoraciones": [
            {"id": "v1", "fecha": "2024-02-01", "producto": "prod1", "valor": 110.0},
            {"id": "v2", "fecha": "2024-02-01", "producto": "prod2", "valor": 220.0},
            {"id": "v3", "fecha": "2024-02-01", "producto": "prod3", "valor": 330.0},
            {"id": "v4", "fecha": "2024-02-01", "producto": "prod4", "valor": 440.0}],
        "comparador": [
            {"id": "real", "nombre": "Mi cartera real", "real": True},
            {"id": "cuatro25", "nombre": "Cuartos",
             "pesos": {"prod1": 25, "prod2": 25, "prod3": 25, "prod4": 25}},
            {"id": "tressolo", "nombre": "Solo tres", "pesos": {"prod3": 50, "prod4": 50}}],
        "hitos": [100000],
        "objetivo": {"activo": True, "importe": 200000, "etiqueta": "Meta"},
    }
    carteras.escribe_indice(tmp_path, {"version": 1, "activa": cid,
        "carteras": [{"id": cid, "nombre": "Principal", "creada": "2024-01-01T00:00:00"}]})
    _escribe_doc(carteras.ruta(tmp_path, cid), doc)
    return doc


def _doc(tmp_path, cid):
    return json.load(open(carteras.ruta(tmp_path, cid), encoding="utf-8"))


def _ids_carteras(tmp_path):
    return [c["id"] for c in carteras.lee_indice(tmp_path).get("carteras", [])]


def test_extraer_copia_deja_origen(entorno):
    """Extraer 2 de 4 (copia) → la nueva tiene esos 2 y solo sus movimientos y
    valoraciones; el origen queda intacto."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)
    original = _doc(tmp_path, "origen")

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod2"],
                           "mover": False, "desde": "origen"}, headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    nueva_id = r.get_json()["cartera"]["id"]
    nueva = _doc(tmp_path, nueva_id)

    assert [p["id"] for p in nueva["productos"]] == ["prod1", "prod2"]
    # Los ids se conservan tal cual (la caché y flujos los reutilizan).
    assert {p["id"] for p in nueva["productos"]} == {"prod1", "prod2"}
    assert {m["producto"] for m in nueva["movimientos"]} == {"prod1", "prod2"}
    assert {v["producto"] for v in nueva["valoraciones"]} == {"prod1", "prod2"}

    # El origen no cambia: sigue con sus 4 productos y todos sus movimientos.
    actual = _doc(tmp_path, "origen")
    assert {p["id"] for p in actual["productos"]} == {p["id"] for p in original["productos"]}
    assert actual["movimientos"] == original["movimientos"]
    assert actual["valoraciones"] == original["valoraciones"]
    assert r.get_json()["origen"] == "origen"


def test_extraer_mover_baja_la_origen(entorno):
    """Extraer con mover=true → el origen pierde esos productos (y sus movimientos
    y valores); los otros se quedan con los suyos."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod3"],
                           "desde": "origen", "mover": True}, headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    nueva_id = r.get_json()["cartera"]["id"]

    origen = _doc(tmp_path, "origen")
    assert {p["id"] for p in origen["productos"]} == {"prod2", "prod4"}
    assert {m["producto"] for m in origen["movimientos"]} == {"prod2", "prod4"}
    assert {v["producto"] for v in origen["valoraciones"]} == {"prod2", "prod4"}
    # La respuesta indica cuántos productos quedan en el origen (para avisar).
    assert r.get_json()["restantes"] == 2

    nueva = _doc(tmp_path, nueva_id)
    assert {p["id"] for p in nueva["productos"]} == {"prod1", "prod3"}


def test_comparador_solo_productos_que_existen(entorno):
    """En ambos documentos, `comparador[].pesos` solo cita productos existentes;
    las entradas de pesos vacías se tiran (como en almacen.borra_producto)."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod2"],
                           "desde": "origen", "mover": True}, headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    nueva_id = r.get_json()["cartera"]["id"]
    nueva, origen = _doc(tmp_path, nueva_id), _doc(tmp_path, "origen")

    for doc in (nueva, origen):
        ids = {p["id"] for p in doc["productos"]}
        for c in doc["comparador"]:
            for pid in (c.get("pesos") or {}):
                assert pid in ids, f"peso «{pid}» sin producto en {c.get('id')}"
            # Ninguna entrada de pesos queda vacía.
            assert c.get("real") or c.get("pesos"), c

    # En la nueva solo sobrevive la entrada «cuatro25» recortada a prod1/prod2.
    por_id = {c["id"]: c for c in nueva["comparador"]}
    assert por_id["cuatro25"]["pesos"] == {"prod1": 25, "prod2": 25}
    assert "tressolo" not in por_id          # quedaba vacía (prod3/prod4 no vienen)
    # En el origen (se llevan prod1/prod2) «cuatro25» queda a prod3/prod4 y
    # «tressolo» se conserva íntegro (sus pesos seguían existiendo).
    por_id_o = {c["id"]: c for c in origen["comparador"]}
    assert por_id_o["cuatro25"]["pesos"] == {"prod3": 25, "prod4": 25}
    assert por_id_o["tressolo"]["pesos"] == {"prod3": 50, "prod4": 50}


def test_extraer_rechaza_y_no_crea(entorno):
    """Id desconocido, lista vacía o `desde` que no existe → 400 en español y no
    se crea ninguna cartera."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)
    h = {"X-Rumbo": "1"}
    ids_antes = _ids_carteras(tmp_path)

    for cuerpo in (
        {"nombre": "X", "productos": ["inexistente"], "desde": "origen"},
        {"nombre": "X", "productos": [], "desde": "origen"},
        {"nombre": "X", "productos": ["prod1"], "desde": "no_existe"},
    ):
        r = cliente.post("/api/carteras/extraer", json=cuerpo, headers=h)
        assert r.status_code == 400, cuerpo
        assert r.get_json()["ok"] is False
        assert r.get_json()["errores"]
    # No se ha creado ninguna cartera en ningún intento fallido.
    assert _ids_carteras(tmp_path) == ids_antes
    assert not os.path.exists(os.path.join(str(tmp_path), "carteras", "x.json"))


def test_extraer_funcion_pura_persiste_nueva_antes(entorno):
    """`carteras.extrae` devuelve (nueva, origen) y deja la nueva en disco
    (añadida al índice) antes de tocar el origen aunque mover=True."""
    servidor, tmp_path = entorno
    _carta_cuatro(tmp_path)

    nueva, origen = carteras.extrae(tmp_path, "origen", "Mía", ["prod4"], mover=True)
    assert {p["id"] for p in nueva["productos"]} == {"prod4"}
    assert {p["id"] for p in origen["productos"]} == {"prod1", "prod2", "prod3"}
    nueva_id = [c["id"] for c in carteras.lee_indice(tmp_path)["carteras"]
                if c.get("id") != "origen"]
    assert len(nueva_id) == 1 and os.path.exists(carteras.ruta(tmp_path, nueva_id[0]))
    # El origen sigue en disco, ya sin el producto extraído.
    assert {p["id"] for p in _doc(tmp_path, "origen")["productos"]} == {"prod1", "prod2", "prod3"}


# ---------------------------------------------------------------- importar

import io

CSV_IMPORTAR = (
    "fecha;tipo_movimiento;importe;unidades;nombre;tipo_producto;moneda\n"
    "2024-06-15;compra;100.00;10;Fondo Nuevo;fondo;EUR\n"
)


def _previsualiza(cliente, csv=CSV_IMPORTAR):
    """Previsualiza un CSV de plantilla y devuelve el token de la respuesta."""
    r = cliente.post("/api/importar/previsualizar",
                     data={"origen": "plantilla",
                           "archivos": [(io.BytesIO(csv.encode()), "importado.csv")]},
                     content_type="multipart/form-data", headers={"X-Rumbo": "1"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["token"]


def _mov_de_fondo_nuevo(doc):
    """Movimientos del producto «Fondo Nuevo» (se crea como producto nuevo al aplicar)."""
    ids = {p["id"] for p in doc["productos"] if p.get("nombre") == "Fondo Nuevo"}
    return [m for m in doc["movimientos"] if m.get("producto") in ids]


def test_confirmar_otra_cartera_rechaza_y_no_escribe(entorno):
    """Previsualizar en A, activar B y confirmar → 400 y no se escribe en A ni B."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    antes_a, antes_b = _doc(tmp_path, "alfa"), _doc(tmp_path, "beta")
    token = _previsualiza(cliente)          # alfa es la activa
    carteras.activa_set(tmp_path, "beta")    # cambiar de cartera antes de confirmar

    r = cliente.post("/api/importar/confirmar", json={"token": token},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 400
    assert any("cartera activa ha cambiado" in e.lower() for e in r.get_json()["errores"])

    # Nada se ha escrito en ninguna cartera.
    assert _doc(tmp_path, "alfa") == antes_a
    assert _doc(tmp_path, "beta") == antes_b


def test_confirmar_misma_cartera_escribe_solo_en_ella(entorno):
    """Previsualizar en A y confirmar en A → el movimiento llega únicamente a A."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    antes_b = _doc(tmp_path, "beta")
    token = _previsualiza(cliente)          # alfa es la activa
    r = cliente.post("/api/importar/confirmar", json={"token": token},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200, r.get_json()

    doc_alfa = _doc(tmp_path, "alfa")
    assert _mov_de_fondo_nuevo(doc_alfa)     # A recibió el movimiento
    assert _doc(tmp_path, "beta") == antes_b  # B no se tocó
    assert _mov_de_fondo_nuevo(_doc(tmp_path, "beta")) == []


def test_extraer_motor_calcula_ambas(entorno):
    """Tras mover un subconjunto, el motor calcula ambas carteras sin avisos."""
    from app import motor
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod2"],
                           "desde": "origen", "mover": True}, headers={"X-Rumbo": "1"})
    nueva_id = r.get_json()["cartera"]["id"]

    for cid, doc in (("origen", _doc(tmp_path, "origen")), (nueva_id, _doc(tmp_path, nueva_id))):
        datos = motor.construir(doc, tmp_path, descargar=False)
        assert datos is not None
        assert set(p["id"] for p in datos.get("productos", [])) == \
            {p["id"] for p in doc["productos"]}


# ---------------------------------------------------------------- aceptación (T-36)

CARTERA_RICA_LEGADA = {
    "version": 1, "titular": "Cartera legado rica",
    "productos": [
        {"id": "leg1", "nombre": "Producto legado", "corto": "Leg",
         "tipo": "accion", "fuente": "manual", "codigo": "AAA",
         "moneda": "EUR", "slot": 1, "largoPlazo": True}],
    "movimientos": [{"id": "ml", "fecha": "2023-01-01", "producto": "leg1",
                     "tipo": "compra", "unidades": 5, "importe": 500.0}],
    "valoraciones": [{"id": "vl", "fecha": "2023-06-01", "producto": "leg1",
                      "valor": 60.0}],
    "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True},
                   {"id": "cuarto", "nombre": "Cuartos", "pesos": {"leg1": 100}}],
    "hitos": [10000, 50000],
    "objetivo": {"activo": True, "importe": 100000, "etiqueta": "Meta"},
}


def _perm(ruta):
    """Modo (permisos) de un archivo o directorio."""
    return stat.S_IMODE(os.stat(ruta).st_mode)


def _sha(ruta):
    """Sha256 de un archivo, para comparar «idéntico» sin depender del reloj."""
    with open(ruta, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _legado_rico(tmp_path):
    """Directorio 1.1.1 completo: cartera, caché compartida, copia automática,
    estado y cálculo propio (los dos últimos son planos, como en la 1.1.1)."""
    d = str(tmp_path)
    escribe_json(os.path.join(d, "cartera.json"), CARTERA_RICA_LEGADA)
    escribe_json(os.path.join(d, "cache", "AAA.json"), {"2024-01-01": 100.0})
    escribe_json(os.path.join(d, "copias", "auto_x.json"), {"legacy": True})
    escribe_json(os.path.join(d, "estado.json"), {"preciosActualizados": "2024-01-01T00:00:00"})
    escribe_json(os.path.join(d, "calculado_propio.json"), {"legacy": True})


def test_permisos_del_layout_nuevo(entorno):
    """F-11 en el layout multicartera: carteras/ es 0700 y cada archivo que
    contiene, 0600; también cuando la carpeta nace con la migración al importar
    (antes de que `main()` pudiera aplicar el umask)."""
    servidor, tmp_path = entorno
    _legado_rico(tmp_path)
    importlib.reload(servidor)             # migra al importar: carteras/ nace aquí
    dir_carts = carteras.ruta_carteras(tmp_path)
    assert _perm(dir_carts) == 0o700
    for r in (carteras.ruta_indice(tmp_path), carteras.ruta(tmp_path, carteras.ID_DEFECTO)):
        assert _perm(r) == 0o600

    # Y también al crear una cartera desde cero (modo propio ya migrado).
    cliente = servidor.app.test_client()
    r = cliente.post("/api/carteras", json={"nombre": "Segunda", "desde": "vacia"},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    assert _perm(dir_carts) == 0o700
    assert _perm(carteras.ruta(tmp_path, r.get_json()["cartera"]["id"])) == 0o600


def test_fidelidad_de_la_migracion_rica(entorno):
    """Un directorio 1.1.1 rico migra sin pérdida: el API devuelve el mismo
    documento (==), la caché compartida y la copia del legado sobreviven, y el
    archivo heredado queda de respaldo bajo copias/."""
    servidor, tmp_path = entorno
    _legado_rico(tmp_path)
    importlib.reload(servidor)
    d = str(tmp_path)
    cliente = servidor.app.test_client()

    j = cliente.get("/api/cartera").get_json()
    assert j["modo"] == "propio"
    assert j["cartera"] == CARTERA_RICA_LEGADA          # mismo documento, == en el JSON

    # La caché es compartida: sigue en el sitio de siempre.
    assert os.path.exists(os.path.join(d, "cache", "AAA.json"))
    # La copia automática del legado se conserva tal cual.
    assert os.path.exists(os.path.join(d, "copias", "auto_x.json"))
    # Y el archivo heredado queda de respaldo bajo copias/.
    respaldos = [n for n in os.listdir(os.path.join(d, "copias"))
                 if n.startswith("migrada_") and n.endswith(".json")]
    assert respaldos
    # El original ya no está en la raíz.
    assert not os.path.exists(os.path.join(d, "cartera.json"))


def test_aislamiento_total_y_borrado(entorno):
    """Escribir en A no toca el JSON de B (idéntico a byte); borrar A tampoco
    lo toca, y A termina en copias/alfa/."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()
    r_alfa, r_beta = carteras.ruta(tmp_path, "alfa"), carteras.ruta(tmp_path, "beta")
    sha_beta_0 = _sha(r_beta)

    r = cliente.post("/api/productos",
                     json={"nombre": "Nuevo en A", "tipo": "fondo", "fuente": "manual"},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    assert _sha(r_beta) == sha_beta_0                  # B idéntico a byte

    r = cliente.delete("/api/carteras/alfa", headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    assert r.get_json()["activa"] == "beta"            # la activa pasa a B
    assert not os.path.exists(r_alfa)                  # A ya no está
    assert _sha(r_beta) == sha_beta_0                  # B sigue idéntico a byte
    # Y A quedó de respaldo bajo copias/alfa/.
    borradas = [n for n in os.listdir(os.path.join(str(tmp_path), "copias", "alfa"))
                if n.startswith("borrada_")]
    assert borradas


def test_concurrencia_mtimes_entre_carteras(entorno):
    """Dos POST /api/productos en carteras distintas, en secuencia: cada
    petición toca solo el archivo de su cartera (los mtimes no cruzan)."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()
    h = {"X-Rumbo": "1"}
    r_alfa, r_beta = carteras.ruta(tmp_path, "alfa"), carteras.ruta(tmp_path, "beta")
    t0 = 1_700_000_000.0                               # mtime viejo conocido
    os.utime(r_alfa, (t0, t0))
    os.utime(r_beta, (t0, t0))

    r = cliente.post("/api/productos",
                     json={"nombre": "En A", "tipo": "fondo", "fuente": "manual"}, headers=h)
    assert r.status_code == 200
    m_alfa = os.path.getmtime(r_alfa)
    assert m_alfa > t0                                 # A sí se tocó
    assert os.path.getmtime(r_beta) == t0              # B no se tocó

    carteras.activa_set(tmp_path, "beta")
    r = cliente.post("/api/productos",
                     json={"nombre": "En B", "tipo": "fondo", "fuente": "manual"}, headers=h)
    assert r.status_code == 200
    assert os.path.getmtime(r_beta) > t0               # B se tocó
    assert os.path.getmtime(r_alfa) == m_alfa          # A no volvió a tocarse


def test_idempotencia_de_la_migracion(entorno):
    """Recargar el servidor tres veces sobre un directorio ya migrado no
    cambia el índice ni el documento (comparado por suma de comprobación)."""
    servidor, tmp_path = entorno
    _legado_rico(tmp_path)
    importlib.reload(servidor)
    suma_indice = _sha(carteras.ruta_indice(tmp_path))
    suma_doc = _sha(carteras.ruta(tmp_path, carteras.ID_DEFECTO))
    for _ in range(3):
        importlib.reload(servidor)
        assert _sha(carteras.ruta_indice(tmp_path)) == suma_indice
        assert _sha(carteras.ruta(tmp_path, carteras.ID_DEFECTO)) == suma_doc


def test_instalacion_fresca_no_crea_nada(entorno):
    """En una carpeta vacía la app queda en modo demo y no crea ni un archivo
    ni un directorio: sin datos propios, sin efectos en el disco."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    assert cliente.get("/api/cartera").get_json()["modo"] == "demo"
    assert list(os.listdir(str(tmp_path))) == []


def _datos_de_respuesta(texto):
    """El objeto asignado a `window.DATOS` en el texto de /datos.js."""
    m = re.search(r"window\.DATOS = (\{.*\});\s*$", texto.strip(), re.S)
    assert m, texto[:120]
    return json.loads(m.group(1))


def test_datos_js_con_cartera_de_url(entorno):
    """Dos pestañas independientes: /datos.js?cartera=otra sirve los datos de
    esa cartera. Id inválido o inexistente -> la activa, sin error."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    # Sin parámetro: la activa (alfa)
    j = _datos_de_respuesta(cliente.get("/datos.js").get_data(as_text=True))
    assert j["titular"] == "Cartera A"

    # La otra cartera por URL: los DATOS son los de beta
    j = _datos_de_respuesta(cliente.get("/datos.js?cartera=beta").get_data(as_text=True))
    assert j["titular"] == "Cartera B"
    assert j["productos"][0]["id"] == "prod_b"

    # Id inválido (mayúsculas) o inexistente -> la activa, sin error
    for mal in ("BETA", "no_existe"):
        r = cliente.get("/datos.js?cartera=" + mal)
        assert r.status_code == 200
        assert _datos_de_respuesta(r.get_data(as_text=True))["titular"] == "Cartera A"
