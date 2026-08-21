"""Los tres tratos de la plata (decisión del dueño), fijados.

(a) Costo del café: entra al gasto y al punto de equilibrio — lo de siempre.
(b) Sale de la caja pero NO es costo del mes: retefuente, reteica, y los giros
    de prima y cesantías (la provisión mensual de nomina.py ya los contó).
    Entran a la AGENDA con su fecha, y al gasto jamás — exclusión POR CLAVE en
    el origen (`_obligaciones_del_periodo`), el mismo mecanismo probado del
    impoconsumo. La diferencia: estas las carga el DUEÑO a mano («antes del
    18», su lista), así que son ELEGIBLES, con el trato dicho en el catálogo.
(c) No es de la empresa: categorías de ámbito «personal». Solo etiquetan filas
    del libro del banco; una obligación con ellas rebota con 400. La cuota del
    carro tiene dónde vivir sin ensuciar el resultado del café.

Y el invariante que reemplaza al alias viejo (CLAVES_NO_ELEGIBLES ya no ES
CLAVES_FUERA_DEL_GASTO): toda clave con puerta del sistema (no elegible) tiene
que estar fuera del gasto — o la puerta y el formulario contarían la misma
plata dos veces. La inversa ya no vale, y este archivo es el que lo sostiene.
"""
import os
import tempfile
import unittest
from datetime import date

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col
from app.database import Base
from app.models.models import CostoCategoria, MovimientoBanco, RolEnum, Tienda, Usuario
from app.schemas.costos import ObligacionCreate
from app.services import banco as banco_svc
from app.services import costos as svc
from app.services.banco import sembrar_cuentas
from app.services.costos import AMBITOS, CLAVES_NO_ELEGIBLES
from app.services.rentabilidad import (CLAVES_FUERA_DEL_GASTO,
                                       costos_fijos_del_mes, get_rentabilidad)


class ClavesBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.vida)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()

        svc.sembrar_categorias(self.db)
        sembrar_cuentas(self.db)
        self.occidente = self.db.query(
            banco_svc.CuentaBancaria).filter_by(nombre="Occidente").first()
        self.hoy = hoy_col()
        self.mes_ini = self.hoy.replace(day=1)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def cat(self, clave):
        return self.db.query(CostoCategoria).filter_by(clave=clave).first()

    def obligacion(self, clave, monto, concepto):
        return svc.crear_obligacion(self.db, ObligacionCreate(
            categoria_id=self.cat(clave).id, concepto=concepto, monto=monto,
            fecha_devengo=self.hoy), self.admin.id)

    def gastos_y_fijos(self):
        rent = get_rentabilidad(self.db, self.mes_ini, self.hoy, None)
        cf = costos_fijos_del_mes(self.db, self.hoy.year, self.hoy.month)
        return rent["resumen"]["gastos"], cf["costos_fijos_devengados"]


class InvarianteDeLasDosListasTest(ClavesBase):

    def test_toda_clave_no_elegible_esta_fuera_del_gasto(self):
        """La mitad del alias viejo que SIGUE valiendo: una categoría con puerta
        del sistema no puede contar en el gasto. La otra mitad (fuera del gasto
        ⇒ no elegible) se rompió a propósito: retefuente y hermanas las carga
        el dueño a mano."""
        self.assertTrue(set(CLAVES_NO_ELEGIBLES) <= set(CLAVES_FUERA_DEL_GASTO))

    def test_toda_clave_fuera_del_gasto_elegible_viaja_marcada(self):
        """Lo que ya no bloquea la lista lo tiene que decir el catálogo: cada
        clave excluida-pero-elegible sale con fuera_del_gasto=True, o el dueño
        elige sin saber el trato."""
        catalogo = {c["clave"]: c for c in svc.listar_categorias(self.db)}
        elegibles_excluidas = set(CLAVES_FUERA_DEL_GASTO) - set(CLAVES_NO_ELEGIBLES)
        for clave in elegibles_excluidas:
            self.assertIn(clave, catalogo, f"«{clave}» tendría que ofrecerse")
            self.assertTrue(catalogo[clave]["fuera_del_gasto"])
        # Y las del café común viajan en False: el flag afirma, no decora.
        self.assertFalse(catalogo["arriendo"]["fuera_del_gasto"])

    def test_los_ambitos_son_un_conjunto_cerrado(self):
        self.assertEqual(set(AMBITOS), {"cafe", "personal", "banco"})


