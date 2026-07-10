"""El SOBRANTE de apertura entra al esperado a consignar del turno (una vez);
el faltante no. La base del cajón sigue siendo lo contado (física intacta)."""
import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, CajaTurno, RolEnum, EstadoTurnoEnum,
)
from app.services import caja as csvc
from app.services import consignaciones as svc


class SobranteAperturaTest(unittest.TestCase):
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
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _turno_cerrado(self, dif_apertura, efectivo=934450, dif_cierre=6850):
        tr = CajaTurno(
            tienda_id=self.t.id, usuario_apertura_id=self.admin.id,
            base_sistema=891100, base_real=891100 + max(0, dif_apertura),
            diferencia_apertura=dif_apertura,
            sobrante_consignable=max(0, dif_apertura) if dif_apertura is not None else None,
            total_efectivo=efectivo,
            diferencia_cierre=dif_cierre, estado=EstadoTurnoEnum.cerrado,
            fecha_apertura=datetime(2026, 7, 9, 13, 0),
            fecha_cierre=datetime(2026, 7, 10, 1, 0),
        )
        self.db.add(tr)
        self.db.commit()
        self.db.refresh(tr)
        return tr

    def test_sobrante_entra_al_esperado_consignar(self):
        tr = self._turno_cerrado(dif_apertura=24600)
        # resumen admin
        fila = next(f for f in svc.get_resumen_admin(self.db, self.t.id) if f["turno_id"] == tr.id)
        self.assertEqual(fila["esperado_consignar"], 934450 + 6850 + 24600)
        # saldos (cascada / apertura del día siguiente)
        s = next(s for s in svc._saldos_consignacion(self.db, self.t.id) if s["turno"].id == tr.id)
        self.assertEqual(s["esperado"], 934450 + 6850 + 24600)

    def test_turno_viejo_null_no_reclama(self):
        # Turno pre-fix: sobrante_consignable NULL aunque tenga diferencia_apertura
        # (arrastre histórico / carga inicial) — NO debe entrar al esperado.
        tr = self._turno_cerrado(dif_apertura=24600)
        tr.sobrante_consignable = None
        self.db.commit()
        fila = next(f for f in svc.get_resumen_admin(self.db, self.t.id) if f["turno_id"] == tr.id)
        self.assertEqual(fila["esperado_consignar"], 934450 + 6850)

    def test_faltante_no_entra(self):
        tr = self._turno_cerrado(dif_apertura=-5000)
        fila = next(f for f in svc.get_resumen_admin(self.db, self.t.id) if f["turno_id"] == tr.id)
        self.assertEqual(fila["esperado_consignar"], 934450 + 6850)   # sin el faltante

    def test_cuadre_inicial_base_sigue_siendo_lo_contado(self):
        tr = CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.admin.id,
                       base_sistema=891100, base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(tr)
        self.db.commit()
        csvc.registrar_cuadre_inicial(self.db, tr.id, self.admin.id,
                                      efectivo_real=915700, justificacion="sobrante")
        self.db.refresh(tr)
        self.assertEqual(tr.base_real, 915700)            # contado (física del cajón intacta)
        self.assertEqual(tr.diferencia_apertura, 24600)   # la novedad registrada
        self.assertEqual(tr.sobrante_consignable, 24600)  # y marcado para bancarse hoy


if __name__ == "__main__":
    unittest.main()
