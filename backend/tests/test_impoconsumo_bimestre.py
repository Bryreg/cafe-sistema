"""EL IMPOCONSUMO: el gasto grande que se veía como menos venta y nunca como plata.

De cada peso facturado, 7,41 centavos son de la DIAN. El sistema ya lo trataba
bien en todos lados —la venta neta lo descuenta, el margen de contribución lo
resta, el piso ya lo tiene adentro— pero en NINGUNA pantalla aparecía como plata
que hay que pagar en una fecha. Con $155,6M facturados en un bimestre son
millones que aparecen de golpe.

Lo que fija este archivo:

1. SE APUNTA AL BIMESTRE CERRADO, NUNCA AL QUE CORRE. El que corre no se declara,
   y ponerlo diría que hay que pagar hoy una plata que todavía se está cobrando.
2. EL MONTO ES MEDIDO, NO NOMINAL. Sale de `Tributos.separar` sobre la venta real
   —7,41% de lo cobrado con la tarifa al 8%— igual que el piso. Un monto
   inventado en una pantalla de plata es peor que un recordatorio sin monto, así
   que hay tres casos en los que vuelve en None CON EL PORQUÉ.
3. EL RECORDATORIO SE PUEDE APAGAR. Una advertencia que no se puede corregir se
   aprende a ignorar. Y NO se puede apagar un bimestre que no cerró: el marcador
   es monótono y apagaría de paso todos los de atrás.
4. SE AGENDA, PERO EN UNA CATEGORÍA QUE EL P&L NO MIRA. Cargarla como costo de
   'impuestos' contaría la misma plata dos veces —el grupo 'fijo' entra al
   numerador del piso y el margen de contribución YA le restó el impoconsumo— y
   ponerla en un grupo 'variable' tampoco alcanza: `tot_gastos` suma TODAS las
   obligaciones sin mirar el grupo. Los tres mundos están medidos en pesos acá
   abajo, porque el que importa es el tercero: categoría dedicada, EXCLUIDA POR
   CLAVE. Los tests fijan las DOS MITADES — que el piso y el P&L NO se mueven, y
   que la agenda y el flujo SÍ la ven.
5. MIENTRAS NO ESTÉ AGENDADA, EL FLUJO LO DECLARA. `sin_salidas_cargadas` solo
   avisaba cuando no había NADA cargado: con un arriendo adentro se apagaba y el
   verde viajaba igual faltando $11,5M. La cobertura es POR CONCEPTO.
"""
import calendar
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base, get_db
from app.models.models import (CajaTurno, Configuracion, CostoCategoria,
                               EstadoTurnoEnum, Obligacion, ParametroTributario,
                               RolEnum, Ticket, Tienda, Usuario)
from app.routers import costos as costos_router
from app.services import costos as svc
from app.services import rentabilidad as rent_svc

# La tarifa sembrada: 8% con el precio de la carta CON el impuesto adentro, o sea
# 7,41% de cada peso cobrado. Igual que en test_piso_venta.
TASA_IMPO = 0.08
I_MEDIDO = 1 - 1 / (1 + TASA_IMPO)


def mediodia(d: date) -> datetime:
    return inicio_dia_col_utc(d) + timedelta(hours=12)


