"""Aplicar el conteo mensual CERRADO al inventario: stock_actual += diferencia
por producto (no el físico absoluto — así los movimientos posteriores al cierre
no se pisan si se aplica días después). Una sola vez; un mes aplicado es
histórico (no se reabre ni corrige). corregir_item permite arreglar un renglón
de un mes cerrado ANTES de aplicar, recalculando diferencias y total."""
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, Inventario, MovimientoInventario,
    RolEnum, CategoriaProductoEnum,
)
from app.services import inventario_mensual as svc


class AplicarMensualTest(unittest.TestCase):
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
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.prod = Producto(nombre="SERVILLETAS", categoria=CategoriaProductoEnum.insumo,
                             unidad_medida="und", controla_stock=True)
        self.db.add(self.prod)
        self.db.flush()
        self.inv_row = Inventario(producto_id=self.prod.id, tienda_id=self.t1.id, stock_actual=10)
        self.db.add(self.inv_row)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _contar_y_cerrar(self, contado):
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        item_id = inv["items"][0]["id"]
        svc.guardar(self.db, inv["id"], [{"id": item_id, "cantidad_real": contado}])
        out = svc.cerrar(self.db, inv["id"], self.admin.id)
        return out["id"], item_id

    def test_aplicar_suma_la_diferencia_al_stock_actual(self):
        # Sistema 10, contado 8 → dif −2. Después del cierre el stock se movió a 6
        # (ventas de días posteriores). Aplicar debe dejar 6 + (−2) = 4, NO 8.
        inv_id, _ = self._contar_y_cerrar(8)
        self.inv_row.stock_actual = 6
        self.db.commit()

        res = svc.aplicar(self.db, inv_id, self.admin.id)

        self.db.refresh(self.inv_row)
        self.assertEqual(self.inv_row.stock_actual, 4)
        self.assertEqual(res["ajustados"], 1)
        mov = self.db.query(MovimientoInventario).filter_by(
            producto_id=self.prod.id, tienda_id=self.t1.id).all()
        self.assertTrue(any("mensual" in (m.motivo or "").lower() for m in mov))
        out = svc.get_actual(self.db, self.t1.id, 2026, 7)
        self.assertIsNotNone(out["fecha_aplicado"])

    def test_aplicar_dos_veces_falla(self):
        inv_id, _ = self._contar_y_cerrar(8)
        svc.aplicar(self.db, inv_id, self.admin.id)
        with self.assertRaises(HTTPException):
            svc.aplicar(self.db, inv_id, self.admin.id)

    def test_aplicar_en_proceso_falla(self):
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        with self.assertRaises(HTTPException):
            svc.aplicar(self.db, inv["id"], self.admin.id)

    def test_aplicar_se_bloquea_en_vez_de_recortar_en_cero(self):
        # dif −8; stock actual ya bajó a 3 → 3 + (−8) = −5.
        #
        # Antes esto se recortaba a 0 en silencio. Como aplicar es IRREVERSIBLE
        # (fecha_aplicado), el stock quedaba mal sin vuelta atrás — y un negativo
        # no es un caso raro a redondear: es la prueba de que la diferencia
        # congelada en el cierre ya no calza con el stock de hoy. Ahora frena
        # antes de tocar nada y el admin corrige el renglón del mes cerrado.
        inv_id, item_id = self._contar_y_cerrar(2)
        self.inv_row.stock_actual = 3
        self.db.commit()

        with self.assertRaises(HTTPException):
            svc.aplicar(self.db, inv_id, self.admin.id)

        self.db.refresh(self.inv_row)
        self.assertEqual(self.inv_row.stock_actual, 3)   # intacto
        self.assertIsNone(svc.get_actual(self.db, self.t1.id, 2026, 7)["fecha_aplicado"])

        # El camino de salida: corregir el conteo del mes y recién ahí aplicar.
        svc.corregir_item(self.db, item_id, 8, self.admin.id)   # dif −2
        res = svc.aplicar(self.db, inv_id, self.admin.id)
        self.db.refresh(self.inv_row)
        self.assertEqual(self.inv_row.stock_actual, 1)
        self.assertEqual(res["ajustados"], 1)

    def test_corregir_item_en_cerrado_recalcula(self):
        # El caso LIMPIAPISOS: cerraron con un dedazo (3800) y hay que corregirlo
        # sin reabrir (reabrir re-sincroniza el sistema y arruina la foto del mes).
        inv_id, item_id = self._contar_y_cerrar(3800)
        out = svc.corregir_item(self.db, item_id, 3, self.admin.id)
        it = next(i for i in out["items"] if i["id"] == item_id)
        self.assertEqual(it["cantidad_real"], 3)
        self.assertEqual(it["diferencia"], -7)
        self.assertEqual(out["valor_diferencia_total"],
                         sum(i["valor_diferencia"] for i in out["items"]))

    def test_corregir_y_reabrir_bloqueados_tras_aplicar(self):
        inv_id, item_id = self._contar_y_cerrar(8)
        svc.aplicar(self.db, inv_id, self.admin.id)
        with self.assertRaises(HTTPException):
            svc.corregir_item(self.db, item_id, 9, self.admin.id)
        with self.assertRaises(HTTPException):
            svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)


if __name__ == "__main__":
    unittest.main()
