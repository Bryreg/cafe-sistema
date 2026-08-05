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
from app.models.models import (
    CajaTurno, DiaOperativo, EstadoTurnoEnum, RolEnum, Ticket, Tienda, Usuario,
)
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

    # ── Día operativo vs día calendario ──────────────────────────────────────
    # El informe tiene que agrupar por el MISMO eje que el cierre de la barista:
    # el día operativo del turno. Si agrupa por calendario, una venta pasada la
    # medianoche cae en un día distinto al de su propio cierre y el informe deja
    # de cuadrar con lo que ella firmó.

    def _turno_con_dia(self, fecha_operativa):
        # Get-or-create: el modelo tiene UniqueConstraint(tienda_id, fecha_operativa)
        # — UN día operativo por sede y fecha, con varios turnos colgando de él.
        dia = self.db.query(DiaOperativo).filter(
            DiaOperativo.tienda_id == self.tienda.id,
            DiaOperativo.fecha_operativa == fecha_operativa,
        ).first()
        if dia is None:
            dia = DiaOperativo(tienda_id=self.tienda.id, fecha_operativa=fecha_operativa,
                               abierto_por_id=self.usuario.id)
            self.db.add(dia)
            self.db.flush()
        turno = CajaTurno(tienda_id=self.tienda.id, usuario_apertura_id=self.usuario.id,
                          base_real=0.0, estado=EstadoTurnoEnum.abierto,
                          dia_operativo_id=dia.id)
        self.db.add(turno)
        self.db.flush()
        return turno

    def _ticket(self, turno, fecha, total):
        self.db.add(Ticket(tienda_id=self.tienda.id, caja_turno_id=turno.id,
                           usuario_id=self.usuario.id, fecha=fecha, total=total,
                           estado="completado", metodo_pago="efectivo", monto_efectivo=total))
        self.db.commit()

    def test_venta_pasada_la_medianoche_cuenta_en_su_dia_operativo(self):
        # 00:30 hora Colombia del 1-ago (UTC 05:30) pero el turno pertenece al día
        # operativo del 31-jul: el cierre la contó en julio, el informe también.
        turno = self._turno_con_dia(date(2026, 7, 31))
        self._ticket(turno, datetime(2026, 8, 1, 5, 30, 0), 40000)

        julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        self.assertIn("2026-07-31", [d["fecha"] for d in julio["dias"]])
        self.assertEqual(julio["total_mes"], 55000.0)   # 15000 del filo + 40000

        agosto = get_informe_contador(self.db, 2026, 8, self.tienda.id)
        self.assertEqual(agosto["total_mes"], 0.0)      # no se cuenta dos veces

    def test_turno_sin_dia_operativo_cae_al_dia_colombia(self):
        # dia_operativo_id es nullable y los turnos previos a la Fase 1 lo tienen
        # en NULL. Con un join estricto el informe se vaciaría: tienen que caer al
        # día calendario Colombia, que es lo único que se sabe de ellos.
        self.assertIsNone(self.turno.dia_operativo_id)
        julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        self.assertEqual([d["fecha"] for d in julio["dias"]], ["2026-07-31"])
        self.assertEqual(julio["total_mes"], 15000.0)

    def test_venta_lejos_de_su_dia_operativo_no_se_pierde(self):
        # abrir_caja BLOQUEA abrir un turno nuevo mientras el de ayer siga abierto,
        # así que el POS sigue vendiendo sobre el viejo y la venta puede quedar a
        # varios días de su día operativo. Con una ventana ensanchada N días fija,
        # esta fila se caía de LOS DOS informes (ni en julio por su día operativo,
        # ni en agosto por su calendario). Filtrando cada eje por su propia columna
        # no hay agujero, sin importar la separación.
        turno = self._turno_con_dia(date(2026, 7, 31))
        self._ticket(turno, datetime(2026, 8, 2, 15, 0, 0), 99000)   # calendario: 2-ago

        julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        self.assertIn("2026-07-31", [d["fecha"] for d in julio["dias"]])
        self.assertEqual(julio["total_mes"], 114000.0)   # 15000 + 99000

        agosto = get_informe_contador(self.db, 2026, 8, self.tienda.id)
        self.assertEqual(agosto["total_mes"], 0.0)       # no se duplica

    def test_el_informe_cuadra_con_el_cierre_del_dia(self):
        # LA propiedad por la que existe este cambio: el total del día en el informe
        # tiene que ser el mismo que la barista firma en el cierre. Los turnos
        # acumulan total_ventas ticket a ticket (crear_ticket), y el cierre cuadra
        # contra ese acumulado. Si los ejes no coinciden, los números tampoco.
        fecha_op = date(2026, 7, 20)
        t1 = self._turno_con_dia(fecha_op)
        t2 = self._turno_con_dia(fecha_op)          # dos turnos, mismo día operativo
        self._ticket(t1, datetime(2026, 7, 20, 18, 0, 0), 30000)
        self._ticket(t2, datetime(2026, 7, 21, 4, 0, 0), 20000)   # 23:00 COL del 20
        for t, total in ((t1, 30000.0), (t2, 20000.0)):
            t.total_ventas = total                  # lo que acumuló crear_ticket
        self.db.commit()

        julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        fila = next(d for d in julio["dias"] if d["fecha"] == fecha_op.isoformat())
        cierre = sum(t.total_ventas for t in (t1, t2))
        self.assertEqual(fila["total"], cierre)
        self.assertEqual(fila["facturas"], 2)

    def test_dia_operativo_manda_sobre_el_calendario(self):
        # Mismo instante, dos turnos: el que declara día operativo gana. Sin esto
        # el test anterior pasaría igual agrupando por calendario.
        turno = self._turno_con_dia(date(2026, 7, 15))
        self._ticket(turno, datetime(2026, 7, 21, 15, 0, 0), 9000)   # calendario: 21-jul

        julio = get_informe_contador(self.db, 2026, 7, self.tienda.id)
        fechas = [d["fecha"] for d in julio["dias"]]
        self.assertIn("2026-07-15", fechas)
        self.assertNotIn("2026-07-21", fechas)


if __name__ == "__main__":
    unittest.main()
