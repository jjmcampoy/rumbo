# -*- coding: utf-8 -*-
"""Pruebas básicas de la API HTTP: modo demo, permisos, validación y estáticos.

Caracterizan el comportamiento de hoy (incluido el 403 en modo demostración) para
que los refactores posteriores tengan una red de seguridad.
"""


CAB = {"X-Rumbo": "1"}   # inofensivo antes de T-16, obligatorio después


def _empezar(cliente):
    """Sale de la demo creando una cartera propia vacía."""
    return cliente.post("/api/empezar", json={}, headers=CAB)


def _crear_producto(cliente, nombre):
    r = cliente.post("/api/productos",
                     json={"nombre": nombre, "tipo": "fondo", "fuente": "manual"},
                     headers=CAB)
    assert r.status_code == 200
    return r.get_json()["item"]["id"]


def test_ping(cliente):
    r = cliente.get("/api/ping")
    assert r.status_code == 200
    assert r.get_json() == {"app": "patrimonio"}


def test_sin_cartera_propia_esta_en_demo(cliente):
    r = cliente.get("/api/cartera")
    assert r.status_code == 200
    assert r.get_json()["modo"] == "demo"


def test_en_demo_no_se_puede_guardar(cliente):
    r = cliente.post("/api/productos", json={"nombre": "Cualquiera", "tipo": "fondo"},
                     headers=CAB)
    assert r.status_code == 403
    assert r.get_json()["errores"]


def test_empezar_pasa_a_modo_propio(cliente):
    assert _empezar(cliente).status_code == 200
    datos = cliente.get("/api/cartera").get_json()
    assert datos["modo"] == "propio"
    assert datos["cartera"]["productos"] == []


def test_guardar_producto_aparece_en_la_cartera(cliente):
    _empezar(cliente)
    ident = _crear_producto(cliente, "Mi fondo")
    productos = cliente.get("/api/cartera").get_json()["cartera"]["productos"]
    assert [p["id"] for p in productos] == [ident]
    assert productos[0]["nombre"] == "Mi fondo"


def test_movimiento_con_fecha_futura_da_400(cliente):
    _empezar(cliente)
    pid = _crear_producto(cliente, "Fondo con movimientos")
    # Con una fecha pasada el movimiento se acepta: el producto y el resto de campos
    # son válidos, así que el 400 de abajo solo puede venir de la fecha futura.
    pasado = {"producto": pid, "tipo": "compra", "fecha": "2024-01-02",
              "importe": 10, "unidades": 1}
    assert cliente.post("/api/movimientos", json=pasado, headers=CAB).status_code == 200

    futuro = dict(pasado, fecha="2099-01-01")
    r = cliente.post("/api/movimientos", json=futuro, headers=CAB)
    assert r.status_code == 400
    errores = r.get_json()["errores"]
    assert errores
    assert any("futura" in e.lower() for e in errores)


def test_borrar_producto_lo_quita_de_la_cartera(cliente):
    _empezar(cliente)
    ident = _crear_producto(cliente, "Para borrar")
    assert cliente.delete(f"/api/productos/{ident}", headers=CAB).status_code == 200
    productos = cliente.get("/api/cartera").get_json()["cartera"]["productos"]
    assert ident not in [p["id"] for p in productos]


def test_datos_js_es_javascript_con_los_datos(cliente):
    r = cliente.get("/datos.js")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/javascript")
    assert r.get_data(as_text=True).startswith("window.DATOS =")


def test_copias_guarda_una_entrada_tras_escribir(cliente):
    assert cliente.get("/api/copias").get_json()["copias"] == []
    _empezar(cliente)
    _crear_producto(cliente, "Uno")
    _crear_producto(cliente, "Dos")
    r = cliente.get("/api/copias")
    assert r.status_code == 200
    assert len(r.get_json()["copias"]) >= 1


def test_estaticos_y_travesia_de_rutas(cliente):
    assert cliente.get("/app.js").status_code == 200
    assert cliente.get("/../app/servidor.py").status_code == 404
