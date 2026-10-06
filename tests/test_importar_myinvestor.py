# -*- coding: utf-8 -*-
"""
Pruebas del importador de MyInvestor (fase 1B).

Los tests marcados con xfail(strict=True) documentan los defectos que I-02 e
I-03 deben corregir: cuando la corrección llegue y se retire la marca, deben
pasar. Los tests que pasan hoy fijan el comportamiento que no debe cambiar.
"""
import copy
import os
import re

import pytest

from app import almacen, importar, motor
from tests.conftest import escribe_cache

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
    """Corta el extracto y devuelve (movs, avisos, reconciliacion) de myinvestor_a_movimientos."""
    lotes, reembolsos, _ = importar.leer_csv_myinvestor(texto)
    return importar.myinvestor_a_movimientos("fondo", lotes, reembolsos, serie_vl)


# ---------------------------------------------------------------- lectura

def test_lee_csv_basico():
    """El extracto real se lee ya: una compra, sin reembolsos."""
    lotes, reembolsos, sin_fecha = importar.leer_csv_myinvestor(EXTRACTO_REAL)
    assert lotes == [["2022-05-04", INVERTIDO, VALOR]]
    assert reembolsos == []
    assert sin_fecha == []


def test_resultado_fiscal_no_es_un_reembolso():
    """Guarda de regresión: con Resultado fiscal != 0 la fila es una COMPRA."""
    lotes, reembolsos, _ = importar.leer_csv_myinvestor(EXTRACTO_REAL)
    assert reembolsos == []
    assert lotes and lotes[0][0] == "2022-05-04"
    # Identidad de la fila real: si MyInvestor cambia el sentido de la columna,
    # esta igualdad deja de cumplirse y la prueba lo dice.
    assert abs((VALOR - INVERTIDO) - RESULTADO) < 0.01


def test_reembolso_cero_cero():
    """
    Rama de reembolso que el código reconoce: una fila 0,00;0,00 con un
    Resultado fiscal distinto de cero se lee como reembolso. Esta forma NO se ha
    observado en el extracto real del usuario: sus únicas filas a cero traen las
    tres columnas a cero (`14/03/2022;0;0;0`) y se ignoran (prueba siguiente).
    """
    lotes, reembolsos, _ = importar.leer_csv_myinvestor(csv(lote("2022-05-04", 0.0, 0.0, 123.45)))
    assert lotes == []
    assert reembolsos == [["2022-05-04", 123.45]]


def test_fila_real_todo_cero_se_ignora():
    """
    Fila real del extracto del usuario, tal cual: `14/03/2022;0;0;0`. Con
    Inversión, Valor de mercado Y Resultado fiscal a cero no hay lote, no hay
    reembolso y no es un error de fecha: se ignora en silencio (hoy cae porque
    `num_es("0")` es falso) y no genera ningún movimiento.
    """
    texto = CABECERA + "14/03/2022;0;0;0\n"
    lotes, reembolsos, sin_fecha = importar.leer_csv_myinvestor(texto)
    assert lotes == []
    assert reembolsos == []
    assert sin_fecha == []
    movs, avisos, recon = importar.myinvestor_a_movimientos(
        "fondo", lotes, reembolsos, serie({"2022-05-04": 20.0}))
    assert movs == []
    assert recon["plusvaliasRealizadas"] == {"n": 0, "importe": 0.0, "desde": None, "hasta": None}
    assert not any("plusvalías ya realizadas" in a for a in avisos)


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
    movs, _, recon = importar_lote(EXTRACTO_REAL, serie_vl)
    assert len(movs) == 1
    assert movs[0]["unidades"] == pytest.approx(INVERTIDO / 20.0)
    assert movs[0]["unidades"] * serie_vl[HOY] == pytest.approx(VALOR, rel=1e-6)
    assert recon["sospechosos"] == 0


