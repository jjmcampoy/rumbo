# -*- coding: utf-8 -*-
"""Pruebas de multicartera: migración transparente, activación y aislamiento.

Cada cartera tiene su propio `carteras/<cid>.json`; el motor, el estado y los
historicos van a rutas que dependen del `cid` activo.
"""
import importlib
import json
import os

from app import carteras
from tests.conftest import cartera_en_disco, cartera_en_disco_v2

CARPETA_A = {
    "version": 1, "titular": "Cartera A",
    "productos": [{"id": "prod_a", "nombre": "Producto A", "corto": "PA",
                   "tipo": "accion", "fuente": "manual", "codigo": "AAA",
                   "moneda": "EUR", "slot": 1, "largoPlazo": False}],
    "movimientos": [{"id": "m1", "fecha": "2024-01-02", "producto": "prod_a",
                     "tipo": "compra", "unidades": 1, "importe": 100.0}],
    "valoraciones": [{"id": "v1", "fecha": "2024-01-03", "producto": "prod_a",
                      "valor": 120.0}],
    "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True}],
    "hitos": [10000],
    "objetivo": {"activo": True, "importe": 100000, "etiqueta": "Meta"},
}

CARPETA_B = {
    "version": 1, "titular": "Cartera B",
    "productos": [{"id": "prod_b", "nombre": "Producto B", "corto": "PB",
                   "tipo": "fondo", "fuente": "manual", "codigo": "BBB",
                   "moneda": "EUR", "slot": 1, "largoPlazo": False}],
    "movimientos": [{"id": "m1", "fecha": "2024-01-02", "producto": "prod_b",
                     "tipo": "compra", "unidades": 2, "importe": 200.0}],
    "valoraciones": [{"id": "v1", "fecha": "2024-01-03", "producto": "prod_b",
                      "valor": 150.0}],
    "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True}],
    "hitos": [10000],
    "objetivo": {"activo": True, "importe": 200000, "etiqueta": "Meta"},
}


def _escribe_doc(ruta, doc):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def _escribir_dos_carteras(tmp_path):
    """Escribe alfa y beta (alfa activa) en el layout multicartera."""
    carteras.escribe_indice(tmp_path, {
        "version": 1, "activa": "alfa",
        "carteras": [
            {"id": "alfa", "nombre": "Cartera A", "creada": "2024-01-01T00:00:00"},
            {"id": "beta", "nombre": "Cartera B", "creada": "2024-01-01T00:00:00"},
        ],
    })
    _escribe_doc(carteras.ruta(tmp_path, "alfa"), CARPETA_A)
    _escribe_doc(carteras.ruta(tmp_path, "beta"), CARPETA_B)


# ---------------------------------------------------------------- migración

def test_migracion_transparente(entorno):
    """Cartera heredada → módulo migra → API sirve el contenido migrado."""
    servidor, tmp_path = entorno
    cartera_en_disco(tmp_path)                # layout legacy 1.1.1
    servidor = importlib.reload(servidor)     # dispara migra_si_hace_falta
    cliente = servidor.app.test_client()
    j = cliente.get("/api/cartera").get_json()
    assert j["modo"] == "propio"
    assert j["cartera"]["productos"][0]["id"] == "accion"
    # El archivo heredado ya no está en la raíz de datos
    assert not os.path.exists(os.path.join(str(tmp_path), "cartera.json"))
    # El documento nuevo está en carteras/principal.json
    assert os.path.exists(os.path.join(str(tmp_path), "carteras", "principal.json"))


# ---------------------------------------------------------------- activación

