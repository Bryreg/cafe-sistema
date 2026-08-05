"""Módulo Costos — Fase 1: obligaciones y pagos fuera del turno de caja.

Hoy el arriendo que se paga un sábado por transferencia desde el celular NO SE
PUEDE REGISTRAR: `registrar_movimiento` (services/caja.py) exige turno ABIERTO y
cuadre de llegada hecho, y `MovimientoCajaRequest` ni siquiera acepta una fecha.

Esta fase es PURAMENTE ADITIVA: tres tablas nuevas (costos_categorias,
obligaciones, pagos) y un router propio. Reglas que se prueban acá:

- una obligación puede ser CORPORATIVA (tienda_id NULL): el arriendo no pertenece
  a una sede. Esa es la razón estructural por la que el modelo no cuelga de
  MovimientoCaja;
- el estado NO se almacena, se DERIVA de la suma de pagos vivos (asimetría
  deliberada con FacturaCompra.valor_pagado, que es justamente la columna que se
  puede desincronizar). Lo único almacenado es `anulada`;
- fecha_pago es obligatoria: es EL DÍA QUE SALIÓ LA PLATA, la columna que hoy no
  existe en ninguna parte;
- todo el módulo es solo-admin (require_admin), igual que rentabilidad.
"""
import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import CostoCategoria, RolEnum, Tienda, Usuario
from app.routers import costos as costos_router