def test_fila_real_traspaso():
    """
    Caso central del informe de fallo: el VL de la fecha fiscal corresponde al
    fondo de ORIGEN (traspaso), no al destino. Las unidades deben salir del
    valor de mercado, no del coste.
    """
    vl_fecha, vl_hoy = 20.0, 40.0
    movs, _, recon = importar_lote(EXTRACTO_REAL, serie({"2022-05-04": vl_fecha}))
    assert movs[0]["unidades"] == pytest.approx(VALOR / 40.0)
    assert movs[0]["unidades"] * vl_hoy == pytest.approx(VALOR, rel=1e-6)
    assert recon["sospechosos"] == 1
    # Documentación del bug: la fórmula antigua (coste / VL de origen) daba
    # 3941.89 / 20.0 * 40.0 = 7883.78 €, un 48.69 % por encima del valor real.
    antiguo = (INVERTIDO / vl_fecha) * vl_hoy
    assert antiguo == pytest.approx(7883.78, abs=0.01)
    assert (antiguo - VALOR) / VALOR == pytest.approx(0.4869, abs=0.001)


def test_fecha_iso():
    """Una fecha ya en ISO (aaaa-mm-dd) debe leerse; antes se descartaba en silencio."""
    texto = CABECERA + f"2020-01-15;100,00;120,00;\n"
    lotes, _, sin_fecha = importar.leer_csv_myinvestor(texto)
    assert lotes == [["2020-01-15", 100.0, 120.0]]
    assert sin_fecha == []


def test_lote_traspaso_valor_correcto():
    """
    Caso sintético I-A de la tabla de auditoría: el valor de mercado manda, no
    el coste. Con coste 10.000, valor 24.000, VL de destino 18,00 el 2019-03-01
    y 40,00 hoy, las unidades correctas son 24.000 / 40 = 600; la fórmula
    actual da 10.000 / 18 = 555,56 (valor 22.222,22 €, -7,41 %).
    """
    texto = csv(lote("2019-03-01", 10000.0, 24000.0))
    serie_vl = {"2019-03-01": 18.0, HOY: 40.0}
    movs, _, recon = importar_lote(texto, serie_vl)
    assert movs[0]["unidades"] == pytest.approx(600.0)
    assert movs[0]["unidades"] * 40.0 == pytest.approx(24000.0)
    assert recon["valorCalculado"] == pytest.approx(24000.0, rel=0.01)


def test_lote_sabado():
    """Lote fechado en sábado con VL del viernes: unidades > 0 y total coherente."""
    # 2022-05-07 es sábado; el VL disponible es el del viernes 2022-05-06.
    texto = csv(lote("2022-05-07", 1000.0, 1050.0))
    movs, _, _ = importar_lote(texto, serie({"2022-05-06": 20.0}))
    assert movs[0]["unidades"] > 0
    assert movs[0]["unidades"] * VL_HOY == pytest.approx(1050.0, rel=0.01)


def test_invariante_reconciliacion():
    fixtures = [
        (EXTRACTO_REAL, {"2022-05-04": 20.0, HOY: 40.0}),
        (csv(lote("2019-03-01", 10000.0, 24000.0)), {"2019-03-01": 18.0, HOY: 40.0}),
        (csv(lote("2022-05-07", 1000.0, 1050.0)), {"2022-05-06": 20.0, HOY: 40.0}),
    ]
    for texto, serie_vl in fixtures:
        lotes, _, _ = importar.leer_csv_myinvestor(texto)
        invertido = sum(l[1] for l in lotes)
        valor = sum(l[2] for l in lotes)
        movs, _, recon = importar_lote(texto, serie_vl)
        compras = [m for m in movs if m["tipo"] == "compra"]
        assert sum(m["importe"] for m in compras) == pytest.approx(invertido)
        calculado = sum(m["unidades"] for m in compras) * serie_vl[HOY]
        assert abs(calculado - valor) / valor <= 0.01
        assert recon["valorCalculado"] == pytest.approx(valor, rel=0.01)


