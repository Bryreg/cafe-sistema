"""Rentabilidad (P&L): ventas - compras - gastos, sin doble conteo.
Clave: los egresos de caja 'Pago proveedor:...' NO cuentan como gasto porque
la compra ya está en FacturaCompra.valor_total."""
import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base
from app.models.models import (
    CajaTurno, CategoriaProductoEnum, EstadoTurnoEnum, FacturaCompra,
    FacturaCompraItem, MovimientoCaja, Producto, ProductoInsumo, Ticket,
    TicketItem, Tienda, TipoPagoEnum, Usuario, RolEnum,
)
from app.services.rentabilidad import get_rentabilidad, get_rentabilidad_productos


class RentabilidadTest(unittest.TestCase):
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
                                base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.turno2 = CajaTurno(tienda_id=self.t2.id, usuario_apertura_id=self.u.id,
                                base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add_all([self.turno1, self.turno2])
        self.db.flush()

        # Mediodía Colombia de hoy, en UTC — cae dentro del rango [hoy, hoy].
        self.ahora = inicio_dia_col_utc(hoy_col()) + (datetime.min.replace(hour=12) - datetime.min)

        # Ventas: 100k + 50k válidas en Vida, 30k ANULADA (no cuenta), 20k en Palmetto.
        self.db.add_all([
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno1.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=100000, estado="completado", metodo_pago="efectivo"),
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno1.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=50000, estado="completado", metodo_pago="tarjeta"),
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno1.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=30000, estado="anulado", metodo_pago="efectivo"),
            Ticket(tienda_id=self.t2.id, caja_turno_id=self.turno2.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=20000, estado="completado", metodo_pago="efectivo"),
        ])

        # Compras: 40k contado en Vida (que además generó egreso de caja) + 25k crédito.
        self.db.add_all([
            FacturaCompra(tienda_id=self.t1.id, proveedor="Distribuidora X",
                          valor_total=40000, tipo_pago=TipoPagoEnum.contado,
                          usuario_id=self.u.id, fecha_recibido=self.ahora),
            FacturaCompra(tienda_id=self.t1.id, proveedor="Lácteos Y",
                          valor_total=25000, tipo_pago=TipoPagoEnum.credito,
                          usuario_id=self.u.id, fecha_recibido=self.ahora),
        ])

        # Movimientos de caja en Vida: el egreso del pago al proveedor NO debe
        # contarse como gasto (ya está en compras); el arriendo SÍ; el ingreso
        # manual no entra al P&L.
        self.db.add_all([
            MovimientoCaja(caja_turno_id=self.turno1.id, tipo="egreso",
                           concepto="Pago proveedor: Distribuidora X — Fact. FV-1",
                           valor=40000, usuario_id=self.u.id, fecha=self.ahora),
            MovimientoCaja(caja_turno_id=self.turno1.id, tipo="egreso",
                           concepto="Arriendo local", valor=10000,
                           usuario_id=self.u.id, fecha=self.ahora),
            MovimientoCaja(caja_turno_id=self.turno1.id, tipo="egreso",
                           concepto="Ajuste factura FV-1: corrección de forma/monto de pago",
                           valor=5000, usuario_id=self.u.id, fecha=self.ahora),
            MovimientoCaja(caja_turno_id=self.turno1.id, tipo="ingreso",
                           concepto="Venta de ayer separada", valor=99999,
                           usuario_id=self.u.id, fecha=self.ahora),
            # Ligado a factura por factura_id con concepto NO reservado (ej. un
            # pago registrado post-fix): tampoco debe contarse como gasto.
            MovimientoCaja(caja_turno_id=self.turno1.id, tipo="egreso",
                           concepto="Pago semanal lácteos", valor=7000,
                           usuario_id=self.u.id, fecha=self.ahora, factura_id=77),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_totales_globales(self):
        r = get_rentabilidad(self.db, hoy_col(), hoy_col())
        self.assertEqual(r["resumen"]["ventas"], 170000)      # 100k+50k+20k, sin la anulada
        self.assertEqual(r["resumen"]["compras"], 65000)      # 40k+25k
        self.assertEqual(r["resumen"]["gastos"], 10000)       # solo el arriendo
        self.assertEqual(r["resumen"]["margen_bruto"], 105000)
        self.assertEqual(r["resumen"]["margen_neto"], 95000)
        self.assertEqual(r["resumen"]["n_tickets"], 3)

    def test_egreso_proveedor_no_es_gasto(self):
        r = get_rentabilidad(self.db, hoy_col(), hoy_col())
        conceptos = [g["concepto"] for g in r["gastos_detalle"]]
        self.assertEqual(conceptos, ["Arriendo local"])

    def test_filtro_por_sede(self):
        r = get_rentabilidad(self.db, hoy_col(), hoy_col(), tienda_id=self.t2.id)
        self.assertEqual(r["resumen"]["ventas"], 20000)
        self.assertEqual(r["resumen"]["compras"], 0)
        self.assertEqual(r["resumen"]["gastos"], 0)
        self.assertEqual(r["resumen"]["margen_neto"], 20000)

    def test_por_sede_desglosa(self):
        r = get_rentabilidad(self.db, hoy_col(), hoy_col())
        por_sede = {s["tienda"]: s for s in r["por_sede"]}
        self.assertEqual(por_sede["Vida"]["ventas"], 150000)
        self.assertEqual(por_sede["Vida"]["compras"], 65000)
        self.assertEqual(por_sede["Vida"]["gastos"], 10000)
        self.assertEqual(por_sede["Palmetto"]["ventas"], 20000)

    def test_pct_margen(self):
        r = get_rentabilidad(self.db, hoy_col(), hoy_col())
        self.assertAlmostEqual(r["resumen"]["pct_margen_neto"], round(95000 / 170000 * 100, 1))

    def test_rango_sin_datos(self):
        from datetime import date
        r = get_rentabilidad(self.db, date(2020, 1, 1), date(2020, 1, 31))
        self.assertEqual(r["resumen"]["ventas"], 0)
        self.assertIsNone(r["resumen"]["pct_margen_neto"])
        self.assertEqual(r["por_mes"], [])

    def test_egreso_con_factura_id_excluido_aunque_concepto_no_matchee(self):
        # El egreso de 7.000 con factura_id=77 y concepto libre NO es gasto.
        r = get_rentabilidad(self.db, hoy_col(), hoy_col())
        self.assertEqual(r["resumen"]["gastos"], 10000)
        self.assertNotIn("Pago semanal lácteos", [g["concepto"] for g in r["gastos_detalle"]])

    def test_eliminar_factura_encuentra_egreso_por_factura_id_tras_renombrar(self):
        # Regresión del hallazgo del review: renombrar el proveedor rompía el
        # match por concepto y el egreso quedaba huérfano (plata invisible).
        from app.services.facturas import eliminar_factura
        f = FacturaCompra(tienda_id=self.t1.id, proveedor="Juan",
                          valor_total=30000, valor_pagado=30000,
                          tipo_pago=TipoPagoEnum.contado,
                          usuario_id=self.u.id, fecha_recibido=self.ahora)
        self.db.add(f)
        self.db.flush()
        self.db.add(MovimientoCaja(
            caja_turno_id=self.turno1.id, tipo="egreso",
            concepto="Pago proveedor: Juan", valor=30000,
            usuario_id=self.u.id, fecha=self.ahora, factura_id=f.id))
        f.proveedor = "Juan Pérez"  # el admin corrigió el nombre después
        self.db.commit()
        out = eliminar_factura(self.db, f.id, self.u.id)
        self.assertEqual(out["egresos_revertidos"], 30000)

    def test_margen_por_producto_receta_y_reventa(self):
        # Insumos: leche $2.5/ml y café $40/gr (vía items de factura con precio).
        leche = Producto(nombre="Leche entera", categoria=CategoriaProductoEnum.insumo,
                         unidad_medida="ml", precio_venta=0)
        cafe = Producto(nombre="Café", categoria=CategoriaProductoEnum.insumo,
                        unidad_medida="gr", precio_venta=0)
        # Venta con receta: capuchino $8.000 = 180 ml leche + 18 gr café.
        capu = Producto(nombre="Capuchino", categoria=CategoriaProductoEnum.bebida,
                        unidad_medida="unidad", precio_venta=8000)
        # Reventa: gaseosa comprada a $2.000, vendida a $5.000.
        gaseosa = Producto(nombre="Gaseosa", categoria=CategoriaProductoEnum.bebida,
                           unidad_medida="unidad", precio_venta=5000)
        # Receta con insumo SIN costo conocido.
        te = Producto(nombre="Té", categoria=CategoriaProductoEnum.bebida,
                      unidad_medida="unidad", precio_venta=4000)
        bolsa_te = Producto(nombre="Bolsa de té", categoria=CategoriaProductoEnum.insumo,
                            unidad_medida="unidad", precio_venta=0)
        self.db.add_all([leche, cafe, capu, gaseosa, te, bolsa_te])
        self.db.flush()

        fact = FacturaCompra(tienda_id=self.t1.id, proveedor="Prov",
                             valor_total=999999, tipo_pago=TipoPagoEnum.credito,
                             usuario_id=self.u.id, fecha_recibido=self.ahora)
        self.db.add(fact)
        self.db.flush()
        self.db.add_all([
            FacturaCompraItem(factura_id=fact.id, producto_id=leche.id,
                              cantidad=10000, precio_unitario=2.5),
            FacturaCompraItem(factura_id=fact.id, producto_id=cafe.id,
                              cantidad=1000, precio_unitario=40),
            FacturaCompraItem(factura_id=fact.id, producto_id=gaseosa.id,
                              cantidad=10, precio_unitario=2000),
            ProductoInsumo(producto_id=capu.id, insumo_id=leche.id, cantidad=180),
            ProductoInsumo(producto_id=capu.id, insumo_id=cafe.id, cantidad=18),
            ProductoInsumo(producto_id=te.id, insumo_id=bolsa_te.id, cantidad=1),
        ])
        # Ventas 30d para el orden por relevancia.
        tk = Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno1.id,
                    usuario_id=self.u.id, fecha=self.ahora, total=8000,
                    estado="completado", metodo_pago="efectivo")
        self.db.add(tk)
        self.db.flush()
        self.db.add(TicketItem(ticket_id=tk.id, producto_id=capu.id,
                               nombre_producto="Capuchino", cantidad=2,
                               precio_unitario=8000, subtotal=16000))
        self.db.commit()

        r = get_rentabilidad_productos(self.db)
        por_nombre = {p["nombre"]: p for p in r["productos"]}

        c = por_nombre["Capuchino"]
        self.assertEqual(c["tipo"], "receta")
        self.assertAlmostEqual(c["costo"], 180 * 2.5 + 18 * 40)   # 450 + 720 = 1170
        self.assertAlmostEqual(c["margen"], 8000 - 1170)
        self.assertTrue(c["costo_completo"])
        self.assertEqual(c["unidades_30d"], 2)

        g = por_nombre["Gaseosa"]
        self.assertEqual(g["tipo"], "reventa")
        self.assertAlmostEqual(g["costo"], 2000)
        self.assertAlmostEqual(g["margen"], 3000)

        t = por_nombre["Té"]
        self.assertFalse(t["costo_completo"])
        self.assertIn("Bolsa de té", t["insumos_sin_costo"])
        self.assertIsNone(t["costo"])  # ningún insumo con costo → sin margen

        # Insumos puros (precio_venta=0) no aparecen en la tabla.
        self.assertNotIn("Leche entera", por_nombre)
        # Orden: el más vendido primero.
        self.assertEqual(r["productos"][0]["nombre"], "Capuchino")

    def test_editar_factura_guarda_fecha_como_medianoche_colombia(self):
        # Regresión: editar guardaba el date pelado (00:00 UTC) y la compra se
        # corría un día hacia atrás en los reportes.
        from datetime import date
        from app.services.facturas import editar_factura
        f = FacturaCompra(tienda_id=self.t1.id, proveedor="Panadería Z",
                          valor_total=15000, valor_pagado=0,
                          tipo_pago=TipoPagoEnum.credito,
                          usuario_id=self.u.id, fecha_recibido=self.ahora)
        self.db.add(f)
        self.db.commit()
        editar_factura(self.db, f.id, self.u.id, fecha_recibido=date(2026, 7, 10))
        self.db.refresh(f)
        self.assertEqual(f.fecha_recibido, inicio_dia_col_utc(date(2026, 7, 10)))


if __name__ == "__main__":
    unittest.main()
