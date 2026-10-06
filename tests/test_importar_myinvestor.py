# -*- coding: utf-8 -*-
"""
Pruebas del importador de MyInvestor (fase 1B).

Los tests marcados con xfail(strict=True) documentan los defectos que I-02 e
I-03 deben corregir: cuando la corrección llegue y se retire la marca, deben
pasar. Los tests que pasan hoy fijan el comportamiento que no debe cambiar.
"""
import pytest

from app import importar, motor

HOY = motor.hoy().isoformat()
VL_HOY = 40.0
CABECERA = "Fecha fiscal;Inversión;Valor de mercado;Resultado fiscal\n"

# Fila real del extracto del usuario, tal cual (ancla la suite a datos reales).
EXTRACTO_REAL = ("Fecha fiscal;Inversión;Valor de mercado;Resultado fiscal\n"
                 "04/05/2022;3941,89;5302,33;1360,44\n")
INVERTIDO, VALOR, RESULTADO = 3941.89, 5302.33, 1360.44


def serie(pares):
    """{fecha_iso: VL} con el VL de hoy añadido."""
    d = dict(pares)
    d[HOY] = VL_HOY
    return d


def csv(*filas):
    """Extracto con la cabecera real y las filas indicadas."""
    return CABECERA + "".join(";".join(str(v) for v in f) + "\n" for f in filas)


def lote(fecha_iso, invertido, valor, resultado=""):
    """Una fila del extracto con formato español (dd/mm/aaaa y 1.234,56)."""
    d, m, a = fecha_iso[8:10], fecha_iso[5:7], fecha_iso[:4]
    def eur(x):
        return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return [f"{d}/{m}/{a}", eur(invertido), eur(valor), eur(resultado) if resultado != "" else ""]


def importar_lote(texto, serie_vl):
    """Corta el extracto y devuelve (movs, sin_vl) de myinvestor_a_movimientos."""
    lotes, reembolsos = importar.leer_csv_myinvestor(texto)
    return importar.myinvestor_a_movimientos("fondo", lotes, reembolsos, serie_vl)


# ---------------------------------------------------------------- lectura

def test_lee_csv_basico():
    """El extracto real se lee ya: una compra, sin reembolsos."""
    lotes, reembolsos = importar.leer_csv_myinvestor(EXTRACTO_REAL)
    assert lotes == [["2022-05-04", INVERTIDO, VALOR]]
    assert reembolsos == []


def test_resultado_fiscal_no_es_un_reembolso():
    """Guarda de regresión: con Resultado fiscal != 0 la fila es una COMPRA."""
    lotes, reembolsos = importar.leer_csv_myinvestor(EXTRACTO_REAL)
    assert reembolsos == []
    assert lotes and lotes[0][0] == "2022-05-04"
    # Identidad de la fila real: si MyInvestor cambia el sentido de la columna,
    # esta igualdad deja de cumplirse y la prueba lo dice.
    assert abs((VALOR - INVERTIDO) - RESULTADO) < 0.01


def test_reembolso_cero_cero():
    """
    Forma aún no observada en un archivo real (ver paso 4 de I-01): una fila
    0,00;0,00 con resultado fiscal se lee como reembolso. Documenta la única
    forma que el código actual reconoce.
    """
    lotes, reembolsos = importar.leer_csv_myinvestor(csv(lote("2022-05-04", 0.0, 0.0, 123.45)))
    assert lotes == []
    assert reembolsos == [["2022-05-04", 123.45]]


# ---------------------------------------------------------------- unidades

def test_fila_real_coherente():
    """
    Fila real con una serie VL coherente: unidades = coste / VL de compra.
    Pasa hoy: con datos coherentes la fórmula actual ya es correcta. La etiqueta
    "(xfail I-02)" del paquete es un error de plan: una serie coherente es
    correcta bajo la fórmula actual, así que esta prueba no se marca.
    """
    vl_fecha = 20.0
    vl_hoy = 20.0 * VALOR / INVERTIDO          # 26.9025...
    serie_vl = {"2022-05-04": vl_fecha, HOY: vl_hoy}
    movs, _ = importar_lote(EXTRACTO_REAL, serie_vl)
    assert len(movs) == 1
    assert movs[0]["unidades"] == pytest.approx(INVERTIDO / 20.0)
    assert movs[0]["unidades"] * serie_vl[HOY] == pytest.approx(VALOR, rel=1e-6)
    assert _reconciliacion(movs, serie_vl)["sospechosos"] == 0


@pytest.mark.xfail(strict=True, reason="I-02")
def test_fila_real_traspaso():
    """
    Caso central del informe de fallo: el VL de la fecha fiscal corresponde al
    fondo de ORIGEN (traspaso), no al destino. Las unidades deben salir del
    valor de mercado, no del coste.
    """
    vl_fecha, vl_hoy = 20.0, 40.0
    movs, _ = importar_lote(EXTRACTO_REAL, serie({"2022-05-04": vl_fecha}))
    assert movs[0]["unidades"] == pytest.approx(VALOR / 40.0)
    assert movs[0]["unidades"] * vl_hoy == pytest.approx(VALOR, rel=1e-6)
    assert _reconciliacion(movs, serie({"2022-05-04": vl_fecha}))["sospechosos"] == 1
    # Documentación del bug: la fórmula antigua (coste / VL de origen) daba
    # 3941.89 / 20.0 * 40.0 = 7883.78 €, un 48.69 % por encima del valor real.
    antiguo = (INVERTIDO / vl_fecha) * vl_hoy
    assert antiguo == pytest.approx(7883.78, abs=0.01)
    assert (antiguo - VALOR) / VALOR == pytest.approx(0.4869, abs=0.001)


