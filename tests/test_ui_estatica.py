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


def test_pill_activa_distinta_de_la_tarjeta():
    """La pill activa de `.segm` no debe pintarse con el color de la tarjeta.

    El fondo de la tarjeta es `--sup`; si el botón seleccionado usa el mismo
    token, la opción activa luce igual que la tarjeta de fondo y parece un
    hueco vacío (y las no seleccionadas parecen las rellenas). La regla debe
    usar otro tono (por ejemplo `--sup3`) para que quede claro cuál está activo.
    """
    html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
    regla = re.search(r"""\.segm button\[aria-pressed="true"\]\{[^}]*\}""", html)
    assert regla, "no se encuentra la regla de la pill activa"
    tok = re.search(r"background:\s*var\((--[a-z0-9]+)\)", regla.group(0))
    assert tok, "la regla de la pill activa no declara background:var(--…)"
    assert tok.group(1) != "--sup", (
        "la opción seleccionada se pinta con el color de la tarjeta (--sup)")