class ReteFuenteYHermanasTest(ClavesBase):
    """El trato (b): a la agenda sí, al gasto jamás — las cuatro claves."""

    CLAVES = ("retefuente", "reteica", "prima", "cesantias")

    def test_cargarlas_deja_el_gasto_y_el_piso_exactamente_quietos(self):
        # Control: un arriendo sí mueve las dos cuentas.
        self.obligacion("arriendo", 4_292_453, "Arriendo Vida")
        gastos_base, fijos_base = self.gastos_y_fijos()
        self.assertEqual(gastos_base, 4_292_453)
        self.assertEqual(fijos_base, 4_292_453)

        self.obligacion("retefuente", 625_000, "Retefuente")
        self.obligacion("reteica", 145_000, "Reteica")
        self.obligacion("prima", 9_000_000, "Prima junio")
        self.obligacion("cesantias", 3_000_000, "Cesantías")

        gastos, fijos = self.gastos_y_fijos()
        # EXACTAMENTE quietos: $12,77M cargados y ni un peso en el P&L ni en el
        # numerador del punto de equilibrio — la provisión y la venta neta ya
        # contaron lo que había que contar.
        self.assertEqual(gastos, gastos_base)
        self.assertEqual(fijos, fijos_base)

    def test_pero_si_entran_a_la_agenda_con_su_saldo(self):
        """«Antes del 18»: la retención tiene fecha y tiene que aparecer donde
        se mira qué hay que pagar — el gasto es lo único que no la ve."""
        r = svc.crear_obligacion(self.db, ObligacionCreate(
            categoria_id=self.cat("retefuente").id, concepto="Retefuente",
            monto=625_000, fecha_devengo=self.hoy,
            fecha_vencimiento=self.hoy.replace(day=18)), self.admin.id)
        agenda = svc.get_agenda(self.db, desde=None, hasta=None, tienda_id=None)
        de_obligaciones = [i["id"] for i in agenda["items"] if i["tipo"] != "factura"]
        self.assertIn(r["id"], de_obligaciones)

    def test_son_elegibles_a_mano(self):
        """La diferencia con el impoconsumo: estas las carga ÉL («antes del
        18»), así que la puerta del formulario está abierta."""
        for clave in self.CLAVES:
            r = self.obligacion(clave, 100_000, f"Prueba {clave}")
            self.assertIsNotNone(r["id"])


class AmbitoPersonalTest(ClavesBase):
    """El trato (c): la cuota del carro tiene dónde vivir — en el libro."""

    def crear_personal(self, nombre="Cuota del carro"):
        return svc.crear_categoria(self.db, nombre, usuario_id=self.admin.id,
                                   ambito="personal")

    def test_se_crea_sobre_la_marcha_y_no_aparece_en_el_catalogo_del_cafe(self):
        cat = self.crear_personal()
        self.assertEqual(cat["ambito"], "personal")
        claves_cafe = {c["clave"] for c in svc.listar_categorias(self.db)}
        self.assertNotIn("cuota_del_carro", claves_cafe)
        claves_todas = {c["clave"] for c in svc.listar_categorias(self.db, ambito=None)}
        self.assertIn("cuota_del_carro", claves_todas)

    def test_una_obligacion_personal_rebota_con_el_motivo(self):
        cat = self.crear_personal()
        with self.assertRaises(HTTPException) as ctx:
            svc.crear_obligacion(self.db, ObligacionCreate(
                categoria_id=cat["id"], concepto="Cuota carro", monto=1_132_205,
                fecha_devengo=self.hoy), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("personal", ctx.exception.detail)
        self.assertIn("libro", ctx.exception.detail)

    def test_la_fila_personal_del_libro_no_toca_resultado_ni_piso(self):
        """El candado entero de la decisión: la plata personal SALE (el saldo
        del libro baja) y el café no se entera en ningún número."""
        gastos_antes, fijos_antes = self.gastos_y_fijos()
        cat = self.crear_personal()

        banco_svc.registrar(self.db, self.hoy, self.occidente.id, "salida",
                            1_132_205, "Cuota del carro", usuario_id=self.admin.id,
                            categoria_id=cat["id"])

        gastos, fijos = self.gastos_y_fijos()
        self.assertEqual(gastos, gastos_antes)
        self.assertEqual(fijos, fijos_antes)
        # Y la fila quedó, con su categoría resuelta, en el libro.
        libro = banco_svc.libro(self.db, self.hoy, self.hoy)
        movs = libro["dias"][0]["movimientos"]
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0]["categoria"], "Cuota del carro")
        self.assertEqual(movs[0]["categoria_ambito"], "personal")


class AmbitoBancoTest(ClavesBase):
    """GMF y comisión: sembradas, solo libro. Julio real: $191.196 + $11.567
    que ningún reporte veía."""

    def test_gmf_y_comision_estan_sembradas_en_ambito_banco(self):
        for clave in ("gmf", "comision_banco"):
            cat = self.cat(clave)
            self.assertIsNotNone(cat, f"falta sembrar «{clave}»")
            self.assertEqual(cat.ambito, "banco")

    def test_no_aparecen_en_el_catalogo_de_obligaciones(self):
        claves = {c["clave"] for c in svc.listar_categorias(self.db)}
        self.assertNotIn("gmf", claves)
        self.assertNotIn("comision_banco", claves)

    def test_una_obligacion_de_gmf_rebota(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.crear_obligacion(self.db, ObligacionCreate(
                categoria_id=self.cat("gmf").id, concepto="GMF", monto=191_196,
                fecha_devengo=self.hoy), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_el_gmf_entra_al_libro_con_su_categoria(self):
        banco_svc.registrar(self.db, self.hoy, self.occidente.id, "salida",
                            18_405, "GMF", usuario_id=self.admin.id,
                            categoria_id=self.cat("gmf").id)
        movs = banco_svc.libro(self.db, self.hoy, self.hoy)["dias"][0]["movimientos"]
        self.assertEqual(movs[0]["categoria_clave"], "gmf")

    def test_crear_una_categoria_de_banco_a_mano_rebota(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.crear_categoria(self.db, "Otra comisión", ambito="banco")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_un_ambito_inventado_rebota_legible(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.crear_categoria(self.db, "Rara", ambito="empresa")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, str)


if __name__ == "__main__":
    unittest.main()
