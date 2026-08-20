"""ARMAR EL MES QUE VIENE: el lote atómico, y la muerte de `recurrencia`.

FASE 4. La única fase que ataca el problema de verdad: que el dueño no va a
cargar nada a mano todos los meses. Sin esto el piso del mes que viene arranca en
cero todos los meses y la pantalla se abandona en noviembre.

Lo que fija este archivo:

1. `recurrencia` SE FUE, Y CREAR/EDITAR SIGUEN FUNCIONANDO. El campo se validaba,
   se guardaba y NADIE lo leía: `_mes_siguiente` copiaba siempre a +1 mes sin
   mirarlo, así que una obligación marcada 'quincenal' daba el mes siguiente
   igual. Como el frontend nunca lo mandó, sacarlo no rompe ningún cliente — pero
   mandarlo tampoco puede reventar, porque un cliente viejo cacheado existe.
2. EL LOTE ES ATÓMICO. Catorce cuentas entran las catorce o no entra ninguna. Con
   N requests sueltas, una tablet que pierde señal en la séptima deja el mes
   armado a la mitad y ninguna pantalla lo dice — y un mes a medio armar hace que
   la proyección salga TRANQUILIZADORA, que es la dirección en la que este módulo
   se equivoca siempre.
3. LA VISTA PREVIA NO ESCRIBE Y DICE LA MISMA LISTA QUE EL COMMIT. Si la previa y
   la creación fueran dos caminos distintos, el dueño aprobaría una lista y se le
   crearía otra.
4. SIGUE SIENDO IDEMPOTENTE, por la MISMA llave que el botón de a una: (serie,
   MES de devengo). Y las dos comparten `_copia_viva_del_mes`, así que no se
   pueden despegar.
5. UNA FILA QUE NO SE PUEDE COPIAR NO TUMBA EL MES. La categoría desactivada o la
   vieja 'proveedores' vuelven con el porqué y el resto se arma.
6. UN MES SALTADO NO PIERDE LA SERIE, y el vencimiento se corre los MISMOS meses
   que el devengo (no se recalcula a +1).
7. LOS DOS CEROS NO SON EL MISMO CERO, que es lo que hacía que toda esta fase
   naciera inerte en el negocio real. Solo se copian solas las series PROBADAS, y
   acá los costos fijos se cargan a mano todos los meses sin que nadie apriete
   nunca «Repetir mes que viene»: cero series, `van_a_crearse: []`, y la pantalla
   leyendo eso como «ya está todo armado» sobre un mes que arrancaba con el piso
   en $0 y $27,6M de fijos por aparecer. Medido con sonda: agosto $27.620.000 de
   fijos y piso $29.829.597,61; septiembre $0,00 y sin piso.

   Ahora la respuesta trae `series_repetibles` y `candidatas` —las cuentas vivas
   que todavía no son serie, ofrecidas para que el dueño elija cuáles van— y las
   dos causas del cero se pueden decir distinto. Lo que NO se elige NO se copia:
   una reparación del molino arrastrada al mes siguiente inventa un costo y eso
   INFLA el piso, que es el mismo error mirado del otro lado.
"""
import os
import tempfile
import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import (CostoCategoria, Obligacion, RolEnum, Tienda,
                               Usuario)
from app.routers import costos as costos_router
from app.services import costos as svc


