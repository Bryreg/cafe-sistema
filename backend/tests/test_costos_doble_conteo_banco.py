"""LA MISMA PLATA, CONTADA DOS VECES: el débito tecleado y la obligación viva.

El dueño teclea el libro del banco contra el extracto, a mano, porque un libro
que cuadra al peso vale más que uno cómodo que no cuadra. Cuando teclea la
salida del arriendo pasan dos cosas y hasta hoy solo se veía una:

    obligación "Arriendo agosto" $2.400.000, vence el día 3
    teclea la salida del banco  $2.400.000  → el saldo del banco BAJA $2.400.000
    la obligación sigue viva en la agenda   → la proyección la sigue restando

    plata contada: $4.800.000. Plata real: $2.400.000.

El error va hacia el lado que ASUSTA (el día en que se queda sin plata sale
antes de lo real), y eso lo hace menos peligroso que el inverso pero igual de
inútil: una pantalla que se adelanta unos días cada mes es una pantalla que se
deja de mirar. `MovimientoBanco.obligacion_id` es lo que le permite al sistema
saber que ese débito y esa obligación son la misma plata; `get_agenda` ahora lo
consume y descuenta lo que ya salió del banco.

Lo que fija este archivo, y por qué cada regla importa:

- el débito enlazado SIN `Pago` saca la obligación de `items` (el bug que se
  arregla: es el único camino por el que la plata se contaba dos veces);
- el camino normal —«Registrar pago» con «Y descontalo del banco» tildado, que
  escribe el `Pago` PRIMERO y el movimiento después— no descuenta dos veces.
  `cubierto_de` toma el MÁXIMO y no la suma justamente por esto: los dos
  registros son la misma plata y no hay enlace entre ellos. Con una suma, una
  obligación pagada a medias desaparecería de la agenda debiendo, que es el
  lado tranquilizador y el peor de los dos errores posibles;
- solo cuentan las SALIDAS: una entrada enlazada es una devolución del
  proveedor, y restarla como si fuera un pago diría que se debe menos;
- un débito de más no puede dejar saldo negativo ni achicar el total de la
  agenda: un cero de más al teclear borraría deuda ajena;
- el pago ANULADO deja de contar pero el débito del libro NO —son dos registros
  independientes y el libro es la verdad del banco—, así que para revivir la
  obligación hay que borrar también el movimiento;
- el caso MIXTO (una parte en efectivo con `Pago`, otra desde el banco tecleada
  aparte) muestra MÁS deuda de la real. Es la dirección prudente, es lo que
  muestra hoy, y está acá para que se lea como decisión y no como descuido;
- la proyección cambia de verdad: el punto de quiebre se corre al día que
  corresponde en vez de dispararse por una salida que ya ocurrió.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col
from app.database import Base, get_db
from app.models.models import (CostoCategoria, CuentaBancaria, RolEnum, Tienda,
                               Usuario)
from app.routers import banco as banco_router
from app.routers import costos as costos_router
from app.services.costos import cubierto_de


class DobleConteoBancoTest(unittest.TestCase):
    """sqlite temporal + los DOS routers reales (patrón de la suite).

    Se montan costos y banco en la misma app porque el arreglo es una sola cosa
    partida en dos endpoints: el débito se teclea en `/banco/movimientos` y el
    efecto se lee en `/costos/agenda`. Probar cada mitad contra un mock de la
    otra dejaría pasar justamente el desacuerdo que importa — que es el bug.
    """

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="Sede Vida")
        self.palmetto = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                           grupo="fijo", orden=0)
        self.db.add(self.cat_arriendo)
        # La cuenta se crea acá y no con `banco.sembrar_cuentas` para que el test
        # no se ate al catálogo real de MEDIUM CAFÉ (Occidente/Bold): lo que se
        # prueba es el enlace movimiento↔obligación, no el catálogo.
        self.cuenta = CuentaBancaria(nombre="Occidente", orden=1)
        self.db.add(self.cuenta)
        self.db.commit()

        self.hoy = hoy_col()

        app = FastAPI(title="Test doble conteo banco")
        app.include_router(costos_router.router, prefix="/api/v1")
        app.include_router(banco_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def dia(self, delta: int) -> date:
        """Día Colombia relativo a hoy: `vencida` y el punto de quiebre se miden
        contra hoy, no contra una fecha fija del calendario."""
        return self.hoy + timedelta(days=delta)

    def obligacion(self, *, concepto="Arriendo agosto", monto=2400000,
                   vencimiento=None, tienda_id="corp") -> int:
        body = {
            "categoria_id": self.cat_arriendo.id,
            "concepto": concepto,
            "monto": monto,
            "fecha_devengo": str(self.dia(0)),
        }
        if vencimiento is not None:
            body["fecha_vencimiento"] = str(vencimiento)
        if tienda_id != "corp":
            body["tienda_id"] = tienda_id
        r = self.client.post("/api/v1/costos/obligaciones", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def pago(self, obligacion_id, monto, metodo="transferencia") -> int:
        r = self.client.post("/api/v1/costos/pagos", json={
            "obligacion_id": obligacion_id, "monto": monto,
            "fecha_pago": str(self.dia(0)), "metodo": metodo})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def anular_pago(self, pago_id):
        r = self.client.delete(f"/api/v1/costos/pagos/{pago_id}",
                               params={"motivo": "Cargado dos veces"})
        self.assertEqual(r.status_code, 200, r.text)

    def debito(self, monto, *, obligacion_id=None, tipo="salida",
               concepto="Arriendo agosto") -> int:
        """Una fila del libro, TECLEADA contra el extracto. El monto va siempre
        positivo: el signo lo pone el tipo."""
        r = self.client.post("/api/v1/banco/movimientos", json={
            "fecha": str(self.dia(0)), "cuenta_id": self.cuenta.id, "tipo": tipo,
            "monto": monto, "concepto": concepto, "obligacion_id": obligacion_id})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def borrar_debito(self, movimiento_id):
        r = self.client.delete(f"/api/v1/banco/movimientos/{movimiento_id}")
        self.assertEqual(r.status_code, 200, r.text)

    def pagar_desde_el_banco(self, obligacion_id, monto) -> tuple:
        """EL CAMINO NORMAL, en el orden exacto en que lo escribe el frontend.

        `FormPagoObligacion` crea el `Pago` PRIMERO (POST /costos/pagos) y el
        movimiento DESPUÉS (POST /banco/movimientos): dos registros para la
        misma plata, sin ningún enlace entre ellos. Reproducir ese orden acá es
        lo que hace que estos tests protejan el flujo real y no uno inventado.
        """
        pago_id = self.pago(obligacion_id, monto)
        mov_id = self.debito(monto, obligacion_id=obligacion_id)
        return pago_id, mov_id

    def agenda(self, **params) -> dict:
        r = self.client.get("/api/v1/costos/agenda", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def saldo_en_agenda(self, obligacion_id, **params):
        """Cuánta plata muestra la agenda para esa obligación, o None si ya no
        la muestra. None y 0 son cosas distintas: 0 nunca aparece, porque una
        obligación sin saldo deja de ser algo que pagar."""
        filas = [i for i in self.agenda(**params)["items"]
                 if i["tipo"] == "obligacion" and i["id"] == obligacion_id]
        self.assertLessEqual(len(filas), 1, "una obligación no puede salir dos veces")
        return filas[0]["monto"] if filas else None

    def declarar_banco(self, saldo, fecha=None):
        body = {"saldo": saldo}
        if fecha is not None:
            body["fecha"] = str(fecha)
        r = self.client.post("/api/v1/costos/saldo-banco", json=body)
        self.assertEqual(r.status_code, 200, r.text)

    def flujo(self, **params) -> dict:
        r = self.client.get("/api/v1/costos/flujo", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── 1. El bug que se arregla ─────────────────────────────────────────────

    def test_debito_tecleado_a_mano_saca_la_obligacion_de_la_agenda(self):
        """EL TEST QUE JUSTIFICA TODO EL CAMBIO.

        Arriendo de $2.400.000 sin ningún `Pago` cargado, pagado desde el banco
        y tecleado a mano en el libro. Antes: el saldo bajaba $2.400.000 Y la
        agenda seguía proyectando los $2.400.000 completos.
        """
        oblig = self.obligacion(monto=2400000, vencimiento=self.dia(3))
        self.assertEqual(self.saldo_en_agenda(oblig), 2400000)   # antes del débito

        self.debito(2400000, obligacion_id=oblig)

        self.assertIsNone(self.saldo_en_agenda(oblig))
        self.assertEqual(self.agenda()["totales"]["monto"], 0)
        self.assertEqual(self.agenda()["totales"]["n"], 0)

    def test_el_debito_sin_enlazar_no_descuenta_nada(self):
        """Sin `obligacion_id` el sistema no puede saber que es la misma plata.

        Es la razón por la que el enlace tiene que existir en la pantalla: un
        débito suelto baja el saldo del banco y deja la obligación entera en la
        agenda — exactamente el doble conteo, intacto. Que este test pase con
        los $2.400.000 completos NO es un defecto: es el límite honesto de lo
        que se puede deducir sin que nadie lo diga.
        """
        oblig = self.obligacion(monto=2400000, vencimiento=self.dia(3))
        self.debito(2400000, obligacion_id=None)
        self.assertEqual(self.saldo_en_agenda(oblig), 2400000)

    # ── 2. El camino que no se puede romper ──────────────────────────────────

    def test_el_camino_normal_no_descuenta_la_misma_plata_dos_veces(self):
        """Pago de $2.400.000 + movimiento de $2.400.000 enlazado.

        Es lo que escribe `FormPagoObligacion` en un solo gesto del dueño. La
        obligación queda en saldo CERO —no en −$2.400.000— y sale de la agenda
        una sola vez.
        """
        oblig = self.obligacion(monto=2400000, vencimiento=self.dia(3))
        self.pagar_desde_el_banco(oblig, 2400000)

        self.assertIsNone(self.saldo_en_agenda(oblig))
        self.assertEqual(self.agenda()["totales"]["monto"], 0)
        # El saldo derivado es 0 y no −2.400.000: con una suma serían $4.800.000
        # cubiertos de una obligación de $2.400.000.
        self.assertEqual(cubierto_de(2400000.0, 2400000.0), 2400000.0)
        self.assertEqual(2400000.0 - cubierto_de(2400000.0, 2400000.0), 0.0)

    def test_un_parcial_del_camino_normal_deja_el_resto_exacto_en_la_agenda(self):
        """ACÁ ES DONDE UNA SUMA GRITA.

        Del arriendo de $2.400.000 se abonó $1.000.000 por el camino normal
        (pago + su débito enlazado). Quedan $1.400.000. Sumando los dos
        registros quedarían $400.000: la agenda mostraría menos deuda de la que
        hay y el dueño creería que le sobra plata que no tiene.
        """
        oblig = self.obligacion(monto=2400000, vencimiento=self.dia(5))
        self.pagar_desde_el_banco(oblig, 1000000)

        self.assertEqual(self.saldo_en_agenda(oblig), 1400000)

    def test_dos_parciales_cada_uno_con_su_debito_cierran_la_obligacion(self):
        """$600.000 el día de la quincena y $400.000 después, cada uno por el
        camino normal. Σ pagos = $1.000.000 y Σ banco = $1.000.000: el máximo da
        $1.000.000 y la obligación se cierra. Sumando serían $2.000.000 sobre
        una obligación de $1.000.000."""
        oblig = self.obligacion(concepto="Energía julio", monto=1000000,
                                vencimiento=self.dia(4))
        self.pagar_desde_el_banco(oblig, 600000)
        self.assertEqual(self.saldo_en_agenda(oblig), 400000)   # a mitad de camino

        self.pagar_desde_el_banco(oblig, 400000)

        self.assertIsNone(self.saldo_en_agenda(oblig))
        self.assertEqual(self.agenda()["totales"]["monto"], 0)

    # ── 3. Parciales tecleados solo en el libro ──────────────────────────────

    def test_un_debito_parcial_sin_pago_deja_el_resto_en_la_agenda(self):
        """Obligación de $1.000.000 con un abono de $400.000 tecleado en el
        libro y sin `Pago`: quedan $600.000, no $1.000.000 ni cero."""
        oblig = self.obligacion(concepto="Internet agosto", monto=1000000,
                                vencimiento=self.dia(2))
        self.debito(400000, obligacion_id=oblig, concepto="Abono internet")

        self.assertEqual(self.saldo_en_agenda(oblig), 600000)

    def test_dos_debitos_sueltos_a_la_misma_obligacion_se_acumulan(self):
        """Dos filas del extracto contra el mismo arriendo suman entre ellas:
        `_salidas_banco_por_obligacion` agrupa por obligación, y sin eso el
        segundo abono no se vería."""
        oblig = self.obligacion(monto=2400000, vencimiento=self.dia(6))
        self.debito(1400000, obligacion_id=oblig, concepto="Arriendo (1 de 2)")
        self.debito(600000, obligacion_id=oblig, concepto="Arriendo (2 de 2)")

        self.assertEqual(self.saldo_en_agenda(oblig), 400000)

    # ── 4. Qué NO descuenta ──────────────────────────────────────────────────

    def test_una_entrada_enlazada_no_descuenta_nada(self):
        """Una ENTRADA enlazada es plata que VOLVIÓ (el proveedor devolvió el
        anticipo, el banco reversó el débito). Contarla como pago diría que se
        debe menos de lo que se debe — y encima por el lado tranquilizador."""
        oblig = self.obligacion(concepto="Anticipo proveedor", monto=2400000,
                                vencimiento=self.dia(3))
        self.debito(2400000, obligacion_id=oblig, tipo="entrada",
                    concepto="Devolución del anticipo")

        self.assertEqual(self.saldo_en_agenda(oblig), 2400000)

    def test_el_debito_enlazado_a_otra_obligacion_no_toca_esta(self):
        """El descuento va por `obligacion_id`, nunca por monto o por concepto:
        identificar un pago por su FORMA es el anti-patrón que este módulo ya
        pagó caro. Dos obligaciones del mismo monto lo dejan a la vista."""
        arriendo = self.obligacion(concepto="Arriendo Vida", monto=2400000,
                                   vencimiento=self.dia(3))
        nomina = self.obligacion(concepto="Nómina quincena", monto=2400000,
                                 vencimiento=self.dia(4))
        self.debito(2400000, obligacion_id=arriendo)

        self.assertIsNone(self.saldo_en_agenda(arriendo))
        self.assertEqual(self.saldo_en_agenda(nomina), 2400000)
        self.assertEqual(self.agenda()["totales"]["monto"], 2400000)

    def test_un_debito_de_mas_no_deja_saldo_negativo_ni_achica_el_total(self):
        """Un cero de más al teclear ($24.000.000 en vez de $2.400.000) tiene
        que quedar contenido en su propia obligación. Si el saldo negativo
        entrara al total, ese error borraría la deuda de las OTRAS filas y la
        agenda mostraría menos plata por pagar de la que hay."""
        arriendo = self.obligacion(concepto="Arriendo Vida", monto=2400000,
                                   vencimiento=self.dia(3))
        nomina = self.obligacion(concepto="Nómina quincena", monto=1000000,
                                 vencimiento=self.dia(4))
        self.debito(24000000, obligacion_id=arriendo)

        self.assertIsNone(self.saldo_en_agenda(arriendo))
        self.assertEqual(self.saldo_en_agenda(nomina), 1000000)
        self.assertEqual(self.agenda()["totales"]["monto"], 1000000)

    # ── 5. Pago anulado ──────────────────────────────────────────────────────

    def test_pago_anulado_no_cuenta_pero_el_debito_del_libro_sigue_contando(self):
        """EL RESULTADO QUE HAY, documentado como es y no como gustaría.

        Anular el `Pago` lo saca de la cuenta (`_pagos_vivos` filtra anulados),
        pero el movimiento del banco NO se entera: son dos registros
        independientes y nadie los enlaza. Con el débito todavía en el libro, la
        obligación sigue fuera de la agenda.

        Y es coherente, no un olvido: el libro es la verdad del banco y sigue
        diciendo que esa plata salió. Si el pago fue un error, el débito también
        lo fue —el saldo del banco está mal mientras siga ahí— y se borra, que
        es lo único que hace el libro (no tiene «anulado» a propósito). Recién
        ahí vuelve la obligación entera.
        """
        oblig = self.obligacion(monto=2400000, vencimiento=self.dia(3))
        pago_id, mov_id = self.pagar_desde_el_banco(oblig, 2400000)
        self.assertIsNone(self.saldo_en_agenda(oblig))

        self.anular_pago(pago_id)
        self.assertIsNone(self.saldo_en_agenda(oblig))   # el débito la sostiene

        self.borrar_debito(mov_id)
        self.assertEqual(self.saldo_en_agenda(oblig), 2400000)

    def test_borrar_el_debito_devuelve_a_la_agenda_lo_que_sostenia(self):
        """Sin ningún `Pago` de por medio: el descuento vive en el enlace, no en
        una columna copiada, así que borrar el movimiento lo revierte solo."""
        oblig = self.obligacion(monto=2400000, vencimiento=self.dia(3))
        mov_id = self.debito(2400000, obligacion_id=oblig)
        self.assertIsNone(self.saldo_en_agenda(oblig))

        self.borrar_debito(mov_id)
        self.assertEqual(self.saldo_en_agenda(oblig), 2400000)

    # ── 6. El caso mixto: prudente a propósito ───────────────────────────────

    def test_el_caso_mixto_muestra_mas_deuda_de_la_real_y_es_deliberado(self):
        """LA DECISIÓN, FIJADA PARA QUE NO PAREZCA UN DESCUIDO.

        Obligación de $1.000.000: pagó $600.000 en EFECTIVO (queda un `Pago` y
        ningún movimiento, porque esa plata nunca tocó el banco) y $400.000
        desde el banco, tecleados aparte y sin `Pago`. La deuda real es CERO.

        `max(600.000, 400.000)` da $600.000 y la agenda muestra $400.000 de
        deuda que ya no existe. Muestra de MÁS, que es la dirección prudente, y
        es exactamente lo que la pantalla mostraba antes de este cambio: no es
        una regresión. Resolverlo de verdad pide un enlace explícito
        `Pago.movimiento_banco_id`; deducirlo por montos que coinciden es el
        anti-patrón que este módulo ya pagó caro.
        """
        oblig = self.obligacion(concepto="Aseo agosto", monto=1000000,
                                vencimiento=self.dia(3))
        self.pago(oblig, 600000, metodo="efectivo")
        self.debito(400000, obligacion_id=oblig, concepto="Aseo (saldo)")

        self.assertEqual(self.saldo_en_agenda(oblig), 400000)
        self.assertEqual(cubierto_de(600000.0, 400000.0), 600000.0)

    # ── 7. La obligación sin fecha también se descuenta ───────────────────────

    def test_la_obligacion_sin_vencimiento_tambien_deja_de_pedir_plata(self):
        """`sin_fecha` es la lista de lo que falta fechar, no una lista aparte
        con sus propias reglas: el descuento se aplica ANTES de partir en
        agendadas y sin fecha. Sin esto, la obligación ya pagada seguiría
        pidiendo una fecha de vencimiento que ya no tiene sentido poner."""
        oblig = self.obligacion(concepto="Mantenimiento máquina", monto=800000,
                                vencimiento=None)
        data = self.agenda()
        self.assertEqual([i["id"] for i in data["sin_fecha"]], [oblig])
        self.assertEqual(data["totales"]["sin_fecha"], 800000)

        self.debito(800000, obligacion_id=oblig, concepto="Mantenimiento")

        data = self.agenda()
        self.assertEqual(data["sin_fecha"], [])
        self.assertEqual(data["totales"]["sin_fecha"], 0)
        self.assertEqual(data["totales"]["n_sin_fecha"], 0)

    # ── 8. La proyección: el número que el dueño mira ────────────────────────

    def test_el_punto_de_quiebre_se_corre_cuando_deja_de_proyectarse(self):
        """LO QUE SE VE EN /plata, que es donde esto se decide.

        Banco declarado $4.400.000; el arriendo de $2.400.000 ya salió y está
        tecleado, así que quedan $2.000.000 reales. La nómina de $2.500.000 vence
        el día 10 y esa sí no está pagada.

        Con el doble conteo, el arriendo se restaba OTRA VEZ el día 3 y la
        pantalla anunciaba el quiebre para ese día: siete días antes de lo real,
        sobre una plata que ya había salido. Ahora el día 3 no tiene salidas y
        el quiebre queda donde de verdad está.
        """
        self.declarar_banco(4400000, fecha=self.dia(-1))
        arriendo = self.obligacion(concepto="Arriendo agosto", monto=2400000,
                                   vencimiento=self.dia(3))
        self.obligacion(concepto="Nómina primera quincena", monto=2500000,
                        vencimiento=self.dia(10))
        self.debito(2400000, obligacion_id=arriendo)

        data = self.flujo()
        self.assertEqual(data["caja_hoy"]["saldo_banco"], 2000000)
        self.assertEqual(data["caja_hoy"]["total"], 2000000)

        por_fecha = {p["fecha"]: p for p in data["serie"]}
        self.assertEqual(por_fecha[str(self.dia(3))]["salidas"], 0)
        self.assertEqual(por_fecha[str(self.dia(10))]["salidas"], 2500000)
        self.assertEqual(data["punto_de_quiebre"], str(self.dia(10)))
        self.assertEqual(data["dias_hasta_quiebre"], 10)
        # El saldo del día del quiebre es la resta que el dueño puede rehacer a
        # mano: 2.000.000 − 2.500.000.
        self.assertEqual(por_fecha[str(self.dia(10))]["saldo"], -500000)

    def test_sin_el_enlace_la_proyeccion_adelanta_el_quiebre(self):
        """El mismo escenario con el débito SIN enlazar, que es lo que pasa hoy
        cuando el dueño teclea el libro y no dice a qué obligación corresponde.
        Está acá para medir el bug, no para bendecirlo: es la línea de base
        contra la cual el test de arriba significa algo."""
        self.declarar_banco(4400000, fecha=self.dia(-1))
        self.obligacion(concepto="Arriendo agosto", monto=2400000,
                        vencimiento=self.dia(3))
        self.obligacion(concepto="Nómina primera quincena", monto=2500000,
                        vencimiento=self.dia(10))
        self.debito(2400000, obligacion_id=None)

        data = self.flujo()
        self.assertEqual(data["punto_de_quiebre"], str(self.dia(3)))
        self.assertEqual(data["dias_hasta_quiebre"], 3)


if __name__ == "__main__":
    unittest.main()
