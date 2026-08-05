"""Módulo Costos — Fase 3: adopción de egresos históricos SIN doble conteo.

Un `MovimientoCaja` de tipo egreso con concepto de texto libre ("Arriendo local")
se puede ADOPTAR: nace una `Obligacion` devengada + un `Pago` espejo del MISMO
monto con `movimiento_caja_id` apuntando al movimiento. **El MovimientoCaja no se
toca ni se borra**: la plata cambia de bolsa, no de tamaño.

EL INVARIANTE que prueba este archivo, y que es la razón de existir de la fase:

    adoptar un egreso NO cambia el total de gastos, ni el margen neto, ni el
    margen bruto, ni las ventas, ni las compras, ni el efectivo esperado del
    turno. Lo único que cambia es DÓNDE aparece el gasto: sale del bloque de
    texto libre (`gastos_detalle` por concepto) y entra agrupado por categoría.

Por eso el P&L hace DOS cosas simétricas y no una: excluye de la query de gastos
los movimientos ya adoptados, y suma las obligaciones devengadas del período. Si
solo hiciera una de las dos, el número se movería — y ese movimiento sería una
mentira contable, no una mejora.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import dia_col, hoy_col, inicio_dia_col_utc
from app.database import Base, get_db
from app.models.models import (
    CajaTurno, CostoCategoria, EstadoTurnoEnum, FacturaCompra, MovimientoCaja,
    Obligacion, Pago, RolEnum, Ticket, Tienda, TipoPagoEnum, Usuario,
)
from app.routers import costos as costos_router
from app.services.costos import adoptar_egreso
from app.services.rentabilidad import get_rentabilidad


class CostosInvarianteTest(unittest.TestCase):
    """Fixtures calcados de test_rentabilidad.py: los mismos egresos, para que el
    invariante se mida contra números ya pinados por esa suite."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t1 = Tienda(nombre="Vida", direccion="x")
        self.t2 = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.t1, self.t2])
        self.db.flush()
        self.u = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                         rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.u)
        self.db.flush()
        self.turno1 = CajaTurno(tienda_id=self.t1.id, usuario_apertura_id=self.u.id,
                                base_real=120000.0, total_efectivo=90000.0,
                                estado=EstadoTurnoEnum.abierto)
        self.turno2 = CajaTurno(tienda_id=self.t2.id, usuario_apertura_id=self.u.id,
                                base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add_all([self.turno1, self.turno2])
        self.db.flush()

        # Catálogo de costos (en producción lo siembra _seed_categorias_costo).
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                           grupo="fijo", orden=0)
        self.cat_servicios = CostoCategoria(clave="servicios", nombre="Servicios",
                                            grupo="fijo", orden=1)
        self.db.add_all([self.cat_arriendo, self.cat_servicios])

        # Mediodía Colombia de hoy, en UTC — cae dentro del rango [hoy, hoy].
        self.ahora = inicio_dia_col_utc(hoy_col()) + (
            datetime.min.replace(hour=12) - datetime.min)

        self.db.add_all([
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno1.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=100000, estado="completado", metodo_pago="efectivo"),
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno1.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=50000, estado="completado", metodo_pago="tarjeta"),
            Ticket(tienda_id=self.t2.id, caja_turno_id=self.turno2.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=20000, estado="completado", metodo_pago="efectivo"),
        ])
        self.db.add_all([
            FacturaCompra(tienda_id=self.t1.id, proveedor="Distribuidora X",
                          valor_total=40000, tipo_pago=TipoPagoEnum.contado,
                          usuario_id=self.u.id, fecha_recibido=self.ahora),
            FacturaCompra(tienda_id=self.t1.id, proveedor="Lácteos Y",
                          valor_total=25000, tipo_pago=TipoPagoEnum.credito,
                          usuario_id=self.u.id, fecha_recibido=self.ahora),
        ])

        # El egreso ADOPTABLE: texto libre, sin factura_id.
        self.mov_arriendo = MovimientoCaja(
            caja_turno_id=self.turno1.id, tipo="egreso", concepto="Arriendo local",
            valor=10000, usuario_id=self.u.id, fecha=self.ahora)
        # Egreso de compra por CONCEPTO reservado, sin factura_id (fila histórica).
        self.mov_proveedor = MovimientoCaja(
            caja_turno_id=self.turno1.id, tipo="egreso",
            concepto="Pago proveedor: Distribuidora X — Fact. FV-1",
            valor=40000, usuario_id=self.u.id, fecha=self.ahora)
        # Egreso ligado a factura por factura_id, con concepto libre.
        self.mov_con_factura = MovimientoCaja(
            caja_turno_id=self.turno1.id, tipo="egreso", concepto="Pago semanal lácteos",
            valor=7000, usuario_id=self.u.id, fecha=self.ahora, factura_id=77)
        # Ingreso: no se adopta (no es un costo).
        self.mov_ingreso = MovimientoCaja(
            caja_turno_id=self.turno1.id, tipo="ingreso", concepto="Venta de ayer separada",
            valor=99999, usuario_id=self.u.id, fecha=self.ahora)
        # Egreso TECLEADO hace 40 días: sirve para probar que el devengo sale de la
        # fecha del movimiento y no de hoy.
        self.mov_viejo = MovimientoCaja(
            caja_turno_id=self.turno1.id, tipo="egreso", concepto="Energía de hace rato",
            valor=33000, usuario_id=self.u.id, fecha=self.ahora - timedelta(days=40))
        self.db.add_all([self.mov_arriendo, self.mov_proveedor, self.mov_con_factura,
                         self.mov_ingreso, self.mov_viejo])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def pl(self, **kw):
        return get_rentabilidad(self.db, hoy_col(), hoy_col(), **kw)

    def efectivo_esperado(self, turno):
        """La fórmula literal de services/caja.py: base + ventas efectivo + Σ ingresos
        − Σ egresos. Si adoptar tocara el MovimientoCaja, este número se movería."""
        ingresos = self.db.query(func.sum(MovimientoCaja.valor)).filter(
            MovimientoCaja.caja_turno_id == turno.id,
            MovimientoCaja.tipo == "ingreso").scalar() or 0.0
        egresos = self.db.query(func.sum(MovimientoCaja.valor)).filter(
            MovimientoCaja.caja_turno_id == turno.id,
            MovimientoCaja.tipo == "egreso").scalar() or 0.0
        return (float(turno.base_real or 0) + float(turno.total_efectivo or 0)
                + float(ingresos) - float(egresos))

    def adoptar_arriendo(self, **kw):
        return adoptar_egreso(self.db, self.mov_arriendo.id,
                              self.cat_arriendo.id, self.u.id, **kw)

    # ── 1-3. El invariante: los totales del P&L no se mueven ─────────────────

    def test_adoptar_no_cambia_el_total_de_gastos(self):
        antes = self.pl()["resumen"]["gastos"]
        self.assertEqual(antes, 10000)   # solo el arriendo, como pina test_rentabilidad
        self.adoptar_arriendo()
        self.assertEqual(self.pl()["resumen"]["gastos"], antes)

    def test_adoptar_no_cambia_los_margenes(self):
        antes = self.pl()["resumen"]
        bruto, neto = antes["margen_bruto"], antes["margen_neto"]
        self.adoptar_arriendo()
        despues = self.pl()["resumen"]
        self.assertEqual(despues["margen_bruto"], bruto)
        self.assertEqual(despues["margen_neto"], neto)
        self.assertEqual(despues["pct_margen_neto"], antes["pct_margen_neto"])

    def test_adoptar_no_cambia_ventas_ni_compras(self):
        antes = self.pl()["resumen"]
        self.adoptar_arriendo()
        despues = self.pl()["resumen"]
        self.assertEqual(despues["ventas"], antes["ventas"])
        self.assertEqual(despues["compras"], antes["compras"])
        self.assertEqual(despues["n_tickets"], antes["n_tickets"])
        self.assertEqual(despues["n_facturas"], antes["n_facturas"])

    # ── 4. El MovimientoCaja no se toca: la caja cuadra igual ────────────────

    def test_adoptar_no_cambia_el_efectivo_esperado_del_turno(self):
        antes = self.efectivo_esperado(self.turno1)
        self.adoptar_arriendo()
        self.db.refresh(self.turno1)
        self.assertAlmostEqual(self.efectivo_esperado(self.turno1), antes)
        # El movimiento sigue existiendo, con el mismo valor y el mismo concepto.
        mov = self.db.query(MovimientoCaja).filter_by(id=self.mov_arriendo.id).first()
        self.assertIsNotNone(mov)
        self.assertEqual(float(mov.valor), 10000)
        self.assertEqual(mov.concepto, "Arriendo local")

    # ── 5. Devengo = día del movimiento, no hoy ──────────────────────────────

    def test_fecha_devengo_por_defecto_es_el_dia_del_movimiento_no_hoy(self):
        o = adoptar_egreso(self.db, self.mov_viejo.id, self.cat_servicios.id, self.u.id)
        esperado = dia_col(self.mov_viejo.fecha)
        self.assertEqual(o["fecha_devengo"], esperado)
        self.assertNotEqual(o["fecha_devengo"], hoy_col())

    def test_fecha_devengo_explicita_manda_y_mueve_el_mes(self):
        # La corrección del devengo es un override EXPLÍCITO (mov.fecha es cuándo se
        # TECLEÓ, no cuándo se pagó): mueve el costo de mes, y por eso nunca es silencioso.
        otro_mes = hoy_col().replace(day=1) - timedelta(days=1)
        o = self.adoptar_arriendo(fecha_devengo=otro_mes)
        self.assertEqual(o["fecha_devengo"], otro_mes)
        # Y el P&L de HOY deja de ver ese gasto: se fue al mes anterior.
        self.assertEqual(self.pl()["resumen"]["gastos"], 0)

    # ── 6. Un pago espejo exacto ─────────────────────────────────────────────

    def test_crea_un_unico_pago_espejo_exacto_y_deja_la_obligacion_pagada(self):
        o = self.adoptar_arriendo()
        self.assertEqual(o["estado"], "pagada")
        self.assertEqual(o["monto"], 10000)
        self.assertEqual(o["pagado"], 10000)
        self.assertEqual(o["saldo"], 0)
        self.assertEqual(o["tienda_id"], self.t1.id)   # la sede sale del turno

        pagos = self.db.query(Pago).filter(
            Pago.movimiento_caja_id == self.mov_arriendo.id).all()
        self.assertEqual(len(pagos), 1)
        p = pagos[0]
        self.assertEqual(float(p.monto), float(self.mov_arriendo.valor))
        self.assertEqual(p.fecha_pago, dia_col(self.mov_arriendo.fecha))
        self.assertEqual(p.movimiento_caja_id, self.mov_arriendo.id)
        self.assertEqual(p.metodo, "efectivo")
        self.assertFalse(bool(p.anulado))
        self.assertEqual(p.obligacion_id, o["id"])
        self.assertIsNone(p.factura_id)

    # ── 7. Se adopta UNA sola vez ────────────────────────────────────────────

    def test_adoptar_dos_veces_da_409(self):
        self.adoptar_arriendo()
        with self.assertRaises(HTTPException) as ctx:
            self.adoptar_arriendo()
        self.assertEqual(ctx.exception.status_code, 409)

    def test_forzar_la_fila_a_mano_revienta_el_indice_unico_parcial(self):
        # La garantía final NO es el servicio, es la DB: índice único PARCIAL sobre
        # movimiento_caja_id (los pagos que no vienen de caja lo tienen NULL de a montones).
        o = self.adoptar_arriendo()
        self.db.add(Pago(obligacion_id=o["id"], tienda_id=self.t1.id, monto=10000,
                         fecha_pago=hoy_col(), metodo="efectivo",
                         movimiento_caja_id=self.mov_arriendo.id, usuario_id=self.u.id))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    # ── 8. Cambia el DÓNDE, no el CUÁNTO ─────────────────────────────────────

    def test_el_egreso_adoptado_sale_del_texto_libre_y_entra_como_categoria(self):
        antes = self.pl()
        self.assertEqual([g["concepto"] for g in antes["gastos_detalle"]], ["Arriendo local"])

        self.adoptar_arriendo()

        despues = self.pl()
        detalle = {g["concepto"]: g for g in despues["gastos_detalle"]}
        self.assertNotIn("Arriendo local", detalle)      # ya no es texto libre
        self.assertIn("Arriendo", detalle)               # ahora es la categoría
        self.assertEqual(detalle["Arriendo"]["total"], 10000)
        self.assertEqual(despues["resumen"]["gastos"], antes["resumen"]["gastos"])
        # Y por sede tampoco se movió: la obligación heredó la sede del turno.
        por_sede = {s["tienda"]: s for s in despues["por_sede"]}
        self.assertEqual(por_sede["Vida"]["gastos"], 10000)

    # ── 9-10-11. Guardas anti-doble-conteo ───────────────────────────────────

    def test_adoptar_un_egreso_con_factura_id_da_400(self):
        # Crearía una obligación espejo de una deuda que ya vive en FacturaCompra.
        with self.assertRaises(HTTPException) as ctx:
            adoptar_egreso(self.db, self.mov_con_factura.id, self.cat_arriendo.id, self.u.id)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_adoptar_un_egreso_con_concepto_de_compra_da_400(self):
        # Cubre las filas anteriores a la columna factura_id: el concepto reservado
        # que escribe services/facturas.py ya está contado dentro de COMPRAS.
        with self.assertRaises(HTTPException) as ctx:
            adoptar_egreso(self.db, self.mov_proveedor.id, self.cat_arriendo.id, self.u.id)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_adoptar_un_ingreso_da_400(self):
        with self.assertRaises(HTTPException) as ctx:
            adoptar_egreso(self.db, self.mov_ingreso.id, self.cat_arriendo.id, self.u.id)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_adoptar_un_movimiento_inexistente_da_404(self):
        with self.assertRaises(HTTPException) as ctx:
            adoptar_egreso(self.db, 999999, self.cat_arriendo.id, self.u.id)
        self.assertEqual(ctx.exception.status_code, 404)

    # ── 12. Corporativas: ni se reparten ni se duplican ──────────────────────

    def test_obligacion_corporativa_suma_al_global_sin_repartirse_entre_sedes(self):
        self.db.add(Obligacion(tienda_id=None, categoria_id=self.cat_arriendo.id,
                               concepto="Arriendo corporativo", monto=500000,
                               fecha_devengo=hoy_col(), usuario_id=self.u.id))
        self.db.commit()

        r = self.pl()
        self.assertEqual(r["resumen"]["gastos"], 510000)   # 10.000 + 500.000

        por_sede = {s["tienda"]: s for s in r["por_sede"]}
        self.assertIn("Corporativo", por_sede)             # nunca "Sede None"
        self.assertIsNone(por_sede["Corporativo"]["tienda_id"])
        self.assertEqual(por_sede["Corporativo"]["gastos"], 500000)
        self.assertEqual(por_sede["Vida"]["gastos"], 10000)
        # Σ por_sede == global: la corporativa entra UNA vez y no se prorratea.
        self.assertEqual(round(sum(s["gastos"] for s in r["por_sede"]), 2),
                         r["resumen"]["gastos"])
        self.assertEqual(round(sum(s["ventas"] for s in r["por_sede"]), 2),
                         r["resumen"]["ventas"])

        # Con la sede filtrada, la corporativa NO se cuela.
        solo_vida = self.pl(tienda_id=self.t1.id)
        self.assertEqual(solo_vida["resumen"]["gastos"], 10000)
        self.assertNotIn("Corporativo", [s["tienda"] for s in solo_vida["por_sede"]])


