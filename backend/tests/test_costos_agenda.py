"""Módulo Costos — Fase 2: vencimientos en facturas + agenda unificada.

Por primera vez existe UNA sola lista de "qué tengo que pagar esta semana" que
mezcla proveedores y costos fijos. Hoy viven en dos mundos incomunicados:
/pagos-proveedores (facturas) y /costos (arriendo, nómina, servicios).

PRINCIPIO INNEGOCIABLE que prueban estos tests: FacturaCompra sigue siendo la
ÚNICA verdad de la deuda con proveedores. La agenda es la UNIÓN DE DOS CONSULTAS,
nunca una tabla copiada — no se crean obligaciones espejo de las facturas. Copiar
la deuda a `obligaciones` crearía dos verdades sobre la misma plata.

Reglas cubiertas:

- la fecha proyectada de una factura es COALESCE(fecha_programada,
  fecha_vencimiento, fecha_recibido + plazo_dias): lo que el dueño DECIDIÓ manda
  sobre lo que el proveedor exige, y eso manda sobre el plazo derivado;
- si las tres son NULL la factura NO aparece: no se inventa un vencimiento
  (las facturas históricas quedan sin fecha a propósito — no hay tabla maestra de
  proveedores de donde derivar un plazo);
- el monto que se agenda es el SALDO, nunca el total;
- las obligaciones corporativas (tienda_id NULL) aparecen en "todas las sedes"
  una sola vez, sin duplicarse entre sedes;
- todo el módulo sigue siendo solo-admin (require_admin).
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


class CostosAgendaTest(unittest.TestCase):
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
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo", grupo="fijo", orden=0)
        self.db.add(self.cat_arriendo)
        self.db.commit()

        self.hoy = hoy_col()

        app = FastAPI(title="Test costos agenda")
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

    def dia(self, delta: int) -> date:
        """Día Colombia relativo a hoy — `vencida` se mide contra hoy, no contra
        una fecha fija del calendario."""
        return self.hoy + timedelta(days=delta)

    def factura(self, *, proveedor="Lácteos S.A.", total=100000, pagado=0,
                recibido=None, vencimiento=None, plazo=None, programada=None,
                tienda=None) -> FacturaCompra:
        """Factura creada por ORM: el alta real pasa por uploads y gate de turno,
        y acá lo que importa es la fila, no el flujo de recepción."""
        f = FacturaCompra(
            tienda_id=(tienda or self.tienda_1).id,
            proveedor=proveedor,
            valor_total=total,
            valor_pagado=pagado,
            tipo_pago=TipoPagoEnum.credito,
            usuario_id=self.admin.id,
            # Timestamps guardados como medianoche COLOMBIA, igual que el alta.
            fecha_recibido=inicio_dia_col_utc(recibido) if recibido else None,
            fecha_vencimiento=inicio_dia_col_utc(vencimiento) if vencimiento else None,
            plazo_dias=plazo,
            fecha_programada=inicio_dia_col_utc(programada) if programada else None,
        )
        self.db.add(f)
        self.db.commit()
        self.db.refresh(f)
        return f

    def obligacion(self, *, concepto="Arriendo agosto", monto=3000000,
                   devengo=None, vencimiento=None, tienda_id="corp") -> int:
        body = {
            "categoria_id": self.cat_arriendo.id,
            "concepto": concepto,
            "monto": monto,
            "fecha_devengo": str(devengo or self.dia(0)),
        }
        if vencimiento is not None:
            body["fecha_vencimiento"] = str(vencimiento)
        if tienda_id != "corp":
            body["tienda_id"] = tienda_id
        r = self.client.post("/api/v1/costos/obligaciones", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def pagar_obligacion(self, obligacion_id, monto):
        r = self.client.post("/api/v1/costos/pagos", json={
            "obligacion_id": obligacion_id, "monto": monto,
            "fecha_pago": str(self.dia(0)), "metodo": "transferencia"})
        self.assertEqual(r.status_code, 200, r.text)

    def agenda(self, **params):
        r = self.client.get("/api/v1/costos/agenda", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def items(self, **params):
        return self.agenda(**params)["items"]

    def _item(self, items, tipo, id_):
        return [i for i in items if i["tipo"] == tipo and i["id"] == id_]

    # ── La unión ─────────────────────────────────────────────────────────────

    def test_agenda_mezcla_facturas_y_obligaciones_ordenadas_por_fecha(self):
        # El valor de la fase: una sola lista donde el arriendo y el proveedor de
        # leche compiten por la misma plata, ordenados por cuándo hay que pagar.
        f_tarde = self.factura(proveedor="Café del Huila", total=500000,
                               vencimiento=self.dia(9))
        oblig = self.obligacion(vencimiento=self.dia(2))
        f_pronto = self.factura(proveedor="Lácteos S.A.", total=100000,
                                vencimiento=self.dia(5))

        items = self.items()
        self.assertEqual(
            [(i["tipo"], i["id"]) for i in items],
            [("obligacion", oblig), ("factura", f_pronto.id), ("factura", f_tarde.id)],
        )
        # Cada ítem dice de qué mundo viene y a quién se le paga.
        prov = self._item(items, "factura", f_pronto.id)[0]
        self.assertEqual(prov["concepto"], "Lácteos S.A.")
        self.assertEqual(prov["tienda_id"], self.tienda_1.id)
        self.assertEqual(prov["fecha"], str(self.dia(5)))
        fijo = self._item(items, "obligacion", oblig)[0]
        self.assertEqual(fijo["concepto"], "Arriendo agosto")
        self.assertEqual(fijo["categoria"], "arriendo")
        self.assertIsNone(fijo["tienda_id"])   # corporativo

    def test_factura_pagada_al_100_no_aparece(self):
        self.factura(total=100000, pagado=100000, vencimiento=self.dia(3))
        pendiente = self.factura(total=80000, pagado=0, vencimiento=self.dia(3))
        items = self.items()
        self.assertEqual([(i["tipo"], i["id"]) for i in items], [("factura", pendiente.id)])

    def test_obligacion_pagada_al_100_no_aparece(self):
        oblig = self.obligacion(monto=200000, vencimiento=self.dia(4))
        self.pagar_obligacion(oblig, 200000)
        self.assertEqual(self.items(), [])

    # ── Precedencia de fechas ────────────────────────────────────────────────

    def test_fecha_programada_manda_sobre_vencimiento_y_vencimiento_sobre_plazo(self):
        # Lo que el dueño DECIDIÓ pagar manda sobre lo que el proveedor exige;
        # y el vencimiento explícito manda sobre el derivado del plazo.
        decidida = self.factura(proveedor="A", vencimiento=self.dia(10),
                                recibido=self.dia(-5), plazo=30, programada=self.dia(3))
        exigida = self.factura(proveedor="B", vencimiento=self.dia(7),
                               recibido=self.dia(-5), plazo=30)
        derivada = self.factura(proveedor="C", recibido=self.dia(-2), plazo=15)

        por_id = {i["id"]: i for i in self.items() if i["tipo"] == "factura"}
        self.assertEqual(por_id[decidida.id]["fecha"], str(self.dia(3)))
        self.assertEqual(por_id[exigida.id]["fecha"], str(self.dia(7)))
        self.assertEqual(por_id[derivada.id]["fecha"], str(self.dia(13)))

    def test_factura_sin_ninguna_fecha_no_aparece(self):
        # NO se inventa un vencimiento: no existe tabla maestra de proveedores de
        # donde derivar un plazo, así que las históricas quedan fuera hasta que
        # alguien les cargue el plazo a mano.
        self.factura(proveedor="Histórica", recibido=self.dia(-40))
        # plazo_dias sin fecha_recibido tampoco alcanza: no hay de dónde contar.
        self.factura(proveedor="Sin recibido", plazo=30)
        self.assertEqual(self.items(), [])

    def test_obligacion_sin_fecha_vencimiento_no_aparece(self):
        self.obligacion(concepto="Nómina sin fecha", vencimiento=None)
        con_fecha = self.obligacion(concepto="Arriendo", vencimiento=self.dia(6))
        items = self.items()
        self.assertEqual([(i["tipo"], i["id"]) for i in items], [("obligacion", con_fecha)])

    # ── El monto agendado es el SALDO ────────────────────────────────────────

    def test_el_monto_es_el_saldo_no_el_total(self):
        f = self.factura(total=100000, pagado=40000, vencimiento=self.dia(2))
        oblig = self.obligacion(monto=3000000, vencimiento=self.dia(3))
        self.pagar_obligacion(oblig, 1000000)

        data = self.agenda()
        por_clave = {(i["tipo"], i["id"]): i for i in data["items"]}
        self.assertEqual(por_clave[("factura", f.id)]["monto"], 60000)
        self.assertEqual(por_clave[("obligacion", oblig)]["monto"], 2000000)
        # El total del período es lo que falta pagar, no lo facturado.
        self.assertEqual(data["totales"]["monto"], 2060000)
        self.assertEqual(data["totales"]["n"], 2)

    # ── Vencida ──────────────────────────────────────────────────────────────

    def test_vencida_solo_cuando_hay_saldo_y_la_fecha_ya_paso(self):
        atrasada = self.factura(proveedor="Atrasada", total=50000, vencimiento=self.dia(-3))
        proxima = self.factura(proveedor="Próxima", total=50000, vencimiento=self.dia(4))
        oblig_atrasada = self.obligacion(concepto="Energía", monto=90000,
                                         vencimiento=self.dia(-1))

        por_clave = {(i["tipo"], i["id"]): i for i in self.items()}
        self.assertTrue(por_clave[("factura", atrasada.id)]["vencida"])
        self.assertFalse(por_clave[("factura", proxima.id)]["vencida"])
        self.assertTrue(por_clave[("obligacion", oblig_atrasada)]["vencida"])

        # Pagada al 100% no está "vencida": ya no está (no hay saldo que deber).
        pagada = self.factura(proveedor="Saldada", total=50000, pagado=50000,
                              vencimiento=self.dia(-3))
        self.assertEqual(self._item(self.items(), "factura", pagada.id), [])

    def test_totales_reportan_lo_vencido_aparte(self):
        self.factura(total=50000, vencimiento=self.dia(-3))
        self.factura(total=30000, vencimiento=self.dia(4))
        t = self.agenda()["totales"]
        self.assertEqual(t["monto"], 80000)
        self.assertEqual(t["vencido"], 50000)

    # ── Filtros ──────────────────────────────────────────────────────────────

    def test_obligacion_corporativa_aparece_sin_filtro_de_sede_y_no_se_duplica(self):
        # El arriendo corporativo (tienda_id NULL) es el gasto más grande:
        # esconderlo de "todas" sería mentir. Y con DOS sedes en la DB, la unión
        # no puede repetirlo una vez por sede.
        corp = self.obligacion(concepto="Arriendo corporativo", vencimiento=self.dia(2))
        items = self.items()
        self.assertEqual(len(self._item(items, "obligacion", corp)), 1)
        self.assertIsNone(self._item(items, "obligacion", corp)[0]["tienda_id"])

    def test_filtro_por_sede(self):
        f1 = self.factura(proveedor="Vida", vencimiento=self.dia(2), tienda=self.tienda_1)
        self.factura(proveedor="Palmetto", vencimiento=self.dia(2), tienda=self.tienda_2)
        o1 = self.obligacion(concepto="Energía Vida", vencimiento=self.dia(3),
                             tienda_id=self.tienda_1.id)
        self.obligacion(concepto="Energía Palmetto", vencimiento=self.dia(3),
                        tienda_id=self.tienda_2.id)

        items = self.items(tienda_id=self.tienda_1.id)
        self.assertEqual({(i["tipo"], i["id"]) for i in items},
                         {("factura", f1.id), ("obligacion", o1)})

    def test_filtro_por_rango_de_fechas(self):
        # El rango se aplica sobre la fecha PROYECTADA, no sobre fecha_recibido.
        dentro = self.factura(proveedor="Dentro", recibido=self.dia(-1), plazo=5)
        self.factura(proveedor="Fuera", vencimiento=self.dia(30))
        self.obligacion(concepto="Vieja", vencimiento=self.dia(-20))

        items = self.items(desde=str(self.dia(0)), hasta=str(self.dia(10)))
        self.assertEqual([(i["tipo"], i["id"]) for i in items], [("factura", dentro.id)])

    # ── Serialización de la factura ──────────────────────────────────────────

    def test_editar_factura_guarda_las_fechas_como_medianoche_colombia(self):
        # Mismo motivo que fecha_recibido: guardar el date pelado (00:00 UTC)
        # corre el vencimiento un día hacia atrás en los reportes.
        from app.services.facturas import editar_factura, get_factura
        f = self.factura(proveedor="Panadería Z", total=15000, recibido=self.dia(-2))
        editar_factura(self.db, f.id, self.admin.id,
                       fecha_vencimiento=self.dia(4), plazo_dias=30,
                       fecha_programada=self.dia(6))
        self.db.refresh(f)
        self.assertEqual(f.fecha_vencimiento, inicio_dia_col_utc(self.dia(4)))
        self.assertEqual(f.fecha_programada, inicio_dia_col_utc(self.dia(6)))
        self.assertEqual(f.plazo_dias, 30)

        d = get_factura(self.db, f.id)
        self.assertEqual(d["plazo_dias"], 30)
        self.assertFalse(d["vencida"])   # vence en 4 días y tiene saldo

    def test_serializar_marca_vencida_solo_con_saldo_y_vencimiento_pasado(self):
        from app.services.facturas import get_factura
        atrasada = self.factura(proveedor="Atrasada", total=50000, vencimiento=self.dia(-2))
        saldada = self.factura(proveedor="Saldada", total=50000, pagado=50000,
                               vencimiento=self.dia(-2))
        sin_fecha = self.factura(proveedor="Sin fecha", total=50000)

        self.assertTrue(get_factura(self.db, atrasada.id)["vencida"])
        self.assertFalse(get_factura(self.db, saldada.id)["vencida"])
        self.assertFalse(get_factura(self.db, sin_fecha.id)["vencida"])

    # ── Rol ──────────────────────────────────────────────────────────────────

    def test_barista_403_en_la_agenda(self):
        self.set_current_user(self.barista)
        r = self.client.get("/api/v1/costos/agenda")
        self.assertEqual(r.status_code, 403, r.text)


if __name__ == "__main__":
    unittest.main()
