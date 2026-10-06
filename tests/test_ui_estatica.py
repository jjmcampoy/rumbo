# -*- coding: utf-8 -*-
"""
test_ui_estatica.py  ·  Guardas baratas de la interfaz (sin navegador)
=====================================================================
Comprueban que el selector de cartera existe en el HTML, que editor.js
habla con la API de carteras, y que la exportación estática no lo muestra.
"""

import copy
import os

from app import exportar

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "web")


def _lee(nombre):
    with open(os.path.join(WEB, nombre), encoding="utf-8") as f:
        return f.read()


def test_marcado_ui():
    html = _lee("index.html")
    assert 'id="selCartera"' in html
    editor = _lee("editor.js")
    for aguja in ("api/carteras", "carteras/extraer", "activar", "__nueva__"):
        assert aguja in editor, aguja
    assert "api/carteras/resumen" in editor


def test_selector_oculto_en_el_html():
    # El selector nace con hidden: sin editor.js (exportación estática) no se ve.
    html = _lee("index.html")
    assert '<select id="selCartera" class="selCartera" hidden' in html


def test_estatico_no_muestra_selector():
    # La exportación quita la pestaña de datos y el editor; el selector debe seguir oculto.
    datos = {"modo": "propio", "avisos": [], "vivo": None, "total": {}, "fechaExtracto": "2024-01-01"}
    html = exportar.pagina(WEB, datos)
    assert 'id="selCartera"' in html
    assert 'class="selCartera" hidden' in html
    # editor.js no va en la exportación: nadie puede quitarle el hidden.
    assert 'src="editor.js"' not in html


def test_extraer_no_toma_la_cartera_de_la_respuesta():
    # POST /api/carteras/extraer devuelve metadatos, no el documento: el editor
    # debe recargar en vez de asignar E.cfg (si no, E.cfg.productos sería un número).
    editor = _lee("editor.js")
    cuerpo = editor[editor.index("async function extraerCartera"):editor.index("copias y web")]
    assert "E.cfg =" not in cuerpo
    assert "location.reload()" in cuerpo


def test_catalogo_cuenta_productos_sin_documento(cliente, entorno):
    """Cada entrada del catálogo trae el número de productos, nunca el documento."""
    from tests.conftest import CARTERA_MINIMA, escribe_json

    _, tmp_path = entorno
    a = copy.deepcopy(CARTERA_MINIMA)          # 1 producto
    b = copy.deepcopy(CARTERA_MINIMA)          # 2 productos
    b["productos"].append({"id": "bono", "nombre": "Bono Prueba", "corto": "Bono",
                           "tipo": "bono", "fuente": "yahoo", "codigo": "BBB",
                           "moneda": "EUR", "slot": 2, "largoPlazo": True})
    escribe_json(os.path.join(tmp_path, "carteras", "a.json"), a)
    escribe_json(os.path.join(tmp_path, "carteras", "b.json"), b)
    escribe_json(os.path.join(tmp_path, "carteras", "indice.json"),
                 {"version": 1, "activa": "a",
                  "carteras": [{"id": "a", "nombre": "Cartera A", "creada": "2024-01-01T00:00:00"},
                               {"id": "b", "nombre": "Cartera B", "creada": "2024-01-01T00:00:00"}]})

    cuerpo = cliente.get("/api/carteras").get_json()
    assert [c["productos"] for c in cuerpo["carteras"]] == [1, 2]
    for c in cuerpo["carteras"]:
        assert "movimientos" not in c and "titular" not in c

    # El catálogo de POST (copia de la cartera de 2 productos) y de DELETE también cuenta.
    r = cliente.post("/api/carteras", json={"nombre": "Copia", "desde": "b"},
                     headers={"X-Rumbo": "1"})
    nuevo = r.get_json()
    assert nuevo["cartera"]["productos"] == 2
    assert [c["productos"] for c in nuevo["carteras"]] == [1, 2, 2]
    r = cliente.delete(f"/api/carteras/{nuevo['cartera']['id']}", headers={"X-Rumbo": "1"})
    assert [c["productos"] for c in r.get_json()["carteras"]] == [1, 2]
