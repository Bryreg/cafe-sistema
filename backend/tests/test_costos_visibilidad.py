"""Fase 1 de desbloqueo del módulo Costos: que lo cargado SE VEA y que no se
cuente dos veces.

El dueño dice «no veo nómina ni arriendo». No es que no se guarde: es que la
Agenda —la pestaña por defecto— esconde tres cosas.

  A2. Una obligación SIN fecha de vencimiento no aparece en ningún lado. «Vence»
      es opcional en el formulario, así que el caso normal (cargar lo obligatorio
      y nada más) produce una pantalla vacía.
  A3. La Agenda rotula por TIPO ('Costo fijo' / 'Proveedor') y nunca por
      CATEGORÍA, aunque el backend ya la manda. Las palabras «Nómina» y
      «Arriendo» no aparecen en la pestaña que el dueño abre primero.
  A4. La categoría 'proveedores' es una trampa de doble conteo: el P&L suma todas
      las obligaciones devengadas Y las FacturaCompra por fecha de recibido.
  A5. `recurrencia` y `plantilla_id` son columnas muertas: con 2 sedes son 12-18
      cargas manuales por mes.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base, get_db
from app.models.models import (CostoCategoria, FacturaCompra, RolEnum, Tienda,
                               TipoPagoEnum, Usuario)
from app.routers import costos as costos_router


class CostosVisibilidadTest(unittest.TestCase):
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
        self.db.add(self.admin)
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                           grupo="fijo", orden=0)
        self.cat_nomina = CostoCategoria(clave="nomina", nombre="Nómina",
                                         grupo="fijo", orden=1)
        # Categoría LEGACY: ya sembrada en las bases que corrieron la versión
        # anterior. No se puede borrar la fila (dejaría obligaciones huérfanas),
        # así que el cierre del agujero tiene que funcionar con ella presente.
        self.cat_proveedores = CostoCategoria(clave="proveedores", nombre="Proveedores",
                                              grupo="variable", orden=3)
        self.db.add_all([self.cat_arriendo, self.cat_nomina, self.cat_proveedores])
        self.db.commit()

        self.hoy = hoy_col()

        app = FastAPI(title="Test costos visibilidad")
        app.include_router(costos_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def dia(self, delta: int) -> date:
        return self.hoy + timedelta(days=delta)

    def crear(self, *, concepto="Arriendo agosto", monto=3000000, categoria=None,
              devengo=None, vencimiento=None, tienda_id="corp", esperado=200):
        body = {
            "categoria_id": (categoria or self.cat_arriendo).id,
            "concepto": concepto,
            "monto": monto,
            "fecha_devengo": str(devengo or self.dia(0)),
        }
        if vencimiento is not None:
            body["fecha_vencimiento"] = str(vencimiento)
        if tienda_id != "corp":
            body["tienda_id"] = tienda_id
        r = self.client.post("/api/v1/costos/obligaciones", json=body)
        self.assertEqual(r.status_code, esperado, r.text)
        return r

    def agenda(self, **params):
        r = self.client.get("/api/v1/costos/agenda", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── A2 · una obligación sin «Vence» no puede ser invisible ───────────────

    def test_obligacion_sin_vencimiento_sale_en_su_propio_bloque(self):
        # El caso que rompe la confianza: el dueño teclea lo obligatorio (concepto,
        # monto, devengo), deja «Vence» vacío porque es opcional, y la Agenda le
        # devuelve una pantalla vacía. Ahora sale aparte, no agendada pero VISIBLE.
        sin = self.crear(concepto="Nómina quincena", monto=4200000,
                         categoria=self.cat_nomina, vencimiento=None).json()["id"]
        con = self.crear(concepto="Arriendo agosto", vencimiento=self.dia(5)).json()["id"]

        data = self.agenda()

        self.assertEqual([(i["tipo"], i["id"]) for i in data["items"]],
                         [("obligacion", con)])
        self.assertEqual([i["id"] for i in data["sin_fecha"]], [sin])
        sf = data["sin_fecha"][0]
        self.assertEqual(sf["concepto"], "Nómina quincena")
        self.assertEqual(sf["monto"], 4200000)      # el SALDO, igual que en items
        self.assertEqual(sf["categoria"], "nomina")

    def test_lo_sin_fecha_no_se_suma_al_total_de_la_agenda(self):
        # Sin fecha no se puede proyectar: si entrara al total, el dueño creería
        # que ese dinero está agendado para algún día de este período.
        self.crear(concepto="Nómina quincena", monto=4200000,
                   categoria=self.cat_nomina, vencimiento=None)
        self.crear(concepto="Arriendo", monto=3000000, vencimiento=self.dia(5))

        t = self.agenda()["totales"]
        self.assertEqual(t["monto"], 3000000)
        self.assertEqual(t["n"], 1)
        # …pero el total pendiente de fechar se declara aparte, para que la
        # pantalla pueda decir cuánta plata está sin agendar.
        self.assertEqual(t["sin_fecha"], 4200000)
        self.assertEqual(t["n_sin_fecha"], 1)

    def test_lo_sin_fecha_no_entra_en_el_flujo_proyectado(self):
        # Sin fecha NO se proyecta: inventarle un día sería fabricar un punto de
        # quiebre (o esconderlo) con un dato que nadie cargó.
        self.crear(concepto="Nómina sin fecha", monto=999_000_000,
                   categoria=self.cat_nomina, vencimiento=None)
        r = self.client.get("/api/v1/costos/flujo", params={"dias": 30})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["totales"]["salidas"], 0)

    def test_sin_fecha_respeta_el_filtro_de_sede_y_excluye_pagadas_y_anuladas(self):
        propia = self.crear(concepto="Energía Vida", monto=200000, vencimiento=None,
                            tienda_id=self.tienda_1.id).json()["id"]
        self.crear(concepto="Energía Palmetto", monto=300000, vencimiento=None,
                   tienda_id=self.tienda_2.id)
        pagada = self.crear(concepto="Agua Vida", monto=50000, vencimiento=None,
                            tienda_id=self.tienda_1.id).json()["id"]
        self.client.post("/api/v1/costos/pagos", json={
            "obligacion_id": pagada, "monto": 50000,
            "fecha_pago": str(self.dia(0)), "metodo": "transferencia"})
        anulada = self.crear(concepto="Anulada Vida", monto=70000, vencimiento=None,
                             tienda_id=self.tienda_1.id).json()["id"]
        self.client.delete(f"/api/v1/costos/obligaciones/{anulada}")

        data = self.agenda(tienda_id=self.tienda_1.id)
        self.assertEqual([i["id"] for i in data["sin_fecha"]], [propia])

    # ── A3 · la categoría tiene que verse ────────────────────────────────────

    def test_cada_item_de_la_agenda_trae_el_nombre_de_su_categoria(self):
        # La agenda ya mandaba la clave ('nomina') pero no el nombre que se pinta.
        # Sin el nombre, la fila solo puede rotularse por TIPO y las palabras que
        # el dueño busca —Nómina, Arriendo— no aparecen en ninguna pantalla.
        self.crear(concepto="Nómina quincena", monto=4200000,
                   categoria=self.cat_nomina, vencimiento=self.dia(3))
        item = self.agenda()["items"][0]
        self.assertEqual(item["categoria"], "nomina")
        self.assertEqual(item["categoria_nombre"], "Nómina")

    def test_la_agenda_resume_cuanta_plata_hay_por_categoria(self):
        self.crear(concepto="Arriendo", monto=3000000, vencimiento=self.dia(2))
        self.crear(concepto="Nómina 1ra", monto=2000000,
                   categoria=self.cat_nomina, vencimiento=self.dia(4))
        self.crear(concepto="Nómina 2da", monto=1000000,
                   categoria=self.cat_nomina, vencimiento=self.dia(6))
        f = FacturaCompra(tienda_id=self.tienda_1.id, proveedor="Lácteos S.A.",
                          valor_total=500000, valor_pagado=0,
                          tipo_pago=TipoPagoEnum.credito, usuario_id=self.admin.id,
                          fecha_vencimiento=inicio_dia_col_utc(self.dia(3)))
        self.db.add(f)
        self.db.commit()

        por_cat = {g["clave"]: g for g in self.agenda()["por_categoria"]}
        self.assertEqual(por_cat["nomina"]["nombre"], "Nómina")
        self.assertEqual(por_cat["nomina"]["monto"], 3000000)
        self.assertEqual(por_cat["nomina"]["n"], 2)
        self.assertEqual(por_cat["arriendo"]["monto"], 3000000)
        # Las facturas no pasan por el catálogo de costos: van a su propio grupo,
        # nunca mezcladas dentro de una categoría de costo fijo.
        self.assertEqual(por_cat["facturas"]["monto"], 500000)
        # Ordenado por plata, que es como se lee («qué me está costando más»).
        self.assertEqual([g["monto"] for g in self.agenda()["por_categoria"]],
                         sorted([g["monto"] for g in self.agenda()["por_categoria"]],
                                reverse=True))

    # ── A4 · 'proveedores' es una trampa de doble conteo ─────────────────────

    def test_no_se_puede_cargar_una_obligacion_en_la_categoria_proveedores(self):
        r = self.crear(concepto="Leche de agosto", monto=800000,
                       categoria=self.cat_proveedores, esperado=400)
        # El mensaje tiene que decir DÓNDE va, no solo que no va acá.
        self.assertIn("factura", r.json()["detail"].lower())

    def test_tampoco_se_puede_mover_una_obligacion_a_proveedores(self):
        oid = self.crear(concepto="Arriendo", monto=3000000).json()["id"]
        r = self.client.patch(f"/api/v1/costos/obligaciones/{oid}",
                              json={"categoria_id": self.cat_proveedores.id})
        self.assertEqual(r.status_code, 400, r.text)

    def test_la_categoria_proveedores_no_se_ofrece_en_el_catalogo(self):
        # Sigue existiendo la fila (hay obligaciones históricas apuntándole), pero
        # no se ofrece: una categoría que el servicio rechaza no puede estar en el
        # desplegable del formulario.
        r = self.client.get("/api/v1/costos/categorias")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("proveedores", [c["clave"] for c in r.json()])

    def test_una_obligacion_historica_en_proveedores_no_se_cuenta_dos_veces_en_el_pyl(self):
        # El agujero: la mercadería YA entra al P&L por FacturaCompra (fecha de
        # recibido) y la obligación devengada sumaba encima. Mismo dinero, dos veces.
        from app.models.models import Obligacion
        from app.services.rentabilidad import get_rentabilidad

        f = FacturaCompra(tienda_id=self.tienda_1.id, proveedor="Lácteos S.A.",
                          valor_total=800000, valor_pagado=0,
                          tipo_pago=TipoPagoEnum.credito, usuario_id=self.admin.id,
                          fecha_recibido=inicio_dia_col_utc(self.dia(0)))
        # Fila LEGACY creada por la versión anterior, cuando el servicio la aceptaba.
        self.db.add_all([f, Obligacion(
            tienda_id=self.tienda_1.id, categoria_id=self.cat_proveedores.id,
            concepto="Leche de agosto", monto=800000, fecha_devengo=self.dia(0),
            usuario_id=self.admin.id)])
        # Un costo fijo real del mismo día: lo que SÍ tiene que sumar.
        self.db.add(Obligacion(
            tienda_id=None, categoria_id=self.cat_arriendo.id, concepto="Arriendo",
            monto=3000000, fecha_devengo=self.dia(0), usuario_id=self.admin.id))
        self.db.commit()

        res = get_rentabilidad(self.db, self.dia(-1), self.dia(1))
        self.assertEqual(res["resumen"]["compras"], 800000)
        # 3.000.000 del arriendo y NI UN PESO de la obligación de proveedores.
        self.assertEqual(res["resumen"]["gastos"], 3000000)

    # ── A5 · repetir el costo del mes que viene en un tap ────────────────────

    def test_repetir_crea_la_copia_del_mes_siguiente_enlazada(self):
        oid = self.crear(concepto="Arriendo agosto", monto=3000000,
                         devengo=date(2026, 8, 1), vencimiento=date(2026, 8, 5)).json()["id"]

        r = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir")
        self.assertEqual(r.status_code, 200, r.text)
        copia = r.json()

        self.assertFalse(copia["ya_existia"])
        self.assertNotEqual(copia["id"], oid)
        self.assertEqual(copia["fecha_devengo"], "2026-09-01")
        self.assertEqual(copia["fecha_vencimiento"], "2026-09-05")
        self.assertEqual(copia["monto"], 3000000)
        self.assertEqual(copia["concepto"], "Arriendo agosto")
        self.assertEqual(copia["estado"], "pendiente")   # nace sin pagos
        # Enlazada por plantilla_id al ORIGEN de la serie (no al padre inmediato):
        # así la serie entera comparte una sola llave.
        self.assertEqual(copia["plantilla_id"], oid)

    def test_repetir_dos_veces_no_duplica_el_costo(self):
        # Un dedo doble en el botón no puede cobrar el arriendo dos veces.
        oid = self.crear(concepto="Arriendo agosto", monto=3000000,
                         devengo=date(2026, 8, 1), vencimiento=date(2026, 8, 5)).json()["id"]
        primera = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir").json()
        segunda = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir").json()

        self.assertEqual(segunda["id"], primera["id"])
        self.assertTrue(segunda["ya_existia"])
        r = self.client.get("/api/v1/costos/obligaciones",
                            params={"desde": "2026-09-01", "hasta": "2026-09-30"})
        self.assertEqual(r.json()["totales"]["n"], 1)

    def test_repetir_encadena_desde_la_copia_sin_perder_la_serie(self):
        oid = self.crear(concepto="Arriendo agosto", monto=3000000,
                         devengo=date(2026, 8, 1), vencimiento=date(2026, 8, 5)).json()["id"]
        sept = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir").json()
        oct_ = self.client.post(f"/api/v1/costos/obligaciones/{sept['id']}/repetir").json()

        self.assertFalse(oct_["ya_existia"])
        self.assertEqual(oct_["fecha_devengo"], "2026-10-01")
        self.assertEqual(oct_["plantilla_id"], oid)   # misma serie, no una nueva

    def test_repetir_desde_fin_de_mes_no_inventa_un_31_de_febrero(self):
        oid = self.crear(concepto="Nómina enero", monto=4000000,
                         categoria=self.cat_nomina,
                         devengo=date(2026, 1, 31), vencimiento=date(2026, 1, 31)).json()["id"]
        copia = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir").json()
        self.assertEqual(copia["fecha_devengo"], "2026-02-28")
        self.assertEqual(copia["fecha_vencimiento"], "2026-02-28")

    def test_repetir_conserva_una_obligacion_sin_vencimiento_sin_vencimiento(self):
        # No se le inventa una fecha de pago a la copia: si el original no la
        # tenía, la copia tampoco (y sale en el bloque «sin fecha» como el padre).
        oid = self.crear(concepto="Servicios", monto=400000,
                         devengo=date(2026, 8, 1), vencimiento=None).json()["id"]
        copia = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir").json()
        self.assertEqual(copia["fecha_devengo"], "2026-09-01")
        self.assertIsNone(copia["fecha_vencimiento"])

    def test_no_se_repite_una_obligacion_legacy_de_proveedores(self):
        # `repetir_obligacion` copiaba `categoria_id` del origen sin pasar por
        # `_validar_categoria`, que es la puerta única donde se bloquea
        # 'proveedores'. Una obligación legacy de proveedor se replicaba mes a
        # mes hacia la Agenda y el Flujo, reinstalando el doble conteo que A4
        # vino a cerrar — y por un botón, no por el formulario.
        from app.models.models import Obligacion
        legacy = Obligacion(
            tienda_id=self.tienda_1.id, categoria_id=self.cat_proveedores.id,
            concepto="Leche de agosto", monto=800000,
            fecha_devengo=date(2026, 8, 1), usuario_id=self.admin.id)
        self.db.add(legacy)
        self.db.commit()

        r = self.client.post(f"/api/v1/costos/obligaciones/{legacy.id}/repetir")

        self.assertEqual(r.status_code, 400, r.text)
        detalle = r.json()["detail"].lower()
        self.assertIn("repetir", detalle)      # por qué falló ESTA acción
        self.assertIn("factura", detalle)      # y qué hacer en su lugar
        # Nada se creó en septiembre.
        listado = self.client.get("/api/v1/costos/obligaciones",
                                  params={"desde": "2026-09-01", "hasta": "2026-09-30"})
        self.assertEqual(listado.json()["totales"]["n"], 0)

    def test_tampoco_se_repite_una_obligacion_de_categoria_desactivada(self):
        # Misma puerta, otro caso: la categoría se desactivó después de crear la
        # obligación. Repetirla la resucitaría un mes más.
        oid = self.crear(concepto="Arriendo", monto=3000000,
                         devengo=date(2026, 8, 1)).json()["id"]
        self.cat_arriendo.activa = False
        self.db.commit()

        r = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir")
        self.assertEqual(r.status_code, 400, r.text)

    def test_no_se_repite_una_obligacion_anulada(self):
        oid = self.crear(concepto="Arriendo", monto=3000000).json()["id"]
        self.client.delete(f"/api/v1/costos/obligaciones/{oid}")
        r = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir")
        self.assertEqual(r.status_code, 400, r.text)


if __name__ == "__main__":
    unittest.main()
