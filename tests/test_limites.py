# -*- coding: utf-8 -*-
"""Límites de subida e importación (F-10)."""
import io

from tests.conftest import cartera_en_disco_v2

CAB = {"X-Rumbo": "1"}   # inofensivo antes de T-16, obligatorio después


def test_demasiados_archivos(cliente, entorno):
    servidor, tmp_path = entorno
    cartera_en_disco_v2(tmp_path)   # fuera de la demo: la importación está permitida
    datos = {"origen": "plantilla"}
    datos["archivos"] = [(io.BytesIO(b"a;b\n1;2\n"), f"f{i}.csv") for i in range(51)]
    r = cliente.post("/api/importar/previsualizar", data=datos,
                     content_type="multipart/form-data", headers=CAB)
    assert r.status_code == 400 and "Demasiados" in r.get_json()["errores"][0]


def test_csv_pequeno_no_se_rechaza(cliente, entorno):
    servidor, tmp_path = entorno
    cartera_en_disco_v2(tmp_path)   # fuera de la demo: la importación está permitida
    datos = {"origen": "plantilla"}
    datos["archivos"] = [(io.BytesIO(b"a;b\n1;2\n"), "pequeno.csv")]
    r = cliente.post("/api/importar/previsualizar", data=datos,
                     content_type="multipart/form-data", headers=CAB)
    # Un CSV pequeño debe llegar a la previsualización: 200 o 400 con mensaje de
    # validación, pero nunca 413.
    assert r.status_code in (200, 400) and r.status_code != 413


def test_archivo_grande(cliente):
    gordo = io.BytesIO(b"x" * (26 * 1024 * 1024))
    r = cliente.post("/api/copia/subir", data={"archivo": (gordo, "copia.json")},
                     content_type="multipart/form-data", headers=CAB)
    assert r.status_code == 413
    assert r.is_json and r.get_json()["ok"] is False
