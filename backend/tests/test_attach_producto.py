"""get_attach_producto: con qué se vende junto un producto, sin truncar.

Cubre lo que el top_pares del pulso no puede responder (un par poco frecuente) y
`tickets_multiples`, que es lo que delata a un combo que empaqueta de a dos algo
que la gente YA se lleva de a dos.
"""
import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, CajaTurno, Ticket, TicketItem,
    RolEnum, CategoriaProductoEnum,
)
from app.services import rentabilidad as svc


class AttachProductoTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.u = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                         rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.u)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.u.id, base_real=0)
        self.db.add(self.turno)
        self.db.flush()

        def prod(nombre, cat, precio):
            p = Producto(nombre=nombre, categoria=cat, unidad_medida="und", precio_venta=precio)
            self.db.add(p)
            self.db.flush()
            return p

        self.cafe = prod("Americano", CategoriaProductoEnum.bebida, 6900)
        self.croi = prod("Croissant", CategoriaProductoEnum.pasteleria, 7900)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _ticket(self, lineas, estado="completado"):
        """lineas: [(producto, cantidad), ...]"""
        tk = Ticket(tienda_id=self.t.id, caja_turno_id=self.turno.id, usuario_id=self.u.id,
                    fecha=datetime.utcnow(), total=0, metodo_pago="efectivo", estado=estado)
        self.db.add(tk)
        self.db.flush()
        for p, c in lineas:
            self.db.add(TicketItem(ticket_id=tk.id, producto_id=p.id, nombre_producto=p.nombre,
                                   cantidad=c, precio_unitario=p.precio_venta,
                                   subtotal=(p.precio_venta or 0) * c))
        self.db.commit()
        return tk

    def _poblar(self):
        self._ticket([(self.cafe, 1), (self.croi, 1)])   # juntos
        self._ticket([(self.cafe, 1)])                    # cafe solo
        self._ticket([(self.croi, 1)])                    # croissant sin bebida
        self._ticket([(self.cafe, 2), (self.croi, 1)])    # DOS cafes + croissant
        self._ticket([(self.cafe, 1), (self.croi, 1)], estado="anulado")  # no cuenta

    def test_croissant_ve_su_par_aunque_sea_poco_frecuente(self):
        self._poblar()
        r = svc.get_attach_producto(self.db, self.croi.id)
        self.assertEqual(r["tickets"], 3)          # dos juntos + uno solo
        self.assertEqual(r["unidades"], 3)
        self.assertEqual(r["con_bebida"], 2)
        self.assertEqual(r["sin_bebida"], 1)
        self.assertEqual(r["pct_con_bebida"], 66.7)
        pares = {p["nombre"]: p["veces"] for p in r["pares"]}
        self.assertEqual(pares, {"Americano": 2})

    def test_tickets_multiples_detecta_el_que_se_lleva_de_a_dos(self):
        self._poblar()
        r = svc.get_attach_producto(self.db, self.cafe.id)
        self.assertEqual(r["tickets"], 3)
        self.assertEqual(r["unidades"], 4)          # 1 + 1 + 2
        self.assertEqual(r["tickets_multiples"], 1)  # el ticket con 2 americanos
        self.assertEqual(r["por_categoria"].get("pasteleria"), 2)

    def test_anulados_no_cuentan(self):
        self._ticket([(self.cafe, 1), (self.croi, 1)], estado="anulado")
        r = svc.get_attach_producto(self.db, self.croi.id)
        self.assertEqual(r["tickets"], 0)
        self.assertEqual(r["pares"], [])

    def test_producto_sin_ventas_no_rompe(self):
        r = svc.get_attach_producto(self.db, self.croi.id)
        self.assertEqual(r["tickets"], 0)
        self.assertIsNone(r["pct_con_bebida"])


if __name__ == "__main__":
    unittest.main()