class LoteBase(unittest.TestCase):
    """sqlite temporal + router real de costos (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                         bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda = Tienda(nombre="Vida", direccion="x")
        # LA SEGUNDA SEDE NO ES DECORADO. El negocio tiene dos, y «Arriendo» vale
        # $8.500.000 en una y $7.200.000 en la otra CON EL MISMO CONCEPTO: es el
        # caso que obliga a que la sede esté en la llave de cobertura.
        self.tienda2 = Tienda(nombre="Centro", direccion="y")
        self.db.add_all([self.tienda, self.tienda2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.cat = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                  grupo="fijo", orden=0)
        self.cat_off = CostoCategoria(clave="viejo", nombre="Viejo",
                                      grupo="fijo", orden=1, activa=False)
        self.cat_prov = CostoCategoria(clave="proveedores", nombre="Proveedores",
                                       grupo="variable", orden=2)
        # Otra categoría VIVA (la de arriba está desactivada), para probar que la
        # categoría NO entra en la llave de cobertura.
        self.cat2 = CostoCategoria(clave="servicios", nombre="Servicios",
                                   grupo="fijo", orden=3)
        self.db.add_all([self.cat, self.cat_off, self.cat_prov, self.cat2])
        self.db.commit()

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

    def obligacion(self, concepto, monto, devengo, vence=None, categoria=None,
                   plantilla_id=None, anulada=False, tienda_id=None):
        o = Obligacion(categoria_id=(categoria or self.cat).id,
                       tienda_id=tienda_id, concepto=concepto, monto=monto,
                       fecha_devengo=devengo, fecha_vencimiento=vence,
                       plantilla_id=plantilla_id, usuario_id=self.admin.id,
                       anulada=anulada)
        self.db.add(o)
        self.db.commit()
        return o

    def serie(self, concepto, monto, devengo, vence=None, categoria=None):
        """Una serie PROBADA: la cabeza y su copia, que es lo que la marca."""
        cabeza = self.obligacion(concepto, monto, devengo, vence, categoria)
        copia = self.obligacion(concepto, monto, svc._corrido(devengo, 1),
                                svc._corrido(vence, 1) if vence else None,
                                categoria, plantilla_id=cabeza.id)
        return cabeza, copia

    def vivas_de(self, anio, mes):
        ini = date(anio, mes, 1)
        fin = svc._corrido(ini, 1)
        return [o for o in self.db.query(Obligacion)
                .filter(Obligacion.anulada == False).all()  # noqa: E712
                if ini <= o.fecha_devengo < fin]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. `recurrencia` SE FUE
# ═══════════════════════════════════════════════════════════════════════════════

class RecurrenciaSeFueTest(LoteBase):

    def test_la_columna_no_existe_en_el_modelo(self):
        """El campo mentía: se validaba, se guardaba y `_mes_siguiente` no lo
        miraba. Dejarlo era peor que las dos alternativas."""
        self.assertFalse(hasattr(Obligacion, "recurrencia"))
        self.assertFalse(hasattr(svc, "RECURRENCIAS"))
        self.assertFalse(hasattr(svc, "_validar_recurrencia"))

    def test_crear_y_editar_siguen_funcionando(self):
        r = self.client.post("/api/v1/costos/obligaciones", json={
            "categoria_id": self.cat.id, "concepto": "Arriendo",
            "monto": 3_000_000, "fecha_devengo": "2026-08-31"})
        self.assertEqual(r.status_code, 200, r.text)
        oid = r.json()["id"]
        self.assertNotIn("recurrencia", r.json())

        r2 = self.client.patch(f"/api/v1/costos/obligaciones/{oid}",
                               json={"monto": 3_200_000})
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["monto"], 3_200_000)

    def test_un_cliente_viejo_que_todavia_lo_manda_no_revienta(self):
        """El frontend nunca lo mandó (verificado en el historial), pero una
        tablet con el bundle viejo cacheado tiene que poder seguir cargando: el
        campo sobrante se ignora, no tumba el alta."""
        r = self.client.post("/api/v1/costos/obligaciones", json={
            "categoria_id": self.cat.id, "concepto": "Internet",
            "monto": 150_000, "fecha_devengo": "2026-08-05",
            "recurrencia": "quincenal"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_repetir_sigue_dando_el_mes_siguiente(self):
        o = self.obligacion("Arriendo", 3_000_000, date(2026, 1, 31))
        r = self.client.post(f"/api/v1/costos/obligaciones/{o.id}/repetir")
        self.assertEqual(r.status_code, 200, r.text)
        # 31 de enero → 28 de febrero: el día se recorta al último real.
        self.assertEqual(r.json()["fecha_devengo"], "2026-02-28")


# ═══════════════════════════════════════════════════════════════════════════════
# 2-3. LA VISTA PREVIA, Y QUE NO ESCRIBE
# ═══════════════════════════════════════════════════════════════════════════════

class VistaPreviaTest(LoteBase):

    def test_la_previa_lista_lo_que_va_a_crear_y_no_crea_nada(self):
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31), date(2026, 8, 5))
        self.serie("Internet", 150_000, date(2026, 7, 5), date(2026, 8, 10))
        antes = self.db.query(Obligacion).count()

        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": False})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertFalse(d["confirmado"])
        self.assertEqual(len(d["van_a_crearse"]), 2)
        self.assertEqual(d["n_creadas"], 0)
        self.assertEqual(d["creadas"], [])
        # NADA se escribió.
        self.assertEqual(self.db.query(Obligacion).count(), antes)

    def test_la_previa_dice_la_plata_que_le_agrega_al_mes(self):
        """El dueño ve los montos ANTES de que existan, que es cuando todavía
        puede decir «ese arriendo subió»."""
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.serie("Internet", 150_000, date(2026, 7, 5))
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": False})
        self.assertEqual(r.json()["total"], 3_150_000)

    def test_la_previa_y_el_commit_dicen_la_misma_lista(self):
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31), date(2026, 8, 5))
        self.serie("Internet", 150_000, date(2026, 7, 5))
        previa = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                                  json={"anio": 2026, "mes": 9,
                                        "confirmar": False}).json()
        hecho = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                                 json={"anio": 2026, "mes": 9,
                                       "confirmar": True}).json()
        clave = lambda v: (v["concepto"], v["monto"], v["fecha_devengo"],  # noqa: E731
                           v["fecha_vencimiento"])
        self.assertEqual(sorted(map(clave, previa["van_a_crearse"])),
                         sorted(map(clave, hecho["van_a_crearse"])))
        self.assertEqual(hecho["n_creadas"], len(previa["van_a_crearse"]))
        self.assertEqual(hecho["total"], previa["total"])

    def test_un_costo_suelto_sin_serie_no_entra(self):
        """`plantilla_id` se escribe solo en las COPIAS: una obligación cargada
        ayer que nadie declaró repetible no puede aparecer sola el mes que viene.
        Armar el mes con costos que nadie dijo que se repiten llenaría el P&L de
        plata que no existe."""
        self.obligacion("Arreglo del molino", 400_000, date(2026, 8, 12))
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": False})
        self.assertEqual(r.json()["van_a_crearse"], [])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LA ATOMICIDAD
# ═══════════════════════════════════════════════════════════════════════════════

class AtomicidadTest(LoteBase):

    def test_o_entran_todas_o_no_entra_ninguna(self):
        """El commit es UNO. Si algo revienta en el medio, la base queda como
        estaba — no con siete de catorce."""
        for i in range(14):
            self.serie(f"Costo {i}", 100_000 + i, date(2026, 7, 10))
        antes = self.db.query(Obligacion).count()

        original = svc.audit.registrar

        def explota(*a, **k):
            raise RuntimeError("se cortó la luz en la séptima")

        svc.audit.registrar = explota
        try:
            with self.assertRaises(RuntimeError):
                svc.armar_mes(self.db, 2026, 9, confirmar=True,
                              usuario_id=self.admin.id)
        finally:
            svc.audit.registrar = original
        self.db.rollback()
        self.assertEqual(self.db.query(Obligacion).count(), antes)
        self.assertEqual(len(self.vivas_de(2026, 9)), 0)

    def test_las_catorce_entran_de_una(self):
        for i in range(14):
            self.serie(f"Costo {i}", 100_000, date(2026, 7, 10))
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": True})
        self.assertEqual(r.json()["n_creadas"], 14)
        self.assertEqual(len(self.vivas_de(2026, 9)), 14)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LA IDEMPOTENCIA, COMPARTIDA CON EL BOTÓN DE A UNA
# ═══════════════════════════════════════════════════════════════════════════════

class IdempotenciaTest(LoteBase):

    def test_tocarlo_dos_veces_no_cobra_el_arriendo_dos_veces(self):
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        uno = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                               json={"anio": 2026, "mes": 9, "confirmar": True}).json()
        dos = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                               json={"anio": 2026, "mes": 9, "confirmar": True}).json()
        self.assertEqual(uno["n_creadas"], 1)
        self.assertEqual(dos["n_creadas"], 0)
        self.assertEqual(len(dos["ya_estaban"]), 1)
        self.assertEqual(len(self.vivas_de(2026, 9)), 1)

    def test_lo_que_ya_armo_el_boton_de_a_una_no_se_duplica(self):
        """Las dos puertas comparten `_copia_viva_del_mes`: no se pueden
        despegar."""
        cabeza, copia = self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.client.post(f"/api/v1/costos/obligaciones/{copia.id}/repetir")
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": True})
        self.assertEqual(r.json()["n_creadas"], 0)
        self.assertEqual(len(self.vivas_de(2026, 9)), 1)

    def test_una_copia_con_el_dia_corregido_a_mano_sigue_siendo_la_del_mes(self):
        """La llave es el MES, no la fecha exacta."""
        cabeza, copia = self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.obligacion("Arriendo", 3_000_000, date(2026, 9, 2),
                        plantilla_id=cabeza.id)
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": True})
        self.assertEqual(r.json()["n_creadas"], 0)

    def test_una_copia_anulada_no_bloquea_el_mes(self):
        """Anular la de septiembre y volver a armar tiene que crearla de nuevo:
        si no, el mes queda sin ese costo y nadie puede repararlo."""
        cabeza, copia = self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.obligacion("Arriendo", 3_000_000, date(2026, 9, 30),
                        plantilla_id=cabeza.id, anulada=True)
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": True})
        self.assertEqual(r.json()["n_creadas"], 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LO QUE NO SE PUEDE COPIAR NO TUMBA EL MES
# ═══════════════════════════════════════════════════════════════════════════════

class LoQueNoSePuedeTest(LoteBase):

    def test_una_fila_legacy_de_proveedores_no_deja_el_mes_sin_armar(self):
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.serie("Mercadería", 800_000, date(2026, 7, 15),
                   categoria=self.cat_prov)
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": True})
        d = r.json()
        self.assertEqual(d["n_creadas"], 1)
        self.assertEqual(len(d["no_se_pueden"]), 1)
        self.assertEqual(d["no_se_pueden"][0]["concepto"], "Mercadería")
        # El porqué viaja en castellano y dice QUÉ HACER en su lugar.
        self.assertIn("Compras", d["no_se_pueden"][0]["porque"])

    def test_una_categoria_desactivada_tambien_vuelve_con_el_porque(self):
        self.serie("Algo viejo", 90_000, date(2026, 7, 3), categoria=self.cat_off)
        d = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9,
                                   "confirmar": True}).json()
        self.assertEqual(d["n_creadas"], 0)
        self.assertIn("desactivada", d["no_se_pueden"][0]["porque"])


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LAS FECHAS: MES SALTADO Y VENCIMIENTO
# ═══════════════════════════════════════════════════════════════════════════════

class LasFechasTest(LoteBase):

    def test_un_mes_saltado_no_pierde_la_serie(self):
        """Si el dueño se saltó agosto, el arriendo de septiembre sale del de
        julio. Con la regla de «solo el mes anterior» esa serie desaparecía."""
        self.serie("Arriendo", 3_000_000, date(2026, 6, 30))  # jun + jul
        d = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9,
                                   "confirmar": False}).json()
        self.assertEqual(len(d["van_a_crearse"]), 1)
        v = d["van_a_crearse"][0]
        self.assertEqual(v["fecha_devengo"], "2026-09-30")
        # Y se DICE de qué mes se copió el monto: es viejo y el dueño tiene
        # derecho a saberlo. (Es 07-30 y no 07-31 porque `_corrido` conserva el
        # día del ORIGEN, que era un 30 de junio — el mismo comportamiento que
        # el botón de a una, a propósito: dos reglas para «correr una fecha»
        # darían dos devengos distintos según qué botón se apretó.)
        self.assertEqual(v["copiado_de"], "2026-07-30")

    def test_el_vencimiento_se_corre_los_mismos_meses_que_el_devengo(self):
        """Devengo el 31 de julio, vence el 5 de agosto. A septiembre son
        30-sep y 5-oct: el vencimiento NO se recalcula a +1 desde donde estaba,
        se corre los MISMOS dos meses."""
        self.serie("Arriendo", 3_000_000, date(2026, 6, 30), date(2026, 7, 5))
        d = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9,
                                   "confirmar": False}).json()
        v = d["van_a_crearse"][0]
        self.assertEqual(v["fecha_devengo"], "2026-09-30")
        self.assertEqual(v["fecha_vencimiento"], "2026-10-05")

    def test_la_previa_nombra_la_sede_para_que_no_haya_dos_arriendos_iguales(self):
        """Con dos sedes, «Arriendo · $3.000.000» dos veces es indistinguible.
        El nombre de la sede sale de la relación, no de un segundo fetch."""
        cabeza = self.obligacion("Arriendo", 3_000_000, date(2026, 7, 31))
        copia = self.obligacion("Arriendo", 3_000_000, date(2026, 8, 31),
                                plantilla_id=cabeza.id)
        # La sede va en las DOS: la copia sale del miembro más nuevo de la
        # serie, así que es la de agosto la que manda.
        cabeza.tienda_id = copia.tienda_id = self.tienda.id
        self.db.commit()
        d = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9,
                                   "confirmar": False}).json()
        self.assertEqual(d["van_a_crearse"][0]["tienda_nombre"], "Vida")

    def test_sin_fecha_de_pago_la_copia_tampoco_la_tiene(self):
        """Inventarle una la metería a la agenda con un vencimiento que nadie
        pactó."""
        self.serie("Contador", 500_000, date(2026, 7, 20))
        d = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9,
                                   "confirmar": False}).json()
        self.assertIsNone(d["van_a_crearse"][0]["fecha_vencimiento"])

    def test_el_dia_31_se_recorta_al_ultimo_real_del_mes_destino(self):
        self.serie("Arriendo", 3_000_000, date(2025, 12, 31))  # dic + ene
        d = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 2,
                                   "confirmar": False}).json()
        self.assertEqual(d["van_a_crearse"][0]["fecha_devengo"], "2026-02-28")

    def test_corrido_cruza_el_anio(self):
        self.assertEqual(svc._corrido(date(2026, 11, 30), 2), date(2027, 1, 30))
        self.assertEqual(svc._corrido(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(svc._corrido(date(2026, 12, 15), 1), date(2027, 1, 15))
        # `_mes_siguiente` es el caso +1 de la misma cuenta: una sola aritmética.
        self.assertEqual(svc._mes_siguiente(date(2026, 1, 31)),
                         svc._corrido(date(2026, 1, 31), 1))


# ═══════════════════════════════════════════════════════════════════════════════
# EL ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

class EndpointTest(LoteBase):

    def test_los_rangos_vuelven_como_400_mostrable_y_no_como_422(self):
        """El `detail` de un 422 es una LISTA y el cliente solo lee strings."""
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 13, "confirmar": False})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)

    def test_sin_confirmar_el_default_es_no_escribir(self):
        """Omitir `confirmar` no puede crear nada: el default seguro es el que no
        toca la base."""
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["confirmado"])
        self.assertEqual(len(self.vivas_de(2026, 9)), 0)

    def test_la_ruta_literal_gana_sobre_la_parametrica(self):
        """`armar-mes` no parsea como int: si la ruta estuviera abajo de
        `/obligaciones/{id}`, FastAPI devolvería un 422 confuso."""
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": False})
        self.assertEqual(r.status_code, 200, r.text)


# ═══════════════════════════════════════════════════════════════════════════════
# DOS TABLETS A LA VEZ: EL CERROJO DE LA SERIE
# ═══════════════════════════════════════════════════════════════════════════════

class DosTabletsALaVezTest(LoteBase):
    """Que la puerta esté CERRADA antes de preguntar si la copia del mes existe.

    ═══════════════════════════════════════════════════════════════════════════
    LO QUE ESTE ARCHIVO NO PUEDE PROBAR, Y HAY QUE DECIRLO
    ═══════════════════════════════════════════════════════════════════════════
    La carrera de verdad —dos requests que ven las dos el mes vacío y las dos
    insertan— NO SE PUEDE REPRODUCIR ACÁ. Dos motivos, los dos duros:

    1. La suite corre sobre SQLite, que serializa las escrituras: no hay dos
       transacciones solapadas que se puedan intercalar en el punto exacto.
    2. El dialecto SQLite de SQLAlchemy IGNORA `FOR UPDATE` al compilar. Aunque
       se lograra el solape, el arreglo no estaría puesto en el SQL que corre,
       así que un test «concurrente» pasaría o fallaría por razones que no son
       las del arreglo.

    Escribir igual un test verde con dos hilos sería un test que PASA POR
    CONSTRUCCIÓN: diría «no hay carrera» sobre un motor donde la carrera no
    existe, y eso es exactamente la clase de tranquilidad falsa que este módulo
    fabrica de más.

    Lo que SÍ se puede fijar, y es lo que se fija:

    - que el cerrojo se PIDE, y se pide ANTES de mirar si la copia existe (si
      alguien saca el `with_for_update()` o lo mueve una línea abajo, estos
      tests se ponen rojos);
    - que ese pedido se convierte en un `FOR UPDATE` REAL en Postgres, que es el
      motor de Render — o sea que el arreglo existe donde el negocio corre;
    - que en SQLite se cae solo, así que la suite no se traba ni cambia de
      comportamiento;
    - que la vista previa NO lockea nada;
    - que las DOS puertas (el lote y el botón de a una) toman el cerrojo por la
      misma llave: la CABEZA de la serie;
    - que el lote las toma en orden creciente, que es lo que evita que dos lotes
      simultáneos se traben en cruz.
    """

    def setUp(self):
        super().setUp()
        self.ejecutadas: list[dict] = []
        event.listen(self.db, "do_orm_execute", self._anotar)

    def tearDown(self):
        event.remove(self.db, "do_orm_execute", self._anotar)
        super().tearDown()

    def _anotar(self, estado):
        """Anota cada SELECT del ORM: su SQL, sus binds y si pide cerrojo.

        Se mira `_for_update_arg` del statement y NO el texto del SQL, porque en
        SQLite el texto NUNCA va a decir FOR UPDATE. La intención vive en el
        statement; que se convierta en cláusula es cosa del dialecto, y eso lo
        prueba aparte `test_el_cerrojo_es_un_for_update_de_verdad_en_postgres`.
        """
        stmt = estado.statement
        compilada = stmt.compile()
        self.ejecutadas.append({
            "sql": str(compilada),
            "params": compilada.params,
            "lockea": getattr(stmt, "_for_update_arg", None) is not None,
            "stmt": stmt,
        })

    # ── Ayudantes de lectura de lo anotado ───────────────────────────────────

    def cerrojos(self):
        return [e for e in self.ejecutadas if e["lockea"]]

    def ids_lockeados(self):
        """El id que pidió cada cerrojo, en el orden en que los pidió."""
        ids = []
        for e in self.cerrojos():
            ids += [v for k, v in e["params"].items() if k.startswith("id_")]
        return ids

    def i_primer_cerrojo(self):
        for i, e in enumerate(self.ejecutadas):
            if e["lockea"]:
                return i
        return None

    @staticmethod
    def _where(sql: str) -> str:
        """Solo el WHERE. SQLAlchemy compila con saltos de línea (`\\nWHERE `),
        así que partir por `' WHERE '` no encuentra nada y todos los detectores
        de abajo devuelven None en silencio — un test que no mira nada y pasa."""
        return sql.split("\nWHERE ", 1)[1] if "\nWHERE " in sql else ""

    def i_primera_lectura_de_la_llave(self):
        """Dónde se preguntó por primera vez «¿ya existe la copia del mes?».

        SE MIRA EL WHERE Y NO EL SQL ENTERO, y el detector se apretó a propósito
        cuando entró `_vivas_del_mes` (la lectura de lo que el mes DESTINO ya
        tiene). Aquel marcador era «`fecha_devengo >=` y de nadie más», y dejó
        de ser cierto: `_vivas_del_mes` usa el mismo rango de mes. Con el
        detector viejo este test señalaba esa lectura —que corre antes de
        cualquier cerrojo y a propósito— y se ponía rojo por una razón que no
        era la suya, o sea que habría dejado de vigilar el orden real.

        Lo que distingue a `_copia_viva_del_mes` es el filtro POR SERIE en el
        WHERE (`plantilla_id = ... OR id = ...`); `plantilla_id` a secas no
        sirve porque también aparece en la lista de columnas de todo SELECT de
        Obligacion.
        """
        for i, e in enumerate(self.ejecutadas):
            donde = self._where(e["sql"])
            if "fecha_devengo >=" in donde and "plantilla_id =" in donde:
                return i
        return None

    def i_lectura_del_mes_destino(self):
        """Dónde se leyó lo que el mes destino YA TIENE: mismo rango de mes, sin
        filtro de serie. Corre ANTES de los cerrojos y tiene que poder hacerlo:
        solo puede EVITAR una escritura, nunca autorizarla."""
        for i, e in enumerate(self.ejecutadas):
            donde = self._where(e["sql"])
            if "fecha_devengo >=" in donde and "plantilla_id =" not in donde:
                return i
        return None

    # ── El lote ──────────────────────────────────────────────────────────────

    def test_el_lote_cierra_la_puerta_antes_de_preguntar_si_ya_existe(self):
        """SIN el cerrojo esto queda en cero y el test se pone rojo.

        El orden es todo el arreglo: mirar y DESPUÉS lockear deja la ventana
        igual de abierta que no lockear nada.
        """
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.ejecutadas.clear()
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": True})
        self.assertEqual(r.status_code, 200, r.text)

        self.assertTrue(self.cerrojos(),
                        "el lote insertó sin pedir el cerrojo de la serie")
        self.assertLess(self.i_primer_cerrojo(), self.i_primera_lectura_de_la_llave(),
                        "se preguntó si ya existía ANTES de cerrar la puerta")

    def test_el_lote_lockea_la_cabeza_de_la_serie_y_no_la_copia(self):
        """La copia del mes es la fila que todavía NO EXISTE: no hay fantasma
        que lockear. La cabeza sí está siempre, así que es el cerrojo de la
        serie entera."""
        cabeza, _copia = self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.ejecutadas.clear()
        self.client.post("/api/v1/costos/obligaciones/armar-mes",
                         json={"anio": 2026, "mes": 9, "confirmar": True})
        self.assertEqual(self.ids_lockeados(), [cabeza.id])

    def test_el_cerrojo_es_un_for_update_de_verdad_en_postgres(self):
        """Que el ORM lo PIDA no alcanza: tiene que llegar al SQL del motor que
        corre en Render. Y en SQLite tiene que caerse solo, o la suite se traba
        contra un motor que ni siquiera tiene la cláusula."""
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.ejecutadas.clear()
        self.client.post("/api/v1/costos/obligaciones/armar-mes",
                         json={"anio": 2026, "mes": 9, "confirmar": True})
        stmt = self.cerrojos()[0]["stmt"]
        en_postgres = str(stmt.compile(dialect=postgresql.dialect())).upper()
        en_sqlite = str(stmt.compile(dialect=sqlite_dialect.dialect())).upper()
        self.assertIn("FOR UPDATE", en_postgres)
        self.assertNotIn("FOR UPDATE", en_sqlite)

    def test_la_vista_previa_no_traba_a_la_otra_tablet(self):
        """`confirmar=False` no escribe nada, así que no tiene por qué hacer
        esperar a nadie. Lockear al MIRAR sería un costo sin contraparte."""
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.ejecutadas.clear()
        r = self.client.post("/api/v1/costos/obligaciones/armar-mes",
                             json={"anio": 2026, "mes": 9, "confirmar": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.cerrojos(), [])

    def test_las_series_se_lockean_en_orden_para_no_trabarse_en_cruz(self):
        """Dos lotes simultáneos tienen que tomar los MISMOS cerrojos EN EL
        MISMO ORDEN. Si uno agarrara el arriendo esperando la nómina y el otro
        al revés, se traban entre ellos y ninguna de las dos tablets arma nada.
        """
        cabezas = [self.serie(f"Fijo {i}", 100_000 * (i + 1),
                              date(2026, 7, 10 + i))[0]
                   for i in range(3)]
        self.ejecutadas.clear()
        self.client.post("/api/v1/costos/obligaciones/armar-mes",
                         json={"anio": 2026, "mes": 9, "confirmar": True})
        ids = self.ids_lockeados()
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(set(ids), {c.id for c in cabezas})

    # ── El botón de a una ────────────────────────────────────────────────────

    def test_repetir_de_a_una_cierra_la_misma_puerta(self):
        """Dejar cerrada UNA sola de las dos puertas no sirve de nada: el dueño
        repite de a una desde Obligaciones mientras la otra tablet arma el mes
        entero, y las dos crean la copia de septiembre."""
        cabeza, copia = self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.ejecutadas.clear()
        r = self.client.post(f"/api/v1/costos/obligaciones/{copia.id}/repetir")
        self.assertEqual(r.status_code, 200, r.text)

        self.assertTrue(self.cerrojos(),
                        "repetir insertó sin pedir el cerrojo de la serie")
        self.assertLess(self.i_primer_cerrojo(), self.i_primera_lectura_de_la_llave())

    def test_repetir_lockea_la_cabeza_aunque_se_repita_desde_la_copia(self):
        """La llave de la serie es SIEMPRE el primer eslabón, no el padre
        inmediato. Si el cerrojo fuera sobre la copia, encadenar
        agosto→septiembre→octubre daría un cerrojo distinto por eslabón y las
        dos requests pasarían igual."""
        cabeza, copia = self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.ejecutadas.clear()
        self.client.post(f"/api/v1/costos/obligaciones/{copia.id}/repetir")
        self.assertEqual(self.ids_lockeados(), [cabeza.id])


if __name__ == "__main__":
    unittest.main()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. LOS DOS CEROS: LA FASE 4 NACÍA INERTE EN ESTE NEGOCIO
# ═══════════════════════════════════════════════════════════════════════════════

class LosDosCerosTest(LoteBase):
    """El escenario REAL de la cafetería, no uno de laboratorio.

    Cinco costos fijos cargados A MANO en agosto —$27.620.000, que es la plata de
    verdad— sin que nadie haya apretado nunca «Repetir mes que viene». Más una
    reparación del molino, que es de una sola vez y NO se puede colar sola: la
    categoría 'mantenimiento' es de grupo FIJO, así que copiarla entraría al
    numerador del piso igual que el arriendo.
    """

    FIJOS = [("Arriendo Vida", 8_500_000), ("Arriendo Centro", 7_200_000),
             ("Nómina administrativa", 6_800_000), ("Servicios públicos", 2_900_000),
             ("Internet y plataformas", 2_220_000)]
    TOTAL_FIJOS = 27_620_000
    MOLINO = 1_400_000

    def cargar_agosto(self, con_molino=True):
        """Como los carga el dueño: a mano, uno por uno, sin plantilla_id."""
        ids = [self.obligacion(c, m, date(2026, 8, 5), date(2026, 8, 10)).id
               for c, m in self.FIJOS]
        molino = (self.obligacion("Reparación del molino", self.MOLINO,
                                  date(2026, 8, 12)) if con_molino else None)
        return ids, molino

    def armar(self, incluir=None, confirmar=False, anio=2026, mes=9):
        cuerpo = {"anio": anio, "mes": mes, "confirmar": confirmar}
        if incluir is not None:
            cuerpo["incluir"] = incluir
        return self.client.post("/api/v1/costos/obligaciones/armar-mes", json=cuerpo)

    # ── EL QUE FALLA HOY ─────────────────────────────────────────────────────

    def test_sin_ninguna_serie_la_respuesta_no_puede_decir_que_no_falta_nada(self):
        """EL TEST DEL BLOQUEANTE. Con seis cuentas vivas y CERO series, la
        respuesta tiene que dejar decir «no hay ninguna marcada para repetirse» y
        NO «ya tienen su copia».

        Antes volvían `van_a_crearse: []`, `ya_estaban: []` y `no_se_pueden: []`,
        que es exactamente lo mismo que devuelve un mes que ya está armado. Con
        esos tres números y nada más, la única frase posible era la
        tranquilizadora, y la pantalla la decía dos veces.
        """
        self.cargar_agosto()
        r = self.armar().json()

        # Los tres de siempre siguen en cero: no hay nada que copiar SOLO.
        self.assertEqual(r["van_a_crearse"], [])
        self.assertEqual(r["ya_estaban"], [])
        # Y acá está la diferencia entre los dos ceros.
        self.assertEqual(r["series_repetibles"], 0)
        self.assertEqual(len(r["candidatas"]), 6)
        self.assertEqual(r["candidatas_de"], "2026-08-01")
        # La plata está a la vista: sin el monto la elección es a ciegas.
        self.assertEqual(sum(c["monto"] for c in r["candidatas"]),
                         self.TOTAL_FIJOS + self.MOLINO)

    def test_un_mes_ya_armado_de_verdad_si_puede_decir_que_no_falta_nada(self):
        """La contracara, para que el test de arriba no pase por casualidad: con
        series de verdad y sus copias hechas, `series_repetibles` NO es cero y
        `ya_estaban` las nombra. Ese cero sí se puede publicar como «al día»."""
        for i in range(3):
            self.serie(f"Costo {i}", 100_000, date(2026, 8, 5))
        self.client.post("/api/v1/costos/obligaciones/armar-mes",
                         json={"anio": 2026, "mes": 10, "confirmar": True})
        r = self.armar(mes=10).json()
        self.assertEqual(r["van_a_crearse"], [])
        self.assertEqual(r["series_repetibles"], 3)
        self.assertEqual(len(r["ya_estaban"]), 3)
        self.assertEqual(r["candidatas"], [])

    # ── QUE SE PUEDAN LLEVAR SIN RETECLEARLAS ────────────────────────────────

    def test_elegir_los_cinco_fijos_los_lleva_al_mes_con_su_plata(self):
        """Lo mínimo para que la fase 4 sirva de algo: el dueño no tiene que
        volver a cargar $27.620.000 a mano el 1 de septiembre."""
        ids, _ = self.cargar_agosto()
        previa = self.armar(incluir=ids).json()
        self.assertEqual(len(previa["van_a_crearse"]), 5)
        self.assertEqual(previa["total"], self.TOTAL_FIJOS)

        hecho = self.armar(incluir=ids, confirmar=True).json()
        self.assertEqual(hecho["n_creadas"], 5)
        self.assertEqual(hecho["n_elegidas"], 5)
        self.assertEqual(sum(o.monto for o in self.vivas_de(2026, 9)),
                         self.TOTAL_FIJOS)

    def test_los_costos_fijos_de_septiembre_dejan_de_ser_cero(self):
        """LA MEDICIÓN QUE IMPORTA, sobre el numerador del piso y no sobre la
        respuesta del lote. Que `n_creadas` diga 5 no prueba que el piso los vea:
        lo que el piso divide es `costos_fijos_devengados` del mes."""
        from app.services.rentabilidad import costos_fijos_del_mes
        ids, _ = self.cargar_agosto()
        antes = costos_fijos_del_mes(self.db, 2026, 9)
        self.assertEqual(antes["costos_fijos_devengados"], 0)
        self.assertFalse(antes["tiene_costos_fijos"])

        self.armar(incluir=ids, confirmar=True)
        despues = costos_fijos_del_mes(self.db, 2026, 9)
        self.assertEqual(despues["costos_fijos_devengados"], self.TOTAL_FIJOS)
        self.assertEqual(despues["n_costos_fijos"], 5)
        self.assertTrue(despues["tiene_costos_fijos"])

    def test_la_reparacion_que_no_se_eligio_no_se_copia(self):
        """LA DIRECCIÓN CONTRARIA, que cuesta igual de caro. Copiar la reparación
        del molino inventa $1.400.000 de costo que nadie va a pagar y SUBE el
        piso: el dueño sale a vender de más contra un número que no es."""
        ids, molino = self.cargar_agosto()
        self.armar(incluir=ids, confirmar=True)
        conceptos = [o.concepto for o in self.vivas_de(2026, 9)]
        self.assertNotIn("Reparación del molino", conceptos)
        self.assertEqual(len(conceptos), 5)
        # Y la suelta que quedó afuera sigue ofreciéndose, no desaparece.
        self.assertIn(molino.id,
                      [c["obligacion_id"] for c in self.armar(mes=10).json()["candidatas"]])

    def test_elegir_es_una_sola_vez_el_mes_siguiente_se_arma_solo(self):
        """La otra mitad del valor: la copia nace con `plantilla_id`, así que a
        partir del mes que viene ya son serie y el lote las agarra solo. Si
        hubiera que elegirlas todos los meses, esto sería retecleado con tildes."""
        ids, _ = self.cargar_agosto()
        self.armar(incluir=ids, confirmar=True)

        octubre = self.armar(mes=10).json()          # SIN incluir nada
        self.assertEqual(octubre["series_repetibles"], 5)
        self.assertEqual(len(octubre["van_a_crearse"]), 5)
        self.assertEqual(octubre["total"], self.TOTAL_FIJOS)

    # ── LA MISMA PUERTA QUE LAS SERIES ───────────────────────────────────────

    def test_elegirlas_dos_veces_no_cobra_el_arriendo_dos_veces(self):
        """Misma llave de idempotencia (serie, MES de devengo) que el botón de a
        una. La segunda pasada las encuentra ya en `ya_estaban`."""
        ids, _ = self.cargar_agosto()
        self.armar(incluir=ids, confirmar=True)
        otra = self.armar(incluir=ids, confirmar=True).json()
        self.assertEqual(otra["n_creadas"], 0)
        self.assertEqual(len(otra["ya_estaban"]), 5)
        self.assertEqual(len(self.vivas_de(2026, 9)), 5)

    def test_la_previa_con_lo_elegido_y_el_commit_dicen_la_misma_lista(self):
        """Si la previa y la creación fueran dos caminos, el dueño aprobaría una
        lista y se le crearía otra — ahora que la lista la arma él tildando, esto
        importa más que antes, no menos."""
        ids, _ = self.cargar_agosto()
        previa = self.armar(incluir=ids).json()
        hecho = self.armar(incluir=ids, confirmar=True).json()

        def clave(v):
            return (v["concepto"], v["monto"], v["fecha_devengo"])

        self.assertEqual(sorted(map(clave, previa["van_a_crearse"])),
                         sorted(map(clave, hecho["van_a_crearse"])))
        self.assertEqual(hecho["total"], previa["total"])

    def test_una_elegida_con_categoria_muerta_no_tumba_el_lote(self):
        """Misma puerta que las series: vuelve en `no_se_pueden` con el porqué y
        las otras entran igual."""
        ids, _ = self.cargar_agosto(con_molino=False)
        legacy = self.obligacion("Lácteos del mes", 900_000, date(2026, 8, 15),
                                 categoria=self.cat_prov)
        r = self.armar(incluir=ids + [legacy.id], confirmar=True).json()
        self.assertEqual(r["n_creadas"], 5)
        self.assertEqual(len(r["no_se_pueden"]), 1)
        self.assertEqual(r["no_se_pueden"][0]["concepto"], "Lácteos del mes")

    # ── LO QUE NO SE PUEDE ELEGIR NO SE IGNORA EN SILENCIO ───────────────────

    def test_un_id_que_no_esta_en_la_oferta_vuelve_400_y_no_crea_nada(self):
        """TILDAR SEIS Y QUE SE CREEN CINCO es la familia de error de esta
        pantalla entera. Se contesta 400 con un texto mostrable y no se escribe
        una sola fila."""
        ids, _ = self.cargar_agosto()
        r = self.armar(incluir=ids + [99_999], confirmar=True)
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)
        self.assertIn("99999", r.json()["detail"])
        self.assertEqual(len(self.vivas_de(2026, 9)), 0)

    def test_una_anulada_despues_de_elegirla_vuelve_400_y_no_se_copia(self):
        """El caso real del 400: el dueño la tildó, se fue a hacer otra cosa y la
        anuló desde Obligaciones. Copiarla igual metería al mes un costo que él
        acaba de dar de baja."""
        ids, _ = self.cargar_agosto()
        muerta = self.db.query(Obligacion).filter(Obligacion.id == ids[0]).first()
        muerta.anulada = True
        self.db.commit()
        r = self.armar(incluir=ids, confirmar=True)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(self.vivas_de(2026, 9)), 0)

    def test_un_id_invalido_vuelve_400_mostrable_y_no_422(self):
        """El `detail` de un 422 es una LISTA y el cliente solo lee strings."""
        r = self.armar(incluir=[0], confirmar=True)
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)

    def test_pedirla_de_nuevo_cuando_ya_es_serie_es_un_no_op_y_no_un_error(self):
        """Confirmar dos veces manda el mismo `incluir`, y para entonces esas
        cuentas YA son serie. Eso no es un id inválido: es el camino normal."""
        ids, _ = self.cargar_agosto()
        self.armar(incluir=ids, confirmar=True)
        r = self.armar(incluir=ids, confirmar=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["n_creadas"], 0)

    # ── QUÉ SE OFRECE, Y DE QUÉ MES ──────────────────────────────────────────

    def test_solo_se_ofrecen_las_del_mes_mas_reciente_con_sueltas(self):
        """Con dos años de costos sueltos la lista sería de cincuenta renglones,
        y una lista que nadie lee es como se termina tildando la de al lado."""
        self.obligacion("Anticipo viejo", 500_000, date(2026, 3, 4))
        self.cargar_agosto(con_molino=False)
        r = self.armar().json()
        self.assertEqual(len(r["candidatas"]), 5)
        self.assertNotIn("Anticipo viejo", [c["concepto"] for c in r["candidatas"]])

    def test_un_mes_saltado_no_vacia_la_oferta(self):
        """Se toma el mes MÁS RECIENTE con sueltas y no «el mes anterior» a
        secas: con julio cargado y agosto en blanco, «el anterior» está vacío y
        la oferta desaparecería entera — o sea el mes que viene en cero otra vez,
        que es justo lo que este arreglo persigue."""
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 7, 5))
        r = self.armar().json()
        self.assertEqual(len(r["candidatas"]), 1)
        self.assertEqual(r["candidatas_de"], "2026-07-01")

    def test_las_de_mas_plata_van_primero(self):
        """El arriendo y la nómina son las que no se pueden olvidar."""
        self.cargar_agosto()
        montos = [c["monto"] for c in self.armar().json()["candidatas"]]
        self.assertEqual(montos, sorted(montos, reverse=True))

    def test_una_suelta_anulada_no_se_ofrece(self):
        """Una cuenta dada de baja no puede volver por la puerta de atrás."""
        self.cargar_agosto(con_molino=False)
        self.obligacion("Compra cancelada", 300_000, date(2026, 8, 20),
                        anulada=True)
        conceptos = [c["concepto"] for c in self.armar().json()["candidatas"]]
        self.assertNotIn("Compra cancelada", conceptos)
        self.assertEqual(len(conceptos), 5)

    def test_la_copia_del_mes_destino_no_se_ofrece_a_si_misma(self):
        """La ventana es `fecha_devengo < primero del mes destino`: una cuenta ya
        cargada a mano EN septiembre no se puede ofrecer para copiar a
        septiembre."""
        self.obligacion("Cargada a mano en septiembre", 700_000, date(2026, 9, 3))
        r = self.armar().json()
        self.assertEqual(r["candidatas"], [])
        self.assertIsNone(r["candidatas_de"])

    def test_sin_ninguna_obligacion_no_hay_nada_que_ofrecer(self):
        """El tercer caso, que tampoco es «ya está armado»: base vacía."""
        r = self.armar().json()
        self.assertEqual(r["series_repetibles"], 0)
        self.assertEqual(r["candidatas"], [])
        self.assertIsNone(r["candidatas_de"])
        self.assertEqual(r["van_a_crearse"], [])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. EL MES DESTINO NO ESTÁ VACÍO, Y NADIE LO ESTABA MIRANDO
# ═══════════════════════════════════════════════════════════════════════════════
# EL BLOQUEANTE DE ESTA RONDA, MEDIDO CON SONDA ANTES DE ESCRIBIR NADA
# ─────────────────────────────────────────────────────────────────────────────
# La ronda pasada arregló que el lote naciera inerte: ahora OFRECE las cuentas
# vivas sin serie para que el dueño elija. Pero la oferta salía de mirar SOLO el
# mes ORIGEN. Y este negocio carga los cinco fijos A MANO todos los meses desde
# hace siete: el mes destino ya los tiene.
#
#   septiembre con sus 5 cargados a mano  →  se ofrecían los 5 de agosto
#   el dueño los tilda                    →  costos_fijos $27.620.000 → $55.240.000
#                                            piso_mes $29.829.597,61 → $59.659.195,23
#
# El piso pidiéndole $59,7M cuando necesita $29,8M, más $27.620.000 de deuda
# inventada en la agenda y en la proyección de caja. Y la alarma se apagaba
# después del tap, así que se quedaba con la sensación de haber hecho el trabajo.
#
# Y HABÍA UN SEGUNDO, PEOR, QUE NO NECESITA NINGÚN TAP: una cuenta que ya es
# serie se copia SOLA. Con el arriendo como serie y septiembre cargado a mano,
# `van_a_crearse` lo traía igual. Ese es el mes que viene del arreglo anterior:
# en cuanto el dueño tilde los cinco YA SON serie, y el 1 de octubre a las 6
# vuelve a cargarlos a mano. `LaSerieTampocoDuplicaTest` lo fija.

class LlaveDeCuentaTest(LoteBase):
    """QUÉ es «la misma cuenta» cuando no hay `plantilla_id` con qué compararla.

    Este test es el candado de la normalización COMPARTIDA con
    `producto_alias.normalizar_alias`: si alguien la afloja del lado de los
    alias, acá empezaría a matchear cuentas que no son la misma, este módulo
    dejaría de ofrecer un costo real y el piso saldría BAJO. Que se rompa un test
    de costos y no una cafetería es todo el punto de fijarlo desde acá.
    """

    def llave(self, concepto, tienda_id=None, categoria=None):
        return svc._llave_de_cuenta(
            self.obligacion(concepto, 1, date(2026, 8, 5),
                            categoria=categoria, tienda_id=tienda_id))

    def test_el_mismo_concepto_escrito_distinto_es_la_misma_cuenta(self):
        """El caso real: el dueño teclea el arriendo cada mes y no siempre igual."""
        base = self.llave("Arriendo Vida")
        self.assertEqual(self.llave("arriendo  vida"), base)
        self.assertEqual(self.llave("  ARRIENDO VIDA "), base)

    def test_las_tildes_y_la_enie_no_hacen_dos_cuentas(self):
        self.assertEqual(self.llave("Nómina administrativa"),
                         self.llave("Nomina administrativa"))
        self.assertEqual(self.llave("Diseño"), self.llave("Diseno"))

    def test_dos_sedes_con_el_mismo_concepto_son_DOS_cuentas(self):
        """MEDIDO: «Arriendo» vale $8.500.000 en Vida y $7.200.000 en Centro. Sin
        la sede en la llave, el de Vida taparía al de Centro, Centro nunca
        entraría al mes y el piso saldría $7.200.000 CORTO."""
        self.assertNotEqual(self.llave("Arriendo", self.tienda.id),
                            self.llave("Arriendo", self.tienda2.id))

    def test_la_corporativa_sin_sede_no_es_la_de_una_sede(self):
        self.assertNotEqual(self.llave("Contador"),
                            self.llave("Contador", self.tienda.id))

    def test_la_categoria_NO_entra_en_la_llave(self):
        """A propósito. Meterla haría la llave más ESTRICTA, y una llave estricta
        falla hacia «no reconozco que ya está» → duplicar: el dueño carga
        septiembre a mano y le pone la categoría equivocada, la llave no matchea
        y la serie copia un segundo arriendo. Lo que la categoría protegía —dos
        costos que comparten concepto y sede— lo cubre el conteo por
        multiplicidad."""
        self.assertEqual(self.llave("Arriendo Vida", categoria=self.cat),
                         self.llave("Arriendo Vida", categoria=self.cat2))


class ElMesDestinoTest(LoteBase):
    """El escenario REAL: los cinco fijos, $27.620.000, cargados a mano SIEMPRE.

    Cada test dice qué tiene el mes destino y qué hace el sistema. Los números
    son los del negocio, no de laboratorio.
    """

    FIJOS = [("Arriendo Vida", 8_500_000), ("Arriendo Centro", 7_200_000),
             ("Nómina administrativa", 6_800_000), ("Servicios públicos", 2_900_000),
             ("Internet y plataformas", 2_220_000)]
    TOTAL = 27_620_000

    def a_mano(self, dia, fijos=None):
        """Como los carga el dueño: uno por uno, sin `plantilla_id`."""
        return [self.obligacion(c, m, dia, date(dia.year, dia.month, 10)).id
                for c, m in (fijos if fijos is not None else self.FIJOS)]

    def armar(self, incluir=None, confirmar=False, anio=2026, mes=9):
        cuerpo = {"anio": anio, "mes": mes, "confirmar": confirmar}
        if incluir is not None:
            cuerpo["incluir"] = incluir
        return self.client.post("/api/v1/costos/obligaciones/armar-mes",
                                json=cuerpo)

    def fijos_de(self, anio=2026, mes=9):
        """EL NUMERADOR DEL PISO, que es lo único que prueba algo. Que
        `n_creadas` diga 5 no dice qué ve el piso."""
        from app.services.rentabilidad import costos_fijos_del_mes
        d = costos_fijos_del_mes(self.db, anio, mes)
        return d["costos_fijos_devengados"], d["n_costos_fijos"]

    # ── EL BLOQUEANTE ────────────────────────────────────────────────────────

    def test_lo_que_el_destino_ya_tiene_no_se_ofrece(self):
        """EL TEST DEL BLOQUEANTE. Septiembre ya tiene sus $27.620.000 cargados a
        mano: no hay una sola cuenta que ofrecer, y el numerador del piso no se
        mueve ni tildando todo lo que haya."""
        self.a_mano(date(2026, 8, 5))
        self.a_mano(date(2026, 9, 5))
        self.assertEqual(self.fijos_de(), (self.TOTAL, 5))

        r = self.armar().json()
        self.assertEqual(r["candidatas"], [])
        self.assertEqual(len(r["ya_en_el_mes"]), 5)
        # El total de lo tapado es exactamente la plata que se habría duplicado.
        self.assertEqual(sum(x["monto"] for x in r["ya_en_el_mes"]), self.TOTAL)
        self.assertEqual(r["mes_destino"], {"n": 5, "total": float(self.TOTAL),
                                            "n_fijos": 5, "fijos": float(self.TOTAL)})

        # Y el commit sin nada elegido tampoco crea nada.
        self.armar(confirmar=True)
        self.assertEqual(self.fijos_de(), (self.TOTAL, 5))

    def test_con_el_destino_vacio_se_siguen_ofreciendo_los_cinco(self):
        """LA CONTRACARA, para que el test de arriba no pase por casualidad:
        tapar de más dejaría el mes que viene en cero, que es el error que la
        ronda pasada arregló y este arreglo no puede reinstalar."""
        ids = self.a_mano(date(2026, 8, 5))
        self.assertEqual(self.fijos_de(), (0, 0))
        r = self.armar().json()
        self.assertEqual(len(r["candidatas"]), 5)
        self.assertEqual(r["ya_en_el_mes"], [])
        self.assertEqual(r["mes_destino"],
                         {"n": 0, "total": 0.0, "n_fijos": 0, "fijos": 0.0})

        self.armar(incluir=ids, confirmar=True)
        self.assertEqual(self.fijos_de(), (self.TOTAL, 5))

    def test_con_algunos_cargados_se_ofrecen_SOLO_los_que_faltan(self):
        """El estado del medio, que es el que más va a pasar: el dueño cargó los
        dos arriendos y todavía no el resto."""
        self.a_mano(date(2026, 8, 5))
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 9, 5))
        self.obligacion("Arriendo Centro", 7_200_000, date(2026, 9, 5))
        self.assertEqual(self.fijos_de(), (15_700_000, 2))

        r = self.armar().json()
        self.assertEqual([c["concepto"] for c in r["candidatas"]],
                         ["Nómina administrativa", "Servicios públicos",
                          "Internet y plataformas"])
        ids = [c["obligacion_id"] for c in r["candidatas"]]
        self.armar(incluir=ids, confirmar=True)
        # Termina EXACTO en la plata del mes, ni de más ni de menos.
        self.assertEqual(self.fijos_de(), (self.TOTAL, 5))

    def test_una_anulada_en_el_destino_no_tapa_nada(self):
        """Una cuenta que el dueño dio de baja NO cubre el mes. Seguir tapándola
        con ella dejaría septiembre sin ese costo y el piso corto."""
        self.a_mano(date(2026, 8, 5))
        self.a_mano(date(2026, 9, 5))
        muerta = (self.db.query(Obligacion)
                  .filter(Obligacion.concepto == "Arriendo Vida",
                          Obligacion.fecha_devengo == date(2026, 9, 5)).first())
        muerta.anulada = True
        self.db.commit()
        self.assertEqual(self.fijos_de(), (19_120_000, 4))

        r = self.armar().json()
        self.assertEqual([c["concepto"] for c in r["candidatas"]],
                         ["Arriendo Vida"])
        self.armar(incluir=[r["candidatas"][0]["obligacion_id"]], confirmar=True)
        self.assertEqual(self.fijos_de(), (self.TOTAL, 5))

    def test_dos_sedes_el_mismo_concepto_y_solo_una_cargada(self):
        """MEDIDO, y es la razón de que la sede esté en la llave. Sin ella el
        arriendo de Centro no entraría nunca y el piso saldría $7.200.000 corto."""
        self.obligacion("Arriendo", 8_500_000, date(2026, 8, 5),
                        tienda_id=self.tienda.id)
        self.obligacion("Arriendo", 7_200_000, date(2026, 8, 5),
                        tienda_id=self.tienda2.id)
        self.obligacion("Arriendo", 8_500_000, date(2026, 9, 5),
                        tienda_id=self.tienda.id)

        r = self.armar().json()
        self.assertEqual(len(r["candidatas"]), 1)
        self.assertEqual(r["candidatas"][0]["tienda_nombre"], "Centro")
        self.assertEqual(r["candidatas"][0]["monto"], 7_200_000)
        self.armar(incluir=[r["candidatas"][0]["obligacion_id"]], confirmar=True)
        self.assertEqual(self.fijos_de(), (15_700_000, 2))

    def test_el_mismo_concepto_escrito_distinto_no_se_duplica(self):
        """«Arriendo Vida» en agosto, «arriendo  vida» tecleado en septiembre."""
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 8, 5))
        self.obligacion("arriendo  vida", 8_500_000, date(2026, 9, 5))
        r = self.armar().json()
        self.assertEqual(r["candidatas"], [])
        self.assertEqual(len(r["ya_en_el_mes"]), 1)
        self.assertEqual(self.fijos_de(), (8_500_000, 1))

    def test_dos_cuentas_con_el_mismo_nombre_se_cuentan_de_a_una(self):
        """MULTIPLICIDAD, y es lo que permite sacar la categoría de la llave: el
        agua y la luz tecleadas las dos «Servicios públicos» en la misma sede.
        Con una sola en el destino, la presencia taparía a las DOS y septiembre
        se quedaría sin la segunda — un costo real afuera del piso."""
        self.obligacion("Servicios públicos", 2_900_000, date(2026, 8, 5))
        self.obligacion("Servicios públicos", 1_500_000, date(2026, 8, 6))
        self.obligacion("Servicios públicos", 2_900_000, date(2026, 9, 5))

        r = self.armar().json()
        self.assertEqual(len(r["candidatas"]), 1)
        self.assertEqual(len(r["ya_en_el_mes"]), 1)
        self.armar(incluir=[r["candidatas"][0]["obligacion_id"]], confirmar=True)
        self.assertEqual(self.fijos_de(), (4_400_000, 2))

    def test_un_mes_saltado_con_el_destino_cargado_tampoco_duplica(self):
        """Julio cargado, agosto en blanco, septiembre ya cargado a mano. La
        oferta sale de julio (el mes más reciente CON sueltas) y el destino la
        tapa igual: la ventana del origen y la cobertura del destino son dos
        preguntas distintas."""
        self.a_mano(date(2026, 7, 5))
        self.a_mano(date(2026, 9, 5))
        r = self.armar().json()
        self.assertEqual(r["candidatas_de"], "2026-07-01")
        self.assertEqual(r["candidatas"], [])
        self.assertEqual(self.fijos_de(), (self.TOTAL, 5))

    def test_el_mes_EN_CURSO_se_comporta_igual_que_el_que_viene(self):
        """El lote contesta por cualquier mes, y el dueño puede pedir el que está
        viviendo. Agosto ya cargado a mano no se puede volver a armar desde
        julio."""
        self.a_mano(date(2026, 7, 5))
        self.a_mano(date(2026, 8, 5))
        r = self.armar(mes=8).json()
        self.assertEqual(r["candidatas"], [])
        self.assertEqual(self.fijos_de(mes=8), (self.TOTAL, 5))

    # ── LO TAPADO SE NOMBRA, NUNCA SE CALLA ──────────────────────────────────

    def test_lo_tapado_vuelve_con_las_DOS_filas_a_la_vista(self):
        """Que el server decida no copiar algo es exactamente la clase de
        decisión que, callada, se lee como «no había nada»."""
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 8, 5))
        self.obligacion("Arriendo Vida", 9_100_000, date(2026, 9, 3))
        x = self.armar().json()["ya_en_el_mes"][0]
        self.assertEqual(x["concepto"], "Arriendo Vida")
        self.assertEqual(x["monto"], 8_500_000)          # la del origen
        self.assertFalse(x["automatica"])                # era suelta, no serie
        self.assertEqual(x["ya"]["monto"], 9_100_000)    # la del destino
        self.assertEqual(x["ya"]["fecha_devengo"], "2026-09-03")

    def test_una_que_se_PARECE_se_ofrece_pero_avisa_en_el_renglon(self):
        """LA LLAVE ES UNA IGUALDAD, así que «Arriendo Vida» y «Arriendo local
        Vida» no matchean y la cuenta se ofrece igual. Aflojar la llave para que
        matcheara escondería costos reales; el remedio es que el aviso esté EN EL
        RENGLÓN, antes del tilde y no después."""
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 8, 5))
        self.obligacion("Arriendo local Vida", 8_500_000, date(2026, 9, 5))
        c = self.armar().json()["candidatas"]
        self.assertEqual(len(c), 1)
        self.assertEqual(len(c[0]["parecidas"]), 1)
        self.assertEqual(c[0]["parecidas"][0]["concepto"], "Arriendo local Vida")
        self.assertEqual(c[0]["parecidas"][0]["monto"], 8_500_000)

    def test_lo_que_ya_tapo_a_otra_no_vuelve_a_aparecer_como_parecida(self):
        """Si una fila del destino ya tapó una cuenta, nombrarla otra vez como
        aviso le haría leer dos veces la misma cuenta."""
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 8, 5))
        self.obligacion("Internet", 2_220_000, date(2026, 8, 6))
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 9, 5))
        c = self.armar().json()["candidatas"]
        self.assertEqual([x["concepto"] for x in c], ["Internet"])
        self.assertEqual(c[0]["parecidas"], [])

    def test_mes_destino_va_SIEMPRE_aunque_este_en_cero(self):
        """`n: 0` es «lo miré y está vacío», que es una afirmación distinta de no
        haber mirado — y es la única que autoriza el aviso fuerte de la pantalla.
        Por eso el campo no puede faltar cuando no hay nada."""
        self.a_mano(date(2026, 8, 5))
        self.assertEqual(self.armar().json()["mes_destino"],
                         {"n": 0, "total": 0.0, "n_fijos": 0, "fijos": 0.0})

    def test_lo_que_el_piso_NO_cuenta_no_puede_pasar_por_mes_cubierto(self):
        """EL NÚMERO CERCA DEL CORRECTO, atajado antes de que llegue a la
        pantalla. La declaración del impoconsumo y las viejas de 'proveedores'
        son obligaciones vivas del mes y NO entran al numerador del piso (el P&L
        las saca por clave). Publicar el total de todo como «lo que el mes ya
        tiene» haría leer como cubierto un mes sin un peso de costos fijos, y
        apagaría justo el aviso que existe para eso.

        La COBERTURA sí las mira —una cuenta ya cargada no se puede duplicar
        aunque sea variable—, así que los dos números son distintos a propósito.
        """
        rara = CostoCategoria(clave="impoconsumo", nombre="Impoconsumo (DIAN)",
                              # Grupo 'fijo' A PROPÓSITO: si la exclusión
                              # dependiera solo del grupo, esta fila pasaría.
                              grupo="fijo", orden=9)
        self.db.add(rara)
        self.db.commit()
        self.a_mano(date(2026, 8, 5))
        self.obligacion("Declaración bimestre", 12_447_999, date(2026, 9, 18),
                        categoria=rara)

        d = self.armar().json()["mes_destino"]
        self.assertEqual(d["n"], 1)                 # la cobertura sí la ve
        self.assertEqual(d["total"], 12_447_999)
        self.assertEqual(d["n_fijos"], 0)           # el piso NO
        self.assertEqual(d["fijos"], 0.0)
        # Y el numerador real del piso está de acuerdo.
        self.assertEqual(self.fijos_de(), (0, 0))

    # ── TILDAR UNA TAPADA ────────────────────────────────────────────────────

    def test_tildar_una_que_el_destino_ya_tiene_vuelve_400_y_no_crea_nada(self):
        """El caso real: mira la previa, se va a Obligaciones, carga esa cuenta a
        mano en septiembre y vuelve a confirmar. Aborta el lote ENTERO: crear las
        otras cuatro y callarse esta es «tildaste cinco y se crearon cuatro»."""
        ids = self.a_mano(date(2026, 8, 5))
        previa = self.armar().json()
        self.assertEqual(len(previa["candidatas"]), 5)
        # Entre la previa y el commit, carga el arriendo a mano en septiembre.
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 9, 5))

        r = self.armar(incluir=ids, confirmar=True)
        self.assertEqual(r.status_code, 400)
        detalle = r.json()["detail"]
        self.assertIsInstance(detalle, str)
        # DICE LA RAZÓN DE VERDAD, no «se anuló o cambió».
        self.assertIn("Arriendo Vida", detalle)
        self.assertIn("septiembre", detalle)
        self.assertIn("8.500.000", detalle)
        # Y no se creó NI UNA.
        self.assertEqual(self.fijos_de(), (8_500_000, 1))


class LaSerieTampocoDuplicaTest(LoteBase):
    """EL DUPLICADO QUE NO NECESITA QUE NADIE TILDE NADA.

    Es el mes que viene del arreglo de la ronda pasada: en cuanto el dueño tilda
    los cinco YA SON serie, y el 1 de octubre a las 6 vuelve a cargarlos a mano
    como hace siete meses. Medido antes de escribir esto: el arriendo pasaba de
    $8.500.000 a $17.000.000 en el numerador del piso, con `van_a_crearse`
    prometiendo la suma y sin un solo tap.
    """

    def armar(self, confirmar=False, anio=2026, mes=9, incluir=None):
        cuerpo = {"anio": anio, "mes": mes, "confirmar": confirmar}
        if incluir is not None:
            cuerpo["incluir"] = incluir
        return self.client.post("/api/v1/costos/obligaciones/armar-mes",
                                json=cuerpo)

    def fijos_de(self, anio=2026, mes=9):
        from app.services.rentabilidad import costos_fijos_del_mes
        d = costos_fijos_del_mes(self.db, anio, mes)
        return d["costos_fijos_devengados"], d["n_costos_fijos"]

    def test_una_serie_no_se_copia_sobre_lo_que_el_dueno_ya_cargo(self):
        self.serie("Arriendo Vida", 8_500_000, date(2026, 7, 5))
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 9, 5))
        self.assertEqual(self.fijos_de(), (8_500_000, 1))

        previa = self.armar().json()
        self.assertEqual(previa["series_repetibles"], 1)
        self.assertEqual(previa["van_a_crearse"], [])
        self.assertEqual(previa["total"], 0)
        self.assertEqual(len(previa["ya_en_el_mes"]), 1)
        # `automatica` separa las dos procedencias: esta se habría copiado SOLA.
        self.assertTrue(previa["ya_en_el_mes"][0]["automatica"])

        hecho = self.armar(confirmar=True).json()
        self.assertEqual(hecho["n_creadas"], 0)
        self.assertEqual(self.fijos_de(), (8_500_000, 1))

    def test_con_el_destino_vacio_la_serie_SI_se_copia(self):
        """La contracara. Tapar de más dejaría el mes sin sus costos fijos, que
        es el error de la ronda anterior a la anterior."""
        self.serie("Arriendo Vida", 8_500_000, date(2026, 7, 5))
        hecho = self.armar(confirmar=True).json()
        self.assertEqual(hecho["n_creadas"], 1)
        self.assertEqual(self.fijos_de(), (8_500_000, 1))

    def test_la_serie_se_queda_con_el_cupo_antes_que_la_suelta(self):
        """EL ORDEN DEL REPARTO ES PARTE DEL ARREGLO. Si la suelta se llevara la
        única fila del destino, la serie —que se copia SOLA— crearía la segunda,
        y ese duplicado no tiene ningún tap donde frenarse."""
        self.serie("Arriendo Vida", 8_500_000, date(2026, 7, 5))
        # Otra cuenta suelta con el MISMO nombre y sede, cargada en agosto.
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 8, 20))
        self.obligacion("Arriendo Vida", 8_500_000, date(2026, 9, 5))

        r = self.armar().json()
        self.assertEqual(r["van_a_crearse"], [])          # la serie, tapada
        self.assertEqual(len(r["ya_en_el_mes"]), 1)
        self.assertTrue(r["ya_en_el_mes"][0]["automatica"])
        # La suelta se ofrece: el destino ya no tiene cupo para taparla, y
        # ofrecerla (con su aviso) es la dirección segura — el dueño decide.
        self.assertEqual(len(r["candidatas"]), 1)
        self.armar(confirmar=True)
        self.assertEqual(self.fijos_de(), (8_500_000, 1))

    def test_confirmar_dos_veces_sigue_siendo_un_no_op_y_no_un_400(self):
        """El camino NORMAL del segundo toque, no un borde. Después del primer
        confirmar la copia vive DENTRO del mes destino, y `_series_y_sueltas`
        solo mira lo anterior: la cabeza vuelve a parecer suelta. Reconocerla por
        IDENTIDAD (misma serie) y no por llave es lo que separa «ya estaba» de
        «esa cuenta ya no es elegible»."""
        o = self.obligacion("Arriendo Vida", 8_500_000, date(2026, 8, 5))
        uno = self.armar(incluir=[o.id], confirmar=True).json()
        self.assertEqual(uno["n_creadas"], 1)

        dos = self.armar(incluir=[o.id], confirmar=True)
        self.assertEqual(dos.status_code, 200, dos.text)
        self.assertEqual(dos.json()["n_creadas"], 0)
        self.assertEqual(len(dos.json()["ya_estaban"]), 1)
        self.assertEqual(dos.json()["ya_en_el_mes"], [])
        self.assertEqual(self.fijos_de(), (8_500_000, 1))

    def test_la_condicion_en_memoria_dice_lo_mismo_que_copia_viva_del_mes(self):
        """`_LoQueElMesYaTiene.sacar_miembro_de` repite en memoria la condición
        de `_copia_viva_del_mes` para repartir el presupuesto. Si las dos se
        despegan, el reparto le da el cupo a otra cuenta y la serie crea la
        copia igual — o sea el duplicado automático, otra vez."""
        cabeza, _copia = self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        self.client.post("/api/v1/costos/obligaciones/armar-mes",
                         json={"anio": 2026, "mes": 9, "confirmar": True})
        vivas = svc._vivas_del_mes(self.db, 2026, 9)
        enmemoria = svc._LoQueElMesYaTiene(vivas).sacar_miembro_de(cabeza.id)
        enbase = svc._copia_viva_del_mes(self.db, cabeza.id, 2026, 9)
        self.assertIsNotNone(enbase)
        self.assertEqual(enmemoria.id, enbase.id)

    def test_la_lectura_del_destino_no_escribe_nada(self):
        """Es de solo lectura y corre ANTES de los cerrojos, a propósito: solo
        puede EVITAR una escritura, nunca autorizarla. La que decide si se
        escribe sigue siendo `_copia_viva_del_mes` después del cerrojo."""
        self.serie("Arriendo", 3_000_000, date(2026, 7, 31))
        antes = self.db.query(Obligacion).count()
        svc._vivas_del_mes(self.db, 2026, 9)
        self.assertEqual(self.db.query(Obligacion).count(), antes)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. DESHACER: TILDAR UNA VEZ NO PUEDE SER PARA SIEMPRE
# ═══════════════════════════════════════════════════════════════════════════════

class DejarDeRepetirTest(LoteBase):
    """Tildar la «Reparación del molino» una sola vez la volvía serie PARA
    SIEMPRE, y el aviso no decía cómo salir.

    Medido antes de escribir el endpoint, y por eso existe: anular la copia de
    octubre NO alcanza (la de septiembre sigue con `plantilla_id` y noviembre se
    vuelve a copiar), y anular la CABEZA tampoco. Había que anularlas todas, una
    por una, sabiendo cuáles son. Eso no se hace en una tablet.
    """

    def armar(self, incluir=None, confirmar=False, anio=2026, mes=9):
        cuerpo = {"anio": anio, "mes": mes, "confirmar": confirmar}
        if incluir is not None:
            cuerpo["incluir"] = incluir
        return self.client.post("/api/v1/costos/obligaciones/armar-mes",
                                json=cuerpo)

    def no_repetir(self, oid):
        return self.client.post(f"/api/v1/costos/obligaciones/{oid}/no-repetir")

    def molino_hecho_serie(self):
        """El escenario medido: se tilda una vez en septiembre y en octubre el
        lote lo copia solo."""
        molino = self.obligacion("Reparación del molino", 3_000_000,
                                 date(2026, 8, 12))
        self.armar(incluir=[molino.id], confirmar=True)
        self.armar(mes=10, confirmar=True)
        return molino

    def test_un_costo_de_una_sola_vez_se_copiaba_todos_los_meses(self):
        """El daño, fijado antes que el arreglo: sin deshacer, $3.000.000 de una
        reparación entran al numerador del piso mes tras mes."""
        from app.services.rentabilidad import costos_fijos_del_mes
        self.molino_hecho_serie()
        for mes in (9, 10):
            self.assertEqual(
                costos_fijos_del_mes(self.db, 2026, mes)["costos_fijos_devengados"],
                3_000_000)
        self.assertEqual(len(self.armar(mes=11).json()["van_a_crearse"]), 1)

    def test_deshacerlo_lo_saca_de_las_que_se_copian_solas(self):
        molino = self.molino_hecho_serie()
        r = self.no_repetir(molino.id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["n_desmarcadas"], 2)   # septiembre y octubre

        nov = self.armar(mes=11).json()
        self.assertEqual(nov["series_repetibles"], 0)
        self.assertEqual(nov["van_a_crearse"], [])

    def test_deshacerlo_la_devuelve_a_la_lista_de_elegir(self):
        """No la esconde: vuelve a ser una cuenta suelta que se OFRECE. Si el
        dueño se arrepiente, la tilda de nuevo — desmarcar no puede ser otra
        puerta de una sola dirección."""
        molino = self.molino_hecho_serie()
        self.no_repetir(molino.id)
        conceptos = [c["concepto"]
                     for c in self.armar(mes=11).json()["candidatas"]]
        self.assertIn("Reparación del molino", conceptos)

    def test_no_mueve_un_peso_de_lo_ya_cargado(self):
        """NO BORRA NI ANULA NADA: las obligaciones ya creadas se deben igual.
        Lo único que cambia es si el mes que viene se copian solas."""
        from app.services.rentabilidad import costos_fijos_del_mes
        molino = self.molino_hecho_serie()
        antes = [costos_fijos_del_mes(self.db, 2026, m)["costos_fijos_devengados"]
                 for m in (8, 9, 10)]
        self.no_repetir(molino.id)
        despues = [costos_fijos_del_mes(self.db, 2026, m)["costos_fijos_devengados"]
                   for m in (8, 9, 10)]
        self.assertEqual(antes, despues)
        self.assertEqual(despues, [3_000_000, 3_000_000, 3_000_000])
        # Y ninguna quedó anulada.
        self.assertEqual(self.db.query(Obligacion).filter(
            Obligacion.anulada == True).count(), 0)  # noqa: E712

    def test_desmarca_la_cadena_ENTERA_desde_cualquier_eslabon(self):
        """La llave es SIEMPRE el primer eslabón, igual que en `repetir` y en el
        lote. Desmarcar desde octubre y que septiembre siguiera marcado dejaría
        la serie viva y noviembre volvería a copiar."""
        self.molino_hecho_serie()
        octubre = (self.db.query(Obligacion)
                   .filter(Obligacion.fecha_devengo >= date(2026, 10, 1),
                           Obligacion.fecha_devengo < date(2026, 11, 1)).first())
        self.no_repetir(octubre.id)
        self.assertEqual(self.armar(mes=11).json()["series_repetibles"], 0)
        vivas = self.db.query(Obligacion).filter(
            Obligacion.plantilla_id.isnot(None),
            Obligacion.anulada == False).count()  # noqa: E712
        self.assertEqual(vivas, 0)

    def test_es_idempotente_y_no_contesta_error(self):
        """Dos tablets, o dos toques. No es un error del dueño: es el estado que
        él quería."""
        molino = self.molino_hecho_serie()
        self.no_repetir(molino.id)
        r = self.no_repetir(molino.id)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ya_estaba"])
        self.assertEqual(r.json()["n_desmarcadas"], 0)

    def test_sobre_una_que_nunca_fue_serie_no_rompe_nada(self):
        o = self.obligacion("Anticipo", 500_000, date(2026, 8, 4))
        r = self.no_repetir(o.id)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ya_estaba"])

    def test_una_que_no_existe_vuelve_404_mostrable(self):
        r = self.no_repetir(99_999)
        self.assertEqual(r.status_code, 404)
        self.assertIsInstance(r.json()["detail"], str)

    def test_toma_el_mismo_cerrojo_que_las_puertas_que_escriben(self):
        """Sin él, desmarcar mientras la otra tablet arma el mes deja media serie
        rota y la otra media copiándose."""
        molino = self.molino_hecho_serie()
        lockeadas = []

        def espiar(estado):
            if getattr(estado.statement, "_for_update_arg", None) is not None:
                lockeadas.append(estado.statement)

        event.listen(self.db, "do_orm_execute", espiar)
        try:
            self.no_repetir(molino.id)
        finally:
            event.remove(self.db, "do_orm_execute", espiar)
        self.assertTrue(lockeadas, "desmarcó la serie sin pedir el cerrojo")
