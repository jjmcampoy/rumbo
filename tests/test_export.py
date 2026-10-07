# -*- coding: utf-8 -*-
"""Pruebas de la exportación estática (app/exportar.py)."""
import os
import shutil

import pytest

from app import exportar

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "web")

DATOS_MINIMOS = {
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


def test_pagina_incluye_datos_y_scripts():
    html = exportar.pagina(WEB, DATOS_MINIMOS)
    assert "window.DATOS =" in html
    assert "window.ESTATICO = true;" in html
    for nombre in ("canal.js", "graficos.js", "app.js"):
        with open(os.path.join(WEB, nombre), encoding="utf-8") as f:
            contenido = f.read()
        # El contenido del script debe aparecer (con </script> escapado).
        assert contenido.replace("</script>", "<\\/script>") in html
    # El cargador ya no va en linea: no queda ninguna referencia a cargador.js.
    assert "cargador.js" not in html


def test_pagina_incluye_icono_base64():
    html = exportar.pagina(WEB, DATOS_MINIMOS)
    assert 'src="icono-64.png"' not in html
    assert "data:image/png;base64" in html


def test_pagina_sin_cargador_lanza_error(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    for nombre in ("icono-64.png", "canal.js", "graficos.js", "app.js"):
        shutil.copy(os.path.join(WEB, nombre), web / nombre)
    (web / "index.html").write_text("<html><body></body></html>", encoding="utf-8")
    with pytest.raises(RuntimeError):
        exportar.pagina(str(web), DATOS_MINIMOS)


def test_el_nombre_de_la_cartera_no_inyecta_html():
    """F-02: el titular es editable («Renombrar») y acaba en el `og:title` del
    export, que es la página que el usuario publica. Debe ir escapado."""
    malo = 'P"><script>alert(1)</script>'
    html = exportar.pagina(WEB, DATOS_MINIMOS, titulo=malo)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # Un nombre normal sigue saliendo tal cual.
    normal = exportar.pagina(WEB, DATOS_MINIMOS, titulo="Mi patrimonio")
    assert 'content="Mi patrimonio · Rumbo"' in normal