def test_cada_cartera_siria_sus_datos(entorno):
    """Al cambiar la cartera activa, /api/cartera y /datos.js sirven la correcta."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    # Alfa es la activa: el API y datos.js la sirven
    j = cliente.get("/api/cartera").get_json()
    assert j["cartera"]["titular"] == "Cartera A"
    assert j["cartera"]["productos"][0]["id"] == "prod_a"
    txt = cliente.get("/datos.js").get_data(as_text=True)
    assert '"prod_a"' in txt and '"prod_b"' not in txt

    # Activar beta
    carteras.activa_set(tmp_path, "beta")

    # Ahora /api/cartera y /datos.js sirven beta
    j = cliente.get("/api/cartera").get_json()
    assert j["cartera"]["titular"] == "Cartera B"
    assert j["cartera"]["productos"][0]["id"] == "prod_b"
    txt = cliente.get("/datos.js").get_data(as_text=True)
    assert '"prod_b"' in txt and '"prod_a"' not in txt


def test_escribir_no_toca_la_otra(entorno):
    """Un POST /api/productos solo afecta al JSON de la cartera activa."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    r = cliente.post("/api/productos",
                     json={"nombre": "Nuevo", "tipo": "fondo", "fuente": "manual"},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200

    # Beta no tiene el nuevo producto
    doc_beta = json.load(open(carteras.ruta(tmp_path, "beta"), encoding="utf-8"))
    assert all(p.get("nombre") != "Nuevo" for p in doc_beta["productos"])

    # Alfa sí lo tiene
    doc_alfa = json.load(open(carteras.ruta(tmp_path, "alfa"), encoding="utf-8"))
    assert any(p.get("nombre") == "Nuevo" for p in doc_alfa["productos"])


# ---------------------------------------------------------------- copias

