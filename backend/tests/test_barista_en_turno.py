"""require_barista_en_turno: en el kiosko, solo una barista DEL turno (sin salida)
puede registrar operaciones que mueven inventario. Admin exento; celular = usuario."""
import os
import tempfile
import unittest
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, CajaTurno, TurnoBarista, RolEnum, EstadoTurnoEnum,
)
from app.core.deps import require_barista_en_turno


class BaristaEnTurnoTest(unittest.TestCase):
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
        self.kiosk = Usuario(nombre="Kiosk", email="kiosk@tienda1.device", password_hash="h",
                             rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.ana = Usuario(nombre="Ana", email="ana@t.local", password_hash="h",
                           rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.sofia = Usuario(nombre="Sofia", email="sofia@t.local", password_hash="h",
                             rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.admin = Usuario(nombre="Admin", email="admin@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add_all([self.kiosk, self.ana, self.sofia, self.admin])
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.ana.id,
                               base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(self.turno)
        self.db.flush()
        self.tb_ana = TurnoBarista(turno_id=self.turno.id, usuario_id=self.ana.id,
                                   nombre_snapshot="Ana")
        self.db.add(self.tb_ana)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_kiosko_barista_del_turno_ok(self):
        out = require_barista_en_turno(x_barista_id=self.ana.id, current_user=self.kiosk, db=self.db)
        self.assertEqual(out, (self.ana.id, "Ana"))

    def test_kiosko_barista_ajena_al_turno_bloquea(self):
        with self.assertRaises(HTTPException) as c:
            require_barista_en_turno(x_barista_id=self.sofia.id, current_user=self.kiosk, db=self.db)
        self.assertEqual(c.exception.status_code, 403)
        self.assertIn("turno", c.exception.detail.lower())

    def test_kiosko_barista_con_salida_bloquea(self):
        self.tb_ana.salida_at = datetime.utcnow()
        self.db.commit()
        with self.assertRaises(HTTPException) as c:
            require_barista_en_turno(x_barista_id=self.ana.id, current_user=self.kiosk, db=self.db)
        self.assertEqual(c.exception.status_code, 403)

    def test_kiosko_sin_barista_activa_bloquea(self):
        with self.assertRaises(HTTPException) as c:
            require_barista_en_turno(x_barista_id=None, current_user=self.kiosk, db=self.db)
        self.assertEqual(c.exception.status_code, 403)

    def test_admin_exento(self):
        out = require_barista_en_turno(x_barista_id=None, current_user=self.admin, db=self.db)
        self.assertEqual(out, (None, None))

    def test_celular_barista_es_el_usuario(self):
        # Login individual (no kiosk@): la barista real es el usuario, sin header.
        out = require_barista_en_turno(x_barista_id=None, current_user=self.ana, db=self.db)
        self.assertEqual(out, (self.ana.id, "Ana"))

    def test_abrir_turno_exige_baristas(self):
        # Sin barista_ids, abrir_caja rechaza (evita turnos sin roster que el guard
        # dejaría inoperables). El check corre antes que el de turno-ya-abierto.
        from app.services import caja as csvc
        with self.assertRaises(HTTPException) as c:
            csvc.abrir_caja(self.db, self.t.id, None, None, self.kiosk.id, barista_ids=None)
        self.assertEqual(c.exception.status_code, 400)
        self.assertIn("barista", c.exception.detail.lower())


if __name__ == "__main__":
    unittest.main()