@pytest.mark.xfail(strict=True, reason="I-03")
def test_fecha_iso():
    """Una fecha ya en ISO (aaaa-mm-dd) debe leerse; hoy se descarta en silencio."""
    texto = CABECERA + f"2020-01-15;100,00;120,00;\n"
    lotes, _ = importar.leer_csv_myinvestor(texto)
    assert lotes == [["2020-01-15", 100.0, 120.0]]


@pytest.mark.xfail(strict=True, reason="I-02")
def test_lote_traspaso_valor_correcto():
    """
    Caso sintético I-A de la tabla de auditoría: el valor de mercado manda, no
    el coste. Con coste 10.000, valor 24.000, VL de destino 18,00 el 2019-03-01
    y 40,00 hoy, las unidades correctas son 24.000 / 40 = 600; la fórmula
    actual da 10.000 / 18 = 555,56 (valor 22.222,22 €, -7,41 %).
    """
    texto = csv(lote("2019-03-01", 10000.0, 24000.0))
    serie_vl = {"2019-03-01": 18.0, HOY: 40.0}
    movs, _ = importar_lote(texto, serie_vl)
    assert movs[0]["unidades"] == pytest.approx(600.0)
    assert movs[0]["unidades"] * 40.0 == pytest.approx(24000.0)


@pytest.mark.xfail(strict=True, reason="I-02/I-03")
def test_lote_sabado():
    """Lote fechado en sábado con VL del viernes: unidades > 0 y total coherente."""
    # 2022-05-07 es sábado; el VL disponible es el del viernes 2022-05-06.
    texto = csv(lote("2022-05-07", 1000.0, 1050.0))
    movs, _ = importar_lote(texto, serie({"2022-05-06": 20.0}))
    assert movs[0]["unidades"] > 0
    assert movs[0]["unidades"] * VL_HOY == pytest.approx(1050.0, rel=0.01)


@pytest.mark.xfail(strict=True, reason="I-02")
def test_invariante_reconciliacion():
    """Para cada fixture: Σ importe == Σ inversión y el total valorado cuadra."""
    fixtures = [
        (EXTRACTO_REAL, serie({"2022-05-04": 20.0})),
        (csv(lote("2022-05-04", 12000.0, 24000.0)), serie({"2022-05-04": 20.0})),
        (csv(lote("2022-05-07", 1000.0, 1050.0)), serie({"2022-05-06": 20.0})),
    ]
    for texto, serie_vl in fixtures:
        movs, _ = importar_lote(texto, serie_vl)
        r = _reconciliacion(movs, serie_vl)
        assert r["sospechosos"] == 0


@pytest.mark.xfail(strict=True, reason="I-02")
def test_lote_con_valor_cero_e_inversion_positiva():
    """Inversión > 0 y Valor de mercado = 0: no debe inventar participaciones."""
    texto = csv(lote("2022-05-04", 500.0, 0.0))
    movs, _ = importar_lote(texto, serie({"2022-05-04": 20.0}))
    compras = [m for m in movs if m["tipo"] == "compra"]
    assert all(m["unidades"] == 0 for m in compras)


def test_dos_lotes_coherentes_sin_cambios():
    """Un archivo limpio de dos lotes ya cuadra al céntimo: no regredar."""
    texto = csv(lote("2022-01-03", 1000.0, 1100.0), lote("2022-06-06", 2000.0, 2200.0))
    serie_vl = serie({"2022-01-03": 10.0, "2022-06-06": 11.0})
    movs, _ = importar_lote(texto, serie_vl)
    assert len(movs) == 2
    assert _reconciliacion(movs, serie_vl)["sospechosos"] == 0


def test_sin_vl_actual():
    """Sin serie VL y sin valor de mercado usable: 0 unidades y aviso, sin excepción."""
    texto = csv(lote("2022-05-04", 1000.0, 0.0))
    movs, sin_vl = importar_lote(texto, {})
    assert movs[0]["unidades"] == 0
    assert sin_vl == 1


# ---------------------------------------------------------------- ayuda

def _reconciliacion(movs, serie_vl):
    """
    Reconciliación de los movimientos contra el extracto: un lote es
    'sospechoso' si su valor actual (unidades × VL de hoy) se desvía más del
    1 % del valor de mercado del extracto.
    """
    compras = [m for m in movs if m["tipo"] == "compra"]
    sospechosos = 0
    for m in compras:
        vl = motor.valor_en(serie_vl, m["fecha"]) or VL_HOY
        valor_esperado = m["unidades"] * vl
        if m["importe"] and abs(valor_esperado - m["importe"]) / m["importe"] > 0.01:
            sospechosos += 1
    return {"sospechosos": sospechosos}
