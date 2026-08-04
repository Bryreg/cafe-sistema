"""Informe Contador: el rango del mes debe usar límites UTC Colombia-aware
(inicio_dia_col_utc/fin_dia_col_utc), no datetime naive, para no perder ni
filtrar mal los tickets vendidos en el filo entre dos días Colombia."""
import os
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import CajaTurno, EstadoTurnoEnum, RolEnum, Ticket, Tienda, Usuario
from app.services.pos import get_informe_contador


class InformeContadorTimezoneTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.usuario = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                               rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.usuario)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.tienda.id, usuario_apertura_id=self.usuario.id,
                               base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(self.turno)
        self.db.flush()

        # 22:00 hora Colombia del 31/jul (venta real de julio) → UTC = +5h =
        # 01/ago 03:00. El timestamp crudo ya cruzó la medianoche UTC aunque
        # para el negocio (Colombia) sigue siendo 31 de julio.
        self.fecha_filo = datetime(2026, 8, 1, 3, 0, 0)
        self.db.add(Ticket(
            tienda_id=self.tienda.id, caja_turno_id=self.turno.id, usuario_id=self.usuario.id,
            fecha=self.fecha_filo, total=15000, estado="completado", metodo_pago="efectivo",
            monto_efectivo=15000,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_venta_de_filo_aparece_en_su_mes_real_julio(self):
        julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        self.assertEqual(julio["total_mes"], 15000.0)
        self.assertEqual([d["fecha"] for d in julio["dias"]], ["2026-07-31"])

    def test_venta_de_filo_no_se_filtra_al_mes_siguiente_agosto(self):
        agosto = get_informe_contador(self.db, 2026, 8, self.tienda.id)
        self.assertEqual(agosto["total_mes"], 0.0)
        self.assertEqual(agosto["dias"], [])

    def test_dias_periodo_del_mes_en_curso_usa_el_dia_colombia(self):
        # El divisor de promedio_venta_diaria debe contar días Colombia, igual
        # que las filas. Con el reloj del server (UTC) iba un día adelante entre
        # las 00:00 y las 05:00 UTC, subestimando el promedio.
        with patch("app.services.pos.hoy_col", return_value=date(2026, 7, 14)):
            julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        self.assertEqual(julio["dias_periodo"], 14)
        self.assertEqual(julio["promedio_venta_diaria"], round(15000 / 14, 2))

    def test_dias_periodo_de_mes_cerrado_es_el_calendario_completo(self):
        with patch("app.services.pos.hoy_col", return_value=date(2026, 9, 3)):
            julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        self.assertEqual(julio["dias_periodo"], 31)


if __name__ == "__main__":
    unittest.main()
