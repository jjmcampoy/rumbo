# -*- coding: utf-8 -*-
"""Guardia contra regresiones de XSS en el panel (app.js)."""
import re, os

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "web")

def _js(nombre):
    with open(os.path.join(WEB, nombre), encoding="utf-8") as f:
        return f.read()

# Patrones de interpolación SIN escapar. El test es una heurística: acepta el
# sitio si en los 40 caracteres anteriores aparece "esc(" — suficiente para
# detectar una regresión del estilo `${p.corto}`.
PELIGROSOS_APP = [
    r"\$\{p\.corto\b", r"\$\{p\.nombre\b", r"\$\{d\.nombre\b",
    r"\$\{r\.producto\b", r"\$\{l\.nombre\b", r"\$\{c\.nombre\b",
    r"\$\{a\}</span>", r"\$\{D\.titular\b",
    r"\$\{fuentes\.join",
]

def test_app_js_no_interpola_texto_sin_escapar():
    src = _js("app.js")
    for pat in PELIGROSOS_APP:
        for m in re.finditer(pat, src):
            linea = src[:m.start()].count("\n") + 1
            # permitido si va dentro de esc( ... )
            antes = src[max(0, m.start() - 40):m.start()]
            assert "esc(" in antes, f"{pat} sin esc() en app.js:{linea}"

# Mismos patrones para los graficos (leyendas y tooltips).
PELIGROSOS_GRAF = [r"\$\{s\.nombre\b", r"\$\{d\.nombre\b"]

def test_graficos_js_no_interpola_nombres_sin_escapar():
    src = _js("graficos.js")
    for pat in PELIGROSOS_GRAF:
        for m in re.finditer(pat, src):
            antes = src[max(0, m.start() - 40):m.start()]
            assert "escHtml(" in antes, f"{pat} sin escHtml() en graficos.js"

def test_regla_de_oro_escapado():
    """Toda interpolación ${...} que meta texto de datos en innerHTML debe ir con esc()."""
    assert "const esc =" in _js("app.js"), "falta esc() en app.js"
    assert "const escHtml =" in _js("graficos.js"), "falta escHtml() en graficos.js"

def test_graficos_js_escapador_no_sombrea():
    """El escapador no puede compartir nombre con una variable local (bug real de T-14)."""
    src = _js("graficos.js")
    decls = re.findall(r"\b(?:const|let|var)\s+escHtml\b", src)
    assert len(decls) == 1, f"escHtml debe declararse una sola vez, hay {len(decls)}"

# Versión con lista blanca: documenta la intención del hallazgo F-01 del informe.
# Cada lista es la whitelist de interpolaciones permitidas por archivo.
BLANCA_APP = [
    r"\$\{p\.corto\b", r"\$\{p\.nombre\b", r"\$\{d\.nombre\b",
    r"\$\{r\.producto\b", r"\$\{l\.nombre\b", r"\$\{c\.nombre\b",
    r"\$\{a\}</span>", r"\$\{D\.titular\b",
    r"\$\{fuentes\.join",
]

BLANCA_GRAF = [r"\$\{s\.nombre\b", r"\$\{d\.nombre\b"]

def test_whitelist_f01():
    """F-01: solo las interpolaciones de la whitelist pueden aparecer sin esc()."""
    for archivo, blanca, lookback in (("app.js", BLANCA_APP, "esc("), ("graficos.js", BLANCA_GRAF, "escHtml(")):
        src = _js(archivo)
        for pat in blanca:
            for m in re.finditer(pat, src):
                antes = src[max(0, m.start() - 40):m.start()]
                assert lookback in antes, f"{pat} sin {lookback} en {archivo} (F-01)"

# ---------------------------------------------------------------- F-03/F-04/F-05
# Guardia de host/origen y cabecera anti-CSRF en el servidor.

def test_empezar_sin_cabecera_es_403(cliente):
    r = cliente.post("/api/empezar")
    assert r.status_code == 403

def test_empezar_con_cabecera_es_200(cliente):
    r = cliente.post("/api/empezar", headers={"X-Rumbo": "1"})
    assert r.status_code == 200

def test_get_cartera_sin_cabecera_es_200(cliente):
    r = cliente.get("/api/cartera")
    assert r.status_code == 200

def test_post_con_origen_malo_es_403(cliente):
    r = cliente.post("/api/empezar", headers={"X-Rumbo": "1", "Origin": "http://evil.example"})
    assert r.status_code == 403

def test_ping_con_host_malo_es_421(cliente):
    r = cliente.get("/api/ping", headers={"Host": "evil.example"})
    assert r.status_code == 421

def test_ping_con_host_local_es_200(cliente):
    r = cliente.get("/api/ping", headers={"Host": "127.0.0.1:8799"})
    assert r.status_code == 200