def test_copias_cartera_activa(entorno):
    """/api/copias lista solo las copias de la cartera activa (copias/<cid>/)."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    for cid, nombre in (("alfa", "copia_alfa.json"), ("beta", "copia_beta.json")):
        carpeta = os.path.join(str(tmp_path), "copias", cid)
        os.makedirs(carpeta, exist_ok=True)
        _escribe_doc(os.path.join(carpeta, nombre), CARPETA_A)

    # Alfa activa: solo su copia aparece
    carteras.activa_set(tmp_path, "alfa")
    j = cliente.get("/api/copias").get_json()
    nombres = [c["archivo"] for c in j["copias"]]
    assert nombres == ["copia_alfa.json"]

    # Beta activa: solo su copia aparece
    carteras.activa_set(tmp_path, "beta")
    j = cliente.get("/api/copias").get_json()
    nombres = [c["archivo"] for c in j["copias"]]
    assert nombres == ["copia_beta.json"]


# ---------------------------------------------------------------- catálogo HTTP

def test_cred_renombrar_borrar(entorno):
    """Crear, renombrar y borrar por HTTP: orden del índice y cartera activa."""
    servidor, tmp_path = entorno
    cartera_en_disco_v2(tmp_path, CARPETA_A, cid="alfa")
    cliente = servidor.app.test_client()
    h = {"X-Rumbo": "1"}

    # Crear dos (la primera ya existe: alfa)
    r = cliente.post("/api/carteras", json={"nombre": "Segunda", "desde": "vacia"}, headers=h)
    assert r.status_code == 200
    nueva = r.get_json()["cartera"]
    # No se activa al crear
    assert r.get_json()["activa"] == "alfa"
    r = cliente.post("/api/carteras", json={"nombre": "Tercera"}, headers=h)
    assert r.status_code == 200
    otra = r.get_json()["cartera"]

    # GET /api/carteras: solo metadata, en el orden del índice, con la activa
    j = cliente.get("/api/carteras").get_json()
    ids = [c["id"] for c in j["carteras"]]
    assert ids == ["alfa", nueva["id"], otra["id"]]
    assert j["activa"] == "alfa"
    assert [c["activa"] for c in j["carteras"]] == [True, False, False]
    assert set(j["carteras"][0]) == {"id", "nombre", "creada", "activa", "productos"}   # solo metadata

    # Renombrar a una: cambia el índice y el titular
    r = cliente.post(f"/api/carteras/{nueva['id']}/renombrar",
                     json={"nombre": "Segunda (renombrada)"}, headers=h)
    assert r.status_code == 200 and r.get_json()["ok"]
    doc = json.load(open(carteras.ruta(tmp_path, nueva["id"]), encoding="utf-8"))
    assert doc["titular"] == "Segunda (renombrada)"

    # Borrar una que no es la activa: la activa no cambia
    r = cliente.delete(f"/api/carteras/{otra['id']}", headers=h)
    assert r.status_code == 200
    assert r.get_json()["activa"] == "alfa"
    j = cliente.get("/api/carteras").get_json()
    assert [c["id"] for c in j["carteras"]] == ["alfa", nueva["id"]]
    # La borrada pasó a copias/<cid>/
    borradas = []
    copia_dir = os.path.join(str(tmp_path), "copias", otra["id"])
    if os.path.isdir(copia_dir):
        borradas = [n for n in os.listdir(copia_dir) if n.startswith("borrada_")]
    assert borradas and borradas[0].endswith(".json")


def test_activar_por_http(entorno):
    """Activar por HTTP: /api/cartera sirve los productos de la nueva activa;
    escribir no toca la otra."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    r = cliente.post("/api/carteras/beta/activar", headers={"X-Rumbo": "1"})
    assert r.status_code == 200 and r.get_json()["activa"] == "beta"

    j = cliente.get("/api/cartera").get_json()
    assert j["cartera"]["productos"][0]["id"] == "prod_b"
    assert j["carteraActiva"] == {"id": "beta", "nombre": "Cartera B"}
    assert [c["activa"] for c in j["carteras"]] == [False, True]

    # Escribir en la activa (beta): alfa no se toca
    r = cliente.post("/api/productos",
                     json={"nombre": "Nueva en beta", "tipo": "fondo", "fuente": "manual"},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    doc_alfa = json.load(open(carteras.ruta(tmp_path, "alfa"), encoding="utf-8"))
    assert all(p["nombre"] != "Nueva en beta" for p in doc_alfa["productos"])


def test_ids_de_url_se_validan(entorno):
    """Todo id de URL se valida: 400 si no es legítimo, 404 si no existe,
    y una URL con `..` nunca provoca un error de ruta (5xx)."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()
    h = {"X-Rumbo": "1"}
    # URL trampa: o se valida o se normaliza; nunca un error de ruta
    r = cliente.get("/api/carteras/../../etc/passwd/activar")
    assert r.status_code in (200, 400, 404)      # nunca un 5xx
    # Id inválido (mayúsculas) → 400 con mensaje en español
    r = cliente.post("/api/carteras/MAYUSCULA/activar", headers=h)
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    # Id legítimo pero inexistente → 404
    r = cliente.delete("/api/carteras/no_existe", headers=h)
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_no_se_puede_borrar_la_ultima(entorno):
    """Borrar la única cartera → 400."""
    servidor, tmp_path = entorno
    cartera_en_disco_v2(tmp_path, CARPETA_A, cid="solo")
    cliente = servidor.app.test_client()
    r = cliente.delete("/api/carteras/solo", headers={"X-Rumbo": "1"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert os.path.exists(carteras.ruta(tmp_path, "solo"))


def test_crear_en_demo_sale_de_la_demo(entorno):
    """En modo demo, crear la primera cartera la activa y deja el modo demo."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    h = {"X-Rumbo": "1"}
    assert cliente.get("/api/cartera").get_json()["modo"] == "demo"

    r = cliente.post("/api/carteras", json={"nombre": "La mía", "desde": "vacia"}, headers=h)
    assert r.status_code == 200
    j = r.get_json()
    assert j["activa"] == j["cartera"]["id"]

    j = cliente.get("/api/cartera").get_json()
    assert j["modo"] == "propio"
    assert j["carteraActiva"]["nombre"] == "La mía"
    assert j["carteras"][0]["activa"] is True


# ---------------------------------------------------------------- extraer
def _carta_cuatro(tmp_path, cid="origen"):
    """Cartera `origen` con 4 productos (cada uno con un movimiento y una
    valoración) y dos comparadores con pesos; la deja activa en el índice."""
    def _pro(id_, nombre, corto, tipo):
        return {"id": id_, "nombre": nombre, "corto": corto, "tipo": tipo,
                "fuente": "manual", "codigo": "", "moneda": "EUR", "slot": 1,
                "largoPlazo": True}
    doc = {
        "version": 1, "titular": "Principal",
        "productos": [_pro("prod1", "Uno", "Uno", "fondo"),
                      _pro("prod2", "Dos", "Dos", "etf"),
                      _pro("prod3", "Tres", "Tres", "accion"),
                      _pro("prod4", "Cuatro", "Cuatro", "cripto")],
        "movimientos": [
            {"id": "m1", "fecha": "2024-01-01", "producto": "prod1", "tipo": "compra",
             "unidades": 1, "importe": 100.0},
            {"id": "m2", "fecha": "2024-01-01", "producto": "prod2", "tipo": "compra",
             "unidades": 2, "importe": 200.0},
            {"id": "m3", "fecha": "2024-01-01", "producto": "prod3", "tipo": "compra",
             "unidades": 3, "importe": 300.0},
            {"id": "m4", "fecha": "2024-01-01", "producto": "prod4", "tipo": "compra",
             "unidades": 4, "importe": 400.0}],
        "valoraciones": [
            {"id": "v1", "fecha": "2024-02-01", "producto": "prod1", "valor": 110.0},
            {"id": "v2", "fecha": "2024-02-01", "producto": "prod2", "valor": 220.0},
            {"id": "v3", "fecha": "2024-02-01", "producto": "prod3", "valor": 330.0},
            {"id": "v4", "fecha": "2024-02-01", "producto": "prod4", "valor": 440.0}],
        "comparador": [
            {"id": "real", "nombre": "Mi cartera real", "real": True},
            {"id": "cuatro25", "nombre": "Cuartos",
             "pesos": {"prod1": 25, "prod2": 25, "prod3": 25, "prod4": 25}},
            {"id": "tressolo", "nombre": "Solo tres", "pesos": {"prod3": 50, "prod4": 50}}],
        "hitos": [100000],
        "objetivo": {"activo": True, "importe": 200000, "etiqueta": "Meta"},
    }
    carteras.escribe_indice(tmp_path, {"version": 1, "activa": cid,
        "carteras": [{"id": cid, "nombre": "Principal", "creada": "2024-01-01T00:00:00"}]})
    _escribe_doc(carteras.ruta(tmp_path, cid), doc)
    return doc


def _doc(tmp_path, cid):
    return json.load(open(carteras.ruta(tmp_path, cid), encoding="utf-8"))


def _ids_carteras(tmp_path):
    return [c["id"] for c in carteras.lee_indice(tmp_path).get("carteras", [])]


def test_extraer_copia_deja_origen(entorno):
    """Extraer 2 de 4 (copia) → la nueva tiene esos 2 y solo sus movimientos y
    valoraciones; el origen queda intacto."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)
    original = _doc(tmp_path, "origen")

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod2"],
                           "mover": False, "desde": "origen"}, headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    nueva_id = r.get_json()["cartera"]["id"]
    nueva = _doc(tmp_path, nueva_id)

    assert [p["id"] for p in nueva["productos"]] == ["prod1", "prod2"]
    # Los ids se conservan tal cual (la caché y flujos los reutilizan).
    assert {p["id"] for p in nueva["productos"]} == {"prod1", "prod2"}
    assert {m["producto"] for m in nueva["movimientos"]} == {"prod1", "prod2"}
    assert {v["producto"] for v in nueva["valoraciones"]} == {"prod1", "prod2"}

    # El origen no cambia: sigue con sus 4 productos y todos sus movimientos.
    actual = _doc(tmp_path, "origen")
    assert {p["id"] for p in actual["productos"]} == {p["id"] for p in original["productos"]}
    assert actual["movimientos"] == original["movimientos"]
    assert actual["valoraciones"] == original["valoraciones"]
    assert r.get_json()["origen"] == "origen"


def test_extraer_mover_baja_la_origen(entorno):
    """Extraer con mover=true → el origen pierde esos productos (y sus movimientos
    y valores); los otros se quedan con los suyos."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod3"],
                           "desde": "origen", "mover": True}, headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    nueva_id = r.get_json()["cartera"]["id"]

    origen = _doc(tmp_path, "origen")
    assert {p["id"] for p in origen["productos"]} == {"prod2", "prod4"}
    assert {m["producto"] for m in origen["movimientos"]} == {"prod2", "prod4"}
    assert {v["producto"] for v in origen["valoraciones"]} == {"prod2", "prod4"}
    # La respuesta indica cuántos productos quedan en el origen (para avisar).
    assert r.get_json()["restantes"] == 2

    nueva = _doc(tmp_path, nueva_id)
    assert {p["id"] for p in nueva["productos"]} == {"prod1", "prod3"}