class ImpoBase(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                         bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.hoy = hoy_col()
        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.tienda.id,
                               usuario_apertura_id=self.admin.id,
                               base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                               fecha_cierre=mediodia(self.hoy),
                               efectivo_final_real=0.0)
        self.db.add(self.turno)
        self.cat_fijo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                       grupo="fijo", orden=0)
        self.cat_imp = CostoCategoria(clave="impuestos", nombre="Impuestos",
                                      grupo="fijo", orden=1)
        self.db.add_all([self.cat_fijo, self.cat_imp])
        self.db.commit()
        # El catálogo REAL, por el mismo camino que en producción: la categoría
        # dedicada del impoconsumo la necesita `agendar_impoconsumo` existiendo, y
        # crearla a mano acá dejaría al test verde con una siembra rota. Las dos
        # de arriba ya están, así que `sembrar_categorias` las saltea.
        svc.sembrar_categorias(self.db)
        self.cat_impo = self.db.query(CostoCategoria).filter(
            CostoCategoria.clave == svc.CLAVE_CATEGORIA_IMPOCONSUMO).one()

        app = FastAPI()
        app.include_router(costos_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Ayudantes ────────────────────────────────────────────────────────────

    @property
    def cerrado(self) -> tuple[int, int]:
        """El bimestre que HOY toca declarar: el anterior al que corre."""
        return svc._bimestre_anterior(*svc._bimestre_de(self.hoy))

    def venta(self, dia: date, total: float):
        t = Ticket(tienda_id=self.tienda.id, caja_turno_id=self.turno.id,
                   usuario_id=self.admin.id, fecha=mediodia(dia), total=total,
                   estado="completado", metodo_pago="efectivo",
                   monto_efectivo=total, monto_tarjeta=0.0)
        self.db.add(t)
        self.db.commit()
        return t

    def vender_en_el_bimestre_cerrado(self, total: float):
        """Una venta bien adentro del bimestre que toca declarar."""
        desde, hasta = svc._rango_bimestre(*self.cerrado)
        self.venta(desde + timedelta(days=3), total)
        return desde, hasta

    def leer(self) -> dict:
        r = self.client.get("/api/v1/costos/impoconsumo")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. EL BIMESTRE: SIEMPRE EL CERRADO
# ═══════════════════════════════════════════════════════════════════════════════

class ElBimestreTest(ImpoBase):

    def test_los_seis_periodos_son_los_de_la_dian(self):
        """ene-feb, mar-abr, may-jun, jul-ago, sep-oct, nov-dic."""
        self.assertEqual(svc._bimestre_de(date(2026, 1, 1)), (2026, 1))
        self.assertEqual(svc._bimestre_de(date(2026, 2, 28)), (2026, 1))
        self.assertEqual(svc._bimestre_de(date(2026, 3, 1)), (2026, 2))
        self.assertEqual(svc._bimestre_de(date(2026, 8, 20)), (2026, 4))
        self.assertEqual(svc._bimestre_de(date(2026, 12, 31)), (2026, 6))
        self.assertEqual(svc._rango_bimestre(2026, 4),
                         (date(2026, 7, 1), date(2026, 8, 31)))
        self.assertEqual(svc._rango_bimestre(2028, 1),
                         (date(2028, 1, 1), date(2028, 2, 29)))  # bisiesto

    def test_en_enero_el_bimestre_a_declarar_es_de_diciembre_del_ano_pasado(self):
        self.assertEqual(svc._bimestre_anterior(2026, 1), (2025, 6))

    def test_apunta_al_cerrado_y_no_al_que_corre(self):
        """Poner el que corre diría que hay que pagar hoy una plata que todavía
        se está cobrando."""
        d = self.leer()
        anio, bim = self.cerrado
        self.assertEqual(d["bimestre"]["anio"], anio)
        self.assertEqual(d["bimestre"]["numero"], bim)
        self.assertLess(date.fromisoformat(d["bimestre"]["hasta"]), self.hoy)

    def test_el_plazo_del_bimestre_de_diciembre_cae_en_enero_del_ano_siguiente(self):
        """El único caso donde el mes del plazo cambia de año. Se prueba sobre la
        función pura porque `hoy` no se puede mover."""
        _desde, hasta = svc._rango_bimestre(2026, 6)
        self.assertEqual(hasta, date(2026, 12, 31))
        siguiente = hasta + timedelta(days=1)
        self.assertEqual((siguiente.year, siguiente.month), (2027, 1))

    def test_leer_no_escribe_nada(self):
        """El GET es de lectura: no puede dejar rastro en `configuracion`."""
        antes = self.db.query(Configuracion).count()
        self.leer()
        self.assertEqual(self.db.query(Configuracion).count(), antes)

    def test_el_nombre_esta_en_el_idioma_del_dueno(self):
        self.assertEqual(svc._nombre_bimestre(2026, 4), "julio-agosto 2026")
        self.assertEqual(svc._nombre_bimestre(2025, 6), "noviembre-diciembre 2025")

    def test_se_nombra_el_MES_del_plazo_y_no_se_inventa_un_dia(self):
        """La fecha exacta la fija la DIAN según el último dígito del NIT y el
        sistema no lo conoce."""
        d = self.leer()
        cierre = date.fromisoformat(d["bimestre"]["hasta"])
        siguiente = cierre + timedelta(days=1)
        self.assertEqual(d["declara_en"]["mes"], siguiente.month)
        self.assertEqual(d["declara_en"]["anio"], siguiente.year)
        # `hasta` del plazo es el ÚLTIMO día de ese mes, que es lo único que se
        # puede afirmar sin el NIT.
        ultimo = calendar.monthrange(siguiente.year, siguiente.month)[1]
        self.assertEqual(d["declara_en"]["hasta"],
                         date(siguiente.year, siguiente.month, ultimo).isoformat())


# ═══════════════════════════════════════════════════════════════════════════════
# 2. EL MONTO: MEDIDO, O NINGUNO
# ═══════════════════════════════════════════════════════════════════════════════

class ElMontoTest(ImpoBase):

    def test_es_el_7_41_por_ciento_de_lo_cobrado_y_no_el_8(self):
        """Con el precio CON impuesto adentro la venta neta es total/(1+tasa).
        Descontar el 8% del precio final deja el impuesto mal liquidado."""
        self.vender_en_el_bimestre_cerrado(155_600_000)
        d = self.leer()
        self.assertIsNone(d["sin_monto_porque"])
        self.assertAlmostEqual(d["monto_medido"], 155_600_000 * I_MEDIDO, delta=1)
        # Y NO es el 8% pelado, que sería $12.448.000.
        self.assertNotAlmostEqual(d["monto_medido"], 155_600_000 * 0.08, delta=1000)
        self.assertEqual(d["ventas"], 155_600_000)

    def test_solo_cuenta_la_venta_DE_ESE_bimestre(self):
        """Una venta de ayer (del bimestre que corre) no puede entrar en la
        declaración del cerrado: sería la doble contabilidad más cara."""
        desde, hasta = self.vender_en_el_bimestre_cerrado(100_000_000)
        self.venta(self.hoy, 50_000_000)          # bimestre en curso
        self.venta(desde - timedelta(days=5), 30_000_000)   # bimestre anterior
        d = self.leer()
        self.assertEqual(d["ventas"], 100_000_000)

    def test_sin_ventas_no_dice_cero_pesos(self):
        """Un $0 acá se lee como «no tenés que declarar nada». Se dice el porqué."""
        d = self.leer()
        self.assertIsNone(d["monto_medido"])
        self.assertIsNone(d["ventas"])
        self.assertIn("no hay ventas registradas", d["sin_monto_porque"])
        # Pero SIGUE habiendo que declarar: la obligación formal existe igual.
        self.assertTrue(d["hay_que_declarar"])

    def test_sin_tarifa_cargada_no_se_inventa_una(self):
        self.vender_en_el_bimestre_cerrado(50_000_000)
        self.db.query(ParametroTributario).delete()
        self.db.commit()
        # `ptsvc.para` siembra si no hay nada; se fuerza el caso poniendo la
        # tarifa en cero, que es lo que devuelve cuando de verdad no hay fila.
        self.db.query(ParametroTributario).delete()
        self.db.add(ParametroTributario(vigente_desde=date(2020, 1, 1),
                                        impoconsumo=0.0,
                                        precio_incluye_impoconsumo=True,
                                        gmf=0.0))
        self.db.commit()
        d = self.leer()
        self.assertIsNone(d["monto_medido"])
        self.assertIn("tarifa", d["sin_monto_porque"])

    def test_si_el_precio_no_lleva_el_impuesto_adentro_no_hay_de_donde_medirlo(self):
        self.vender_en_el_bimestre_cerrado(50_000_000)
        self.db.query(ParametroTributario).delete()
        self.db.add(ParametroTributario(vigente_desde=date(2020, 1, 1),
                                        impoconsumo=0.08,
                                        precio_incluye_impoconsumo=False,
                                        gmf=0.004))
        self.db.commit()
        d = self.leer()
        self.assertIsNone(d["monto_medido"])
        self.assertIn("no llevan el impoconsumo adentro", d["sin_monto_porque"])

    def test_el_campo_se_llama_medido_y_no_a_pagar(self):
        """La declaración la arma el contador: exclusiones, correcciones y
        ajustes que el sistema no ve. El nombre del campo tiene que decirlo."""
        d = self.leer()
        self.assertIn("monto_medido", d)
        self.assertNotIn("monto_a_pagar", d)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EL INTERRUPTOR
# ═══════════════════════════════════════════════════════════════════════════════

class ElInterruptorTest(ImpoBase):

    def test_marcarla_apaga_el_recordatorio(self):
        self.vender_en_el_bimestre_cerrado(80_000_000)
        anio, bim = self.cerrado
        self.assertTrue(self.leer()["hay_que_declarar"])

        r = self.client.post("/api/v1/costos/impoconsumo/declarado",
                             json={"anio": anio, "bimestre": bim})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["ya_estaba"])

        d = self.leer()
        self.assertFalse(d["hay_que_declarar"])
        self.assertTrue(d["declarado"])

    def test_marcarla_dos_veces_no_rompe_nada(self):
        anio, bim = self.cerrado
        self.client.post("/api/v1/costos/impoconsumo/declarado",
                         json={"anio": anio, "bimestre": bim})
        r = self.client.post("/api/v1/costos/impoconsumo/declarado",
                             json={"anio": anio, "bimestre": bim})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ya_estaba"])

    def test_no_se_puede_apagar_un_bimestre_que_no_cerro(self):
        """Sería apagar por adelantado un aviso sobre plata que ni siquiera
        terminó de cobrarse — y como el marcador es monótono, apagaría de paso
        todos los de atrás."""
        anio, bim = svc._bimestre_de(self.hoy)
        r = self.client.post("/api/v1/costos/impoconsumo/declarado",
                             json={"anio": anio, "bimestre": bim})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)
        self.assertIn("todavía no cerró", r.json()["detail"])

    def test_marcar_uno_da_por_declarados_los_anteriores(self):
        anio, bim = self.cerrado
        self.client.post("/api/v1/costos/impoconsumo/declarado",
                         json={"anio": anio, "bimestre": bim})
        ant = svc._bimestre_anterior(anio, bim)
        self.assertTrue(svc.leer_impoconsumo_declarado(self.db) >= ant)

    def test_el_marcador_no_retrocede(self):
        anio, bim = self.cerrado
        self.client.post("/api/v1/costos/impoconsumo/declarado",
                         json={"anio": anio, "bimestre": bim})
        ant_anio, ant_bim = svc._bimestre_anterior(anio, bim)
        r = self.client.post("/api/v1/costos/impoconsumo/declarado",
                             json={"anio": ant_anio, "bimestre": ant_bim})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ya_estaba"])
        self.assertEqual(svc.leer_impoconsumo_declarado(self.db), (anio, bim))

    def test_un_marcador_corrupto_se_lee_como_no_declarado(self):
        """Ante la duda el recordatorio APARECE. Apagarlo por un string que no se
        entiende sería el error tranquilizador de siempre."""
        for basura in ("", "  ", "sí", "2026", "2026-9", "1999-2", "2026-abril"):
            self.db.query(Configuracion).filter(
                Configuracion.clave == svc.CLAVE_IMPOCONSUMO_DECLARADO).delete()
            self.db.add(Configuracion(clave=svc.CLAVE_IMPOCONSUMO_DECLARADO,
                                      valor=basura))
            self.db.commit()
            self.assertIsNone(svc.leer_impoconsumo_declarado(self.db), basura)
            self.assertTrue(self.leer()["hay_que_declarar"], basura)

    def test_los_rangos_vuelven_como_400_mostrable(self):
        for cuerpo in ({"anio": 1999, "bimestre": 2}, {"anio": 2026, "bimestre": 7},
                       {"anio": 2026, "bimestre": 0}):
            r = self.client.post("/api/v1/costos/impoconsumo/declarado", json=cuerpo)
            self.assertEqual(r.status_code, 400, cuerpo)
            self.assertIsInstance(r.json()["detail"], str)

    def test_declarado_no_paga_el_p_and_l(self):
        """Con nada que mostrar, la respuesta sale sin tocar `get_rentabilidad`:
        esta página se abre todos los días antes de abrir el local."""
        anio, bim = self.cerrado
        self.client.post("/api/v1/costos/impoconsumo/declarado",
                         json={"anio": anio, "bimestre": bim})
        llamadas = []
        original = svc.rent_svc.get_rentabilidad
        svc.rent_svc.get_rentabilidad = lambda *a, **k: llamadas.append(a) or original(*a, **k)
        try:
            self.leer()
        finally:
            svc.rent_svc.get_rentabilidad = original
        self.assertEqual(llamadas, [])


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LAS DOS MITADES: EL PISO Y EL P&L NO SE MUEVEN; LA AGENDA Y EL FLUJO SÍ
# ═══════════════════════════════════════════════════════════════════════════════
#
# Los tres mundos, medidos sobre esta misma base ($155,6M facturados en el
# bimestre → $11.525.925,93 de impoconsumo):
#
#   (B) obligación en categoría de grupo FIJO: piso +$12.447.999, P&L −$11.525.926
#   (C) obligación en grupo VARIABLE sin excluir: piso quieto, P&L −$11.525.926
#   (D) categoría DEDICADA excluida por clave:   piso quieto, P&L quieto, agenda +
#
# (B) y (C) están acá como MEDICIÓN DEL DAÑO EVITADO, no como comportamiento que
# se defienda: son el número que tiene que tener delante el que un día quiera
# simplificar la exclusión.

