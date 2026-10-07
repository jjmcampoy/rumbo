# -*- coding: utf-8 -*-
"""Pruebas de multicartera: migración transparente, activación y aislamiento.

Cada cartera tiene su propio `carteras/<cid>.json`; el motor, el estado y los
historicos van a rutas que dependen del `cid` activo.
"""
import importlib
import json
import os

from app import carteras
from tests.conftest import cartera_en_disco

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