class AdopcionEndpointsTest(unittest.TestCase):
    """La bandeja y la adopción por HTTP: siguen siendo solo-admin como el resto del
    módulo, y la bandeja solo lista lo que de verdad se puede adoptar."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.barista = Usuario(nombre="Barista", email="b@t.local", password_hash="h",
                               rol=RolEnum.barista, tienda_id=self.tienda.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.cat = CostoCategoria(clave="arriendo", nombre="Arriendo", grupo="fijo", orden=0)
        self.db.add(self.cat)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.tienda.id, usuario_apertura_id=self.admin.id,
                               base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(self.turno)
        self.db.flush()

        ahora = inicio_dia_col_utc(hoy_col()) + (datetime.min.replace(hour=12) - datetime.min)
        self.mov = MovimientoCaja(caja_turno_id=self.turno.id, tipo="egreso",
                                  concepto="Arriendo local", valor=10000,
                                  usuario_id=self.admin.id, fecha=ahora)
        self.mov_proveedor = MovimientoCaja(
            caja_turno_id=self.turno.id, tipo="egreso",
            concepto="Pago proveedor: Distribuidora X", valor=40000,
            usuario_id=self.admin.id, fecha=ahora)
        self.db.add_all([self.mov, self.mov_proveedor])
        self.db.commit()

        app = FastAPI(title="Test adopción de egresos")
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

    def test_bandeja_lista_solo_lo_adoptable_y_se_vacia_al_adoptar(self):
        r = self.client.get("/api/v1/costos/egresos-sin-adoptar")
        self.assertEqual(r.status_code, 200, r.text)
        # El pago a proveedor NO aparece: no es adoptable (ya está en Compras).
        self.assertEqual([e["id"] for e in r.json()["egresos"]], [self.mov.id])
        self.assertEqual(r.json()["totales"]["monto"], 10000)

        r = self.client.post(f"/api/v1/costos/egresos/{self.mov.id}/adoptar",
                             json={"categoria_id": self.cat.id})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["estado"], "pagada")

        r = self.client.get("/api/v1/costos/egresos-sin-adoptar")
        self.assertEqual(r.json()["egresos"], [])

    def test_barista_403_en_los_endpoints_nuevos(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.barista
        r = self.client.get("/api/v1/costos/egresos-sin-adoptar")
        self.assertEqual(r.status_code, 403, r.text)
        r = self.client.post(f"/api/v1/costos/egresos/{self.mov.id}/adoptar",
                             json={"categoria_id": self.cat.id})
        self.assertEqual(r.status_code, 403, r.text)


if __name__ == "__main__":
    unittest.main()
