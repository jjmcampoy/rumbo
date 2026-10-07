# -*- coding: utf-8 -*-
"""Guardias baratas de la UI multi‑cartera (T-34), sin navegador."""
import os

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "web")


def test_marcado_ui():
    html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
    assert 'id="selCartera"' in html
    editor = open(os.path.join(WEB, "editor.js"), encoding="utf-8").read()
    for aguja in ("api/carteras", "carteras/extraer", "activar", "__nueva__"):
        assert aguja in editor, aguja
    # la llamada real: una sola cuerda o un comentario no pueden satisfacerla
    assert 'api("GET", "api/carteras/resumen")' in editor


def test_estatico_no_muestra_selector():
    # la exportación quita la pestaña de datos y el editor; el selector debe seguir oculto
    html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
    sel = next(l for l in html.splitlines() if 'id="selCartera"' in l)
    assert "hidden" in sel, sel