def test_lote_con_valor_cero_e_inversion_positiva():
    """Inversión > 0 y Valor de mercado = 0: no debe inventar participaciones."""
    texto = csv(lote("2022-05-04", 500.0, 0.0))
    movs, avisos, _ = importar_lote(texto, serie({"2022-05-04": 20.0}))
    compras = [m for m in movs if m["tipo"] == "compra"]
    assert all(m["unidades"] == 0 for m in compras)
    assert any("sin valor de mercado" in a for a in avisos)


def test_dos_lotes_coherentes_sin_cambios():
    """Un archivo limpio de dos lotes ya cuadra al céntimo: no regredar."""
    # VL coherente con el extracto: 10,00 en la fecha de cada compra y 11,00 hoy.
    # Coste/NAV y valor/NAV coinciden en los dos lotes (100 y 200 participaciones).
    texto = csv(lote("2022-01-03", 1000.0, 1100.0), lote("2022-06-06", 2000.0, 2200.0))
    serie_vl = {"2022-01-03": 10.0, "2022-06-06": 10.0, HOY: 11.0}
    movs, _, recon = importar_lote(texto, serie_vl)
    assert len(movs) == 2
    assert recon["sospechosos"] == 0
    assert recon["valorCalculado"] == pytest.approx(3300.0)


def test_sin_vl_actual():
    """
    Inversión > 0 y Valor de mercado = 0 sin serie VL: la fila se trata como
    reembolso (lote que ya no se tiene) y, por la decisión de I-08, un reembolso
    no genera movimiento; además falta el VL actual y se avisa.
    """
    texto = csv(lote("2022-05-04", 1000.0, 0.0))
    movs, avisos, recon = importar_lote(texto, {})
    assert [m for m in movs if m["tipo"] == "compra"] == []
    assert movs == []              # sin VL no se inventan participaciones ni ventas
    assert any("valor liquidativo actual" in a for a in avisos)
    assert recon["plusvaliasRealizadas"]["n"] == 1


# ---------------------------------------------------------------- fechas y cabeceras (I-03)

def test_fecha_no_interpretable_se_reporta():
    """Una fecha imposible (31/02) no se descarta: se devuelve para que el plan la reporte."""
    texto = CABECERA + "31/02/2022;100,00;120,00;\n"
    lotes, reembolsos, sin_fecha = importar.leer_csv_myinvestor(texto)
    assert lotes == []
    assert reembolsos == []
    assert sin_fecha == [(2, "31/02/2022")]


def test_fecha_mm_dd_rechazada():
    """Un 05/04/2022 se lee día primero (5 de abril); un 13/12/2022 no existe y se reporta."""
    lotes, _, _ = importar.leer_csv_myinvestor(CABECERA + "05/04/2022;100,00;120,00;\n")
    assert lotes == [["2022-04-05", 100.0, 120.0]]
    _, _, sin_fecha = importar.leer_csv_myinvestor(CABECERA + "31/13/2022;100,00;120,00;\n")
    assert sin_fecha == [(2, "31/13/2022")]


def test_cabecera_reordenada():
    """Con las columnas en otro orden, cada una se encuentra por su nombre."""
    texto = ("Inversión;Fecha fiscal;Resultado fiscal;Valor de mercado\n"
             "3941,89;04/05/2022;1360,44;5302,33\n")
    lotes, reembolsos, sin_fecha = importar.leer_csv_myinvestor(texto)
    assert lotes == [["2022-05-04", INVERTIDO, VALOR]]
    assert reembolsos == []
    assert sin_fecha == []
    # Y el reembolso se lee de la columna de resultado, dondequiera que esté.
    texto = ("Inversión;Fecha fiscal;Resultado fiscal;Valor de mercado\n"
             "0,00;04/05/2022;123,45;0,00\n")
    _, reembolsos, _ = importar.leer_csv_myinvestor(texto)
    assert reembolsos == [["2022-05-04", 123.45]]


