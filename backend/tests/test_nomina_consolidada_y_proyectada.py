"""La nómina del NEGOCIO: el número que se puede sumar, y el del mes que viene.

El caso es el real: MEDIUM CAFÉ, siete personas (seis baristas y el
administrador), dos sedes, agosto de 2026, pago el 31.

Dos agujeros distintos, y los dos daban de MENOS:

1. NO HABÍA UN NÚMERO GLOBAL. `/horarios/resumen` exige `tienda_id`, y sumar los
   dos resúmenes NO da la nómina: quien cubre en las dos sedes aparece ENTERA en
   los dos (el auxilio de transporte, el piso del IBC, los aportes y las
   prestaciones son mensuales POR TRABAJADOR), así que la suma la cuenta dos
   veces. Y partirla tampoco: prorratear por fracción de devengado dejaba las
   partes sumando 0,934 de la persona. `consolidada` arma el universo UNA vez y
   liquida UNA vez por cabeza — es la única forma correcta de tenerlo.

2. LA PROYECCIÓN DABA $0. `_acreditar` suma tramos planeados solo en los días
   que YA tienen una novedad remunerada encima, así que un mes que todavía no
   ocurrió —sin marcaciones y sin novedades— proyecta cero. Con él daban cero el
   punto de quiebre, el piso de venta y el colchón para activaciones. La
   proyectada sale del CONTRATO y no de las horas, y no puede dar $0 mientras
   haya un contrato con sueldo.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    CajaTurno, ContratoBarista, EstadoTurnoEnum, NovedadNomina, RolEnum,
    Tienda, TipoNovedadNominaEnum, TurnoBarista, Usuario,
)
from app.services import horarios as hsvc
from app.services import nomina as nsvc
from app.services import parametros_nomina as pnsvc

COL = timedelta(hours=5)   # Colombia UTC-5: hora local + 5 = UTC

# Agosto de 2026. El 31 es el último día del mes y el día de pago.
ANIO, MES = 2026, 8
PRIMERO = date(2026, 8, 1)
ULTIMO = date(2026, 8, 31)
# Martes 2026-08-11, dentro de la semana del lunes 2026-08-10.
MARTES = date(2026, 8, 11)

# Sueldos de la planilla real: seis baristas al mínimo y el administrador arriba.
SALARIO_ADMIN = 4_000_000.0


def utc(y, m, d, h, mi=0):
    """Instante UTC que corresponde a esa hora de RELOJ en Colombia."""
    return datetime(y, m, d, h, mi) + COL


class _Planilla(unittest.TestCase):
    """Las siete personas de MEDIUM CAFÉ, repartidas en las dos sedes.

    Los seis baristas van con `salario_en_smmlv=1.0` —que es como están cargados
    de verdad— para que el sueldo salga del mínimo vigente en la fecha liquidada
    y no de un número tecleado alguna vez.
    """

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
        self.db.add(self.admin)
        self.baristas = []
        for i, (nombre, sede) in enumerate([
                ("Catherin", self.vida), ("Daniela", self.vida),
                ("Estefanía", self.vida), ("Fabián", self.palmetto),
                ("Gloria", self.palmetto), ("Hernán", self.palmetto)]):
            u = Usuario(nombre=nombre, email=f"b{i}@t.local", password_hash="h",
                        rol=RolEnum.barista, tienda_id=sede.id, activo=True)
            self.baristas.append(u)
            self.db.add(u)
        self.db.commit()

        self.contratar(self.admin, salario_mensual=SALARIO_ADMIN)
        for u in self.baristas:
            self.contratar(u, en_smmlv=1.0)

        # El mínimo y el auxilio de 2026 salen de la siembra de parámetros.
        self.params = pnsvc.para(self.db, PRIMERO)
        self.minimo = self.params.smmlv

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def contratar(self, usuario, salario_mensual=0.0, en_smmlv=None):
        self.db.add(ContratoBarista(usuario_id=usuario.id,
                                    salario_mensual=salario_mensual,
                                    salario_en_smmlv=en_smmlv))
        self.db.commit()

    def publicar_turno(self, tienda, usuario, dia=MARTES, inicio="08:00", fin="16:00"):
        hsvc.guardar_turno(self.db, tienda.id, usuario.id, dia, inicio, fin,
                           creado_por_id=self.admin.id)
        hsvc.publicar_semana(self.db, tienda.id, hsvc.lunes_de(dia), self.admin.id)

    def marcar_8h(self, tienda, usuario, dia=MARTES):
        """Un tramo REAL 08:00 → 16:00, como lo deja el flujo de caja."""
        entrada, salida = utc(dia.year, dia.month, dia.day, 8), utc(dia.year, dia.month, dia.day, 16)
        turno = CajaTurno(tienda_id=tienda.id, usuario_apertura_id=usuario.id,
                          base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                          fecha_apertura=entrada, fecha_cierre=salida)
        self.db.add(turno)
        self.db.flush()
        self.db.add(TurnoBarista(turno_id=turno.id, usuario_id=usuario.id,
                                 nombre_snapshot=usuario.nombre,
                                 created_at=entrada, salida_at=salida))
        self.db.commit()

    def incapacidad(self, tienda, usuario, dia=MARTES):
        self.db.add(NovedadNomina(
            tienda_id=tienda.id, usuario_id=usuario.id,
            nombre_snapshot=usuario.nombre,
            tipo=TipoNovedadNominaEnum.incapacidad,
            fecha_desde=dia, fecha_hasta=dia, remunerada=True))
        self.db.commit()

    def fila(self, payload, usuario):
        clave = "personas" if "personas" in payload else "baristas"
        for f in payload[clave]:
            if f["usuario_id"] == usuario.id:
                return f
        return None

    def consolidada(self):
        return nsvc.consolidada(self.db, ANIO, MES)

    def resumen(self, tienda):
        return nsvc.resumen_mensual(self.db, tienda.id, ANIO, MES)


# ═══════════════════════════════════════════════════════════════════════════════
# (a) LA CONSOLIDADA: un universo, una liquidación por cabeza
# ═══════════════════════════════════════════════════════════════════════════════

class ConsolidadaUniversoTest(_Planilla):
    """Quién aparece cuando la pantalla es el negocio entero."""

    def test_estan_las_siete_personas(self):
        """El administrador incluido: a la planilla se entra por tener CONTRATO,
        no por tener rol barista."""
        payload = self.consolidada()
        self.assertEqual(len(payload["personas"]), 7)
        self.assertIsNotNone(self.fila(payload, self.admin))

    def test_cada_persona_aparece_una_sola_vez(self):
        """La garantía dura del consolidado: un id, una fila. Con la persona
        cubriendo en las dos sedes, un consolidado armado sumando resúmenes la
        traería dos veces."""
        cath = self.baristas[0]
        self.marcar_8h(self.vida, cath)
        self.marcar_8h(self.palmetto, cath, dia=MARTES + timedelta(days=1))
        ids = [f["usuario_id"] for f in self.consolidada()["personas"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_lleva_tienda_id(self):
        """No es «una sede más»: la clave no está para que ninguna pantalla la
        trate como un filtro."""
        self.assertNotIn("tienda_id", self.consolidada())

    def test_entra_quien_tiene_contrato_y_ninguna_sede_asignada(self):
        """El caso que se caería armando el universo con dos llamadas por sede:
        `Usuario.tienda_id` en NULL no matchea ninguna de las dos, y ese sueldo
        desaparecía del total sin que nada avisara."""
        suelto = Usuario(nombre="Zulema", email="z@t.local", password_hash="h",
                         rol=RolEnum.barista, tienda_id=None, activo=True)
        self.db.add(suelto)
        self.db.commit()
        self.contratar(suelto, en_smmlv=1.0)
        self.assertIsNotNone(self.fila(self.consolidada(), suelto))
        # Y no está en ninguno de los dos resúmenes por sede, que es el punto.
        self.assertIsNone(self.fila(self.resumen(self.vida), suelto))
        self.assertIsNone(self.fila(self.resumen(self.palmetto), suelto))

    def test_el_kiosko_nunca_entra(self):
        kiosk = Usuario(nombre="Kiosk", email="kiosk@vida.device", password_hash="h",
                        rol=RolEnum.barista, tienda_id=self.vida.id, activo=True)
        self.db.add(kiosk)
        self.db.commit()
        self.contratar(kiosk, en_smmlv=1.0)
        self.assertIsNone(self.fila(self.consolidada(), kiosk))

    def test_no_advierte_que_no_se_sumen_los_resumenes(self):
        """La advertencia de «SUMAR DOS RESÚMENES LA CUENTA DOS VECES» es cierta
        para las pantallas por sede y sería un absurdo acá: este total se suma.
        Una advertencia que no aplica enseña a no leer ninguna."""
        avisos = self.consolidada()["advertencias"]
        self.assertNotIn(nsvc.ADVERTENCIA_NO_SUMAR_SEDES, avisos)
        self.assertIn(nsvc.ADVERTENCIA_NO_SUMAR_SEDES, self.resumen(self.vida)["advertencias"])


class ConsolidadaNoEsLaSumaDeLosResumenesTest(_Planilla):
    """EL TEST DEL ENCARGO: la plata que se contaba dos veces al sumar sedes.

    Catherin trabaja el martes en Vida y el miércoles en Palmetto. Su
    liquidación es UNA —el auxilio, el piso del IBC, los aportes y las
    prestaciones son mensuales por trabajador— y aparece entera en los dos
    resúmenes.
    """

    def setUp(self):
        super().setUp()
        self.cath = self.baristas[0]
        self.marcar_8h(self.vida, self.cath, dia=MARTES)
        self.marcar_8h(self.palmetto, self.cath, dia=MARTES + timedelta(days=1))

    def test_la_suma_de_los_dos_resumenes_cuenta_de_mas(self):
        """La medición: sumar las dos pantallas infla el costo en la
        liquidación entera de quien cubrió en las dos."""
        suma_sedes = (self.resumen(self.vida)["totales"]["total_costo_empleador"]
                      + self.resumen(self.palmetto)["totales"]["total_costo_empleador"])
        consolidado = self.consolidada()["totales"]["total_costo_empleador"]
        de_mas = round(suma_sedes - consolidado, 2)
        self.assertGreater(de_mas, 0)
        # Lo que sobra es exactamente su liquidación repetida.
        fila_cath = self.fila(self.consolidada(), self.cath)
        self.assertAlmostEqual(de_mas, fila_cath["liquidacion"]["costo_empleador"],
                               places=2)

    def test_el_total_es_la_suma_de_las_liquidaciones_de_cada_persona(self):
        """Los cinco números se SUMAN, nunca se recalculan sobre un devengado
        agregado: el piso del IBC y el tope del auxilio son por PERSONA."""
        payload = self.consolidada()
        for clave, campo in (("total_costo_empleador", "costo_empleador"),
                             ("total_neto", "neto_a_pagar"),
                             ("total_devengado", "devengado")):
            esperado = round(sum(f["liquidacion"][campo] for f in payload["personas"]), 2)
            self.assertAlmostEqual(payload["totales"][clave], esperado, places=2)

    def test_la_liquidacion_consolidada_de_la_persona_es_la_misma_que_ve_cada_sede(self):
        """No es un tercer número: el resumen por sede ya muestra la liquidación
        ENTERA de la persona. La consolidada tiene que coincidir al peso, o hay
        dos matemáticas para la misma obligación."""
        de_vida = self.fila(self.resumen(self.vida), self.cath)["liquidacion"]
        consolidada = self.fila(self.consolidada(), self.cath)["liquidacion"]
        self.assertAlmostEqual(consolidada["costo_empleador"],
                               de_vida["costo_empleador"], places=2)
        self.assertAlmostEqual(consolidada["devengado"], de_vida["devengado"], places=2)

    def test_las_horas_de_las_dos_sedes_se_suman_una_sola_vez(self):
        """16 h en total: 8 en Vida y 8 en Palmetto, ni 8 ni 32."""
        fila = self.fila(self.consolidada(), self.cath)
        self.assertAlmostEqual(fila["total_acreditado"], 16.0, places=2)

    def test_nadie_queda_marcado_en_varias_sedes(self):
        """En la vista del negocio entero no hay «otra sede» de la cual estar:
        `devengado_en_esta_sede` es el devengado y `en_varias_sedes` es False."""
        fila = self.fila(self.consolidada(), self.cath)
        self.assertFalse(fila["liquidacion"]["en_varias_sedes"])
        self.assertAlmostEqual(fila["liquidacion"]["devengado_en_esta_sede"],
                               fila["liquidacion"]["devengado"], places=2)
        self.assertEqual(self.consolidada()["totales"]["en_varias_sedes"], 0)


class ConsolidadaInsumosDeTodasLasSedesTest(_Planilla):
    """La regla de oro: TODO insumo de la liquidación viene consolidado."""

    def test_la_novedad_de_una_sede_acredita_el_turno_publicado_en_la_otra(self):
        """Incapacidad escrita en Vida, turno publicado en Palmetto, sin
        marcación: el día vale las 8 h que tenía programadas."""
        cath = self.baristas[0]
        self.publicar_turno(self.palmetto, cath)
        self.incapacidad(self.vida, cath)
        self.assertAlmostEqual(self.fila(self.consolidada(), cath)["total_acreditado"],
                               8.0, places=2)

    def test_un_dia_ya_marcado_no_se_paga_dos_veces_por_tener_novedad(self):
        cath = self.baristas[0]
        self.publicar_turno(self.palmetto, cath)
        self.marcar_8h(self.palmetto, cath)
        self.incapacidad(self.vida, cath)
        self.assertAlmostEqual(self.fila(self.consolidada(), cath)["total_acreditado"],
                               8.0, places=2)


class ConsolidadaMesInvalidoTest(_Planilla):
    def test_mes_fuera_de_rango_es_un_400_con_texto(self):
        """Las validaciones contestan 400 con un string: el `detail` de un 422
        es una lista y el cliente solo lee strings."""
        with self.assertRaises(HTTPException) as ctx:
            nsvc.consolidada(self.db, ANIO, 13)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, str)

    def test_anio_fuera_del_calendario_no_revienta_con_un_500(self):
        with self.assertRaises(HTTPException) as ctx:
            nsvc.consolidada(self.db, 0, MES)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, str)


# ═══════════════════════════════════════════════════════════════════════════════
# (b) LA PROYECTADA: del CONTRATO, y nunca $0
# ═══════════════════════════════════════════════════════════════════════════════

class ProyectadaNoDaCeroTest(_Planilla):
    """EL BUG, fijado explícitamente y en las dos direcciones.

    Septiembre de 2026 no tiene ni una marcación, ni un turno publicado, ni una
    novedad: es el mes que viene. `_acreditar` no tiene de dónde sacar un tramo y
    devuelve vacío, así que todo lo que pase por las horas da $0.
    """

    def setUp(self):
        super().setUp()
        self.anio_sig, self.mes_sig = 2026, 9

    def proyectada(self):
        return nsvc.proyectada(self.db, self.anio_sig, self.mes_sig)

    def test_la_proyectada_no_puede_dar_cero_con_contratos_activos(self):
        """LA INVARIANTE. Siete contratos con sueldo cargado: el mes que viene
        cuesta plata, y decir $0 es lo que dejaba la nómina fuera del punto de
        quiebre, del piso de venta y del colchón para activaciones."""
        totales = self.proyectada()["totales"]
        self.assertGreater(totales["total_costo_empleador"], 0)
        self.assertGreater(totales["total_devengado"], 0)
        self.assertGreater(totales["total_neto"], 0)

    def test_un_mes_sin_ningun_turno_publicado_igual_proyecta_el_sueldo_completo(self):
        """El otro test que pide el encargo. Publicar el horario NO arreglaba
        nada —el planeado solo se acredita en días con novedad remunerada—, así
        que la prueba es que sin un solo turno publicado el número ya está
        completo: es el sueldo pactado del mes entero, no una fracción."""
        turnos = hsvc.turnos_publicados(
            self.db, self.vida.id, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(list(turnos), [])
        cath = self.fila(self.proyectada(), self.baristas[0])
        self.assertAlmostEqual(cath["liquidacion"]["devengado"], self.minimo, places=2)

    def test_el_camino_por_las_horas_SI_da_cero_ese_mismo_mes(self):
        """La contraprueba que hace que el test de arriba signifique algo: el
        cálculo que este encargo NO usa devuelve exactamente $0 para ese mes.
        Sin esto, «la proyectada no da cero» podría estar pasando de casualidad.
        """
        por_horas = nsvc.consolidada(self.db, self.anio_sig, self.mes_sig)
        self.assertEqual(por_horas["totales"]["total_costo_empleador"], 0.0)
        self.assertGreater(self.proyectada()["totales"]["total_costo_empleador"], 0)

    def test_estan_las_siete_personas_con_su_sueldo(self):
        payload = self.proyectada()
        self.assertEqual(len(payload["personas"]), 7)
        self.assertEqual(payload["totales"]["sin_sueldo"], 0)
        self.assertAlmostEqual(
            self.fila(payload, self.admin)["salario_mensual"], SALARIO_ADMIN, places=2)

    def test_el_costo_es_bastante_mas_que_la_suma_de_los_sueldos(self):
        """El sueldo no es lo que cuesta la persona: el costo empleador es ~1,55
        a 1,69 veces. Es el número que el dueño necesita para saber cuánta plata
        tener, y el que faltaba en todas las proyecciones."""
        payload = self.proyectada()
        sueldos = sum(f["salario_mensual"] for f in payload["personas"])
        self.assertGreater(payload["totales"]["total_costo_empleador"], sueldos * 1.2)

    def test_marca_que_es_una_proyeccion_y_de_donde_sale(self):
        payload = self.proyectada()
        self.assertTrue(payload["es_proyeccion"])
        self.assertEqual(payload["base_liquidacion"], "contrato")
        self.assertTrue(payload["advertencias"])


class ProyectadaSinSueldoCargadoTest(_Planilla):
    """Quien no tiene sueldo cargado proyecta $0 — y no cobra auxilio."""

    def setUp(self):
        super().setUp()
        self.nueva = Usuario(nombre="Yamile", email="y@t.local", password_hash="h",
                             rol=RolEnum.barista, tienda_id=self.vida.id, activo=True)
        self.db.add(self.nueva)
        self.db.commit()

    def test_aparece_marcada_y_no_suma_plata(self):
        fila = self.fila(nsvc.proyectada(self.db, 2026, 9), self.nueva)
        self.assertIsNotNone(fila)
        self.assertFalse(fila["tiene_sueldo"])
        self.assertEqual(fila["liquidacion"]["costo_empleador"], 0.0)

    def test_sin_devengado_no_hay_auxilio_de_transporte(self):
        """El guardia que ya tiene el resumen mensual: `auxilio_del_periodo` le
        da derecho a cualquier sueldo por debajo del tope y $0 está por debajo,
        así que sin esto una barista sin contrato aparecía cobrando el auxilio
        entero y nada más."""
        fila = self.fila(nsvc.proyectada(self.db, 2026, 9), self.nueva)
        self.assertEqual(fila["liquidacion"]["auxilio"]["total"], 0.0)
        self.assertEqual(fila["liquidacion"]["auxilio"]["dias"], 0)

    def test_el_total_lo_cuenta_en_sin_sueldo(self):
        payload = nsvc.proyectada(self.db, 2026, 9)
        self.assertEqual(payload["totales"]["sin_sueldo"], 1)


class ProyectadaSueldoDeSuFechaTest(_Planilla):
    """El sueldo se resuelve por la fecha del PERÍODO PROYECTADO, no por hoy."""

    def test_enero_del_ano_que_viene_usa_el_minimo_de_ese_ano(self):
        """Un contrato que dice «1 SMMLV» vale el mínimo del mes que se proyecta.
        Proyectar enero con el mínimo del año anterior nace corto justo en el mes
        en que el sueldo sube."""
        de_2025 = pnsvc.para(self.db, date(2025, 6, 1)).smmlv
        de_2026 = pnsvc.para(self.db, date(2026, 6, 1)).smmlv
        self.assertGreater(de_2026, de_2025)
        cath = self.baristas[0]
        en_2025 = self.fila(nsvc.proyectada(self.db, 2025, 6), cath)
        en_2026 = self.fila(nsvc.proyectada(self.db, 2026, 6), cath)
        self.assertAlmostEqual(en_2025["salario_mensual"], de_2025, places=2)
        self.assertAlmostEqual(en_2026["salario_mensual"], de_2026, places=2)

    def test_el_auxilio_va_por_los_30_dias_del_mes_comercial(self):
        """Febrero (28 días) y agosto (31) pagan el MISMO auxilio: el mes de
        nómina son 30 días siempre, que es el divisor con el que se liquida un
        mes cerrado."""
        feb = nsvc.proyectada(self.db, 2026, 2)
        ago = nsvc.proyectada(self.db, 2026, 8)
        self.assertEqual(feb["dias_auxilio_base"], 30)
        self.assertEqual(ago["dias_auxilio_base"], 30)
        self.assertAlmostEqual(feb["totales"]["total_auxilio"],
                               ago["totales"]["total_auxilio"], places=2)

    def test_el_administrador_no_cobra_auxilio_porque_supera_el_tope(self):
        """$4.000.000 está por encima de 2 SMMLV: el auxilio es para quien gana
        poco, y el cálculo tiene que decir POR QUÉ no lo lleva."""
        fila = self.fila(nsvc.proyectada(self.db, 2026, 9), self.admin)
        self.assertFalse(fila["liquidacion"]["auxilio"]["tiene_derecho"])
        self.assertEqual(fila["liquidacion"]["auxilio"]["total"], 0.0)
        self.assertIsNotNone(fila["liquidacion"]["auxilio"]["razon"])

    def test_las_novedades_ya_cargadas_del_mes_futuro_no_bajan_la_proyeccion(self):
        """Unas vacaciones se pagan igual; una incapacidad cambia quién pone la
        plata, no si se debe. Descontarlas bajaría el número por un dato que no
        significa lo que parece."""
        cath = self.baristas[0]
        sin_novedad = nsvc.proyectada(self.db, 2026, 9)["totales"]["total_costo_empleador"]
        self.incapacidad(self.vida, cath, dia=date(2026, 9, 8))
        con_novedad = nsvc.proyectada(self.db, 2026, 9)["totales"]["total_costo_empleador"]
        self.assertAlmostEqual(sin_novedad, con_novedad, places=2)


class ProyectadaVsConsolidadaTest(_Planilla):
    """Las dos bases sobre el MISMO mes, para que se vea qué mide cada una."""

    def test_un_mes_trabajado_a_medias_da_menos_por_horas_que_por_contrato(self):
        """Es exactamente por esto que el mes en curso se agenda por CONTRATO:
        preguntarle a las horas devuelve la parte trabajada hasta hoy con cara de
        total, o sea la mitad del sueldo dicha como si fuera el mes entero."""
        for u in self.baristas:
            self.marcar_8h(self.vida if u.tienda_id == self.vida.id else self.palmetto, u)
        por_horas = self.consolidada()["totales"]["total_costo_empleador"]
        por_contrato = nsvc.proyectada(self.db, ANIO, MES)["totales"]["total_costo_empleador"]
        self.assertGreater(por_horas, 0)
        self.assertGreater(por_contrato, por_horas)


# ═══════════════════════════════════════════════════════════════════════════════
# (c) EL ENDPOINT GLOBAL: sin tienda_id
# ═══════════════════════════════════════════════════════════════════════════════

class EndpointNominaConsolidadaTest(_Planilla):
    """`/horarios/nomina-consolidada` — el primer endpoint de nómina GLOBAL.

    Se prueba por el handler y no por HTTP: el router es una función, y lo que
    hay que fijar es que NO pide `tienda_id` y que la base se valida con un 400
    legible.
    """

    def _handler(self, **kw):
        from app.routers.horarios import nomina_consolidada
        return nomina_consolidada(db=self.db, admin=self.admin, **kw)

    def test_responde_sin_tienda_id(self):
        payload = self._handler(anio=ANIO, mes=MES, base="real")
        self.assertEqual(len(payload["personas"]), 7)
        self.assertIn("totales", payload)
        self.assertNotIn("tienda_id", payload)

    def test_la_base_contrato_devuelve_la_proyeccion(self):
        payload = self._handler(anio=2026, mes=9, base="contrato")
        self.assertTrue(payload["es_proyeccion"])
        self.assertGreater(payload["totales"]["total_costo_empleador"], 0)

    def test_una_base_inventada_es_un_400_con_texto(self):
        with self.assertRaises(HTTPException) as ctx:
            self._handler(anio=ANIO, mes=MES, base="inventada")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, str)

    def test_el_endpoint_por_sede_sigue_exigiendo_tienda_id(self):
        """Lo que este endpoint agrega no le saca nada al que ya estaba: el
        resumen por sede sigue siendo la pantalla de «qué me cuesta Vida»."""
        import inspect
        from app.routers.horarios import resumen
        firma = inspect.signature(resumen)
        self.assertIn("tienda_id", firma.parameters)
        self.assertNotIn("tienda_id",
                         inspect.signature(self._sin_self_nomina()).parameters)

    def _sin_self_nomina(self):
        from app.routers.horarios import nomina_consolidada
        return nomina_consolidada


if __name__ == "__main__":
    unittest.main()