class CostosObligacionesTest(unittest.TestCase):
    """sqlite temporal + router real de costos (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda_1 = Tienda(nombre="Vida", direccion="Sede Vida")
        self.tienda_2 = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.tienda_1, self.tienda_2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda_1.id, activo=True)
        self.barista = Usuario(nombre="Barista Uno", email="barista1@test.local",
                               password_hash="h", rol=RolEnum.barista,
                               tienda_id=self.tienda_1.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        # Catálogo mínimo de categorías (en producción lo siembra _seed_categorias_costo).
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo", grupo="fijo", orden=0)
        self.cat_servicios = CostoCategoria(clave="servicios", nombre="Servicios", grupo="fijo", orden=1)
        self.cat_vieja = CostoCategoria(clave="obsoleta", nombre="Obsoleta", grupo="variable",
                                        orden=9, activa=False)
        self.db.add_all([self.cat_arriendo, self.cat_servicios, self.cat_vieja])
        self.db.commit()

        app = FastAPI(title="Test costos obligaciones")
        app.include_router(costos_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        self.app = app
        self.client = TestClient(app)
        self.set_current_user(self.admin)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def set_current_user(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def crear_obligacion(self, **over):
        body = {
            "categoria_id": self.cat_arriendo.id,
            "concepto": "Arriendo agosto",
            "monto": 3000000,
            "fecha_devengo": "2026-08-01",
        }
        body.update(over)
        return self.client.post("/api/v1/costos/obligaciones", json=body)

    def pagar(self, obligacion_id, monto, fecha_pago="2026-08-05", **over):
        body = {"obligacion_id": obligacion_id, "monto": monto,
                "fecha_pago": fecha_pago, "metodo": "transferencia"}
        body.update(over)
        return self.client.post("/api/v1/costos/pagos", json=body)

    def listar(self, **params):
        r = self.client.get("/api/v1/costos/obligaciones", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _uno(self, obligacion_id, **params):
        """La obligación tal como sale del listado (fuente única del estado)."""
        data = self.listar(**params)
        for o in data["obligaciones"]:
            if o["id"] == obligacion_id:
                return o
        return None

    # ── Alta de obligaciones ─────────────────────────────────────────────────

    def test_crear_obligacion_corporativa_sin_sede(self):
        # El arriendo/nómina corporativa NO pertenece a una sede: tienda_id NULL
        # tiene que ser un caso de primera clase, no un accidente.
        r = self.crear_obligacion()
        self.assertEqual(r.status_code, 200, r.text)
        creada = r.json()
        self.assertIsNone(creada["tienda_id"])
        self.assertEqual(creada["estado"], "pendiente")

        o = self._uno(creada["id"])
        self.assertIsNotNone(o)
        self.assertEqual(o["concepto"], "Arriendo agosto")
        self.assertEqual(o["categoria_clave"], "arriendo")
        self.assertEqual(o["monto"], 3000000)
        self.assertEqual(o["saldo"], 3000000)
        self.assertEqual(o["fecha_devengo"], "2026-08-01")

    def test_crear_obligacion_de_una_sede(self):
        r = self.crear_obligacion(tienda_id=self.tienda_1.id, concepto="Energía Vida",
                                  categoria_id=self.cat_servicios.id, monto=450000)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["tienda_id"], self.tienda_1.id)
        self.assertEqual(r.json()["tienda_nombre"], "Vida")

    def test_monto_no_positivo_400(self):
        for monto in (0, -1):
            r = self.crear_obligacion(monto=monto)
            self.assertEqual(r.status_code, 400, f"monto={monto}: {r.text}")

    def test_concepto_vacio_400(self):
        r = self.crear_obligacion(concepto="   ")
        self.assertEqual(r.status_code, 400, r.text)

    def test_categoria_inexistente_o_inactiva_400(self):
        r = self.crear_obligacion(categoria_id=9999)
        self.assertEqual(r.status_code, 400, r.text)
        # Baja lógica: una categoría desactivada no puede recibir gastos nuevos.
        r = self.crear_obligacion(categoria_id=self.cat_vieja.id)
        self.assertEqual(r.status_code, 400, r.text)

    def test_sede_inexistente_400(self):
        r = self.crear_obligacion(tienda_id=9999)
        self.assertEqual(r.status_code, 400, r.text)

    def test_sin_fecha_devengo_422(self):
        # fecha_devengo define A QUÉ MES pertenece el costo en el P&L: sin ella la
        # obligación no se puede ubicar en el tiempo.
        r = self.client.post("/api/v1/costos/obligaciones", json={
            "categoria_id": self.cat_arriendo.id, "concepto": "Arriendo", "monto": 1000,
        })
        self.assertEqual(r.status_code, 422, r.text)

    # ── Estado DERIVADO de la suma de pagos ──────────────────────────────────

    def test_estado_pendiente_sin_pagos(self):
        oid = self.crear_obligacion().json()["id"]
        o = self._uno(oid)
        self.assertEqual(o["estado"], "pendiente")
        self.assertEqual(o["pagado"], 0)
        self.assertEqual(o["saldo"], 3000000)

    def test_estado_parcial_con_pago_parcial(self):
        oid = self.crear_obligacion().json()["id"]
        r = self.pagar(oid, 1000000)
        self.assertEqual(r.status_code, 200, r.text)
        o = self._uno(oid)
        self.assertEqual(o["estado"], "parcial")
        self.assertEqual(o["pagado"], 1000000)
        self.assertEqual(o["saldo"], 2000000)

    def test_estado_pagada_cuando_los_pagos_suman_el_monto(self):
        oid = self.crear_obligacion().json()["id"]
        self.assertEqual(self.pagar(oid, 1000000).status_code, 200)
        self.assertEqual(self.pagar(oid, 2000000, fecha_pago="2026-08-20").status_code, 200)
        o = self._uno(oid)
        self.assertEqual(o["estado"], "pagada")
        self.assertEqual(o["pagado"], 3000000)
        self.assertEqual(o["saldo"], 0)
        self.assertEqual(len(o["pagos"]), 2)

    def test_pago_de_mas_deja_la_obligacion_pagada_sin_saldo_negativo(self):
        oid = self.crear_obligacion().json()["id"]
        self.assertEqual(self.pagar(oid, 5000000).status_code, 200)
        o = self._uno(oid)
        self.assertEqual(o["estado"], "pagada")
        self.assertEqual(o["saldo"], 0)   # el saldo nunca es negativo

    # ── Bajas lógicas (nunca DELETE: dejaría pagos huérfanos) ────────────────

    def test_anular_obligacion_la_saca_de_listados_y_totales(self):
        oid_a = self.crear_obligacion().json()["id"]
        oid_b = self.crear_obligacion(concepto="Internet", monto=200000,
                                      categoria_id=self.cat_servicios.id).json()["id"]
        antes = self.listar()
        self.assertEqual(antes["totales"]["monto"], 3200000)

        r = self.client.delete(f"/api/v1/costos/obligaciones/{oid_a}")
        self.assertEqual(r.status_code, 200, r.text)

        despues = self.listar()
        self.assertIsNone(self._uno(oid_a))
        self.assertIsNotNone(self._uno(oid_b))
        self.assertEqual(despues["totales"]["monto"], 200000)
        self.assertEqual(despues["totales"]["n"], 1)
        # Sigue existiendo: se puede pedir explícitamente por estado.
        anuladas = self.listar(estado="anulada")
        self.assertEqual([o["id"] for o in anuladas["obligaciones"]], [oid_a])

    def test_pago_sobre_obligacion_anulada_400(self):
        oid = self.crear_obligacion().json()["id"]
        self.assertEqual(self.client.delete(f"/api/v1/costos/obligaciones/{oid}").status_code, 200)
        r = self.pagar(oid, 1000)
        self.assertEqual(r.status_code, 400, r.text)

    def test_anular_pago_devuelve_de_pagada_a_parcial(self):
        oid = self.crear_obligacion().json()["id"]
        p1 = self.pagar(oid, 1000000).json()
        p2 = self.pagar(oid, 2000000, fecha_pago="2026-08-20").json()
        self.assertEqual(self._uno(oid)["estado"], "pagada")

        r = self.client.delete(f"/api/v1/costos/pagos/{p2['id']}")
        self.assertEqual(r.status_code, 200, r.text)

        o = self._uno(oid)
        self.assertEqual(o["estado"], "parcial")
        self.assertEqual(o["pagado"], 1000000)
        self.assertEqual(o["saldo"], 2000000)
        # El pago anulado no cuenta pero no se borra (la traza queda).
        self.assertEqual([p["id"] for p in o["pagos"]], [p1["id"]])

    # ── Validación de pagos ──────────────────────────────────────────────────

    def test_pago_monto_no_positivo_400(self):
        oid = self.crear_obligacion().json()["id"]
        for monto in (0, -5000):
            r = self.pagar(oid, monto)
            self.assertEqual(r.status_code, 400, f"monto={monto}: {r.text}")

    def test_pago_sin_fecha_pago_422(self):
        # fecha_pago es EL DÍA QUE SALIÓ LA PLATA — sin ella el pago no sirve
        # para nada (es justamente la columna que hoy no existe en ningún lado).
        oid = self.crear_obligacion().json()["id"]
        r = self.client.post("/api/v1/costos/pagos", json={
            "obligacion_id": oid, "monto": 1000, "metodo": "efectivo",
        })
        self.assertEqual(r.status_code, 422, r.text)

    def test_pago_no_puede_apuntar_a_obligacion_y_factura_a_la_vez(self):
        oid = self.crear_obligacion().json()["id"]
        r = self.pagar(oid, 1000, factura_id=1)
        self.assertEqual(r.status_code, 400, r.text)

    def test_pago_sin_obligacion_ni_factura_400(self):
        r = self.client.post("/api/v1/costos/pagos", json={
            "monto": 1000, "fecha_pago": "2026-08-05", "metodo": "efectivo",
        })
        self.assertEqual(r.status_code, 400, r.text)

    def test_pago_metodo_invalido_400(self):
        oid = self.crear_obligacion().json()["id"]
        r = self.pagar(oid, 1000, metodo="bitcoin")
        self.assertEqual(r.status_code, 400, r.text)

    def test_pago_a_obligacion_inexistente_404(self):
        r = self.pagar(9999, 1000)
        self.assertEqual(r.status_code, 404, r.text)

    def test_pago_hereda_la_sede_de_la_obligacion(self):
        oid = self.crear_obligacion(tienda_id=self.tienda_2.id).json()["id"]
        p = self.pagar(oid, 1000).json()
        self.assertEqual(p["tienda_id"], self.tienda_2.id)

    # ── Filtros ──────────────────────────────────────────────────────────────

    def test_filtro_por_sede_distingue_corporativas_sin_ocultarlas_en_todas(self):
        corp = self.crear_obligacion(concepto="Arriendo corporativo").json()["id"]
        v1 = self.crear_obligacion(tienda_id=self.tienda_1.id, concepto="Energía Vida",
                                   categoria_id=self.cat_servicios.id, monto=100000).json()["id"]
        v2 = self.crear_obligacion(tienda_id=self.tienda_2.id, concepto="Energía Palmetto",
                                   categoria_id=self.cat_servicios.id, monto=200000).json()["id"]

        # "Todas" NO puede esconder las corporativas: son el gasto más grande.
        todas = {o["id"] for o in self.listar()["obligaciones"]}
        self.assertEqual(todas, {corp, v1, v2})

        # Una sede concreta trae SOLO lo suyo.
        solo_1 = {o["id"] for o in self.listar(tienda_id=self.tienda_1.id)["obligaciones"]}
        self.assertEqual(solo_1, {v1})

        # Y las corporativas se pueden aislar.
        solo_corp = {o["id"] for o in self.listar(solo_corporativas=True)["obligaciones"]}
        self.assertEqual(solo_corp, {corp})

    def test_filtro_por_categoria_y_por_estado(self):
        arr = self.crear_obligacion().json()["id"]
        srv = self.crear_obligacion(concepto="Agua", categoria_id=self.cat_servicios.id,
                                    monto=90000).json()["id"]
        self.pagar(srv, 90000)

        ids = {o["id"] for o in self.listar(categoria="servicios")["obligaciones"]}
        self.assertEqual(ids, {srv})
        ids = {o["id"] for o in self.listar(estado="pendiente")["obligaciones"]}
        self.assertEqual(ids, {arr})
        ids = {o["id"] for o in self.listar(estado="pagada")["obligaciones"]}
        self.assertEqual(ids, {srv})

    def test_filtro_por_rango_de_devengo_y_de_vencimiento(self):
        jul = self.crear_obligacion(concepto="Arriendo julio", fecha_devengo="2026-07-01",
                                    fecha_vencimiento="2026-07-10").json()["id"]
        ago = self.crear_obligacion(concepto="Arriendo agosto", fecha_devengo="2026-08-01",
                                    fecha_vencimiento="2026-08-10").json()["id"]

        ids = {o["id"] for o in self.listar(desde="2026-08-01", hasta="2026-08-31")["obligaciones"]}
        self.assertEqual(ids, {ago})
        ids = {o["id"] for o in self.listar(campo_fecha="vencimiento", desde="2026-07-01",
                                            hasta="2026-07-31")["obligaciones"]}
        self.assertEqual(ids, {jul})

    def test_totales_descuentan_lo_ya_pagado(self):
        oid = self.crear_obligacion().json()["id"]
        self.pagar(oid, 1000000)
        t = self.listar()["totales"]
        self.assertEqual(t["monto"], 3000000)
        self.assertEqual(t["pagado"], 1000000)
        self.assertEqual(t["saldo"], 2000000)

    # ── Edición ──────────────────────────────────────────────────────────────

    def test_editar_obligacion(self):
        oid = self.crear_obligacion().json()["id"]
        r = self.client.patch(f"/api/v1/costos/obligaciones/{oid}", json={
            "concepto": "Arriendo agosto (corregido)", "monto": 3200000,
            "beneficiario": "Inmobiliaria X", "tienda_id": self.tienda_1.id,
        })
        self.assertEqual(r.status_code, 200, r.text)
        o = self._uno(oid)
        self.assertEqual(o["concepto"], "Arriendo agosto (corregido)")
        self.assertEqual(o["monto"], 3200000)
        self.assertEqual(o["beneficiario"], "Inmobiliaria X")
        self.assertEqual(o["tienda_id"], self.tienda_1.id)

    def test_editar_con_monto_no_positivo_400(self):
        oid = self.crear_obligacion().json()["id"]
        r = self.client.patch(f"/api/v1/costos/obligaciones/{oid}", json={"monto": 0})
        self.assertEqual(r.status_code, 400, r.text)

    # ── Categorías ───────────────────────────────────────────────────────────

    def test_listar_categorias_solo_activas_y_ordenadas(self):
        r = self.client.get("/api/v1/costos/categorias")
        self.assertEqual(r.status_code, 200, r.text)
        claves = [c["clave"] for c in r.json()]
        self.assertEqual(claves, ["arriendo", "servicios"])   # 'obsoleta' está inactiva

    # ── Rol ──────────────────────────────────────────────────────────────────

    def test_barista_403_en_todos_los_endpoints(self):
        oid = self.crear_obligacion().json()["id"]
        pid = self.pagar(oid, 1000).json()["id"]
        self.set_current_user(self.barista)
        llamadas = [
            ("get",    "/api/v1/costos/categorias", None),
            ("get",    "/api/v1/costos/obligaciones", None),
            ("post",   "/api/v1/costos/obligaciones", {"categoria_id": self.cat_arriendo.id,
                                                       "concepto": "X", "monto": 100,
                                                       "fecha_devengo": "2026-08-01"}),
            ("patch",  f"/api/v1/costos/obligaciones/{oid}", {"monto": 50}),
            ("delete", f"/api/v1/costos/obligaciones/{oid}", None),
            ("post",   "/api/v1/costos/pagos", {"obligacion_id": oid, "monto": 100,
                                                "fecha_pago": "2026-08-05",
                                                "metodo": "efectivo"}),
            ("delete", f"/api/v1/costos/pagos/{pid}", None),
        ]
        for metodo, url, body in llamadas:
            r = getattr(self.client, metodo)(url, **({"json": body} if body else {}))
            self.assertEqual(r.status_code, 403, f"{metodo.upper()} {url}: {r.text}")


if __name__ == "__main__":
    unittest.main()