def test_comparador_solo_productos_que_existen(entorno):
    """En ambos documentos, `comparador[].pesos` solo cita productos existentes;
    las entradas de pesos vacías se tiran (como en almacen.borra_producto)."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod2"],
                           "desde": "origen", "mover": True}, headers={"X-Rumbo": "1"})
    assert r.status_code == 200
    nueva_id = r.get_json()["cartera"]["id"]
    nueva, origen = _doc(tmp_path, nueva_id), _doc(tmp_path, "origen")

    for doc in (nueva, origen):
        ids = {p["id"] for p in doc["productos"]}
        for c in doc["comparador"]:
            for pid in (c.get("pesos") or {}):
                assert pid in ids, f"peso «{pid}» sin producto en {c.get('id')}"
            # Ninguna entrada de pesos queda vacía.
            assert c.get("real") or c.get("pesos"), c

    # En la nueva solo sobrevive la entrada «cuatro25» recortada a prod1/prod2.
    por_id = {c["id"]: c for c in nueva["comparador"]}
    assert por_id["cuatro25"]["pesos"] == {"prod1": 25, "prod2": 25}
    assert "tressolo" not in por_id          # quedaba vacía (prod3/prod4 no vienen)
    # En el origen (se llevan prod1/prod2) «cuatro25» queda a prod3/prod4 y
    # «tressolo» se conserva íntegro (sus pesos seguían existiendo).
    por_id_o = {c["id"]: c for c in origen["comparador"]}
    assert por_id_o["cuatro25"]["pesos"] == {"prod3": 25, "prod4": 25}
    assert por_id_o["tressolo"]["pesos"] == {"prod3": 50, "prod4": 50}


def test_extraer_rechaza_y_no_crea(entorno):
    """Id desconocido, lista vacía o `desde` que no existe → 400 en español y no
    se crea ninguna cartera."""
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)
    h = {"X-Rumbo": "1"}
    ids_antes = _ids_carteras(tmp_path)

    for cuerpo in (
        {"nombre": "X", "productos": ["inexistente"], "desde": "origen"},
        {"nombre": "X", "productos": [], "desde": "origen"},
        {"nombre": "X", "productos": ["prod1"], "desde": "no_existe"},
    ):
        r = cliente.post("/api/carteras/extraer", json=cuerpo, headers=h)
        assert r.status_code == 400, cuerpo
        assert r.get_json()["ok"] is False
        assert r.get_json()["errores"]
    # No se ha creado ninguna cartera en ningún intento fallido.
    assert _ids_carteras(tmp_path) == ids_antes
    assert not os.path.exists(os.path.join(str(tmp_path), "carteras", "x.json"))


def test_extraer_funcion_pura_persiste_nueva_antes(entorno):
    """`carteras.extrae` devuelve (nueva, origen) y deja la nueva en disco
    (añadida al índice) antes de tocar el origen aunque mover=True."""
    servidor, tmp_path = entorno
    _carta_cuatro(tmp_path)

    nueva, origen = carteras.extrae(tmp_path, "origen", "Mía", ["prod4"], mover=True)
    assert {p["id"] for p in nueva["productos"]} == {"prod4"}
    assert {p["id"] for p in origen["productos"]} == {"prod1", "prod2", "prod3"}
    nueva_id = [c["id"] for c in carteras.lee_indice(tmp_path)["carteras"]
                if c.get("id") != "origen"]
    assert len(nueva_id) == 1 and os.path.exists(carteras.ruta(tmp_path, nueva_id[0]))
    # El origen sigue en disco, ya sin el producto extraído.
    assert {p["id"] for p in _doc(tmp_path, "origen")["productos"]} == {"prod1", "prod2", "prod3"}


# ---------------------------------------------------------------- importar

import io

CSV_IMPORTAR = (
    "fecha;tipo_movimiento;importe;unidades;nombre;tipo_producto;moneda\n"
    "2024-06-15;compra;100.00;10;Fondo Nuevo;fondo;EUR\n"
)


def _previsualiza(cliente, csv=CSV_IMPORTAR):
    """Previsualiza un CSV de plantilla y devuelve el token de la respuesta."""
    r = cliente.post("/api/importar/previsualizar",
                     data={"origen": "plantilla",
                           "archivos": [(io.BytesIO(csv.encode()), "importado.csv")]},
                     content_type="multipart/form-data", headers={"X-Rumbo": "1"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["token"]


def _mov_de_fondo_nuevo(doc):
    """Movimientos del producto «Fondo Nuevo» (se crea como producto nuevo al aplicar)."""
    ids = {p["id"] for p in doc["productos"] if p.get("nombre") == "Fondo Nuevo"}
    return [m for m in doc["movimientos"] if m.get("producto") in ids]


def test_confirmar_otra_cartera_rechaza_y_no_escribe(entorno):
    """Previsualizar en A, activar B y confirmar → 400 y no se escribe en A ni B."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    antes_a, antes_b = _doc(tmp_path, "alfa"), _doc(tmp_path, "beta")
    token = _previsualiza(cliente)          # alfa es la activa
    carteras.activa_set(tmp_path, "beta")    # cambiar de cartera antes de confirmar

    r = cliente.post("/api/importar/confirmar", json={"token": token},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 400
    assert any("cartera activa ha cambiado" in e.lower() for e in r.get_json()["errores"])

    # Nada se ha escrito en ninguna cartera.
    assert _doc(tmp_path, "alfa") == antes_a
    assert _doc(tmp_path, "beta") == antes_b


def test_confirmar_misma_cartera_escribe_solo_en_ella(entorno):
    """Previsualizar en A y confirmar en A → el movimiento llega únicamente a A."""
    servidor, tmp_path = entorno
    _escribir_dos_carteras(tmp_path)
    cliente = servidor.app.test_client()

    antes_b = _doc(tmp_path, "beta")
    token = _previsualiza(cliente)          # alfa es la activa
    r = cliente.post("/api/importar/confirmar", json={"token": token},
                     headers={"X-Rumbo": "1"})
    assert r.status_code == 200, r.get_json()

    doc_alfa = _doc(tmp_path, "alfa")
    assert _mov_de_fondo_nuevo(doc_alfa)     # A recibió el movimiento
    assert _doc(tmp_path, "beta") == antes_b  # B no se tocó
    assert _mov_de_fondo_nuevo(_doc(tmp_path, "beta")) == []


def test_extraer_motor_calcula_ambas(entorno):
    """Tras mover un subconjunto, el motor calcula ambas carteras sin avisos."""
    from app import motor
    servidor, tmp_path = entorno
    cliente = servidor.app.test_client()
    _carta_cuatro(tmp_path)

    r = cliente.post("/api/carteras/extraer",
                     json={"nombre": "Selección", "productos": ["prod1", "prod2"],
                           "desde": "origen", "mover": True}, headers={"X-Rumbo": "1"})
    nueva_id = r.get_json()["cartera"]["id"]

    for cid, doc in (("origen", _doc(tmp_path, "origen")), (nueva_id, _doc(tmp_path, nueva_id))):
        datos = motor.construir(doc, tmp_path, descargar=False)
        assert datos is not None
        assert set(p["id"] for p in datos.get("productos", [])) == \
            {p["id"] for p in doc["productos"]}