def test_delimitador_por_cabecera():
    """El separador se decide con la cabecera: los comas de 1.234,56 no lo engañan."""
    texto = "Fecha fiscal;Inversión;Valor de mercado;Resultado fiscal\n" \
            "04/05/2022;1.234,56;2.345,67;\n"
    lotes, _, _ = importar.leer_csv_myinvestor(texto)
    assert lotes == [["2022-05-04", 1234.56, 2345.67]]


def test_bom_utf8():
    """Un BOM al principio no rompe el nombre de la primera columna."""
    texto = "\ufeff" + CABECERA + "04/05/2022;100,00;120,00;\n"
    lotes, _, sin_fecha = importar.leer_csv_myinvestor(texto)
    assert lotes == [["2022-05-04", 100.0, 120.0]]
    assert sin_fecha == []


# ---------------------------------------------------------------- ayuda

def test_valor_de_extracto_extremo_usa_el_valor_de_mercado():
    """
    Verifica la vía del valor de mercado con un extracto incoherente: el valor
    de mercado (240.000 €) no cuadra con el coste (10.000 €), así que las
    unidades salen de valor / VL actual. El guard 0,5 <= k <= 2 del recalibrado
    es inalcanzable por construcción cuando las unidades salen del valor de
    mercado: k = valor_total / calculado es siempre ~1, porque calculado ya es
    Σ (valor_i / VL actual) × VL actual = valor_total.
    """
    # Coste 10.000, VL de compra 18,00 -> 555,56 participaciones; con VL de hoy
    # 40,00 el valor plausible es 22.222,22 €. El extracto dice 240.000 € (10x).
    texto = csv(lote("2019-03-01", 10000.0, 240000.0))
    serie_vl = {"2019-03-01": 18.0, HOY: 40.0}
    movs, avisos, recon = importar_lote(texto, serie_vl)
    # k = 240.000 / 240.000 = 1: las unidades salen del valor de mercado y el
    # recalibrado no tiene nada que corregir; el desvío se reporta igual.
    assert movs[0]["unidades"] == pytest.approx(240000.0 / 40.0, rel=1e-6)
    assert recon["desvio"] == pytest.approx(0.0, abs=0.01)
    assert recon["valorCalculado"] == pytest.approx(240000.0, rel=1e-6)


def test_nota_por_lote_no_por_contador():
    """
    Regresión: la nota «(posible traspaso)» es por lote, no por el contador
    acumulado. Un extracto cuyo primer lote es un traspaso y cuyo segundo es
    coherente debe marcar SOLO el primero.
    """
    texto = csv(lote("2022-01-03", 3941.89, 5302.33), lote("2022-05-04", 1000.0, 4000.0))
    serie_vl = serie({"2022-01-03": 20.0, "2022-05-04": 10.0})
    movs, _, recon = importar_lote(texto, serie_vl)
    compras = [m for m in movs if m["tipo"] == "compra"]
    assert len(compras) == 2
    assert compras[0]["nota"] == "MyInvestor (posible traspaso)"
    assert compras[1]["nota"] == "MyInvestor"
    assert recon["sospechosos"] == 1


# ---------------------------------------------------------------- duplicados y origen (I-04)

ISIN = "TEST12345678"
ARCHIVO = "TEST123456789.csv"


def cartera_fondo(datos_dir):
    """Cartera mínima con un fondo cotizado y su serie VL sembrada en la caché."""
    cfg = {"productos": [{"id": "fondo", "nombre": "Fondo Test", "corto": "Fondo Test",
                          "tipo": "fondo", "fuente": "yahoo", "codigo": ISIN, "moneda": "EUR"}],
           "movimientos": [], "valoraciones": []}
    escribe_cache(datos_dir, ISIN, {"2022-05-04": 20.0, HOY: 40.0})
    return cfg


