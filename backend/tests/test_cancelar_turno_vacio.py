"""cancelar_turno_vacio: borra un turno abierto SIN actividad (demo/error) y sus
baristas; rechaza si tiene ventas, movimientos, conteo o si ya está cerrado."""
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, CajaTurno, TurnoBarista, MovimientoCaja,
    RolEnum, EstadoTurnoEnum,
)
from app.services import caja as svc


class CancelarTurnoVacioTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.t = Tienda(nombre="Palmetto", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _turno(self, **ov):
        tr = CajaTurno(
            tienda_id=self.t.id, usuario_apertura_id=self.admin.id,
            base_real=ov.get("base_real", 0.0), total_ventas=ov.get("total_ventas", 0.0),
            total_efectivo=ov.get("total_efectivo", 0.0), total_tarjeta=ov.get("total_tarjeta", 0.0),
            tiene_ventas=ov.get("tiene_ventas", False),
            estado=ov.get("estado", EstadoTurnoEnum.abierto),
        )
        self.db.add(tr)
        self.db.commit()
        self.db.refresh(tr)
        return tr

    def test_cancela_turno_vacio_y_baristas(self):
        tr = self._turno()
        self.db.add(TurnoBarista(turno_id=tr.id, usuario_id=self.admin.id, nombre_snapshot="Catherin"))
        self.db.commit()
        svc.cancelar_turno_vacio(self.db, tr.id, self.admin.id)
        self.assertIsNone(self.db.query(CajaTurno).filter_by(id=tr.id).first())
        self.assertEqual(self.db.query(TurnoBarista).filter_by(turno_id=tr.id).count(), 0)

    def test_rechaza_con_ventas(self):
        tr = self._turno(total_ventas=5000, tiene_ventas=True)
        with self.assertRaises(HTTPException) as c:
            svc.cancelar_turno_vacio(self.db, tr.id, self.admin.id)
        self.assertEqual(c.exception.status_code, 400)
        self.assertIsNotNone(self.db.query(CajaTurno).filter_by(id=tr.id).first())  # sigue vivo

    def test_rechaza_con_movimiento(self):
        tr = self._turno()
        self.db.add(MovimientoCaja(caja_turno_id=tr.id, tipo="egreso",
                                   concepto="prueba", valor=1000, usuario_id=self.admin.id))
        self.db.commit()
        with self.assertRaises(HTTPException) as c:
            svc.cancelar_turno_vacio(self.db, tr.id, self.admin.id)
        self.assertEqual(c.exception.status_code, 400)

    def test_rechaza_cerrado(self):
        tr = self._turno(estado=EstadoTurnoEnum.cerrado)
        with self.assertRaises(HTTPException) as c:
            svc.cancelar_turno_vacio(self.db, tr.id, self.admin.id)
        self.assertEqual(c.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