class LasDosMitadesTest(ImpoBase):

    def preparar(self):
        """Venta del bimestre cerrado + venta y arriendo del mes en curso."""
        self.vender_en_el_bimestre_cerrado(155_600_000)
        self.venta(self.hoy.replace(day=1), 30_000_000)
        self.obligacion_fija(10_000_000, self.hoy.replace(day=1),
                             vence=date(self.hoy.year, self.hoy.month, 28))
        return round(155_600_000 * I_MEDIDO, 2)

    def piso_y_pl(self):
        h = self.hoy
        piso = svc.get_piso(self.db, h.year, h.month)
        pl = rent_svc.get_rentabilidad(self.db, h.replace(day=1), h)["resumen"]
        return piso, pl

    # ── LA MITAD QUE NO SE PUEDE MOVER ───────────────────────────────────────

    def test_agendarla_deja_el_piso_y_el_margen_neto_EXACTAMENTE_igual(self):
        """LA MITAD QUE DECIDE SI ESTO SE PUEDE HACER.

        Delta $0 en los dos, no «parecido»: cualquier movimiento acá es el doble
        conteo volviendo, y el margen ya se mide sobre la venta NETA.
        """
        impo = self.preparar()
        piso_antes, pl_antes = self.piso_y_pl()

        anio, bim = self.cerrado
        r = svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        self.assertAlmostEqual(float(r["monto"]), impo, delta=1.0)

        piso_desp, pl_desp = self.piso_y_pl()
        self.assertEqual(piso_desp["piso_mes"], piso_antes["piso_mes"])
        self.assertEqual(pl_desp["margen_neto"], pl_antes["margen_neto"])
        self.assertEqual(pl_desp["gastos"], pl_antes["gastos"])
        self.assertAlmostEqual(piso_desp["margen_contribucion"],
                               piso_antes["margen_contribucion"], places=9)

    def test_tampoco_entra_al_desglose_de_gastos_por_categoria(self):
        """`Σ por_categoria` tiene que seguir dando `resumen.gastos`. Si la fila
        apareciera acá, el desglose sumaría más que el total y el dueño vería una
        categoría de gasto que ningún margen descontó."""
        self.preparar()
        anio, bim = self.cerrado
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)

        h = self.hoy
        det = rent_svc.get_rentabilidad(self.db, h.replace(day=1), h)
        claves = {g["clave"] for g in det["gastos_por_categoria"]}
        self.assertNotIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO, claves)
        self.assertAlmostEqual(sum(g["total"] for g in det["gastos_por_categoria"]),
                               det["resumen"]["gastos"], places=2)

    def test_no_cuenta_como_costo_fijo_devengado(self):
        """El numerador del piso no la puede ver, ni siquiera para contarla."""
        self.preparar()
        anio, bim = self.cerrado
        antes = rent_svc.costos_fijos_del_mes(self.db, self.hoy.year, self.hoy.month)
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        desp = rent_svc.costos_fijos_del_mes(self.db, self.hoy.year, self.hoy.month)
        self.assertEqual(desp["costos_fijos_devengados"],
                         antes["costos_fijos_devengados"])
        self.assertEqual(desp["n_costos_fijos"], antes["n_costos_fijos"])
        self.assertNotIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO,
                         {g["clave"] for g in desp["por_categoria"]})

    # ── LA MITAD QUE TIENE QUE MOVERSE ───────────────────────────────────────

    def test_la_agenda_SI_la_ve_con_su_monto(self):
        impo = self.preparar()
        antes = svc.get_agenda(self.db)["totales"]["monto"]
        anio, bim = self.cerrado
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        desp = svc.get_agenda(self.db)
        self.assertAlmostEqual(desp["totales"]["monto"] - antes, impo, delta=1.0)
        fila = [i for i in desp["items"]
                if i["categoria"] == svc.CLAVE_CATEGORIA_IMPOCONSUMO]
        self.assertEqual(len(fila), 1)
        self.assertAlmostEqual(fila[0]["monto"], impo, delta=1.0)

    def test_el_flujo_proyectado_SI_le_baja_la_caja(self):
        """El agujero en pesos: sin la obligación el saldo mínimo del mes no la
        resta, y la pantalla que decide si el dueño gasta dice verde."""
        impo = self.preparar()
        self.con_plata_en_caja(6_500_000)
        antes = svc.get_flujo_proyectado(self.db)

        anio, bim = self.cerrado
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        desp = svc.get_flujo_proyectado(self.db)

        self.assertAlmostEqual(antes["saldo_minimo"] - desp["saldo_minimo"],
                               impo, delta=1.0)
        # Y aparece el día en que se queda sin plata, que antes no existía.
        self.assertIsNone(antes["punto_de_quiebre"])
        self.assertIsNotNone(desp["punto_de_quiebre"])

    def test_el_devengo_ata_la_declaracion_a_SU_bimestre(self):
        """El devengo es del bimestre y el vencimiento del mes siguiente. Si se
        agendara por el vencimiento, dos bimestres consecutivos se pisarían."""
        self.preparar()
        anio, bim = self.cerrado
        r = svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        desde, hasta = svc._rango_bimestre(anio, bim)
        self.assertEqual(r["fecha_devengo"], hasta)
        _primero, vence = svc._mes_de_declaracion(hasta)
        self.assertEqual(r["fecha_vencimiento"], vence)
        self.assertGreater(vence, hasta)

    # ── LAS PUERTAS ──────────────────────────────────────────────────────────

    def test_dos_taps_no_pagan_la_dian_dos_veces(self):
        self.preparar()
        anio, bim = self.cerrado
        primera = svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        self.assertFalse(primera["ya_existia"])
        segunda = svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        self.assertTrue(segunda["ya_existia"])
        self.assertEqual(segunda["id"], primera["id"])
        self.assertEqual(
            self.db.query(Obligacion).join(CostoCategoria).filter(
                CostoCategoria.clave == svc.CLAVE_CATEGORIA_IMPOCONSUMO).count(), 1)

    def test_no_se_agenda_un_bimestre_que_todavia_no_cerro(self):
        """Lo que lleva facturado no es lo que se va a declarar: congelaría una
        cifra siempre MENOR que la real, o sea del lado tranquilizador."""
        anio, bim = svc._bimestre_de(self.hoy)
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)
        self.assertIn("todavía no cerró", r.json()["detail"])

    def test_sin_monto_medido_no_se_crea_una_obligacion_en_cero(self):
        """Una fila en $0 en la agenda se lee como «esto ya está resuelto»: sería
        peor que no tenerla, porque apagaría el aviso sin reservar un peso."""
        anio, bim = self.cerrado          # sin ninguna venta cargada
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no hay ventas registradas", r.json()["detail"])
        self.assertEqual(self.db.query(Obligacion).count(), 0)

    def test_sin_monto_medido_pero_con_la_cifra_del_contador_SI_se_agenda(self):
        """El sistema no puede medirlo, pero el papel del contador existe."""
        anio, bim = self.cerrado
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim, "monto": 9_000_000})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(float(r.json()["monto"]), 9_000_000)
        self.assertTrue(r.json()["detalle"]["monto_editado"])

    # ── EL MONTO A MANO NO PUEDE APAGAR EL AVISO CON CUALQUIER CIFRA ─────────
    #
    # Crear esta fila apaga `_cobertura_impoconsumo` por el SOLO hecho de existir
    # (no mira saldo ni monto), así que un $1 escrito acá apagaba el aviso de que
    # faltaban $11,5M por reservar y dejaba la proyección de caja igual de
    # equivocada, ahora con un renglón menos que la contradiga.

    def test_un_peso_escrito_a_mano_NO_apaga_el_aviso_de_once_millones(self):
        """EL AGUJERO, EN UN SOLO TEST. Antes esto creaba la obligación y
        `salidas_incompletas` se apagaba con $11.525.925,93 sin reservar."""
        impo = self.preparar()
        anio, bim = self.cerrado
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim, "monto": 1})

        self.assertEqual(r.status_code, 400, r.text)
        # LAS DOS CIFRAS Y LA BASE, en el mensaje: el dueño tiene que poder ver
        # contra qué se lo comparó sin abrir otra pantalla.
        detalle = r.json()["detail"]
        # «$1» a secas también sería prefijo de «$155,600,000»: se pide la frase.
        self.assertIn("Escribiste $1 ", detalle)
        self.assertIn(f"${impo:,.0f}", detalle)
        self.assertIn("155,600,000", detalle)
        # Y NO ESCRIBIÓ NADA: el aviso sigue prendido con la plata entera.
        self.assertEqual(
            self.db.query(Obligacion).join(CostoCategoria).filter(
                CostoCategoria.clave == svc.CLAVE_CATEGORIA_IMPOCONSUMO).count(), 0)
        falta = {c["clave"]: c for c in svc.get_flujo_proyectado(self.db)[
            "advertencias"]["conceptos_sin_cargar"]}
        self.assertAlmostEqual(falta[svc.CLAVE_CATEGORIA_IMPOCONSUMO]["monto"],
                               impo, delta=1.0)

    def test_el_digito_perdido_tambien_rebota(self):
        """Un dígito que falta es un factor de diez exacto, y es la forma más
        probable de escribir mal esta cifra en una tablet."""
        impo = self.preparar()
        anio, bim = self.cerrado
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim,
                                   "monto": round(impo / 10, 2)})
        self.assertEqual(r.status_code, 400, r.text)

    def test_la_cifra_del_contador_mas_baja_pero_parecida_SI_entra(self):
        """El papel manda: el contador tiene exclusiones y correcciones que el
        sistema no ve. El corte va en un quinto justamente para no pelearse con
        una declaración legítima."""
        impo = self.preparar()
        anio, bim = self.cerrado
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim,
                                   "monto": round(impo / 2, 2)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(float(r.json()["monto"]), impo / 2, delta=1.0)

    def test_escribir_de_MAS_no_rebota_nunca(self):
        """La asimetría es a propósito: de más reserva de más, que es incómodo y
        seguro. Solo se frena lo que apaga un aviso sin reservar la plata."""
        impo = self.preparar()
        anio, bim = self.cerrado
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim,
                                   "monto": round(impo * 10, 2)})
        self.assertEqual(r.status_code, 200, r.text)

    def test_sin_nada_que_medir_no_se_rebota_contra_un_cero_inventado(self):
        """Sin ventas, `medido` no mide nada: comparar contra él sería rebotar
        contra un cero que solo significa «no se pudo preguntar». Es el mismo
        caso del test de acá arriba, mirado desde la guarda nueva."""
        anio, bim = self.cerrado          # sin ninguna venta cargada
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim, "monto": 1})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(float(r.json()["monto"]), 1)

    def test_a_mano_no_se_puede_cargar_en_esa_categoria(self):
        """El monto lo mide el sistema y la fecha la fija la DIAN. Tecleada a
        mano entraría con lo que a alguien le parezca — y como esta categoría no
        entra al P&L, ningún margen la corrige después."""
        r = self.client.post("/api/v1/costos/obligaciones", json={
            "categoria_id": self.cat_impo.id, "concepto": "Impo",
            "monto": 1_000_000, "fecha_devengo": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no se carga a mano", r.json()["detail"])

    def test_no_aparece_en_el_desplegable_de_categorias(self):
        claves = {c["clave"] for c in svc.listar_categorias(self.db)}
        self.assertNotIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO, claves)
        self.assertIn("arriendo", claves)

    def test_el_recordatorio_sigue_siendo_lectura_pura(self):
        """Agendarla es un BOTÓN, no un efecto de mirar la pantalla."""
        self.vender_en_el_bimestre_cerrado(155_600_000)
        antes = self.db.query(Obligacion).count()
        self.leer()
        self.assertEqual(self.db.query(Obligacion).count(), antes)

    def test_el_recordatorio_dice_si_ya_esta_agendada(self):
        impo = self.preparar()
        self.assertIsNone(self.leer()["agendada"])
        anio, bim = self.cerrado
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        ag = self.leer()["agendada"]
        self.assertIsNotNone(ag)
        self.assertAlmostEqual(ag["monto"], impo, delta=1.0)

    # ── EL DAÑO EVITADO, MEDIDO ──────────────────────────────────────────────

    def test_B_en_grupo_fijo_inflaria_el_piso_por_plata_ya_contada(self):
        """(B) El margen de contribución ya le restó el impoconsumo. Cargarla
        además como obligación de 'impuestos' —grupo FIJO— la mete al numerador
        del piso: el mismo impuesto por arriba y por abajo."""
        impo = self.preparar()
        piso_limpio, _ = self.piso_y_pl()
        self.obligacion_fija(impo, self.hoy.replace(day=1), categoria=self.cat_imp)
        piso_sucio, pl_sucio = self.piso_y_pl()

        inflado = piso_sucio["piso_mes"] - piso_limpio["piso_mes"]
        self.assertAlmostEqual(inflado, impo / piso_limpio["margen_contribucion"],
                               delta=1.0)
        self.assertGreater(inflado, impo)   # el daño es MAYOR que el impuesto

    def test_C_en_grupo_variable_deja_el_piso_quieto_y_hunde_el_P_and_L(self):
        """(C) EL PEOR DE LOS TRES, y el que justifica que la exclusión sea por
        CLAVE y no por grupo: el piso no se mueve —parece arreglado— pero
        `tot_gastos` suma todas las obligaciones sin mirar el grupo y el margen
        neto cae por la plata entera. El error es MUDO."""
        impo = self.preparar()
        piso_limpio, pl_limpio = self.piso_y_pl()

        cat_var = CostoCategoria(clave="impo_variable", nombre="Impo var",
                                 grupo="variable", orden=9)
        self.db.add(cat_var)
        self.db.commit()
        self.obligacion_fija(impo, self.hoy.replace(day=1), categoria=cat_var)
        piso_sucio, pl_sucio = self.piso_y_pl()

        self.assertEqual(piso_sucio["piso_mes"], piso_limpio["piso_mes"])
        self.assertAlmostEqual(pl_limpio["margen_neto"] - pl_sucio["margen_neto"],
                               impo, delta=1.0)

    # ── Ayudantes ────────────────────────────────────────────────────────────

    def obligacion_fija(self, monto, devengo, categoria=None, vence=None):
        o = Obligacion(categoria_id=(categoria or self.cat_fijo).id,
                       tienda_id=None, concepto="x", monto=monto,
                       fecha_devengo=devengo, fecha_vencimiento=vence,
                       usuario_id=self.admin.id, anulada=False)
        self.db.add(o)
        self.db.commit()
        return o

    def con_plata_en_caja(self, base):
        """Un turno ABIERTO con base: es de donde sale el efectivo de hoy, o sea
        el punto de partida de la serie del flujo."""
        t = CajaTurno(tienda_id=self.tienda.id, usuario_apertura_id=self.admin.id,
                      base_real=base, estado=EstadoTurnoEnum.abierto)
        self.db.add(t)
        self.db.commit()
        return t


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LA COBERTURA DEL FLUJO ES POR CONCEPTO, NO UN BOOLEANO DE «HAY ALGO»
# ═══════════════════════════════════════════════════════════════════════════════
#
# `sin_salidas_cargadas` es `not salidas_dia`: se apaga con UNA obligación
# cualquiera. Con el arriendo cargado, el verde volvía a viajar sin reserva
# aunque faltaran $11,5M de la DIAN — y el propio docstring de
# `get_flujo_proyectado` dice que «la AUSENCIA de un punto de quiebre, sola, no
# significa nada». La única señal que implementaba esa frase se desarmaba con una
# obligación.

class CoberturaDelFlujoTest(ImpoBase):

    def preparar(self):
        self.vender_en_el_bimestre_cerrado(155_600_000)
        self.venta(self.hoy.replace(day=1), 30_000_000)
        return round(155_600_000 * I_MEDIDO, 2)

    def arriendo(self):
        self.db.add(Obligacion(
            categoria_id=self.cat_fijo.id, tienda_id=None, concepto="Arriendo",
            monto=10_000_000, fecha_devengo=self.hoy.replace(day=1),
            fecha_vencimiento=date(self.hoy.year, self.hoy.month, 28),
            usuario_id=self.admin.id, anulada=False))
        self.db.commit()

    def falta(self, flujo) -> dict:
        return {c["clave"]: c for c in flujo["advertencias"]["conceptos_sin_cargar"]}

    def test_con_un_arriendo_cargado_el_flag_viejo_se_apaga_y_el_nuevo_no(self):
        """EL BLOQUEANTE, EN UN SOLO TEST: una obligación alcanzaba para apagar
        la única señal de cobertura que había."""
        impo = self.preparar()
        self.arriendo()
        f = svc.get_flujo_proyectado(self.db)

        # El flag viejo ya se apagó: hay UNA salida cargada.
        self.assertFalse(f["advertencias"]["sin_salidas_cargadas"])
        # El nuevo sigue prendido y DICE QUÉ FALTA, con nombre y plata.
        self.assertTrue(f["advertencias"]["salidas_incompletas"])
        c = self.falta(f)[svc.CLAVE_CATEGORIA_IMPOCONSUMO]
        self.assertAlmostEqual(c["monto"], impo, delta=1.0)
        self.assertIn(self.cerrado_nombre, c["nombre"])

    def test_agendarla_la_saca_de_la_lista(self):
        """Una advertencia que no se puede apagar se aprende a ignorar."""
        self.preparar()
        self.arriendo()
        self.assertIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO,
                      self.falta(svc.get_flujo_proyectado(self.db)))
        anio, bim = self.cerrado
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        self.assertNotIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO,
                         self.falta(svc.get_flujo_proyectado(self.db)))

    def test_marcarla_como_declarada_NO_la_saca_porque_declarar_no_es_pagar(self):
        """EL TEST QUE AFIRMABA LO CONTRARIO, DADO VUELTA A PROPÓSITO.

        Decía «si el dueño dice que ya la declaró, no se le discute», y con eso
        el interruptor del TRÁMITE apagaba el aviso de la CAJA: cero pesos
        movidos, un aviso menos. Declarar es un trámite ante la DIAN; pagar es
        plata que sale del cajón, y en el rato que va de uno a otro la caja tiene
        que seguir viendo la salida. La cobertura la decide una sola pregunta —¿hay
        una obligación viva de este bimestre?— y esa la contesta la base, no una
        afirmación del dueño sobre otra cosa. Ver `_cobertura_impoconsumo`.
        """
        self.preparar()
        anio, bim = self.cerrado
        r = self.client.post("/api/v1/costos/impoconsumo/declarado",
                             json={"anio": anio, "bimestre": bim})
        self.assertEqual(r.status_code, 200)
        # El marcador SÍ quedó escrito: lo que no hace es cubrir la caja.
        self.assertEqual(svc.leer_impoconsumo_declarado(self.db), (anio, bim))
        self.assertIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO,
                      self.falta(svc.get_flujo_proyectado(self.db)))
        # Y el camino para apagarlo sigue existiendo, con la plata escrita:
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        self.assertNotIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO,
                         self.falta(svc.get_flujo_proyectado(self.db)))

    def test_sin_monto_medible_se_nombra_igual_pero_sin_inventar_un_cero(self):
        """Un 0 acá se leería como «no hay nada que reservar», que es la
        conclusión opuesta a la verdadera."""
        self.arriendo()               # sin ventas en el bimestre cerrado
        c = self.falta(svc.get_flujo_proyectado(self.db))[svc.CLAVE_CATEGORIA_IMPOCONSUMO]
        self.assertIsNone(c["monto"])
        self.assertIn("no hay ventas registradas", c["sin_monto_porque"])

    def test_no_avisa_de_una_salida_que_vence_despues_del_horizonte(self):
        """Lo que vence fuera de la ventana no le falta a ESTA proyección, y
        avisarlo sería el ruido que hace que los avisos se ignoren."""
        self.preparar()
        self.arriendo()
        # Horizonte de un solo día: el vencimiento de la declaración queda afuera
        # salvo que ya esté vencida, en cuyo caso se apila en hoy+1 y SÍ cuenta.
        _desde, hasta = svc._rango_bimestre(*self.cerrado)
        _p, vence = svc._mes_de_declaracion(hasta)
        f = svc.get_flujo_proyectado(self.db, dias=1)
        esperado = vence <= self.hoy + timedelta(days=1)
        self.assertEqual(svc.CLAVE_CATEGORIA_IMPOCONSUMO in self.falta(f), esperado)

    def test_la_nomina_vencida_NO_se_anuncia_como_salida_futura(self):
        """Al revés que la declaración de la DIAN, y la diferencia importa: una
        nómina cuyo día de pago ya pasó se pagó —la gente no sigue viniendo si
        no— así que esa plata ya salió del cajón. Anunciarla la restaría de
        nuevo y correría el punto de quiebre por plata que no existe."""
        self.preparar()
        self.arriendo()
        f = svc.get_flujo_proyectado(self.db)
        c = self.falta(f).get(svc.CLAVE_CATEGORIA_NOMINA)
        if c is not None:
            self.assertFalse(c["vencido"])
            self.assertGreater(date.fromisoformat(str(c["vence"])), self.hoy)

    @property
    def cerrado_nombre(self) -> str:
        return svc._nombre_bimestre(*self.cerrado)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LA FILA CREADA NO SE PUEDE EDITAR HACIA EL DOBLE CONTEO