def descarga_de_la_cache(datos_dir, monkeypatch):
    """descargar_serie simulado que lee la caché sembrada (patrón de tests/test_motor.py)."""
    def _lee(simbolo, anos=None):
        ruta = os.path.join(str(datos_dir), "cache",
                            re.sub(r"[^A-Za-z0-9._-]", "_", simbolo) + ".json")
        return motor.lee_cache(ruta)
    monkeypatch.setattr(motor, "descargar_serie", _lee)


def plan_myinvestor(cfg, datos_dir, nombre, texto):
    return importar.preparar_myinvestor(cfg, [(nombre, texto.encode("utf-8"))], str(datos_dir))


def test_dos_filas_identicas_en_un_plan(entorno):
    """Dos filas idénticas del mismo plan: una se añade, la otra cuenta como repetida."""
    _, datos_dir = entorno
    cfg = cartera_fondo(datos_dir)
    filas = [(n, {"fecha": "2022-05-04", "tipo_movimiento": "compra", "identificador": ISIN,
                  "unidades": "10", "importe": "200"}) for n in (1, 2)]
    plan = importar.preparar_tabla(cfg, filas, str(datos_dir))
    informe = importar.aplicar(cfg, plan)
    assert informe["añadidos"] == 1
    assert informe["repetidos"] == 1


def test_repetir_el_mismo_plan_no_infla(entorno):
    """Reaplicar el mismo plan sin reemplazo: el movimiento ya está y cuenta como repetido."""
    _, datos_dir = entorno
    cfg = cartera_fondo(datos_dir)
    filas = [(1, {"fecha": "2022-05-04", "tipo_movimiento": "compra", "identificador": ISIN,
                  "unidades": "10", "importe": "200"})]
    plan = importar.preparar_tabla(cfg, filas, str(datos_dir))
    primero = importar.aplicar(cfg, plan)
    assert primero["añadidos"] == 1
    plan2 = importar.preparar_tabla(cfg, filas, str(datos_dir))
    segundo = importar.aplicar(cfg, plan2)
    assert segundo["añadidos"] == 0
    assert segundo["repetidos"] == 1
    assert segundo["sustituidos"] == 0
    assert len(cfg["movimientos"]) == 1


def test_mismo_isin_en_dos_archivos(entorno):
    """El mismo ISIN en dos archivos: el plan trae un error con ambos nombres y no añade nada."""
    _, datos_dir = entorno
    cfg = cartera_fondo(datos_dir)
    plan = importar.preparar_myinvestor(
        cfg, [("TEST123456789.csv", EXTRACTO_REAL.encode("utf-8")),
              ("TEST123456789_v2.csv", EXTRACTO_REAL.encode("utf-8"))], str(datos_dir))
    assert any("TEST123456789.csv" in e["mensaje"] and "TEST123456789_v2.csv" in e["mensaje"]
               for e in plan.errores)
    assert plan.movimientos == []
    informe = importar.aplicar(cfg, plan)
    assert informe["añadidos"] == 0


def test_editar_movimiento_importado_conserva_el_origen(entorno, monkeypatch):
    """Editar un movimiento importado por MyInvestor conserva su origen y el reimport sustituye."""
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = cartera_fondo(datos_dir)
    plan = plan_myinvestor(cfg, datos_dir, ARCHIVO, EXTRACTO_REAL)
    importar.aplicar(cfg, plan)
    mov = cfg["movimientos"][0]
    assert mov["origen"] == "myinvestor"
    almacen.guarda_movimiento(cfg, {"id": mov["id"], "producto": "fondo", "tipo": "compra",
                                    "fecha": mov["fecha"], "importe": 999.0, "unidades": mov["unidades"]})
    assert cfg["movimientos"][0]["origen"] == "myinvestor"
    plan2 = plan_myinvestor(cfg, datos_dir, ARCHIVO, EXTRACTO_REAL)
    informe = importar.aplicar(cfg, plan2)
    assert informe["añadidos"] == 1
    assert informe["repetidos"] == 0
    assert informe["sustituidos"] == 1
    assert len(cfg["movimientos"]) == 1


