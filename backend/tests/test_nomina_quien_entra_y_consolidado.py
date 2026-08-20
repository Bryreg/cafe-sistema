"""Dos preguntas que este módulo venía confundiendo, y la plata que se caía.

1. QUIÉN ENTRA A LA NÓMINA. No se entra por tener rol barista: se entra por
   TENER CONTRATO CARGADO. El rol dice qué se puede hacer en el sistema; el
   contrato dice que se le paga. El administrador cobra sueldo —el más grande de
   la planilla— y quedaba fuera de la lista de contratos y del resumen del mes,
   así que su costo daba $0 en toda proyección.

2. QUÉ INSUMOS VAN CONSOLIDADOS. La regla de oro del módulo (services/nomina.py):
   TODO insumo de la liquidación de una persona viene de TODAS las sedes. Ya se
   habían corregido los tramos, las pausas de almuerzo y las novedades del
   resumen mensual; quedaba `costo_laboral` —el que consume el P&L— leyendo las
   novedades filtradas por sede. Consecuencia medida acá: una incapacidad
   cargada en Vida para alguien con turno publicado en Palmetto no acreditaba
   NADA en el margen, mientras la pantalla de nómina sí la acreditaba. Dos
   números para la misma obligación, y el del margen siempre el más barato.

Lo que NO cambia y también está fijado acá: quién entra sigue siendo una
pregunta de SEDE. El consolidado es un insumo del CÁLCULO de quien ya está en la
pantalla, nunca un criterio de pertenencia a ella.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    CajaTurno, ContratoBarista, EstadoTurnoEnum, NovedadNomina, RolEnum,
    Tienda, TipoNovedadNominaEnum, TurnoBarista, Usuario,
)
from app.services import horarios as hsvc
from app.services import nomina as nsvc

COL = timedelta(hours=5)   # Colombia UTC-5: hora local + 5 = UTC

# 1.800.000 / 240 = $7.500 la hora ordinaria diurna → $60.000 el turno de 8 h.
SALARIO = 1_800_000.0
VALOR_HORA = SALARIO / 240.0
TURNO_8H = 8 * VALOR_HORA


def utc(y, m, d, h, mi=0):
    """Instante UTC que corresponde a esa hora de RELOJ en Colombia."""
    return datetime(y, m, d, h, mi) + COL


class _Base(unittest.TestCase):
    """Dos sedes, un admin y una barista. El martes 2026-08-11 es el día testigo."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.palmetto = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()

        self.admin = Usuario(nombre="Aldo Admin", email="admin@t.local",
                             password_hash="h", rol=RolEnum.admin,
                             tienda_id=self.vida.id, activo=True)
        self.cath = Usuario(nombre="Catherin", email="cath@t.local",
                            password_hash="h", rol=RolEnum.barista,
                            tienda_id=self.vida.id, activo=True)
        self.db.add_all([self.admin, self.cath])
        self.db.commit()

        self.martes = date(2026, 8, 11)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def con_contrato(self, usuario, salario=SALARIO):
        self.db.add(ContratoBarista(usuario_id=usuario.id, salario_mensual=salario))
        self.db.commit()

    def publicar_turno(self, tienda, usuario, dia=None, inicio="08:00", fin="16:00"):
        d = dia or self.martes
        hsvc.guardar_turno(self.db, tienda.id, usuario.id, d, inicio, fin,
                           creado_por_id=self.admin.id)
        hsvc.publicar_semana(self.db, tienda.id, hsvc.lunes_de(d), self.admin.id)

    def incapacidad(self, tienda, usuario, dia=None):
        """La novedad se inserta a mano y no por `novedades_nomina.crear` a
        propósito: ese camino dispara notificaciones y push, que no son lo que
        se está midiendo. Lo que importa es la FILA, que es lo que lee el
        cálculo."""
        d = dia or self.martes
        self.db.add(NovedadNomina(
            tienda_id=tienda.id, usuario_id=usuario.id,
            nombre_snapshot=usuario.nombre,
            tipo=TipoNovedadNominaEnum.incapacidad,
            fecha_desde=d, fecha_hasta=d, remunerada=True))
        self.db.commit()

    def marcar_8h(self, tienda, usuario, dia=None):
        """Un tramo REAL 08:00 → 16:00, como lo deja el flujo de caja."""
        d = dia or self.martes
        entrada, salida = utc(d.year, d.month, d.day, 8), utc(d.year, d.month, d.day, 16)
        turno = CajaTurno(tienda_id=tienda.id, usuario_apertura_id=usuario.id,
                          base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                          fecha_apertura=entrada, fecha_cierre=salida)
        self.db.add(turno)
        self.db.flush()
        self.db.add(TurnoBarista(turno_id=turno.id, usuario_id=usuario.id,
                                 nombre_snapshot=usuario.nombre,
                                 created_at=entrada, salida_at=salida))
        self.db.commit()

    def fila_de(self, resumen, usuario):
        for b in resumen["baristas"]:
            if b["usuario_id"] == usuario.id:
                return b
        return None

    def resumen(self, tienda):
        return nsvc.resumen_mensual(self.db, tienda.id, self.martes.year, self.martes.month)

    def costo(self, tienda_id=None):
        return nsvc.costo_laboral(self.db, self.martes, self.martes, tienda_id=tienda_id)


