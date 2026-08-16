"""Agregados ADITIVOS del P&L que la fusion Rentabilidad+Costos saca a la luz.

Dos datos que el backend ya podia dar y que ninguna pantalla mostraba:

  - `gastos_por_categoria`: el MISMO `resumen.gastos` partido por categoria de
    costo (nomina, arriendo, servicios...). Hasta ahora el P&L solo publicaba
    `gastos_detalle`, que mezcla el nombre de la categoria con el texto libre del
    egreso de caja en una sola lista: leerlo obligaba a adivinar cual es cual.
  - `descuentos`: la plata REGALADA en mostrador (Ticket.descuento). Se escribe
    en cada venta desde el POS y no se sumaba en ningun reporte, asi que un
    descuento y una venta que no ocurrio se veian exactamente igual.

Los dos son ADITIVOS: estos tests fijan que ninguna formula vieja se mueva.
"""
import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base
from app.models.models import (
    CajaTurno, CostoCategoria, EstadoTurnoEnum, MovimientoCaja, Obligacion,
    RolEnum, Ticket, Tienda, Usuario,
)
from app.services.rentabilidad import get_rentabilidad


class PlataAgregadosTest(unittest.TestCase):
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
        self.db.add(self.t1)
        self.db.flush()
        self.u = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                         rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.u)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.t1.id, usuario_apertura_id=self.u.id,
                               base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(self.turno)
        self.db.flush()

        self.hoy = hoy_col()
        self.ahora = inicio_dia_col_utc(self.hoy) + (datetime.min.replace(hour=12) - datetime.min)

        # Categorias de costo (las mismas claves que siembra el catalogo real).
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo", grupo="fijo")
        self.cat_nomina = CostoCategoria(clave="nomina", nombre="Nomina", grupo="fijo")
        self.cat_prov = CostoCategoria(clave="proveedores", nombre="Proveedores", grupo="variable")
        self.db.add_all([self.cat_arriendo, self.cat_nomina, self.cat_prov])
        self.db.flush()

        # Obligaciones devengadas hoy: 200k arriendo + 300k nomina.
        self.db.add_all([
            Obligacion(tienda_id=None, categoria_id=self.cat_arriendo.id,
                       concepto="Arriendo del mes", monto=200000,
                       fecha_devengo=self.hoy, usuario_id=self.u.id),
            Obligacion(tienda_id=self.t1.id, categoria_id=self.cat_nomina.id,
                       concepto="Nomina quincena", monto=300000,
                       fecha_devengo=self.hoy, usuario_id=self.u.id),
        ])

        # Egreso de caja suelto (sin adoptar): sigue siendo gasto, pero no tiene
        # categoria — su bolsa propia en el desglose.
        self.db.add(MovimientoCaja(caja_turno_id=self.turno.id, tipo="egreso",
                                   concepto="Domicilio de emergencia", valor=15000,
                                   usuario_id=self.u.id, fecha=self.ahora))

        # Ventas: 100k con 10k de descuento, 50k sin descuento, y una ANULADA con
        # 7k de descuento que no puede contar en ningun lado.
        self.db.add_all([
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=100000, descuento=10000,
                   estado="completado", metodo_pago="efectivo"),
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=50000, descuento=0,
                   estado="completado", metodo_pago="tarjeta"),
            Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno.id, usuario_id=self.u.id,
                   fecha=self.ahora, total=30000, descuento=7000,
                   estado="anulado", metodo_pago="efectivo"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── gastos_por_categoria ─────────────────────────────────────────────────

    def test_gastos_por_categoria_suma_exactamente_el_gasto_del_resumen(self):
        """Invariante: el desglose es una PARTICION de `gastos`, no otro numero."""
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        desglose = r["gastos_por_categoria"]
        self.assertAlmostEqual(sum(g["total"] for g in desglose), r["resumen"]["gastos"])
        self.assertAlmostEqual(r["resumen"]["gastos"], 200000 + 300000 + 15000)

    def test_gastos_por_categoria_usa_la_clave_estable_y_el_grupo(self):
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        por_clave = {g["clave"]: g for g in r["gastos_por_categoria"]}
        self.assertAlmostEqual(por_clave["arriendo"]["total"], 200000)
        self.assertEqual(por_clave["arriendo"]["nombre"], "Arriendo")
        self.assertEqual(por_clave["arriendo"]["grupo"], "fijo")
        self.assertAlmostEqual(por_clave["nomina"]["total"], 300000)
        self.assertEqual(por_clave["nomina"]["n"], 1)

    def test_gastos_por_categoria_separa_los_egresos_sin_categorizar(self):
        """El egreso de caja suelto no se disfraza de categoria: bolsa propia y
        declarada, que es justo la que se vacia adoptandolo."""
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        por_clave = {g["clave"]: g for g in r["gastos_por_categoria"]}
        self.assertIn("sin_categorizar", por_clave)
        self.assertAlmostEqual(por_clave["sin_categorizar"]["total"], 15000)
        self.assertIsNone(por_clave["sin_categorizar"]["grupo"])

    def test_gastos_por_categoria_ordenado_por_plata(self):
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        totales = [g["total"] for g in r["gastos_por_categoria"]]
        self.assertEqual(totales, sorted(totales, reverse=True))

    def test_gastos_por_categoria_excluye_proveedores_legacy(self):
        """Misma exclusion anti-doble-conteo que `gastos`: la mercaderia ya entro
        por FacturaCompra. Si el desglose la mostrara, sumaria mas que el total."""
        self.db.add(Obligacion(tienda_id=self.t1.id, categoria_id=self.cat_prov.id,
                               concepto="Factura legacy", monto=999999,
                               fecha_devengo=self.hoy, usuario_id=self.u.id))
        self.db.commit()
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        claves = {g["clave"] for g in r["gastos_por_categoria"]}
        self.assertNotIn("proveedores", claves)
        self.assertAlmostEqual(sum(g["total"] for g in r["gastos_por_categoria"]),
                               r["resumen"]["gastos"])

    def test_gastos_por_categoria_respeta_el_filtro_de_sede(self):
        """Con sede filtrada, la corporativa (arriendo) queda afuera igual que en
        `gastos`: el desglose no puede contar plata que el total no cuenta."""
        r = get_rentabilidad(self.db, self.hoy, self.hoy, tienda_id=self.t1.id)
        claves = {g["clave"] for g in r["gastos_por_categoria"]}
        self.assertNotIn("arriendo", claves)
        self.assertIn("nomina", claves)
        self.assertAlmostEqual(sum(g["total"] for g in r["gastos_por_categoria"]),
                               r["resumen"]["gastos"])

    # ── descuentos ───────────────────────────────────────────────────────────

    def test_descuentos_suma_solo_tickets_vivos(self):
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        self.assertAlmostEqual(r["resumen"]["descuentos"], 10000)   # sin los 7k anulados
        self.assertEqual(r["resumen"]["n_tickets_con_descuento"], 1)

    def test_descuentos_no_mueve_ventas_ni_margen(self):
        """Ticket.total YA viene neto de descuento: exponerlo es contar lo que se
        regalo, nunca volver a restarlo."""
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        self.assertAlmostEqual(r["resumen"]["ventas"], 150000)
        # El margen arranca de la venta NETA, no de lo cobrado: el impoconsumo
        # que va adentro del precio es de la DIAN. Lo que este test cuida es que
        # el DESCUENTO no vuelva a restarse, y eso sigue valiendo.
        self.assertAlmostEqual(
            r["resumen"]["margen_neto"],
            r["resumen"]["venta_neta"] - r["resumen"]["compras"] - r["resumen"]["gastos"],
            places=1)
        self.assertAlmostEqual(r["resumen"]["venta_neta"], round(150000 / 1.08, 2))

    def test_pct_descuento_sobre_la_venta_bruta(self):
        """El % se mide contra lo que se HABRIA facturado (venta + descuento):
        contra la venta neta daria un numero inflado."""
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        self.assertAlmostEqual(r["resumen"]["pct_descuento"],
                               round(10000 / 160000 * 100, 1))

    def test_sin_ventas_el_pct_descuento_es_none(self):
        from datetime import date
        r = get_rentabilidad(self.db, date(2020, 1, 1), date(2020, 1, 31))
        self.assertAlmostEqual(r["resumen"]["descuentos"], 0)
        self.assertIsNone(r["resumen"]["pct_descuento"])
        self.assertEqual(r["gastos_por_categoria"], [])


if __name__ == "__main__":
    unittest.main()