def test_importar_myinvestor_dos_veces(entorno, monkeypatch):
    """Idempotencia: importar dos veces el mismo extracto deja la cartera igual."""
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = cartera_fondo(datos_dir)
    plan = plan_myinvestor(cfg, datos_dir, ARCHIVO, EXTRACTO_REAL)
    primero = importar.aplicar(cfg, plan)
    n = primero["añadidos"]
    copia = copy.deepcopy(cfg)
    plan2 = plan_myinvestor(cfg, datos_dir, ARCHIVO, EXTRACTO_REAL)
    segundo = importar.aplicar(cfg, plan2)
    assert segundo["sustituidos"] > 0
    assert segundo["añadidos"] == n
    assert segundo["repetidos"] == 0
    assert cfg == copia


# ---------------------------------------------------------------- reembolsos informativos (I-08)

def test_reembolso_no_genera_movimiento():
    """
    Un lote que se sigue teniendo más una fila de reembolso: solo se importa la
    compra. La plusvalía ya realizada va a la reconciliación y a los avisos,
    nunca a `movs`: MyInvestor no da ni el importe cobrado ni la fecha de venta.
    """
    texto = csv(lote("2022-05-04", 1000.0, 1200.0, 200.0),
                lote("2022-03-01", 0.0, 0.0, 123.45))
    movs, avisos, recon = importar_lote(texto, serie({"2022-05-04": 20.0}))
    assert len(movs) == 1
    assert movs[0]["tipo"] == "compra"
    assert recon["plusvaliasRealizadas"] == {"n": 1, "importe": 123.45,
                                             "desde": "2022-03-01", "hasta": "2022-03-01"}
    assert any("plusvalías ya realizadas" in a for a in avisos)


def test_reimportar_borra_la_venta_fantasma(entorno, monkeypatch):
    """
    Regresión sobre datos ya importados con el código anterior: la venta
    fantasma (unidades 0, importe = plusvalía, origen myinvestor) desaparece al
    reimportar el mismo fondo y no se recrea.
    """
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = cartera_fondo(datos_dir)
    cfg["movimientos"] = [{"id": "vieja", "fecha": "2022-03-01", "producto": "fondo",
                           "tipo": "venta", "unidades": 0, "importe": 123.45,
                           "origen": "myinvestor"}]
    texto = csv(lote("2022-05-04", 1000.0, 1200.0, 200.0),
                lote("2022-03-01", 0.0, 0.0, 123.45))
    plan = plan_myinvestor(cfg, datos_dir, ARCHIVO, texto)
    informe = importar.aplicar(cfg, plan)
    assert informe["sustituidos"] == 1
    assert cfg["movimientos"] and all(m["tipo"] == "compra" for m in cfg["movimientos"])


def test_importar_reembolso_no_es_una_venta(entorno, monkeypatch):
    """
    Extremo a extremo: el extracto con una fila de reembolso no añade ninguna
    venta, `totales["ventas"]` queda a 0 (el importe se muestra en la
    reconciliación) y `motor.construir` no avisa de sobreventa.
    """
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = cartera_fondo(datos_dir)
    texto = csv(lote("2022-05-04", 1000.0, 1200.0, 200.0),
                lote("2022-03-01", 0.0, 0.0, 123.45))
    plan = plan_myinvestor(cfg, datos_dir, ARCHIVO, texto)
    informe = importar.aplicar(cfg, plan)
    assert not any(m["tipo"] == "venta" for m in cfg["movimientos"])
    assert informe["totales"]["ventas"] == 0
    assert len(informe["reconciliacion"]) == 1
    pr = informe["reconciliacion"][0]["plusvaliasRealizadas"]
    assert pr["n"] == 1 and pr["importe"] == 123.45
    datos = motor.construir(cfg, str(datos_dir), descargar=False)
    assert not any("vendes más unidades" in a for a in datos["avisos"])


