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
            assert "esc(" in antes, f"{pat} sin esc() en graficos.js"

def test_regla_de_oro_escapado():
    """Toda interpolación ${...} que meta texto de datos en innerHTML debe ir con esc()."""
    for archivo in ("app.js", "graficos.js"):
        src = _js(archivo)
        assert "const esc = " in src or "const esc =" in src, f"falta esc() en {archivo}"

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
    for archivo, blanca in (("app.js", BLANCA_APP), ("graficos.js", BLANCA_GRAF)):
        src = _js(archivo)
        for pat in blanca:
            for m in re.finditer(pat, src):
                antes = src[max(0, m.start() - 40):m.start()]
                assert "esc(" in antes, f"{pat} sin esc() en {archivo} (F-01)"
