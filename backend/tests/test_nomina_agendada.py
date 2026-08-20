"""La nómina agendada como OBLIGACIÓN de verdad, y la cadena que eso enciende.

El caso es el real: MEDIUM CAFÉ, siete personas, agosto de 2026, la nómina
entera se paga el 31.

Hasta acá el costo laboral existía como cálculo y como pantalla, pero no como
PLATA QUE HAY QUE PAGAR: no era una `Obligacion`, así que no estaba en la
agenda, no bajaba el flujo proyectado, no tenía botón [Pagar] y no bajaba ningún
saldo. El punto de quiebre, el piso de venta y el colchón para activaciones se
calculaban todos sin el gasto más grande del negocio.

La segunda mitad de este archivo es una AUDITORÍA, no una prueba de código
nuevo: el diseño da por hecho que agendar la nómina como obligación real dispara
cinco comportamientos que ya existen, sin escribir una línea más. Acá se verifica
cada uno contra el código que hay, incluido el que NO se comporta como el diseño
esperaba (ver `NominaEnElPLTest`).
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col
from app.database import Base
from app.models.models import (
    CajaTurno, Configuracion, ContratoBarista, CostoCategoria, CuentaBancaria,
    EstadoTurnoEnum, MovimientoBanco, Obligacion, RolEnum, Tienda,
    TurnoBarista, Usuario,
)
from app.schemas.costos import PagoCreate
from app.services import costos as svc
from app.services.rentabilidad import _nomina_del_periodo, get_rentabilidad

COL = timedelta(hours=5)   # Colombia UTC-5: hora local + 5 = UTC

ANIO, MES = 2026, 8
PRIMERO = date(2026, 8, 1)
ULTIMO = date(2026, 8, 31)          # el día de pago
MARTES = date(2026, 8, 11)

SALARIO_ADMIN = 4_000_000.0


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi) + COL


class _Planilla(unittest.TestCase):
    """Siete personas con contrato en dos sedes, y el catálogo de costos."""

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

        self.db.add(ContratoBarista(usuario_id=self.admin.id,
                                    salario_mensual=SALARIO_ADMIN))
        for u in self.baristas:
            self.db.add(ContratoBarista(usuario_id=u.id, salario_mensual=0.0,
                                        salario_en_smmlv=1.0))
        self.db.commit()

        svc.sembrar_categorias(self.db)
        self.cat_nomina = self.db.query(CostoCategoria).filter(
            CostoCategoria.clave == "nomina").first()
        self.cat_arriendo = self.db.query(CostoCategoria).filter(
            CostoCategoria.clave == "arriendo").first()

        # Todos marcan un turno de 8 h el martes. Con esto agosto tiene costo
        # calculado, así que el mes sirve de caso real lo mire uno como mes
        # cerrado (horas) o como mes en curso (contrato) — el test no depende de
        # qué día se corra.
        for u in [self.admin] + self.baristas:
            sede = self.vida if u.tienda_id == self.vida.id else self.palmetto
            self.marcar_8h(sede, u)

        self.hoy = hoy_col()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def marcar_8h(self, tienda, usuario, dia=MARTES):
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

    def agendar(self, anio=ANIO, mes=MES, monto=None):
        return svc.agendar_nomina(self.db, anio, mes, self.admin.id, monto=monto)

    def obligacion(self, obligacion_id):
        return self.db.query(Obligacion).filter(
            Obligacion.id == obligacion_id).first()

    def mes_relativo(self, meses: int) -> tuple:
        """(año, mes) desplazado desde el mes de HOY. Sirve para probar las dos
        ramas de la fuente sin quedar atado a una fecha del calendario que se
        vuelve pasado sola."""
        total = self.hoy.year * 12 + (self.hoy.month - 1) + meses
        return total // 12, total % 12 + 1


# ═══════════════════════════════════════════════════════════════════════════════
# (d) EL DÍA DE PAGO — un dato, no una constante
# ═══════════════════════════════════════════════════════════════════════════════

class DiaDePagoTest(_Planilla):
    """UNA clave en `configuracion`, con «último día del mes» por defecto."""

    def test_por_defecto_es_el_ultimo_dia_del_mes(self):
        self.assertEqual(svc.leer_dia_pago_nomina(self.db), svc.DIA_PAGO_ULTIMO)
        self.assertEqual(svc.fecha_de_pago_nomina(self.db, ANIO, MES), ULTIMO)

    def test_el_ultimo_dia_sigue_al_calendario_de_cada_mes(self):
        """Febrero de 2026 termina el 28, abril el 30 y agosto el 31: es una
        fecha derivada, no un 31 quemado."""
        self.assertEqual(svc.fecha_de_pago_nomina(self.db, 2026, 2), date(2026, 2, 28))
        self.assertEqual(svc.fecha_de_pago_nomina(self.db, 2026, 4), date(2026, 4, 30))
        self.assertEqual(svc.fecha_de_pago_nomina(self.db, 2026, 8), date(2026, 8, 31))

    def test_un_dia_configurado_se_respeta(self):
        self.db.add(Configuracion(clave=svc.CLAVE_NOMINA_DIA_PAGO, valor="5"))
        self.db.commit()
        self.assertEqual(svc.fecha_de_pago_nomina(self.db, ANIO, MES), date(2026, 8, 5))

    def test_un_dia_configurado_se_recorta_al_ultimo_real_del_mes(self):
        """Sin el recorte, un día 31 pediría un 31 de febrero y reventaría."""
        self.db.add(Configuracion(clave=svc.CLAVE_NOMINA_DIA_PAGO, valor="31"))
        self.db.commit()
        self.assertEqual(svc.fecha_de_pago_nomina(self.db, 2026, 2), date(2026, 2, 28))

    def test_basura_guardada_cae_al_ultimo_dia_y_no_revienta(self):
        """La fila es TEXTO. Un valor podrido de otra versión no puede tumbar el
        agendado, y errar hacia el final del mes es la dirección prudente:
        adelantar la fecha correría el punto de quiebre hacia atrás sin que nadie
        lo pidiera."""
        fila = Configuracion(clave=svc.CLAVE_NOMINA_DIA_PAGO, valor="el ultimo, obvio")
        self.db.add(fila)
        self.db.commit()
        self.assertEqual(svc.leer_dia_pago_nomina(self.db), svc.DIA_PAGO_ULTIMO)
        for basura in ("0", "-3", "99", "", "  "):
            fila.valor = basura
            self.db.commit()
            self.assertEqual(svc.fecha_de_pago_nomina(self.db, ANIO, MES), ULTIMO)

    def test_es_una_sola_clave(self):
        """UN pago, no un reparto: no hay una segunda clave de quincena. El día
        que el negocio cambie se agrega entonces — una fecha que nadie usa se
        llena de casos raros y de tests que fijan algo que nunca ocurrió."""
        self.agendar()
        claves = {c.clave for c in self.db.query(Configuracion).all()
                  if "nomina" in c.clave}
        self.assertEqual(claves, {svc.CLAVE_NOMINA_DIA_PAGO} & claves)
        self.assertLessEqual(len(claves), 1)


# ═══════════════════════════════════════════════════════════════════════════════
# (e) AGENDAR LA NÓMINA
# ═══════════════════════════════════════════════════════════════════════════════

class AgendarNominaTest(_Planilla):
    """Una obligación CORPORATIVA, con las dos fechas y el monto del cálculo."""

    def test_nace_corporativa_sin_sede(self):
        """`tienda_id` NULL, igual que el arriendo. Repartirla entre las sedes
        por fracción de devengado se probó y no cierra: la liquidación de una
        persona es UNA y no tiene versión «de esta sede»."""
        res = self.agendar()
        self.assertIsNone(res["tienda_id"])
        self.assertEqual(res["categoria_clave"], "nomina")

    def test_el_devengo_es_el_ultimo_dia_del_mes_devengado(self):
        self.assertEqual(self.agendar()["fecha_devengo"], ULTIMO)

    def test_el_vencimiento_es_el_dia_de_pago(self):
        """Con pago a fin de mes las dos fechas coinciden — y por eso hay que
        escribirlas por separado: coinciden por casualidad, no por definición."""
        self.assertEqual(self.agendar()["fecha_vencimiento"], ULTIMO)

    def test_las_dos_fechas_se_separan_cuando_el_dia_de_pago_cambia(self):
        """La prueba de que devengo y vencimiento NO son la misma cosa: movido
        el día de pago, el costo sigue siendo de agosto y la plata sale el 5."""
        self.db.add(Configuracion(clave=svc.CLAVE_NOMINA_DIA_PAGO, valor="5"))
        self.db.commit()
        res = self.agendar()
        self.assertEqual(res["fecha_devengo"], ULTIMO)
        self.assertEqual(res["fecha_vencimiento"], date(2026, 8, 5))

    def test_el_monto_es_el_costo_empleador_de_las_siete_personas(self):
        """Y no el neto ni la suma de los sueldos: es lo que sale del negocio,
        ~1,55 a 1,69 veces el sueldo. Es además el número que reemplaza al
        calculado en el P&L, que solo tiene el devengado."""
        res = self.agendar()
        self.assertEqual(res["detalle"]["personas"], 7)
        self.assertAlmostEqual(res["monto"], res["detalle"]["total_costo_empleador"],
                               places=2)
        self.assertGreater(res["monto"], res["detalle"]["total_neto"])

    def test_la_respuesta_abre_el_monto_para_que_la_pantalla_lo_explique(self):
        detalle = self.agendar()["detalle"]
        for clave in ("total_devengado", "total_auxilio", "total_deducciones",
                      "total_neto", "total_costo_empleador", "sin_sueldo",
                      "monto_calculado", "monto_editado", "advertencias"):
            self.assertIn(clave, detalle)
        self.assertFalse(detalle["monto_editado"])

    def test_el_monto_es_editable_antes_de_confirmar(self):
        """El dueño puede tener la liquidación del contador, que trae retención
        en la fuente, embargos y el redondeo de PILA — cosas que el cálculo
        declara que NO incluye. Imponerle el estimado sería confiar más en la
        estimación que en el papel."""
        res = self.agendar(monto=21_000_000)
        self.assertEqual(res["monto"], 21_000_000.0)
        self.assertTrue(res["detalle"]["monto_editado"])
        self.assertNotEqual(res["detalle"]["monto_calculado"], 21_000_000.0)

    def test_un_monto_invalido_es_un_400_con_texto(self):
        for malo in (0, -5, "hola"):
            with self.assertRaises(HTTPException) as ctx:
                self.agendar(monto=malo)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIsInstance(ctx.exception.detail, str)

    def test_el_concepto_nombra_el_mes(self):
        self.assertEqual(self.agendar()["concepto"], "Nómina agosto 2026")

    def test_queda_pendiente_y_con_saldo_entero(self):
        res = self.agendar()
        self.assertEqual(res["estado"], "pendiente")
        self.assertAlmostEqual(res["saldo"], res["monto"], places=2)


class FuenteSegunElMesDevengadoTest(_Planilla):
    """«El mes de DEVENGO decide de qué fuente sale el número.»"""

    def test_un_mes_ya_terminado_sale_de_lo_trabajado(self):
        anio, mes = self.mes_relativo(-1)
        res = self.agendar(anio=anio, mes=mes, monto=1_000_000)
        self.assertEqual(res["fuente"], "real")

    def test_el_mes_que_viene_sale_del_contrato(self):
        anio, mes = self.mes_relativo(1)
        res = self.agendar(anio=anio, mes=mes)
        self.assertEqual(res["fuente"], "contrato")
        self.assertGreater(res["monto"], 0)

    def test_el_mes_en_curso_sale_del_contrato_y_no_de_medio_mes_de_horas(self):
        """El mes en curso todavía no tiene todas sus marcaciones: pedirle el
        número a las horas devolvería la parte trabajada hasta hoy con cara de
        total, o sea medio sueldo dicho como si fuera el mes entero."""
        anio, mes = self.mes_relativo(0)
        self.assertEqual(self.agendar(anio=anio, mes=mes)["fuente"], "contrato")

    def test_el_mes_que_viene_no_da_cero_aunque_no_haya_ni_un_turno(self):
        """LA INVARIANTE DE LA PROYECTADA, vista desde el agendado: sin esto el
        botón crearía una obligación de $0 o directamente fallaría."""
        anio, mes = self.mes_relativo(2)
        self.assertGreater(self.agendar(anio=anio, mes=mes)["monto"], 0)


class AgendarNominaIdempotenteTest(_Planilla):
    """Dos taps no pagan la nómina dos veces."""

    def test_agendar_dos_veces_devuelve_la_misma_obligacion(self):
        primera = self.agendar()
        segunda = self.agendar()
        self.assertFalse(primera["ya_existia"])
        self.assertTrue(segunda["ya_existia"])
        self.assertEqual(primera["id"], segunda["id"])

    def test_no_crea_una_segunda_fila(self):
        self.agendar()
        self.agendar()
        self.agendar()
        n = self.db.query(Obligacion).filter(
            Obligacion.categoria_id == self.cat_nomina.id).count()
        self.assertEqual(n, 1)

    def test_la_idempotencia_es_por_MES_de_devengo_no_por_fecha_exacta(self):
        """Si alguien le corrigió el día al devengo, sigue siendo la nómina de
        ese mes y volver a agendar no puede duplicarla."""
        primera = self.agendar()
        fila = self.obligacion(primera["id"])
        fila.fecha_devengo = date(2026, 8, 15)
        self.db.commit()
        self.assertTrue(self.agendar()["ya_existia"])

    def test_una_nomina_de_UNA_SEDE_ya_cargada_tambien_bloquea(self):
        """No se filtra por sede a propósito. En `_nomina_del_periodo` una
        obligación de nómina de una sede apaga el cálculo de esa sede y una
        corporativa lo apaga en todas, pero las DOS entran a `gastos`: ignorar
        la de sede haría que el P&L del mes sumara las dos y contara la misma
        nómina dos veces."""
        self.db.add(Obligacion(tienda_id=self.vida.id, categoria_id=self.cat_nomina.id,
                               concepto="Nómina Vida agosto", monto=6_000_000,
                               fecha_devengo=date(2026, 8, 30),
                               usuario_id=self.admin.id))
        self.db.commit()
        res = self.agendar()
        self.assertTrue(res["ya_existia"])
        self.assertEqual(res["tienda_id"], self.vida.id)
        self.assertEqual(self.db.query(Obligacion).filter(
            Obligacion.categoria_id == self.cat_nomina.id).count(), 1)

    def test_una_nomina_anulada_no_bloquea(self):
        """La baja lógica libera el mes: si el dueño la anuló fue para
        rehacerla."""
        primera = self.agendar()
        svc.anular_obligacion(self.db, primera["id"], self.admin.id, "monto mal")
        segunda = self.agendar()
        self.assertFalse(segunda["ya_existia"])
        self.assertNotEqual(segunda["id"], primera["id"])

    def test_una_obligacion_de_OTRO_mes_no_bloquea(self):
        self.agendar(anio=2026, mes=7, monto=19_000_000)
        self.assertFalse(self.agendar(anio=2026, mes=8)["ya_existia"])

    def test_un_arriendo_del_mismo_mes_no_bloquea(self):
        """Bloquea la categoría 'nomina', no cualquier obligación del mes."""
        self.db.add(Obligacion(tienda_id=None, categoria_id=self.cat_arriendo.id,
                               concepto="Arriendo agosto", monto=2_400_000,
                               fecha_devengo=ULTIMO, usuario_id=self.admin.id))
        self.db.commit()
        self.assertFalse(self.agendar()["ya_existia"])


class AgendarNominaAtomicaTest(_Planilla):
    """Todo o nada: un fallo no puede dejar media obligación cargada."""

    def test_un_calculo_en_cero_no_crea_nada(self):
        """Un cero es «nadie cargó los sueldos», no «la nómina no cuesta».
        Crearla en $0 la dejaría marcada como cargada y APAGARÍA el cálculo de
        ese mes en el P&L: el costo laboral pasaría a valer cero por haber
        apretado un botón."""
        self.db.query(ContratoBarista).delete()
        self.db.commit()
        anio, mes = self.mes_relativo(1)
        with self.assertRaises(HTTPException) as ctx:
            self.agendar(anio=anio, mes=mes)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, str)
        self.assertEqual(self.db.query(Obligacion).count(), 0)

    def test_sin_la_categoria_nomina_no_crea_nada_y_dice_que_falta(self):
        self.db.query(Obligacion).delete()
        self.db.delete(self.cat_nomina)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            self.agendar()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Nómina", ctx.exception.detail)
        self.assertEqual(self.db.query(Obligacion).count(), 0)

    def test_con_la_categoria_desactivada_no_crea_nada(self):
        self.cat_nomina.activa = False
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            self.agendar()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self.db.query(Obligacion).count(), 0)

    def test_un_mes_invalido_es_un_400_y_no_deja_rastro(self):
        with self.assertRaises(HTTPException) as ctx:
            self.agendar(mes=13)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, str)
        self.assertEqual(self.db.query(Obligacion).count(), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# LAS CINCO COSAS QUE ESTO TENÍA QUE ENCENDER SOLO
# ═══════════════════════════════════════════════════════════════════════════════

class UnoElBotonPagarFuncionaTest(_Planilla):
    """(1) `registrar_pago` exige `obligacion_id` o `factura_id`.

    Ése es el motivo por el cual la nómina no se podía pagar desde el sistema:
    no era ninguna de las dos cosas. Con una Obligacion real, el botón funciona
    sin tocar una línea de `registrar_pago`.
    """

    def setUp(self):
        super().setUp()
        self.nomina = self.agendar()

    def test_un_pago_sin_obligacion_ni_factura_se_rechaza(self):
        """La guarda que dejaba la nómina afuera, fijada explícitamente."""
        with self.assertRaises(HTTPException) as ctx:
            svc.registrar_pago(self.db, PagoCreate(
                monto=1000, fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_ahora_la_nomina_se_puede_pagar(self):
        pago = svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=self.nomina["monto"],
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        self.assertEqual(pago["obligacion_id"], self.nomina["id"])
        self.assertEqual(pago["fecha_pago"], ULTIMO)

    def test_el_pago_de_una_corporativa_no_se_atribuye_a_ninguna_sede(self):
        pago = svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=1_000_000,
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        self.assertIsNone(pago["tienda_id"])

    def test_un_pago_parcial_deja_la_obligacion_en_parcial(self):
        svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=self.nomina["monto"] / 2,
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        fila = svc.listar_obligaciones(self.db, categoria="nomina")["obligaciones"][0]
        self.assertEqual(fila["estado"], "parcial")


class DosElSaldoBajaSoloTest(_Planilla):
    """(2) `_pagos_vivos` y `_salidas_banco_por_obligacion` bajan el saldo."""

    def setUp(self):
        super().setUp()
        self.nomina = self.agendar()
        self.cuenta = CuentaBancaria(nombre="Occidente", orden=1)
        self.db.add(self.cuenta)
        self.db.commit()

    def _fila(self):
        return svc.listar_obligaciones(self.db, categoria="nomina")["obligaciones"][0]

    def test_el_pago_registrado_baja_el_saldo(self):
        svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=self.nomina["monto"],
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        fila = self._fila()
        self.assertEqual(fila["saldo"], 0.0)
        self.assertEqual(fila["estado"], "pagada")

    def test_el_debito_tecleado_en_el_banco_baja_el_saldo_sin_pago(self):
        """Sin `Pago` de por medio: el dueño teclea el débito contra el extracto
        y la obligación deja de pedir plata. Sin esto, el saldo del banco bajaba
        y la agenda seguía proyectando la misma salida — la misma plata contada
        dos veces."""
        self.db.add(MovimientoBanco(
            fecha=ULTIMO, cuenta_id=self.cuenta.id, tipo="salida",
            monto=self.nomina["monto"], concepto="Nómina agosto",
            obligacion_id=self.nomina["id"], usuario_id=self.admin.id))
        self.db.commit()
        fila = self._fila()
        self.assertEqual(fila["saldo"], 0.0)
        self.assertEqual(fila["salido_del_banco"], self.nomina["monto"])
        self.assertEqual(fila["pagado"], 0.0)

    def test_el_pago_mas_el_debito_no_se_restan_dos_veces(self):
        """El camino NORMAL escribe los dos para la misma plata. `cubierto_de`
        toma el MÁXIMO, no la suma: sumándolos la obligación desaparecería de la
        agenda debiendo, que es el lado tranquilizador."""
        svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=self.nomina["monto"],
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        self.db.add(MovimientoBanco(
            fecha=ULTIMO, cuenta_id=self.cuenta.id, tipo="salida",
            monto=self.nomina["monto"], concepto="Nómina agosto",
            obligacion_id=self.nomina["id"], usuario_id=self.admin.id))
        self.db.commit()
        self.assertEqual(self._fila()["saldo"], 0.0)

    def test_pagada_sale_de_la_agenda(self):
        """La agenda responde «cuánta plata falta», no «cuánto se debía»."""
        antes = svc.get_agenda(self.db)
        self.assertTrue(any(i["categoria"] == "nomina" for i in antes["items"]))
        svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=self.nomina["monto"],
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        despues = svc.get_agenda(self.db)
        self.assertFalse(any(i["categoria"] == "nomina" for i in despues["items"]))

    def test_anular_el_pago_devuelve_el_saldo(self):
        pago = svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=self.nomina["monto"],
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        svc.anular_pago(self.db, pago["id"], self.admin.id, "no era")
        self.assertAlmostEqual(self._fila()["saldo"], self.nomina["monto"], places=2)


class TresLaNominaEntraAlFlujoTest(_Planilla):
    """(3) `_salidas_por_dia` consume `get_agenda["items"]`.

    La nómina entra al flujo proyectado con SU fecha de vencimiento, que es el
    día en que sale la plata. Es el punto de quiebre el que cambia.
    """

    def setUp(self):
        super().setUp()
        self.nomina = self.agendar()

    def test_aparece_en_la_agenda_con_su_categoria(self):
        items = [i for i in svc.get_agenda(self.db)["items"] if i["categoria"] == "nomina"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["fecha"], ULTIMO)
        self.assertAlmostEqual(items[0]["monto"], self.nomina["monto"], places=2)

    def test_cae_en_el_dia_de_pago_de_la_proyeccion(self):
        """`_salidas_por_dia` recibe el `hoy` como parámetro, así que esto se
        mide sin depender del reloj de la máquina."""
        por_dia = svc._salidas_por_dia(self.db, date(2026, 8, 20), 30, None)
        self.assertIn(ULTIMO, por_dia)
        self.assertAlmostEqual(por_dia[ULTIMO], self.nomina["monto"], places=2)

    def test_el_dia_de_pago_manda_sobre_el_devengo(self):
        """La distinción que la invariante obliga a escribir: movido el día de
        pago al 5, la salida se dibuja el 5 aunque el costo siga siendo del
        último día de agosto."""
        svc.anular_obligacion(self.db, self.nomina["id"], self.admin.id, "rehacer")
        self.db.add(Configuracion(clave=svc.CLAVE_NOMINA_DIA_PAGO, valor="5"))
        self.db.commit()
        nueva = self.agendar()
        por_dia = svc._salidas_por_dia(self.db, date(2026, 8, 1), 30, None)
        self.assertIn(date(2026, 8, 5), por_dia)
        self.assertNotIn(ULTIMO, por_dia)
        self.assertEqual(nueva["fecha_devengo"], ULTIMO)

    def test_una_nomina_ya_pagada_no_se_proyecta_como_salida_futura(self):
        svc.registrar_pago(self.db, PagoCreate(
            obligacion_id=self.nomina["id"], monto=self.nomina["monto"],
            fecha_pago=ULTIMO, metodo="transferencia"), self.admin.id)
        por_dia = svc._salidas_por_dia(self.db, date(2026, 8, 20), 30, None)
        self.assertNotIn(ULTIMO, por_dia)

    def test_en_la_vista_de_UNA_sede_la_corporativa_no_baja_el_flujo(self):
        """LÍMITE CONOCIDO Y DECLARADO, no una regresión: `get_agenda` filtrada
        por sede excluye las corporativas (repartirlas las duplicaría), así que
        el flujo de Vida no ve la nómina. `_corporativas_fuera` existe justo para
        que la respuesta lo diga en `advertencias` en vez de mostrar un verde."""
        solo_vida = svc._salidas_por_dia(self.db, date(2026, 8, 20), 30, self.vida.id)
        self.assertNotIn(ULTIMO, solo_vida)
        fuera = svc._corporativas_fuera(self.db, date(2026, 8, 20), 30)
        self.assertAlmostEqual(fuera, self.nomina["monto"], places=2)


class CuatroNominaEnElPLTest(_Planilla):
    """(4) `_nomina_del_periodo` apaga el cálculo del mes que tiene obligación.

    Y ACÁ ESTÁ EL HALLAZGO: lo apaga en el P&L CONSOLIDADO, pero NO en el P&L de
    una sede. La detección arranca con `if tienda_id is not None: filter(
    Obligacion.tienda_id == tienda_id)`, y una obligación corporativa tiene
    `tienda_id` en NULL: nunca matchea ese filtro. Mirando el P&L de Vida, la
    nómina corporativa no se detecta y el costo calculado de esa sede se sigue
    sumando.

    NO es doble conteo dentro de una misma pantalla —la obligación corporativa
    tampoco entra a `gastos` de esa sede, por el mismo filtro— y está declarado
    en el docstring de `_nomina_del_periodo`. Pero la consecuencia hay que
    decirla: el P&L de Vida más el de Palmetto NO da el P&L consolidado, y las
    vistas por sede muestran un costo laboral (el calculado, que es solo
    devengado) que el consolidado ya reemplazó por la nómina real.
    """

    def _pl(self, tienda_id=None):
        rows = self._oblig_rows(tienda_id)
        return _nomina_del_periodo(self.db, PRIMERO, ULTIMO, tienda_id, rows)

    def _oblig_rows(self, tienda_id=None):
        q = (self.db.query(Obligacion.fecha_devengo, Obligacion.monto,
                           Obligacion.tienda_id, CostoCategoria.nombre,
                           CostoCategoria.grupo, CostoCategoria.clave)
             .join(CostoCategoria, CostoCategoria.id == Obligacion.categoria_id)
             .filter(Obligacion.anulada.is_(False),
                     Obligacion.fecha_devengo >= PRIMERO,
                     Obligacion.fecha_devengo <= ULTIMO))
        if tienda_id is not None:
            q = q.filter(Obligacion.tienda_id == tienda_id)
        return q.all()

    def test_sin_obligacion_el_pl_usa_el_calculo(self):
        """El punto de partida: hay horas marcadas, así que hay costo calculado.
        Sin esto, «el cálculo se apagó» no probaría nada."""
        self.assertGreater(self._pl()["total"], 0)
        self.assertEqual(self._pl()["meses_manuales"], [])

    def test_con_la_obligacion_el_calculo_del_mes_se_apaga_en_el_consolidado(self):
        self.agendar()
        nomina = self._pl()
        self.assertEqual(nomina["total"], 0.0)
        self.assertIn("2026-08", nomina["meses_manuales"])

    def test_apaga_las_DOS_sedes_en_el_consolidado(self):
        """Una corporativa cubre a todo el mundo: no puede apagar Vida y dejar
        el cálculo de Palmetto adentro."""
        antes = self._pl()["pares"]
        self.assertTrue(any(v > 0 for v in antes.values()))
        self.agendar()
        self.assertEqual([v for v in self._pl()["pares"].values() if v], [])

    def test_HALLAZGO_en_la_vista_de_una_sede_NO_lo_apaga(self):
        """La verificación que el encargo pedía hacer explícita. Se fija el
        comportamiento REAL, no el esperado: cambiarlo movería el margen
        histórico de las dos sedes y es una decisión del dueño, no un arreglo
        que se cuela en este commit."""
        self.agendar()
        por_sede = self._pl(self.vida.id)
        self.assertGreater(por_sede["total"], 0)          # el cálculo sigue vivo
        self.assertEqual(por_sede["meses_manuales"], [])  # no la detectó

    def test_HALLAZGO_las_dos_sedes_no_suman_el_consolidado(self):
        """La consecuencia medible del hallazgo de arriba."""
        self.agendar()
        suma = (self._pl(self.vida.id)["total"] + self._pl(self.palmetto.id)["total"])
        self.assertGreater(suma, self._pl()["total"])

    def test_una_nomina_de_UNA_sede_apaga_solo_esa_sede(self):
        """El comportamiento que SÍ funciona por sede, y que es el motivo por el
        cual la detección tiene el filtro que produce el hallazgo."""
        self.db.add(Obligacion(tienda_id=self.vida.id, categoria_id=self.cat_nomina.id,
                               concepto="Nómina Vida", monto=6_000_000,
                               fecha_devengo=ULTIMO, usuario_id=self.admin.id))
        self.db.commit()
        pares = self._pl()["pares"]
        self.assertEqual(pares.get(("2026-08", self.vida.id), 0.0), 0.0)
        self.assertGreater(pares.get(("2026-08", self.palmetto.id), 0.0), 0.0)

    def test_la_misma_plata_no_se_cuenta_dos_veces_en_los_gastos(self):
        """La prueba end to end de la convivencia: agendar sube los gastos en el
        monto de la nómina MENOS el cálculo que reemplaza, no en el monto entero
        encima del cálculo."""
        antes = get_rentabilidad(self.db, PRIMERO, ULTIMO)
        self.assertGreater(antes["resumen"]["nomina_calculada"], 0)
        res = self.agendar()
        despues = get_rentabilidad(self.db, PRIMERO, ULTIMO)
        self.assertAlmostEqual(
            despues["resumen"]["gastos"],
            antes["resumen"]["gastos"] - antes["resumen"]["nomina_calculada"] + res["monto"],
            places=2)


class CincoCostosFijosDevengadosTest(_Planilla):
    """(5) `costos_fijos_devengados` suma los fijos + el total de nómina.

    Con la obligación cargada, `nomina["total"]` pasa a valer 0 para ese mes y la
    nómina entra por el otro término, el de las obligaciones fijas: la categoría
    'nomina' es del grupo FIJO. El piso del mes —«cuánto hay que vender para no
    perder»— deja de estar $20.000.000 abajo.
    """

    def setUp(self):
        super().setUp()
        # Lo que el cálculo aportaba al piso ANTES de agendar. Se mide y se
        # exige > 0: si diera 0, el test de abajo pasaría por casualidad.
        self.calculada = get_rentabilidad(self.db, PRIMERO, ULTIMO)["resumen"]["nomina_calculada"]
        self.assertGreater(self.calculada, 0)

    def _fijos(self):
        return get_rentabilidad(self.db, PRIMERO, ULTIMO)["resumen"]["costos_fijos_devengados"]

    def test_la_nomina_agendada_entra_al_piso_del_mes(self):
        antes = self._fijos()
        res = self.agendar()
        self.assertAlmostEqual(self._fijos(), antes - self.calculada + res["monto"],
                               places=2)
        self.assertGreater(self._fijos(), antes)

    def test_la_categoria_nomina_es_fija(self):
        """Si alguien la moviera a variable, esta plata se caería del piso del
        mes en silencio — que es exactamente lo que le pasaba a 'mantenimiento'
        y 'otros'."""
        self.assertEqual(self.cat_nomina.grupo, "fijo")

    def test_el_semaforo_deja_de_decir_que_no_hay_costos_fijos(self):
        self.agendar()
        resumen = get_rentabilidad(self.db, PRIMERO, ULTIMO)["resumen"]
        self.assertGreater(resumen["n_costos_fijos"], 0)
        self.assertGreater(resumen["costos_fijos_devengados"], 0)

    def test_la_nomina_aparece_en_el_desglose_por_categoria(self):
        """El desglose es una PARTICIÓN: Σ por_categoria tiene que dar
        `resumen.gastos`, así que la nómina no puede entrar solo al total."""
        self.agendar()
        pl = get_rentabilidad(self.db, PRIMERO, ULTIMO)
        por_cat = {c["clave"]: c for c in pl["gastos_por_categoria"]}
        self.assertIn("nomina", por_cat)
        self.assertEqual(por_cat["nomina"]["grupo"], "fijo")
        self.assertAlmostEqual(
            round(sum(c["total"] for c in pl["gastos_por_categoria"]), 2),
            pl["resumen"]["gastos"], places=2)


if __name__ == "__main__":
    unittest.main()