# ═══════════════════════════════════════════════════════════════════════════════
# (a) LA GRIETA: el P&L leía las novedades filtradas por sede
# ═══════════════════════════════════════════════════════════════════════════════

class NovedadConsolidadaEnElPLTest(_Base):
    """Incapacidad cargada en Vida, turno publicado en Palmetto, cero marcación.

    El día tiene que valer 8 h acreditadas en las DOS lecturas. Antes valía 8 h
    en la pantalla de nómina y $0 en el margen: la vuelta de Palmetto no veía la
    novedad (estaba cargada en Vida) y la de Vida no tenía el turno que
    acreditar. El día se evaporaba entre las dos.
    """

    def setUp(self):
        super().setUp()
        self.con_contrato(self.cath)
        self.publicar_turno(self.palmetto, self.cath)
        self.incapacidad(self.vida, self.cath)

    def test_el_pl_acredita_las_horas_del_turno_de_la_otra_sede(self):
        self.assertAlmostEqual(self.costo()["total"], TURNO_8H, places=2)

    def test_las_horas_del_pl_son_las_del_turno_publicado(self):
        self.assertAlmostEqual(self.costo()["horas"], 8.0, places=2)

    def test_el_costo_queda_atribuido_a_la_sede_del_TURNO_no_a_la_de_la_novedad(self):
        """La plata la causa el turno que se iba a trabajar, no el papel de la
        incapacidad: si se atribuyera a la sede donde el admin escribió la
        novedad, el margen de Vida cargaría un costo que es de Palmetto."""
        pares = self.costo()["por_mes_sede"]
        self.assertAlmostEqual(pares.get(("2026-08", self.palmetto.id), 0.0),
                               TURNO_8H, places=2)
        self.assertAlmostEqual(pares.get(("2026-08", self.vida.id), 0.0), 0.0, places=2)

    def test_coincide_al_peso_con_la_pantalla_de_nomina(self):
        """EL TEST DEL ENCARGO: las mismas horas acá y allá. Si los dos números
        se separan otra vez, es porque volvió a colarse un insumo por sede."""
        fila = self.fila_de(self.resumen(self.palmetto), self.cath)
        self.assertEqual(fila["total_acreditado"], 8.0)
        self.assertAlmostEqual(fila["estimado"]["total"], self.costo()["total"], places=2)

    def test_la_persona_cuenta_una_sola_vez_aunque_haya_dos_sedes(self):
        """El consolidado no puede convertirse en doble conteo: el mismo día no
        se paga en las dos vueltas del loop de sedes."""
        self.assertEqual(self.costo()["personas"], 1)
        self.assertAlmostEqual(self.costo()["total"], TURNO_8H, places=2)

    def test_filtrando_por_la_sede_de_la_novedad_el_costo_sigue_siendo_de_palmetto(self):
        """Un P&L de Vida no se lleva el costo del turno de Palmetto de arrastre
        por tener la novedad escrita ahí."""
        self.assertAlmostEqual(self.costo(tienda_id=self.vida.id)["total"], 0.0, places=2)
        self.assertAlmostEqual(self.costo(tienda_id=self.palmetto.id)["total"],
                               TURNO_8H, places=2)


class NovedadConsolidadaNoInflaElUniversoTest(_Base):
    """La otra mitad de la regla: quién entra sigue siendo pregunta de SEDE.

    Consolidar las novedades para el CÁLCULO no puede meter a la gente de la
    otra sede en el recorrido de ésta — es el descuido que en el resumen mensual
    llegó a mostrar la nómina de las dos sedes dentro del número de una.
    """

    def test_una_novedad_ajena_no_agrega_gente_ni_costo_a_esta_sede(self):
        otra = Usuario(nombre="Luisa", email="luisa@t.local", password_hash="h",
                       rol=RolEnum.barista, tienda_id=self.palmetto.id, activo=True)
        self.db.add(otra)
        self.db.commit()
        self.con_contrato(otra)
        # Trabajó de verdad en Palmetto y tiene una novedad escrita en Vida.
        self.marcar_8h(self.palmetto, otra)
        self.incapacidad(self.vida, otra)

        self.assertAlmostEqual(self.costo(tienda_id=self.vida.id)["total"], 0.0, places=2)
        self.assertEqual(self.costo(tienda_id=self.vida.id)["personas"], 0)

    def test_un_dia_ya_marcado_no_se_paga_dos_veces_por_tener_novedad(self):
        """`_acreditar` no acredita el planeado de un día CON marcación propia.
        Consolidar la novedad no puede romper esa guarda."""
        self.con_contrato(self.cath)
        self.publicar_turno(self.palmetto, self.cath)
        self.marcar_8h(self.palmetto, self.cath)
        self.incapacidad(self.vida, self.cath)
        self.assertAlmostEqual(self.costo()["total"], TURNO_8H, places=2)