# ═══════════════════════════════════════════════════════════════════════════════
#
# La categoría dedicada dejaba el piso y el margen quietos, pero la fila quedaba
# en la pantalla de Obligaciones con sus botones. `_validar_categoria` miraba
# SOLO el destino, así que la puerta estaba cerrada por un lado y abierta por el
# otro: el dueño le cambiaba la categoría y volvía el mundo (B) de la sección 4.
#
# MEDIDO sobre esta base ($155,6M facturados adentro del último mes del bimestre,
# que es donde devenga la declaración): el piso de ese mes subía $12.447.999,00 y
# el margen neto caía $11.525.925,93. Los mismos pesos de (B), reinstalados con
# dos taps.

class LaFilaNoSeEditaTest(ImpoBase):

    def preparar(self) -> float:
        """La venta del bimestre va al ÚLTIMO mes, que es donde DEVENGA la
        declaración: es el único mes cuyo P&L y cuyo piso la fila puede mover, y
        medir en otro mes daría delta $0 por la ventana, no por la guarda."""
        _desde, hasta = svc._rango_bimestre(*self.cerrado)
        self.venta(hasta - timedelta(days=3), 155_600_000)
        self.db.add(Obligacion(
            categoria_id=self.cat_fijo.id, tienda_id=None, concepto="Arriendo",
            monto=10_000_000, fecha_devengo=hasta.replace(day=1),
            fecha_vencimiento=hasta, usuario_id=self.admin.id, anulada=False))
        self.db.commit()
        return round(155_600_000 * I_MEDIDO, 2)

    def del_devengo(self):
        """(piso, resumen del P&L) del mes al que pertenece la declaración."""
        _desde, hasta = svc._rango_bimestre(*self.cerrado)
        piso = svc.get_piso(self.db, hasta.year, hasta.month)
        pl = rent_svc.get_rentabilidad(self.db, hasta.replace(day=1), hasta)["resumen"]
        return piso, pl

    def agendada(self) -> int:
        anio, bim = self.cerrado
        return svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)["id"]

    # ── LA PUERTA ────────────────────────────────────────────────────────────

    def test_cambiarle_la_categoria_a_una_de_grupo_fijo_rebota(self):
        """EL BLOQUEANTE. `_validar_categoria` valida el DESTINO; sin mirar el
        ORIGEN, la fila se editaba hacia 'impuestos' y el doble conteo volvía."""
        self.preparar()
        oid = self.agendada()
        r = self.client.patch(f"/api/v1/costos/obligaciones/{oid}",
                              json={"categoria_id": self.cat_imp.id})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIsInstance(r.json()["detail"], str)
        self.assertIn("no se corrige a mano", r.json()["detail"])

    def test_y_el_piso_y_el_margen_no_se_mueven_NI_UN_CENTAVO(self):
        """El test anterior mira el código HTTP; este mira la plata, que es lo
        que importa. Delta $0 exacto en los dos, sobre el mes del devengo."""
        self.preparar()
        oid = self.agendada()
        piso_antes, pl_antes = self.del_devengo()

        self.client.patch(f"/api/v1/costos/obligaciones/{oid}",
                          json={"categoria_id": self.cat_imp.id})

        piso_desp, pl_desp = self.del_devengo()
        self.assertEqual(piso_desp["piso_mes"], piso_antes["piso_mes"])
        self.assertEqual(pl_desp["margen_neto"], pl_antes["margen_neto"])
        self.assertEqual(pl_desp["gastos"], pl_antes["gastos"])

    def test_guardar_con_el_select_EN_BLANCO_tampoco_la_mueve(self):
        """EL CAMINO REAL, y el que el 400 del destino no cubría.

        `listar_categorias` esconde esta clave, así que el desplegable del
        formulario no tiene la opción de la fila y abría vacío. El dueño elegía
        la primera de la lista —'arriendo', grupo fijo— y eso el server lo
        aceptaba: mismo daño en pesos, sin que nadie tecleara «impuestos».
        """
        self.preparar()
        oid = self.agendada()
        cats = svc.listar_categorias(self.db)
        # Se confirma la premisa: la categoría de la fila NO está en el desplegable.
        obl = self.db.query(Obligacion).filter(Obligacion.id == oid).one()
        self.assertNotIn(obl.categoria_id, [c["id"] for c in cats])

        piso_antes, pl_antes = self.del_devengo()
        r = self.client.patch(f"/api/v1/costos/obligaciones/{oid}", json={
            "categoria_id": cats[0]["id"], "concepto": obl.concepto,
            "monto": float(obl.monto), "fecha_devengo": obl.fecha_devengo.isoformat(),
        })
        self.assertEqual(r.status_code, 400, r.text)
        piso_desp, pl_desp = self.del_devengo()
        self.assertEqual(piso_desp["piso_mes"], piso_antes["piso_mes"])
        self.assertEqual(pl_desp["margen_neto"], pl_antes["margen_neto"])

    def test_tampoco_se_le_toca_el_monto_ni_la_fecha(self):
        """Se bloquea la FILA, no el campo de la categoría.

        El monto lo mide el sistema sobre la venta real y el vencimiento sale del
        calendario de la DIAN. Y el devengo es peor: corrido UN día afuera del
        bimestre, `_obligacion_de_impoconsumo` deja de encontrarla y el botón de
        agendar —que era idempotente— crea una SEGUNDA fila. Medido saltándose
        la guarda a mano: la agenda pasa de $31,5M a $43,0M, la DIAN cobrada dos
        veces.
        """
        self.preparar()
        oid = self.agendada()
        for cuerpo in ({"monto": 1.0},
                       {"fecha_devengo": self.hoy.isoformat()},
                       {"fecha_vencimiento": self.hoy.isoformat()},
                       {"concepto": "otra cosa"}):
            r = self.client.patch(f"/api/v1/costos/obligaciones/{oid}", json=cuerpo)
            self.assertEqual(r.status_code, 400, f"{cuerpo} → {r.text}")
        obl = self.db.query(Obligacion).filter(Obligacion.id == oid).one()
        _desde, hasta = svc._rango_bimestre(*self.cerrado)
        self.assertEqual(obl.fecha_devengo, hasta)
        self.assertGreater(float(obl.monto), 1.0)

    def test_repetir_tampoco_porque_el_impuesto_es_BIMESTRAL(self):
        """`repetir` copia al MES siguiente y esto se declara cada dos meses: la
        copia sería una declaración que no existe. Ya lo cerraba la validación
        del origen de `repetir_obligacion`; queda fijado para que no se caiga."""
        self.preparar()
        oid = self.agendada()
        antes = svc.get_agenda(self.db)["totales"]["monto"]
        r = self.client.post(f"/api/v1/costos/obligaciones/{oid}/repetir")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("No se puede repetir", r.json()["detail"])
        self.assertEqual(svc.get_agenda(self.db)["totales"]["monto"], antes)
        self.assertEqual(
            self.db.query(Obligacion).join(CostoCategoria).filter(
                CostoCategoria.clave == svc.CLAVE_CATEGORIA_IMPOCONSUMO).count(), 1)

    # ── LA SALIDA QUE SÍ TIENE QUE SEGUIR ABIERTA ────────────────────────────

    def test_anular_sigue_andando_y_es_la_forma_de_corregir_el_monto(self):
        """Si el número del contador es otro: se anula y se vuelve a agendar con
        esa cifra. Cerrar la edición sin dejar esta salida dejaría al dueño
        atado a una cifra que el sistema midió y él sabe que está mal."""
        self.preparar()
        oid = self.agendada()
        self.assertEqual(
            self.client.delete(f"/api/v1/costos/obligaciones/{oid}").status_code, 200)
        anio, bim = self.cerrado
        r = self.client.post("/api/v1/costos/impoconsumo/agendar",
                             json={"anio": anio, "bimestre": bim, "monto": 9_000_000})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(float(r.json()["monto"]), 9_000_000)
        self.assertFalse(r.json()["ya_existia"])

    def test_anularla_devuelve_el_aviso_de_la_caja(self):
        """La salida se corrige sola: sin obligación viva, la cobertura del flujo
        vuelve a decir que esa plata no está adentro."""
        self.preparar()
        oid = self.agendada()
        falta = lambda: {c["clave"] for c in svc.get_flujo_proyectado(
            self.db)["advertencias"]["conceptos_sin_cargar"]}
        self.assertNotIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO, falta())
        self.client.delete(f"/api/v1/costos/obligaciones/{oid}")
        self.assertIn(svc.CLAVE_CATEGORIA_IMPOCONSUMO, falta())

    def test_una_obligacion_normal_se_sigue_editando(self):
        """La guarda es por CLAVE y no un candado general sobre editar."""
        self.preparar()
        o = self.db.query(Obligacion).filter(
            Obligacion.categoria_id == self.cat_fijo.id).first()
        r = self.client.patch(f"/api/v1/costos/obligaciones/{o.id}",
                              json={"monto": 2_400_000,
                                    "categoria_id": self.cat_imp.id})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(float(r.json()["monto"]), 2_400_000)
        self.assertEqual(r.json()["categoria_clave"], "impuestos")

    def test_la_vieja_de_proveedores_se_escapaba_por_el_MISMO_agujero(self):
        """No es un caso aparte: la lista es una sola (`CLAVES_NO_ELEGIBLES`).
        Una obligación legacy de proveedor editada al primer renglón del select
        empezaba a contarse ADEMÁS de su FacturaCompra."""
        cat_prov = CostoCategoria(clave=svc.CLAVE_CATEGORIA_PROVEEDORES,
                                  nombre="Proveedores", grupo="variable", orden=9)
        self.db.add(cat_prov)
        self.db.commit()
        legacy = Obligacion(categoria_id=cat_prov.id, tienda_id=None,
                            concepto="Café Nariño", monto=3_000_000,
                            fecha_devengo=self.hoy, usuario_id=self.admin.id,
                            anulada=False)
        self.db.add(legacy)
        self.db.commit()
        r = self.client.patch(f"/api/v1/costos/obligaciones/{legacy.id}",
                              json={"categoria_id": self.cat_fijo.id})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Compras", r.json()["detail"])

    # ── LO QUE LA PANTALLA NECESITA PARA NO OFRECER EL BOTÓN ─────────────────

    def test_la_fila_viaja_diciendo_que_no_se_edita_a_mano(self):
        """Sin este campo la pantalla tendría que copiar la lista de claves, y
        una segunda copia de la regla se despega en la primera que se agregue.
        Con él, «Corregir» y «Repetir» no se dibujan sobre esta fila: un botón
        que solo existe para dar un 400 enseña a desconfiar de la pantalla."""
        self.preparar()
        self.agendada()
        filas = {o["categoria_clave"]: o
                 for o in svc.listar_obligaciones(self.db)["obligaciones"]}
        self.assertFalse(filas[svc.CLAVE_CATEGORIA_IMPOCONSUMO]["editable_a_mano"])
        self.assertTrue(filas["arriendo"]["editable_a_mano"])

    def test_el_campo_y_la_validacion_no_se_pueden_desincronizar(self):
        """Los dos salen de `CLAVES_NO_ELEGIBLES` con la MISMA expresión. Se
        recorre el catálogo entero: si mañana alguien agrega una clave a la lista
        y se olvida de un lado, este test lo levanta."""
        self.preparar()
        for cat in self.db.query(CostoCategoria).all():
            o = Obligacion(categoria_id=cat.id, tienda_id=None, concepto="x",
                           monto=1000, fecha_devengo=self.hoy,
                           usuario_id=self.admin.id, anulada=False)
            self.db.add(o)
            self.db.commit()
            dice = svc._serializar(o, [])["editable_a_mano"]
            try:
                svc._validar_origen(self.db, o)
                deja = True
            except HTTPException:
                deja = False
            self.assertEqual(dice, deja, cat.clave)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. DECLARAR NO ES RESERVAR — Y LA PANTALLA TIENE QUE PODER TAPAR EL HUECO