# ---------------------------------------------------------------- avisos de coherencia (I-07)

def test_unidades_diez_veces_mal_se_avisa(entorno, monkeypatch):
    """
    Una fila de compra cuyas unidades están 10x por debajo del importe se marca
    con un aviso de coherencia, pero la fila se importa igual: es una advertencia,
    no un rechazo (con comisiones de entrada el desvío puede ser legítimo).
    """
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = cartera_fondo(datos_dir)
    # 100 € con 0,5 unidades implican 200 €/unidad; el VL del día es 20,00.
    filas = [(1, {"fecha": "2022-05-04", "tipo_movimiento": "compra", "identificador": ISIN,
                  "unidades": "0,5", "importe": "100"})]
    plan = importar.preparar_tabla(cfg, filas, str(datos_dir))
    assert plan.errores == []
    assert len(plan.movimientos) == 1
    mv = plan.movimientos[0]
    assert mv["unidades"] == 0.5
    assert any("ojo: 200.00 €/unidad frente a 20.00 € del 2022-05-04" in m for m in mv["marcas"])
    informe = importar.vista_previa(cfg, plan)
    assert informe["añadidos"] == 1
    assert any("ojo: 200.00 €/unidad" in m for f in informe["filas"] for m in f["marcas"])


# ---------------------------------------------------------------- saldos de productos cotizados (I-05)

def test_saldo_de_producto_cotizado_se_rechaza(entorno, monkeypatch):
    """Un saldo de un producto con precio automático no se descarta en silencio: se reporta."""
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = cartera_fondo(datos_dir)
    filas = [(1, {"fecha": "2022-05-04", "tipo_movimiento": "saldo",
                  "identificador": ISIN, "importe": "5000"})]
    plan = importar.preparar_tabla(cfg, filas, str(datos_dir))
    assert any("precio automático" in e["mensaje"] for e in plan.errores)
    assert plan.valoraciones == []
    assert plan.movimientos == []
    informe = importar.aplicar(cfg, plan)
    assert informe["añadidos"] == 0
    assert cfg["valoraciones"] == []


def test_saldo_de_producto_manual_se_acepta(entorno, monkeypatch):
    """El mismo saldo, para un producto con «Valor anotado a mano», sí se anota."""
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = {"productos": [{"id": "manual", "nombre": "Inmueble", "corto": "Inmueble",
                          "tipo": "inmueble", "fuente": "manual", "moneda": "EUR"}],
           "movimientos": [], "valoraciones": []}
    filas = [(1, {"fecha": "2022-05-04", "tipo_movimiento": "saldo",
                  "nombre": "Inmueble", "importe": "5000"})]
    plan = importar.preparar_tabla(cfg, filas, str(datos_dir))
    assert plan.errores == []
    assert len(plan.valoraciones) == 1
    assert plan.valoraciones[0]["valor"] == 5000.0
    informe = importar.aplicar(cfg, plan)
    assert informe["saldos"] == 1
    assert len(cfg["valoraciones"]) == 1


def test_construir_avisa_de_valores_no_usados(entorno, monkeypatch):
    """Un producto cotizado con valores anotados a mano avisa de que no se usan."""
    _, datos_dir = entorno
    descarga_de_la_cache(datos_dir, monkeypatch)
    cfg = cartera_fondo(datos_dir)
    cfg["movimientos"] = [{"id": "m1", "fecha": "2022-05-04", "producto": "fondo",
                           "tipo": "compra", "unidades": 10, "importe": 200.0}]
    cfg["valoraciones"] = [{"id": "v1", "fecha": "2022-05-04", "producto": "fondo", "valor": 999.0}]
    datos = motor.construir(cfg, str(datos_dir), descargar=False)
    assert any("no se usan porque su precio es automático" in a for a in datos["avisos"])
