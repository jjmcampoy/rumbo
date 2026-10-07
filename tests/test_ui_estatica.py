# -*- coding: utf-8 -*-
"""Guardias baratas de la UI multi‑cartera (T-34), sin navegador."""
import os
import re

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "web")


def test_marcado_ui():
    html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
    assert 'id="selCartera"' in html
    editor = open(os.path.join(WEB, "editor.js"), encoding="utf-8").read()
    for aguja in ("api/carteras", "carteras/extraer", "activar", "__nueva__"):
        assert aguja in editor, aguja
    # la llamada real: una sola cuerda o un comentario no pueden satisfacerla
    assert 'api("GET", "api/carteras/resumen?series=1")' in editor


def test_estatico_no_muestra_selector():
    # la exportación quita la pestaña de datos y el editor; el selector debe seguir oculto
    html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
    sel = next(l for l in html.splitlines() if 'id="selCartera"' in l)
    assert "hidden" in sel, sel


def test_contenedor_grafico_comparar():
    # el grafico de la evolucion conjunta (T-50) necesita .envGraf: el tooltip
    # (.gtt) va en position:absolute y solo se ancla con .envGraf{position:relative}
    editor = open(os.path.join(WEB, "editor.js"), encoding="utf-8").read()
    assert 'id="grafComparar" class="envGraf"' in editor


def test_selectores_con_elemento():
    """Cada `$("#id")` del editor tiene que tener su `id="…"` en algún sitio.

    T-34 dejó los tres campos del formulario de carteras con `name=` pero sin
    `id=`, así que sus handlers leían cadena vacía: el formulario pedía el
    nombre aunque estuviera escrito, y el selector de origen se ignoraba
    (creaba una cartera vacía). El fallo era invisible para el resto de la
    suite, que llama a la API directamente.
    """
    editor = open(os.path.join(WEB, "editor.js"), encoding="utf-8").read()
    todos = editor
    for fichero in ("index.html", "app.js"):
        todos += open(os.path.join(WEB, fichero), encoding="utf-8").read()
    declarados = set(re.findall(r'id="([A-Za-z0-9_-]+)"', todos))
    usados = set(re.findall(r"""\$\(\s*["']#([A-Za-z0-9_-]+)["']""", editor))
    faltan = sorted(usados - declarados)
    assert not faltan, "selectores sin elemento: %s" % faltan