# ═══════════════════════════════════════════════════════════════════════════════
#
# `_cobertura_impoconsumo` ya no mira el marcador (sección 5). Falta la otra
# mitad: con el bimestre marcado como declarado y SIN agendar, el aviso del flujo
# manda al dueño a «Una vez al mes» — y ahí `get_impoconsumo` devolvía
# `monto_medido: None` porque el atajo caro se disparaba con «declarado» solo. El
# botón se quedaba sin cifra con que rotularse: una acción que se evapora.

class DeclararNoEsReservarTest(ImpoBase):

    def test_declarada_sin_agendar_TRAE_el_monto_para_poder_ofrecer_el_boton(self):
        self.vender_en_el_bimestre_cerrado(155_600_000)
        anio, bim = self.cerrado
        self.client.post("/api/v1/costos/impoconsumo/declarado",
                         json={"anio": anio, "bimestre": bim})
        d = self.leer()
        self.assertFalse(d["hay_que_declarar"])   # el trámite, apagado
        self.assertIsNone(d["agendada"])          # la plata, sin reservar
        self.assertAlmostEqual(d["monto_medido"], 155_600_000 * I_MEDIDO, delta=1)

    def test_declarada_Y_agendada_deja_de_pagar_la_medicion(self):
        """El atajo caro sigue existiendo: pide LAS DOS cosas, que es lo que de
        verdad quiere decir «no queda nada que hacer acá»."""
        self.vender_en_el_bimestre_cerrado(155_600_000)
        anio, bim = self.cerrado
        svc.agendar_impoconsumo(self.db, anio, bim, self.admin.id)
        self.client.post("/api/v1/costos/impoconsumo/declarado",
                         json={"anio": anio, "bimestre": bim})
        d = self.leer()
        self.assertIsNone(d["monto_medido"])
        self.assertIsNone(d["ventas"])
        self.assertIsNotNone(d["agendada"])

    def test_marcarla_declarada_no_mueve_UN_PESO_de_la_agenda(self):
        """El hecho crudo del bloqueante: el tap es sobre el TRÁMITE. Si además
        moviera plata, sería otra cosa — y si no la mueve, no puede apagar el
        aviso de la caja."""
        self.vender_en_el_bimestre_cerrado(155_600_000)
        antes = svc.get_agenda(self.db)["totales"]["monto"]
        anio, bim = self.cerrado
        self.client.post("/api/v1/costos/impoconsumo/declarado",
                         json={"anio": anio, "bimestre": bim})
        self.assertEqual(svc.get_agenda(self.db)["totales"]["monto"], antes)
        self.assertEqual(self.db.query(Obligacion).count(), 0)


if __name__ == "__main__":
    unittest.main()
