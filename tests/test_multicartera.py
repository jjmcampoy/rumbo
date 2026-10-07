# -*- coding: utf-8 -*-
"""Pruebas de multicartera: migración transparente, activación y aislamiento.

Cada cartera tiene su propio `carteras/<cid>.json`; el motor, el estado y los
historicos van a rutas que dependen del `cid` activo.
"""
import importlib
import json
import os

from app import carteras
from tests.conftest import cartera_en_disco, cartera_en_disco_v2

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
    assert set(j["carteras"][0]) == {"id", "nombre", "creada", "activa"}   # solo metadata

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