# ═══════════════════════════════════════════════════════════════════════════════
# (b) EL SUELDO DEL ADMINISTRADOR: se entra por contrato, no por rol
# ═══════════════════════════════════════════════════════════════════════════════

class QuienEntraALaNominaTest(_Base):
    def test_el_admin_con_contrato_aparece_en_la_planilla_de_su_sede(self):
        self.con_contrato(self.admin, 4_000_000.0)
        ids = [u.id for u in hsvc.personas_de_nomina(self.db, self.vida.id)]
        self.assertIn(self.admin.id, ids)

    def test_el_admin_sin_contrato_sigue_afuera(self):
        """La otra mitad del criterio: nadie se mete solo en la planilla por
        tener permisos. Alguien tiene que declarar que se le paga."""
        ids = [u.id for u in hsvc.personas_de_nomina(self.db, self.vida.id)]
        self.assertNotIn(self.admin.id, ids)

    def test_el_admin_no_entra_a_la_grilla_de_turnos_ni_con_contrato(self):
        """`baristas_de` responde «a quién le toca turno» y esa pregunta no
        cambió: unificar las dos listas metería al admin en el horario del
        mostrador."""
        self.con_contrato(self.admin, 4_000_000.0)
        ids = [u.id for u in hsvc.baristas_de(self.db, self.vida.id)]
        self.assertNotIn(self.admin.id, ids)

    def test_el_kiosko_nunca_entra_aunque_le_carguen_contrato(self):
        """El kiosko es un DISPOSITIVO. Que el criterio pase a ser el contrato
        no puede abrirle la puerta a un usuario que no es una persona."""
        kiosk = Usuario(nombre="Kiosk", email="kiosk@vida.device", password_hash="h",
                        rol=RolEnum.barista, tienda_id=self.vida.id, activo=True)
        self.db.add(kiosk)
        self.db.commit()
        self.con_contrato(kiosk)
        ids = [u.id for u in hsvc.personas_de_nomina(self.db, self.vida.id)]
        self.assertNotIn(kiosk.id, ids)
        self.assertFalse(nsvc._es_persona(kiosk, {kiosk.id}))

    def test_el_admin_con_contrato_aparece_en_el_resumen_del_mes(self):
        """EL CONTEO, que es lo que alimenta la proyección: sin esto el sueldo
        más grande de la planilla no existe para ninguna pantalla."""
        self.con_contrato(self.admin, 4_000_000.0)
        fila = self.fila_de(self.resumen(self.vida), self.admin)
        self.assertIsNotNone(fila)
        self.assertTrue(fila["tiene_contrato"])
        self.assertEqual(fila["salario_mensual"], 4_000_000.0)

    def test_sin_contrato_el_admin_no_ensucia_el_resumen(self):
        self.assertIsNone(self.fila_de(self.resumen(self.vida), self.admin))

    def test_las_horas_que_el_admin_marca_valen_como_las_de_cualquiera(self):
        """Si tiene contrato y marcó en caja, su tiempo es costo laboral. Antes
        `_es_persona` lo descartaba por el rol y esas horas eran gratis."""
        self.con_contrato(self.admin, SALARIO)
        self.marcar_8h(self.vida, self.admin)
        self.assertAlmostEqual(self.costo(tienda_id=self.vida.id)["total"],
                               TURNO_8H, places=2)

    def test_sin_contrato_esas_mismas_horas_no_cuentan(self):
        """La garantía de que esto no le mueve el número a nadie que todavía no
        cargó el contrato del admin."""
        self.marcar_8h(self.vida, self.admin)
        self.assertAlmostEqual(self.costo(tienda_id=self.vida.id)["total"], 0.0, places=2)
        self.assertEqual(self.costo(tienda_id=self.vida.id)["personas"], 0)

    def test_la_barista_entra_por_rol_aunque_no_tenga_contrato(self):
        """Nada de lo anterior le cierra la puerta a quien ya entraba: la
        barista sin contrato tiene que seguir apareciendo, justamente para que
        la pantalla pueda avisar que sus horas valen $0."""
        ids = [u.id for u in hsvc.personas_de_nomina(self.db, self.vida.id)]
        self.assertIn(self.cath.id, ids)

    def test_el_admin_de_la_otra_sede_no_se_cuela(self):
        """`personas_de_nomina` sigue siendo POR SEDE: el contrato dice que se
        le paga, no en qué local aparece."""
        self.con_contrato(self.admin, 4_000_000.0)
        ids = [u.id for u in hsvc.personas_de_nomina(self.db, self.palmetto.id)]
        self.assertNotIn(self.admin.id, ids)

    def test_un_admin_dado_de_baja_no_vuelve_por_tener_contrato_viejo(self):
        """La baja de verdad es `Usuario.activo`. Un contrato que quedó cargado
        no puede resucitar a alguien que ya no trabaja acá."""
        self.con_contrato(self.admin, 4_000_000.0)
        self.admin.activo = False
        self.db.commit()
        ids = [u.id for u in hsvc.personas_de_nomina(self.db, self.vida.id)]
        self.assertNotIn(self.admin.id, ids)


if __name__ == "__main__":
    unittest.main()
