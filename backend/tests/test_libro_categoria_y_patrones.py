"""Tres piezas de la decisión «el patrón se aprende, no se teclea».

1. LOS PAGOS EN EFECTIVO SE VEN EN EL LIBRO, EN SU DÍA — pero JAMÁS suman al
   saldo: esa plata salió del cajón o de la mano y nunca pasó por una cuenta.
   Sumarlos rompería la invariante inicial + entra − sale = final contra el
   extracto (y la hoja de julio, que es la prueba de aceptación).

2. «CUÁNTO NOS ESTAMOS GASTANDO EN CADA COSA» ES LA SERIE, mes a mes — no un
   total del mes suelto. Lo sin categoría viaja como «Sin clasificar»: un
   estado dicho, nunca un cero escondido.

3. EL PATRÓN DE PAGO SE DERIVA DEL HISTORIAL y se propone con su soporte
   («4 de 5»). El que no es claro NO SE PUBLICA: proponer un patrón dudoso es
   peor que no proponer nada — sería decidir con un dato cerca del correcto.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col
from app.database import Base
from app.models.models import (CostoCategoria, Obligacion, Pago, RolEnum,
                               Tienda, Usuario)
from app.services import banco as banco_svc
from app.services import costos as costos_svc
from app.services.banco import libro, por_categoria_anual, registrar, sembrar_cuentas


class Base_(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.vida)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        sembrar_cuentas(self.db)
        costos_svc.sembrar_categorias(self.db)
        self.occ = self.db.query(banco_svc.CuentaBancaria).filter_by(
            nombre="Occidente").first()
        self.hoy = hoy_col()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def cat(self, clave):
        return self.db.query(CostoCategoria).filter_by(clave=clave).first()

    def obligacion(self, concepto, tienda=True):
        o = Obligacion(tienda_id=self.vida.id if tienda else None,
                       categoria_id=self.cat("arriendo").id, concepto=concepto,
                       monto=1_000_000, fecha_devengo=self.hoy.replace(day=1),
                       usuario_id=self.admin.id)
        self.db.add(o)
        self.db.commit()
        return o

    def pago(self, obligacion, fecha, metodo="efectivo", monto=100_000):
        p = Pago(obligacion_id=obligacion.id, tienda_id=obligacion.tienda_id,
                 monto=monto, fecha_pago=fecha, metodo=metodo,
                 usuario_id=self.admin.id)
        self.db.add(p)
        self.db.commit()
        return p


class PagosEfectivoEnElLibroTest(Base_):

    def test_el_pago_en_efectivo_se_ve_en_su_dia_y_no_toca_el_saldo(self):
        ob = self.obligacion("Proveedor de la bodega")
        self.pago(ob, self.hoy, monto=350_000)

        l = libro(self.db, self.hoy, self.hoy)
        d = l["dias"][0]
        self.assertEqual(len(d["pagos_efectivo"]), 1)
        self.assertEqual(d["pagos_efectivo"][0]["monto"], 350_000)
        self.assertEqual(d["pagos_efectivo"][0]["detalle"], "Proveedor de la bodega")
        # Y el saldo del banco NI SE ENTERA: esa plata nunca pasó por la cuenta.
        self.assertEqual(d["total_salidas"], 0)

    def test_una_transferencia_no_entra_a_esa_lista(self):
        """La transferencia SÍ pasa por el banco: su lugar es el movimiento
        tecleado (o el pago con descuento), no la lista informativa."""
        ob = self.obligacion("Arriendo")
        self.pago(ob, self.hoy, metodo="transferencia")
        l = libro(self.db, self.hoy, self.hoy)
        self.assertEqual(l["dias"][0]["pagos_efectivo"], [])

    def test_el_pago_anulado_no_aparece(self):
        ob = self.obligacion("Proveedor")
        p = self.pago(ob, self.hoy)
        p.anulado = True
        self.db.commit()
        l = libro(self.db, self.hoy, self.hoy)
        self.assertEqual(l["dias"][0]["pagos_efectivo"], [])


class PorCategoriaAnualTest(Base_):

    def salida(self, dia, monto, clave=None):
        cat = self.cat(clave).id if clave else None
        registrar(self.db, dia, self.occ.id, "salida", monto, "x",
                  usuario_id=self.admin.id, categoria_id=cat)

    def test_la_serie_por_categoria_mes_a_mes(self):
        anio = self.hoy.year
        self.salida(date(anio, 3, 10), 4_000_000, "arriendo")
        self.salida(date(anio, 4, 12), 4_100_000, "arriendo")
        self.salida(date(anio, 4, 20), 191_196, "gmf")

        series = {c["nombre"]: c for c in
                  por_categoria_anual(self.db, anio)["categorias"]}
        arriendo = series["Arriendo"]
        self.assertEqual(arriendo["meses"][2], 4_000_000)   # marzo
        self.assertEqual(arriendo["meses"][3], 4_100_000)   # abril
        self.assertEqual(arriendo["total"], 8_100_000)
        self.assertEqual(series["GMF (4×1000)"]["ambito"], "banco")

    def test_lo_sin_categoria_se_dice_no_se_esconde(self):
        self.salida(date(self.hoy.year, 5, 2), 700_000)
        series = por_categoria_anual(self.db, self.hoy.year)["categorias"]
        sin = next(c for c in series if c["clave"] is None)
        self.assertEqual(sin["nombre"], "Sin clasificar")
        self.assertEqual(sin["total"], 700_000)

    def test_las_entradas_no_entran(self):
        """La pregunta es cuánto se GASTA: una consignación no es un gasto."""
        registrar(self.db, date(self.hoy.year, 5, 2), self.occ.id, "entrada",
                  1_000_000, "Consignación", usuario_id=self.admin.id)
        self.assertEqual(por_categoria_anual(self.db, self.hoy.year)["categorias"], [])


class PatronesDePagoTest(Base_):

    def patrones(self):
        return {p["concepto"]: p for p in
                costos_svc.get_patrones_de_pago(self.db)["patrones"]}

    def _viernes(self, n):
        """Los próximos-pasados n viernes."""
        d = self.hoy
        while d.weekday() != 4:
            d -= timedelta(days=1)
        return [d - timedelta(weeks=i) for i in range(n)]

    def test_todos_los_viernes(self):
        ob = self.obligacion("Proveedores")
        for f in self._viernes(4):
            self.pago(ob, f)
        p = self.patrones()["Proveedores"]
        self.assertEqual(p["tipo"], "dia_semana")
        self.assertEqual(p["dia"], 4)
        self.assertIn("los viernes", p["texto"])
        self.assertIn("4 de 4", p["texto"])

    def test_cerca_del_dia_del_mes(self):
        ob = self.obligacion("Arriendo Vida")
        for mes, dia in ((3, 13), (4, 14), (5, 15), (6, 14)):
            self.pago(ob, date(self.hoy.year, mes, dia))
        p = self.patrones()["Arriendo Vida"]
        self.assertEqual(p["tipo"], "dia_del_mes")
        self.assertEqual(p["dia"], 14)

    def test_siempre_antes_del(self):
        ob = self.obligacion("Retefuente")
        for mes, dia in ((3, 5), (4, 12), (5, 17), (6, 9)):
            self.pago(ob, date(self.hoy.year, mes, dia))
        p = self.patrones()["Retefuente"]
        self.assertEqual(p["tipo"], "antes_del")
        self.assertEqual(p["dia"], 18)

    def test_con_dos_pagos_no_hay_patron(self):
        """Dos coincidencias son casualidad, no costumbre."""
        ob = self.obligacion("Zinko")
        for f in self._viernes(2):
            self.pago(ob, f)
        self.assertNotIn("Zinko", self.patrones())

    def test_el_patron_dudoso_no_se_publica(self):
        """Días dispersos por todo el mes: proponer algo sería inventar."""
        ob = self.obligacion("Varios")
        for mes, dia in ((3, 2), (4, 28), (5, 11), (6, 21)):
            self.pago(ob, date(self.hoy.year, mes, dia))
        self.assertNotIn("Varios", self.patrones())

    def test_dos_escrituras_del_mismo_concepto_son_una_costumbre(self):
        """«Arriendo Vida» y «arriendo  vida» agrupan juntos: es la misma llave
        normalizada de «armar el mes»."""
        ob1 = self.obligacion("Arriendo Vida")
        ob2 = self.obligacion("arriendo  vida")
        for mes, ob in ((3, ob1), (4, ob2), (5, ob1)):
            self.pago(ob, date(self.hoy.year, mes, 14))
        patrones = self.patrones()
        # Un solo patrón para la cuenta, con los tres pagos adentro.
        del_arriendo = [p for c, p in patrones.items()
                        if c.lower().startswith("arriendo")]
        self.assertEqual(len(del_arriendo), 1)
        self.assertEqual(del_arriendo[0]["n_pagos"], 3)


if __name__ == "__main__":
    unittest.main()
