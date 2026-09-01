"""El conteo mensual de una sede no se escribe desde otra.

`guardar` y `cerrar` son las dos escrituras de barista del módulo —el kiosko las
llama con un JWT de diez años— y hasta ahora recibían un `inv_id` y nada más:
ninguna miraba a qué sede pertenecía el conteo. Los ids son consecutivos, así
que el conteo del mes de la sede de al lado estaba literalmente a un número de
distancia, y cerrar el mes ajeno —irreversible: congela las diferencias y le
pone el valor del sistema a todo lo no contado— quedaba a un dígito de un
teclado en el mostrador.

El resto del módulo ya se defendía así (`iniciar`, `actual`): esto empareja las
dos que faltaban.
"""
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import ensure_tienda_access
from app.database import Base
from app.models.models import (CategoriaProductoEnum, Inventario, Producto,
                               RolEnum, Tienda, Usuario)
from app.services import inventario_mensual as svc


class SedeAjenaTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.centro = Tienda(nombre="Centro", direccion="y")
        self.db.add_all([self.vida, self.centro])
        self.db.flush()
        self.de_centro = Usuario(nombre="Barista Centro", email="c@t.local", password_hash="h",
                                 rol=RolEnum.barista, tienda_id=self.centro.id, activo=True)
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add_all([self.de_centro, self.admin])
        self.db.flush()
        p = Producto(nombre="LECHE", categoria=CategoriaProductoEnum.insumo,
                     unidad_medida="und", controla_stock=True, precio_venta=5000)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.vida.id, stock_actual=100))
        self.db.commit()
        self.inv_vida = svc.iniciar(self.db, self.vida.id, 2026, 9, self.admin.id)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_tienda_de_identifica_la_sede_del_conteo(self):
        self.assertEqual(svc.tienda_de(self.db, self.inv_vida["id"]), self.vida.id)

    def test_barista_de_otra_sede_no_pasa_la_guarda(self):
        with self.assertRaises(HTTPException) as ctx:
            ensure_tienda_access(self.de_centro, svc.tienda_de(self.db, self.inv_vida["id"]))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_conteo_inexistente_es_404_no_500(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.tienda_de(self.db, 999999)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
