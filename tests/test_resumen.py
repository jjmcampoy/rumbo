# -*- coding: utf-8 -*-
"""Pruebas de /api/carteras/resumen: cifras por cartera y un total conjunto.
Todo sin red: los cálculos se siembran o se hacen con carteras manuales."""
import json
import os

from app import carteras
from tests.conftest import escribe_json


def calc_sembrado(patrimonio, aportado, fecha="2024-06-30"):
    """Cálculo guardado mínimo (los totales salen de lo sembrado)."""
    plus = round(patrimonio - aportado, 2)
    return {
        "generado": "2024-07-01T08:00:00",
        "titular": "Prueba", "moneda": "EUR",
        "fechaExtracto": fecha,
        "fechas": [fecha],
        "productos": [], "otrosActivos": [], "pasivos": [],
        "total": {
            "patrimonio": patrimonio, "aportado": aportado,
            "valorConCoste": patrimonio, "plusvalia": plus,
            "rentabilidad": round(plus / aportado, 4) if aportado else None,
            "tir": None,
        },
    }


def doc_manual(tmp_path, cid, valor, importe):
    """Cartera con un producto manual (un valor anotado y una compra)."""
    doc = {
        "version": 1, "titular": "Cartera " + cid.upper(),
        "productos": [{"id": "acc", "nombre": "Acción", "corto": "Acc",
                       "tipo": "accion", "fuente": "manual", "codigo": "",
                       "moneda": "EUR", "slot": 1, "largoPlazo": True}],
        "movimientos": [{"id": "m1", "fecha": "2024-01-02", "producto": "acc",
                         "tipo": "compra", "unidades": 1, "importe": importe}],
        "valoraciones": [{"id": "v1", "fecha": "2024-06-30", "producto": "acc",
                          "valor": valor}],
        "comparador": [{"id": "real", "nombre": "Real", "real": True}],
        "hitos": [1000],
        "objetivo": {"activo": True, "importe": 10000, "etiqueta": "Meta"},
    }
    ruta = carteras.ruta(tmp_path, cid)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return doc


def con_dos_carteras(tmp_path):
    """Índice con alfa (activa) y beta."""
    carteras.escribe_indice(tmp_path, {
        "version": 1, "activa": "alfa",
        "carteras": [
            {"id": "alfa", "nombre": "Cartera A", "creada": "2024-01-01T00:00:00"},
            {"id": "beta", "nombre": "Cartera B", "creada": "2024-01-01T00:00:00"},
        ]})


def por_id(j, cid):
    return next(c for c in j["carteras"] if c["id"] == cid)


def test_resumen_con_cache_sembrada(entorno):
    """Dos carteras con cálculo guardado → 2 entradas + total coherente."""
    servidor, tmp_path = entorno
    con_dos_carteras(tmp_path)
    doc_manual(tmp_path, "alfa", 120, 100)
    doc_manual(tmp_path, "beta", 110, 80)
    for cid, valor, apostado in (("alfa", 120, 100), ("beta", 110, 80)):
        escribe_json(os.path.join(str(tmp_path), "calculado", cid + ".json"),
                     calc_sembrado(valor, apostado))

    cliente = servidor.app.test_client()
    r = cliente.get("/api/carteras/resumen")
    assert r.status_code == 200
    j = r.get_json()

    ids = [c["id"] for c in j["carteras"]]
    assert ids == ["alfa", "beta"]
    a = por_id(j, "alfa")
    assert a["patrimonio"] == 120 and a["aportado"] == 100
    assert a["activa"] is True
    assert a.get("error") is None
    assert a["nProductos"] == 0
    assert a["fechaExtracto"] == "2024-06-30"

    t = j["total"]
    assert abs(t["patrimonio"] - 230) < 0.01                      # 120 + 110
    assert abs(t["aportado"] - 180) < 0.01                       # 100 + 80
    assert abs(t["plusvalia"] - 50) < 0.01                       # 20 + 30
    assert abs(t["rentabilidad"] - 50 / 180) < 0.0001
    # Sin flujos en el cálculo sembrado, la TIR total es None, sin excepción.
    assert t["tir"] is None or isinstance(t["tir"], float)


def test_resumen_calcula_sin_cache(entorno):
    """Sin cálculo guardado: se calcula offline y la cartera aparece."""
    servidor, tmp_path = entorno
    con_dos_carteras(tmp_path)
    doc_manual(tmp_path, "alfa", 120, 100)
    doc_manual(tmp_path, "beta", 60, 80)

    cliente = servidor.app.test_client()
    r = cliente.get("/api/carteras/resumen")
    assert r.status_code == 200
    j = r.get_json()

    # Se calcularon offline y se guardaron.
    for cid in ("alfa", "beta"):
        ruta = os.path.join(str(tmp_path), "calculado", cid + ".json")
        assert os.path.exists(ruta)
    a, b = por_id(j, "alfa"), por_id(j, "beta")
    assert abs(a["patrimonio"] - 120) < 0.01
    assert abs(a["aportado"] - 100) < 0.01
    assert abs(b["patrimonio"] - 60) < 0.01
    assert b["nProductos"] == 1

    t = j["total"]
    assert abs(t["patrimonio"] - (120 + 60)) < 0.01
    # Con flujos en ambas, la TIR total es un float (o None si no converge).
    assert t["tir"] is None or isinstance(t["tir"], float)


def test_resumen_cartera_rota_no_tumba_al_resto(entorno):
    """Documento inválido → entrada con error; la otra se devuelve y el total
    la excluye; HTTP 200 siempre."""
    servidor, tmp_path = entorno
    con_dos_carteras(tmp_path)
    doc_manual(tmp_path, "alfa", 120, 100)
    # Beta: documento ilegible (JSON inválido), sin cálculo guardado.
    with open(carteras.ruta(tmp_path, "beta"), "w", encoding="utf-8") as f:
        f.write("{esto no es json")
    escribe_json(os.path.join(str(tmp_path), "calculado", "alfa.json"),
                 calc_sembrado(120, 100))

    cliente = servidor.app.test_client()
    r = cliente.get("/api/carteras/resumen")
    assert r.status_code == 200
    j = r.get_json()

    b = por_id(j, "beta")
    assert b.get("error")
    assert b["patrimonio"] is None and b["nProductos"] == 0

    a = por_id(j, "alfa")
    assert a["patrimonio"] == 120

    # El total solo cuenta la cartera sana.
    t = j["total"]
    assert abs(t["patrimonio"] - 120) < 0.01
    assert abs(t["aportado"] - 100) < 0.01
    assert abs(t["plusvalia"] - 20) < 0.01
    assert abs(t["rentabilidad"] - 0.2) < 0.0001
    assert t["tir"] is None or isinstance(t["tir"], float)


def test_resumen_tir_jamás_excepcion(entorno):
    """total.tir es un float o None en cualquier caso; nunca lanza."""
    servidor, tmp_path = entorno
    con_dos_carteras(tmp_path)
    doc_manual(tmp_path, "alfa", 120, 100)               # con flujos
    # Beta con cálculo sembrado pero sin productos: aporta valor sin flujos.
    doc_manual(tmp_path, "beta", 60, 80)
    escribe_json(os.path.join(str(tmp_path), "calculado", "beta.json"),
                 calc_sembrado(60, 80))

    cliente = servidor.app.test_client()
    r = cliente.get("/api/carteras/resumen")
    assert r.status_code == 200
    t = r.get_json()["total"]
    assert t["tir"] is None or isinstance(t["tir"], float)
