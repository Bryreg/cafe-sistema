"""Módulo Costos — Fase 4: flujo de caja proyectado.

El único número que ningún reporte del sistema puede producir hoy: EL DÍA EN QUE
SE ACABA LA PLATA. Todo lo demás (ventas, P&L, agenda) mira para atrás o mira una
sola dimensión; esto cruza lo que hay con lo que entra y lo que sale.

    saldo_proyectado(D) = caja_hoy + Σ entradas(d) − Σ salidas(d),  d en (hoy, D]

Reglas que prueban estos tests, y por qué cada una importa:

- la venta esperada es la MEDIANA por día de la semana sobre 8 semanas, no el
  promedio: un solo día atípico (una venta corporativa, un festivo) no puede
  mover la proyección de todas las semanas siguientes;
- las consignaciones NO son entrada: mueven plata del cajón al banco. Sumarlas
  contaría la misma plata dos veces contra caja_hoy;
- los MovimientoCaja egreso YA registrados no se restan otra vez: ya están
  descontados dentro del efectivo esperado de la registradora;
- lo VENCIDO cae ENTERO en hoy+1, no se reparte ni se ignora: se debe AHORA, y
  sin esta regla la mora desaparecería silenciosamente de la proyección;
- el saldo del banco ARRANCA en un input del dueño (el sistema registra
  consignaciones, nunca un saldo bancario) y de ahí en adelante lo mueve el
  LIBRO: la proyección lee `banco.saldo_al_cierre(hoy)`, no el ancla cruda, así
  que una salida ya tecleada baja las dos pantallas y no solo una;
- si el ancla está vieja, la respuesta lo dice en vez de mentir: lo que envejece
  es la conciliación contra el extracto, y los movimientos posteriores no la
  reemplazan;
- el saldo del banco se valida EN EL HANDLER, no con restricciones de pydantic:
  un `inf` en un 422 de pydantic arrastra el valor ofensivo al cuerpo del error y
  revienta al serializarlo a JSON.
"""
import json
import math
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base, get_db
from app.models.models import (CajaTurno, Configuracion, Consignacion,
                               CostoCategoria, CuentaBancaria, EntregaTurno,
                               EstadoConsignacionEnum, EstadoTurnoEnum,
                               FacturaCompra, MovimientoBanco, MovimientoCaja,
                               RolEnum, Ticket, Tienda, TipoPagoEnum, Usuario)
from app.routers import costos as costos_router


class CostosFlujoTest(unittest.TestCase):
    """sqlite temporal + router real de costos (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda_1 = Tienda(nombre="Vida", direccion="Sede Vida")
        self.tienda_2 = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.tienda_1, self.tienda_2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda_1.id, activo=True)
        self.barista = Usuario(nombre="Barista Uno", email="barista1@test.local",
                               password_hash="h", rol=RolEnum.barista,
                               tienda_id=self.tienda_1.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                           grupo="fijo", orden=0)
        self.db.add(self.cat_arriendo)
        self.db.commit()

        self.hoy = hoy_col()

        app = FastAPI(title="Test costos flujo")
        app.include_router(costos_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        self.app = app
        self.client = TestClient(app)
        self.set_current_user(self.admin)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def set_current_user(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def dia(self, delta: int) -> date:
        """Día Colombia relativo a hoy — la proyección se mide contra hoy, no
        contra una fecha fija del calendario."""
        return self.hoy + timedelta(days=delta)

    def mediodia(self, d: date) -> datetime:
        """Instante UTC del mediodía Colombia de `d`: cae sin ambigüedad dentro
        del día de negocio `d` (dia_col lo devuelve tal cual)."""
        return inicio_dia_col_utc(d) + timedelta(hours=12)

    def turno(self, *, tienda=None, abierto=False, base=0.0, efectivo_ventas=0.0) -> CajaTurno:
        t = CajaTurno(
            tienda_id=(tienda or self.tienda_1).id,
            usuario_apertura_id=self.admin.id,
            base_real=base,
            total_efectivo=efectivo_ventas,
            estado=EstadoTurnoEnum.abierto if abierto else EstadoTurnoEnum.cerrado,
        )
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def ticket(self, turno: CajaTurno, d: date, total: float, estado="completado"):
        self.db.add(Ticket(tienda_id=turno.tienda_id, caja_turno_id=turno.id,
                           usuario_id=self.admin.id, fecha=self.mediodia(d),
                           total=total, estado=estado, metodo_pago="efectivo"))
        self.db.commit()

    def movimiento(self, turno: CajaTurno, tipo: str, valor: float, concepto="Arriendo local"):
        mov = MovimientoCaja(caja_turno_id=turno.id, tipo=tipo, concepto=concepto,
                             valor=valor, usuario_id=self.admin.id,
                             fecha=self.mediodia(self.hoy))
        self.db.add(mov)
        self.db.commit()
        self.db.refresh(mov)
        return mov

    def factura(self, *, proveedor="Lácteos S.A.", total=100000, pagado=0,
                recibido=None, vencimiento=None, plazo=None, programada=None,
                tienda=None) -> FacturaCompra:
        f = FacturaCompra(
            tienda_id=(tienda or self.tienda_1).id,
            proveedor=proveedor,
            valor_total=total,
            valor_pagado=pagado,
            tipo_pago=TipoPagoEnum.credito,
            usuario_id=self.admin.id,
            fecha_recibido=inicio_dia_col_utc(recibido) if recibido else None,
            fecha_vencimiento=inicio_dia_col_utc(vencimiento) if vencimiento else None,
            plazo_dias=plazo,
            fecha_programada=inicio_dia_col_utc(programada) if programada else None,
        )
        self.db.add(f)
        self.db.commit()
        self.db.refresh(f)
        return f

    def obligacion(self, *, concepto="Arriendo agosto", monto=3000000,
                   devengo=None, vencimiento=None, tienda_id="corp") -> int:
        body = {
            "categoria_id": self.cat_arriendo.id,
            "concepto": concepto,
            "monto": monto,
            "fecha_devengo": str(devengo or self.dia(0)),
        }
        if vencimiento is not None:
            body["fecha_vencimiento"] = str(vencimiento)
        if tienda_id != "corp":
            body["tienda_id"] = tienda_id
        r = self.client.post("/api/v1/costos/obligaciones", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def pagar_obligacion(self, obligacion_id, monto) -> int:
        r = self.client.post("/api/v1/costos/pagos", json={
            "obligacion_id": obligacion_id, "monto": monto,
            "fecha_pago": str(self.dia(0)), "metodo": "transferencia"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def flujo(self, **params) -> dict:
        r = self.client.get("/api/v1/costos/flujo", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def por_fecha(self, data: dict) -> dict:
        return {p["fecha"]: p for p in data["serie"]}

    def declarar_banco(self, saldo, fecha=None):
        """El cuerpo se serializa a mano con `json.dumps` (allow_nan por defecto)
        porque httpx se niega a mandar inf/NaN. Sin esto el caso más peligroso
        —el valor que revienta al serializar— nunca llegaría al servidor, que es
        justamente lo que hay que probar. El `json.loads` de Starlette sí acepta
        los literales Infinity/NaN, igual que un cliente real que los mande."""
        body = {"saldo": saldo}
        if fecha is not None:
            body["fecha"] = str(fecha)
        return self.client.post("/api/v1/costos/saldo-banco",
                                content=json.dumps(body),
                                headers={"content-type": "application/json"})

    def cuenta_banco(self) -> CuentaBancaria:
        """La cuenta del libro. Se crea acá y no con `banco.sembrar_cuentas` para
        que el test no se ate al catálogo real de MEDIUM CAFÉ (Occidente/Bold):
        lo que se está probando es la cadena del saldo, no el catálogo."""
        cuenta = self.db.query(CuentaBancaria).first()
        if cuenta is None:
            cuenta = CuentaBancaria(nombre="Occidente", orden=1)
            self.db.add(cuenta)
            self.db.commit()
            self.db.refresh(cuenta)
        return cuenta

    def mov_banco(self, tipo: str, monto: float, fecha=None) -> MovimientoBanco:
        """Un movimiento TECLEADO del libro (services/banco.py). El monto va
        siempre positivo: el signo lo pone el tipo."""
        mov = MovimientoBanco(fecha=fecha or self.hoy, cuenta_id=self.cuenta_banco().id,
                              tipo=tipo, monto=monto, concepto=f"Movimiento {tipo}",
                              usuario_id=self.admin.id)
        self.db.add(mov)
        self.db.commit()
        self.db.refresh(mov)
        return mov

    def ultimos_dias_de_semana(self, weekday: int) -> list:
        """Los 8 días `weekday` que caen dentro de la ventana de historia
        [hoy-56, hoy-1] — cualquier ventana de 56 días tiene exactamente 8."""
        dias = [self.dia(-n) for n in range(1, 57) if self.dia(-n).weekday() == weekday]
        self.assertEqual(len(dias), 8, "la ventana de 8 semanas debe tener 8 lunes")
        return dias

    # ── 1. Mediana, no promedio ──────────────────────────────────────────────

    def test_venta_esperada_usa_mediana_por_dia_de_semana_no_promedio(self):
        # 8 lunes: siete de 100.000 y uno atípico de 1.000.000 (una venta
        # corporativa, un evento). El promedio daría 212.500 y proyectaría ese
        # exceso en TODOS los lunes siguientes; la mediana lo ignora.
        turno = self.turno(abierto=False)
        lunes = self.ultimos_dias_de_semana(0)
        for d in lunes[1:]:
            self.ticket(turno, d, 100000)
        self.ticket(turno, lunes[0], 1000000)

        siguiente_lunes = next(self.dia(n) for n in range(1, 8) if self.dia(n).weekday() == 0)
        punto = self.por_fecha(self.flujo())[str(siguiente_lunes)]
        self.assertEqual(punto["entradas"], 100000)

    def test_venta_esperada_es_por_dia_de_la_semana(self):
        # El martes no hereda la venta del lunes: cada día de la semana tiene su
        # propia mediana (un lunes no se parece a un sábado).
        turno = self.turno(abierto=False)
        for d in self.ultimos_dias_de_semana(0):
            self.ticket(turno, d, 100000)
        for d in self.ultimos_dias_de_semana(1):
            self.ticket(turno, d, 300000)

        serie = self.por_fecha(self.flujo())
        prox_lunes = next(self.dia(n) for n in range(1, 8) if self.dia(n).weekday() == 0)
        prox_martes = next(self.dia(n) for n in range(1, 8) if self.dia(n).weekday() == 1)
        self.assertEqual(serie[str(prox_lunes)]["entradas"], 100000)
        self.assertEqual(serie[str(prox_martes)]["entradas"], 300000)

    def test_ticket_anulado_no_cuenta_como_venta_esperada(self):
        turno = self.turno(abierto=False)
        for d in self.ultimos_dias_de_semana(0):
            self.ticket(turno, d, 500000, estado="anulado")
        prox_lunes = next(self.dia(n) for n in range(1, 8) if self.dia(n).weekday() == 0)
        self.assertEqual(self.por_fecha(self.flujo())[str(prox_lunes)]["entradas"], 0)

    # ── 2. Las consignaciones no son entrada ─────────────────────────────────

    def test_consignaciones_no_cuentan_como_entrada(self):
        # Una consignación mueve plata del cajón al banco: es una transferencia
        # INTERNA. Sumarla como entrada contaría la misma plata dos veces contra
        # el efectivo que ya está en caja_hoy.
        turno = self.turno(abierto=True, base=200000)
        self.db.add(Consignacion(tienda_id=self.tienda_1.id, caja_turno_id=turno.id,
                                 valor=500000, usuario_id=self.admin.id,
                                 fecha=self.mediodia(self.hoy)))
        self.db.commit()

        data = self.flujo()
        self.assertEqual(sum(p["entradas"] for p in data["serie"]), 0)
        # Y el saldo proyectado sigue siendo el efectivo de la registradora.
        self.assertEqual(data["serie"][0]["saldo"], 200000)

    # ── 3. Los egresos ya registrados no se restan otra vez ──────────────────

    def test_egresos_de_caja_ya_registrados_no_se_restan_otra_vez(self):
        # El egreso ya salió del cajón: está descontado DENTRO del efectivo
        # esperado (base + ventas + ingresos − egresos). Restarlo también como
        # salida futura sería contar el mismo gasto dos veces.
        turno = self.turno(abierto=True, base=100000)
        self.movimiento(turno, "egreso", 30000)

        data = self.flujo()
        self.assertEqual(data["caja_hoy"]["efectivo_registradora"], 70000)
        self.assertEqual(sum(p["salidas"] for p in data["serie"]), 0)
        self.assertEqual(data["serie"][0]["saldo"], 70000)   # 70.000, no 40.000

    def test_efectivo_de_la_registradora_replica_la_formula_del_cuadre(self):
        # base_real + total_efectivo + ingresos − egresos, igual que caja.py.
        turno = self.turno(abierto=True, base=100000, efectivo_ventas=250000)
        self.movimiento(turno, "ingreso", 20000, concepto="Préstamo socio")
        self.movimiento(turno, "egreso", 30000)
        self.assertEqual(self.flujo()["caja_hoy"]["efectivo_registradora"], 340000)

    def test_sin_turno_abierto_se_usa_el_efectivo_del_ultimo_cuadre(self):
        turno = self.turno(abierto=False, base=999999)
        self.db.add_all([
            EntregaTurno(turno_id=turno.id, tienda_id=self.tienda_1.id,
                         usuario_id=self.admin.id, fecha_hora=self.mediodia(self.dia(-3)),
                         efectivo_esperado=100000, efectivo_real=100000,
                         ventas_efectivo_siigo=0, ventas_tarjeta_bold=0,
                         diferencia_efectivo=0, diferencia_tarjeta=0),
            EntregaTurno(turno_id=turno.id, tienda_id=self.tienda_1.id,
                         usuario_id=self.admin.id, fecha_hora=self.mediodia(self.dia(-1)),
                         efectivo_esperado=80000, efectivo_real=75000,
                         ventas_efectivo_siigo=0, ventas_tarjeta_bold=0,
                         diferencia_efectivo=-5000, diferencia_tarjeta=0),
        ])
        self.db.commit()
        # El ÚLTIMO cuadre y su efectivo REAL (lo que de verdad había), no el
        # esperado ni la base del turno cerrado.
        self.assertEqual(self.flujo()["caja_hoy"]["efectivo_registradora"], 75000)

    # ── 4. Lo vencido cae entero en hoy+1 ────────────────────────────────────

    def test_todo_lo_vencido_cae_entero_en_manana(self):
        # Se debe AHORA. Repartirlo en el horizonte o dejarlo fuera haría
        # desaparecer la mora de la proyección justo cuando más importa.
        self.factura(proveedor="Atrasada", total=60000, vencimiento=self.dia(-5))
        self.obligacion(concepto="Energía vencida", monto=40000, vencimiento=self.dia(-3))
        self.obligacion(concepto="Arriendo", monto=10000, vencimiento=self.dia(10))

        serie = self.por_fecha(self.flujo())
        self.assertEqual(serie[str(self.dia(1))]["salidas"], 100000)
        self.assertEqual(serie[str(self.dia(10))]["salidas"], 10000)
        self.assertEqual(serie[str(self.dia(2))]["salidas"], 0)

    def test_una_salida_futura_cae_en_su_propio_dia(self):
        self.obligacion(concepto="Nómina", monto=500000, vencimiento=self.dia(7))
        serie = self.por_fecha(self.flujo())
        self.assertEqual(serie[str(self.dia(7))]["salidas"], 500000)
        self.assertEqual(serie[str(self.dia(6))]["salidas"], 0)

    # ── 5. Saldo del banco declarado ─────────────────────────────────────────

    def test_saldo_banco_viejo_viene_marcado_desactualizado(self):
        # El sistema NO puede derivar el saldo bancario: registra consignaciones,
        # nunca un saldo. Si el dato del dueño está viejo, se dice — no se miente.
        r = self.declarar_banco(500000, fecha=self.dia(-8))
        self.assertEqual(r.status_code, 200, r.text)

        caja = self.flujo()["caja_hoy"]
        self.assertTrue(caja["saldo_banco_desactualizado"])
        self.assertEqual(caja["saldo_banco"], 500000)
        self.assertEqual(caja["saldo_banco_fecha"], str(self.dia(-8)))
        # Desactualizado no significa ignorado: sigue sumando al total.
        self.assertEqual(caja["total"], 500000)

    def test_saldo_banco_reciente_no_esta_desactualizado(self):
        self.assertEqual(self.declarar_banco(500000, fecha=self.dia(-2)).status_code, 200)
        self.assertFalse(self.flujo()["caja_hoy"]["saldo_banco_desactualizado"])

    def test_sin_saldo_banco_declarado_la_respuesta_lo_marca(self):
        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["saldo_banco"], 0)
        self.assertIsNone(caja["saldo_banco_fecha"])
        self.assertTrue(caja["saldo_banco_desactualizado"])

    def test_saldo_banco_se_persiste_en_configuracion(self):
        self.assertEqual(self.declarar_banco(1250000).status_code, 200)
        filas = {c.clave: c.valor for c in self.db.query(Configuracion).all()}
        self.assertEqual(float(filas["saldo_banco"]), 1250000)
        self.assertEqual(filas["saldo_banco_fecha"], str(self.hoy))

    # ── 6. Punto de quiebre ──────────────────────────────────────────────────

    def test_punto_de_quiebre_es_null_cuando_la_serie_nunca_cruza_cero(self):
        self.turno(abierto=True, base=100000)
        data = self.flujo()
        self.assertIsNone(data["punto_de_quiebre"])
        self.assertTrue(all(p["saldo"] >= 0 for p in data["serie"]))

    def test_punto_de_quiebre_es_el_dia_exacto_en_que_cruza(self):
        # 100.000 en caja; el día 3 hay que pagar 150.000 y no entra nada.
        self.turno(abierto=True, base=100000)
        self.obligacion(concepto="Arriendo", monto=150000, vencimiento=self.dia(3))

        data = self.flujo()
        self.assertEqual(data["punto_de_quiebre"], str(self.dia(3)))
        serie = self.por_fecha(data)
        self.assertEqual(serie[str(self.dia(2))]["saldo"], 100000)
        self.assertEqual(serie[str(self.dia(3))]["saldo"], -50000)

    def test_el_horizonte_es_parametrizable_y_por_defecto_30_dias(self):
        self.assertEqual(len(self.flujo()["serie"]), 30)
        data = self.flujo(dias=7)
        self.assertEqual(len(data["serie"]), 7)
        self.assertEqual(data["serie"][0]["fecha"], str(self.dia(1)))
        self.assertEqual(data["serie"][-1]["fecha"], str(self.dia(7)))

    # ── 7. Sin fecha no entra ────────────────────────────────────────────────

    def test_factura_sin_ninguna_de_las_tres_fechas_no_entra(self):
        # No se inventa un vencimiento: no hay tabla maestra de proveedores de
        # donde derivar un plazo. Meterla en hoy+1 "por las dudas" inventaría una
        # deuda inmediata que nadie exigió.
        self.turno(abierto=True, base=100000)
        self.factura(proveedor="Histórica", total=900000, recibido=self.dia(-40))
        self.factura(proveedor="Sin recibido", total=900000, plazo=30)

        data = self.flujo()
        self.assertEqual(sum(p["salidas"] for p in data["serie"]), 0)
        self.assertIsNone(data["punto_de_quiebre"])

    def test_obligacion_sin_fecha_vencimiento_no_entra(self):
        self.obligacion(concepto="Nómina sin fecha", monto=800000, vencimiento=None)
        self.assertEqual(sum(p["salidas"] for p in self.flujo()["serie"]), 0)

    # ── 8. Anuladas y pagos anulados ─────────────────────────────────────────

    def test_obligacion_anulada_no_entra_y_pago_anulado_devuelve_el_saldo(self):
        anulada = self.obligacion(concepto="Anulada", monto=70000, vencimiento=self.dia(4))
        self.assertEqual(
            self.client.delete(f"/api/v1/costos/obligaciones/{anulada}").status_code, 200)
        self.assertEqual(sum(p["salidas"] for p in self.flujo()["serie"]), 0)

        # Pagada al 100% tampoco entra: no hay saldo que deber.
        pagada = self.obligacion(concepto="Pagada", monto=50000, vencimiento=self.dia(4))
        pago_id = self.pagar_obligacion(pagada, 50000)
        self.assertEqual(sum(p["salidas"] for p in self.flujo()["serie"]), 0)

        # Al anular el pago, el saldo vuelve y la salida reaparece: el estado se
        # DERIVA de los pagos vivos, no hay contador que corregir.
        self.assertEqual(self.client.delete(f"/api/v1/costos/pagos/{pago_id}").status_code, 200)
        serie = self.por_fecha(self.flujo())
        self.assertEqual(serie[str(self.dia(4))]["salidas"], 50000)

    def test_factura_parcialmente_pagada_proyecta_solo_el_saldo(self):
        self.factura(proveedor="Parcial", total=100000, pagado=40000, vencimiento=self.dia(5))
        self.assertEqual(self.por_fecha(self.flujo())[str(self.dia(5))]["salidas"], 60000)

    # ── 9. Validación del saldo del banco (en el handler, no en pydantic) ────

    def test_saldo_banco_invalido_responde_400_con_cuerpo_serializable(self):
        # GOTCHA del repo: con Field(ge=0)/allow_inf_nan el 422 de pydantic
        # arrastra el valor ofensivo al cuerpo del error, y un `inf` NO es
        # serializable a JSON: la propia respuesta de error revienta. Por eso la
        # validación vive en el handler y responde 400 con un string.
        for valor in (-1, float("inf"), float("-inf"), float("nan")):
            with self.subTest(valor=valor):
                r = self.declarar_banco(valor)
                self.assertEqual(r.status_code, 400, r.text)
                cuerpo = r.json()                      # no debe reventar
                self.assertIsInstance(cuerpo["detail"], str)

    def test_saldo_banco_con_techo(self):
        r = self.declarar_banco(1e13)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIsInstance(r.json()["detail"], str)

    def test_saldo_banco_invalido_no_pisa_el_valor_guardado(self):
        self.assertEqual(self.declarar_banco(300000).status_code, 200)
        self.assertEqual(self.declarar_banco(float("nan")).status_code, 400)
        self.assertEqual(self.flujo()["caja_hoy"]["saldo_banco"], 300000)

    def test_saldo_banco_guardado_corrupto_no_rompe_la_lectura(self):
        # Defensa en profundidad: si una fila quedó con basura de otra versión,
        # el flujo responde 0 en vez de tumbar la pantalla entera del dueño.
        self.db.add(Configuracion(clave="saldo_banco", valor="inf"))
        self.db.add(Configuracion(clave="saldo_banco_fecha", valor="no-es-fecha"))
        self.db.commit()
        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["saldo_banco"], 0)
        self.assertIsNone(caja["saldo_banco_fecha"])
        self.assertTrue(math.isfinite(caja["total"]))

    def test_saldo_banco_con_fecha_futura_es_400(self):
        r = self.declarar_banco(100000, fecha=self.dia(3))
        self.assertEqual(r.status_code, 400, r.text)

    # ── 10. Rol ──────────────────────────────────────────────────────────────

    def test_barista_403_en_flujo_y_en_saldo_banco(self):
        self.set_current_user(self.barista)
        self.assertEqual(self.client.get("/api/v1/costos/flujo").status_code, 403)
        self.assertEqual(self.declarar_banco(100000).status_code, 403)

    # ── Filtro de sede ───────────────────────────────────────────────────────

    def test_filtro_por_sede_aisla_el_efectivo_y_las_salidas(self):
        self.turno(tienda=self.tienda_1, abierto=True, base=100000)
        self.turno(tienda=self.tienda_2, abierto=True, base=700000)
        self.factura(proveedor="Palmetto", total=50000, vencimiento=self.dia(2),
                     tienda=self.tienda_2)

        solo_vida = self.flujo(tienda_id=self.tienda_1.id)
        self.assertEqual(solo_vida["caja_hoy"]["efectivo_registradora"], 100000)
        self.assertEqual(sum(p["salidas"] for p in solo_vida["serie"]), 0)

        todas = self.flujo()
        self.assertEqual(todas["caja_hoy"]["efectivo_registradora"], 800000)
        self.assertEqual(sum(p["salidas"] for p in todas["serie"]), 50000)

    def test_filtro_por_sede_no_da_all_clear_cuando_el_negocio_quiebra(self):
        """El banco es de la EMPRESA: filtrando por sede no entra al total.

        La agenda con `tienda_id` EXCLUYE las obligaciones corporativas (arriendo,
        nómina: tienda_id NULL). Si además se sumaba el saldo bancario COMPLETO, la
        sede sumaba toda la plata del negocio y restaba solo sus propias salidas:
        una serie sistemáticamente optimista, donde un quiebre real del negocio se
        veía verde apenas se filtraba por sede.
        """
        self.turno(tienda=self.tienda_1, abierto=True, base=50000)
        self.assertEqual(self.declarar_banco(100000, fecha=self.dia(-1)).status_code, 200)
        # Corporativa (sin tienda_id): la agenda de la sede NUNCA la ve.
        self.obligacion(concepto="Arriendo corporativo", monto=300000,
                        vencimiento=self.dia(3))

        # El negocio SÍ quiebra: 50.000 + 100.000 no alcanzan para 300.000.
        self.assertEqual(self.flujo()["punto_de_quiebre"], str(self.dia(3)))

        sede = self.flujo(tienda_id=self.tienda_1.id)
        # La sede arranca solo con SU efectivo: la cuenta bancaria no es suya.
        self.assertFalse(sede["caja_hoy"]["saldo_banco_incluido"])
        self.assertEqual(sede["caja_hoy"]["total"], 50000)
        self.assertEqual(sede["serie"][0]["saldo"], 50000)
        # Y no puede presentarse como all-clear: dice qué plata quedó fuera.
        self.assertTrue(sede["advertencias"]["excluye_corporativas"])
        self.assertEqual(sede["advertencias"]["corporativas_fuera"], 300000)

    # ── 12. El conteo que manda es el del CIERRE ─────────────────────────────

    def test_sin_turno_abierto_manda_el_conteo_del_cierre_no_el_de_la_manana(self):
        """`cerrar_caja` NO deja EntregaTurno: guarda el conteo real del cierre en
        `caja_turnos.efectivo_final_real` (services/caja.py:518). El único
        EntregaTurno del día es el cuadre de LLEGADA, así que leer "el último
        cuadre de cualquier tipo" devolvía la base de la mañana. De noche, con la
        sede cerrada —justo cuando el dueño mira—, la caja de hoy se desplomaba a
        la base de apertura e inventaba un punto de quiebre con alerta roja.

        Se replica con los servicios reales (no con filas a mano) porque el bug
        vivía justamente en lo que esos servicios escriben y lo que no.
        """
        from app.services import caja as caja_svc
        from app.services import ventas as ventas_svc

        caja_svc.abrir_caja(self.db, self.tienda_1.id, 100000, "Base inicial",
                            self.admin.id, barista_ids=[self.barista.id],
                            tipo_turno="apertura")
        turno = self.db.query(CajaTurno).filter(
            CajaTurno.tienda_id == self.tienda_1.id,
            CajaTurno.estado == EstadoTurnoEnum.abierto).first()
        caja_svc.registrar_cuadre_llegada(self.db, turno.id, self.admin.id,
                                          100000, "apertura")
        # Los conteos de inventario son un gate ajeno al efectivo: se tildan para
        # poder vender y cerrar sin arrastrar todo el módulo de inventario acá.
        turno.tiene_conteo_apertura = True
        self.db.commit()
        ventas_svc.registrar_venta(self.db, self.tienda_1.id, 900000, 0, 0, 0,
                                   None, self.admin.id)
        turno.tiene_conteo_cierre = True
        self.db.commit()
        caja_svc.cerrar_caja(self.db, turno.id, 1000000, None, self.admin.id)

        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["efectivo_registradora"], 1000000)   # no 100.000
        self.assertEqual(caja["total"], 1000000)
        self.assertEqual(caja["por_tienda"][0]["origen"], "ultimo_cierre")

    # ── 13. La plata ya consignada no está en la registradora ────────────────

    def test_consignaciones_realizadas_no_siguen_contando_en_la_registradora(self):
        """El depósito ya salió del cajón y está dentro del `saldo_banco` que
        declara el dueño. Sin descontarlo, la misma plata se cuenta dos veces y el
        punto de quiebre se corre hacia el futuro — el sentido que tranquiliza."""
        turno = self.turno(abierto=True, base=0, efectivo_ventas=500000)
        self.db.add(Consignacion(tienda_id=self.tienda_1.id, caja_turno_id=turno.id,
                                 valor=300000, usuario_id=self.admin.id,
                                 estado=EstadoConsignacionEnum.realizada,
                                 fecha=self.mediodia(self.hoy)))
        self.db.commit()

        self.assertEqual(self.flujo()["caja_hoy"]["efectivo_registradora"], 200000)

    # ── 14. El verde no puede afirmar seguridad sin datos ────────────────────

    def test_la_respuesta_marca_que_le_falta_informacion(self):
        """Las entradas se derivan solas de cada ticket; las salidas existen SOLO
        si alguien las tecleó. Por eso la PRESENCIA de un punto de quiebre
        significa algo y su AUSENCIA no significa nada: la respuesta tiene que
        decir qué le falta para que la pantalla no venda tranquilidad."""
        data = self.flujo()
        self.assertIsNone(data["punto_de_quiebre"])          # "verde" sin datos
        self.assertTrue(data["advertencias"]["sin_salidas_cargadas"])
        self.assertTrue(data["advertencias"]["sin_historia_ventas"])
        self.assertTrue(data["advertencias"]["saldo_banco_desactualizado"])

        turno = self.turno(abierto=False)
        for d in self.ultimos_dias_de_semana(0):
            self.ticket(turno, d, 100000)
        self.obligacion(concepto="Arriendo", monto=10000, vencimiento=self.dia(10))
        self.assertEqual(self.declarar_banco(500000).status_code, 200)

        adv = self.flujo()["advertencias"]
        self.assertFalse(adv["sin_salidas_cargadas"])
        self.assertFalse(adv["sin_historia_ventas"])
        self.assertFalse(adv["saldo_banco_desactualizado"])

    # ── 15. La proyección arranca del LIBRO, no del ancla cruda ──────────────
    #
    # El ancla es el saldo que el dueño copió del extracto ESE DÍA, y el sistema
    # le pide actualizarlo cada 7 días. Entre una carga y la siguiente él sí
    # teclea los movimientos en el libro («La plata»), que está a UN TOQUE de
    # esta pantalla. Con el ancla cruda pasaba esto: cargaba una salida de
    # 3.000.000, el libro le decía que le quedaban 2.000.000, y el flujo seguía
    # proyectando desde 5.000.000 y calculaba el punto de quiebre con plata que
    # ya no estaba. El saldo del banco tiene UNA sola matemática y vive en
    # services/banco.py: acá se lee, no se recalcula.

    def test_una_salida_ya_tecleada_en_el_libro_baja_la_plata_de_la_proyeccion(self):
        self.assertEqual(self.declarar_banco(5000000, fecha=self.dia(-1)).status_code, 200)
        self.mov_banco("salida", 3000000)

        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["saldo_banco"], 2000000)      # no 5.000.000
        self.assertEqual(caja["total"], 2000000)
        # El número se puede explicar: de dónde sale y qué lo movió.
        self.assertEqual(caja["saldo_banco_origen"], "libro")
        self.assertEqual(caja["saldo_banco_declarado"], 5000000)
        self.assertEqual(caja["saldo_banco_movimientos"], -3000000)
        self.assertEqual(self.flujo()["serie"][0]["saldo"], 2000000)

    def test_una_entrada_ya_tecleada_en_el_libro_sube_la_plata_de_la_proyeccion(self):
        self.assertEqual(self.declarar_banco(5000000, fecha=self.dia(-1)).status_code, 200)
        self.mov_banco("entrada", 800000)
        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["saldo_banco"], 5800000)
        self.assertEqual(caja["saldo_banco_movimientos"], 800000)

    def test_el_punto_de_quiebre_se_calcula_con_la_plata_que_de_verdad_queda(self):
        """El caso del reporte, entero: sin esto el quiebre se corría hacia el
        futuro —el sentido que tranquiliza— con plata que ya salió."""
        self.assertEqual(self.declarar_banco(5000000, fecha=self.dia(-1)).status_code, 200)
        self.obligacion(concepto="Nómina", monto=4000000, vencimiento=self.dia(3))
        self.assertIsNone(self.flujo()["punto_de_quiebre"])   # 5M − 4M: alcanza

        self.mov_banco("salida", 3000000)                     # ya salió del banco
        data = self.flujo()
        self.assertEqual(data["punto_de_quiebre"], str(self.dia(3)))
        self.assertEqual(self.por_fecha(data)[str(self.dia(3))]["saldo"], -2000000)

    def test_los_movimientos_ANTERIORES_al_ancla_no_se_restan_otra_vez(self):
        """Un movimiento previo al extracto YA está adentro del saldo que el
        banco emitió. Volver a restarlo sería contar el mismo gasto dos veces —
        la misma familia de error que las consignaciones y los egresos de caja."""
        self.assertEqual(self.declarar_banco(5000000, fecha=self.dia(-1)).status_code, 200)
        self.mov_banco("salida", 1000000, fecha=self.dia(-5))
        self.assertEqual(self.flujo()["caja_hoy"]["saldo_banco"], 5000000)

    def test_sin_ancla_los_movimientos_sueltos_no_inventan_un_saldo(self):
        """Un neto de movimientos NO es un saldo: sin extracto no se sabe sobre
        cuánta plata se movieron. Se cae al ancla (0) y se marca desactualizado,
        que es el comportamiento honesto de siempre."""
        self.mov_banco("entrada", 900000)
        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["saldo_banco"], 0)
        self.assertEqual(caja["saldo_banco_origen"], "ancla")
        self.assertTrue(caja["saldo_banco_desactualizado"])

    def test_el_ancla_vieja_se_sigue_avisando_aunque_el_libro_este_al_dia(self):
        """Lo que envejece es la CONCILIACIÓN contra el extracto. Un libro lleno
        de movimientos sobre un ancla de hace un mes puede estar al día o puede
        tener un débito automático que nadie tecleó, y el sistema no sabe cuál de
        las dos: por eso la vigencia se mide contra la fecha del extracto."""
        self.assertEqual(self.declarar_banco(500000, fecha=self.dia(-8)).status_code, 200)
        self.mov_banco("entrada", 100000)
        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["saldo_banco"], 600000)
        self.assertTrue(caja["saldo_banco_desactualizado"])
        self.assertEqual(caja["saldo_banco_fecha"], str(self.dia(-8)))

    def test_la_consignacion_sigue_contando_una_sola_vez_con_el_libro(self):
        """La regla 1 del anti-doble-conteo, ahora con el libro en el medio: los
        300.000 consignados salen del cajón (la registradora los descuenta) y
        entran al banco cuando el dueño los teclea. Una vez, no dos."""
        turno = self.turno(abierto=True, base=0, efectivo_ventas=500000)
        self.db.add(Consignacion(tienda_id=self.tienda_1.id, caja_turno_id=turno.id,
                                 valor=300000, usuario_id=self.admin.id,
                                 estado=EstadoConsignacionEnum.realizada,
                                 fecha=self.mediodia(self.hoy)))
        self.db.commit()
        self.assertEqual(self.declarar_banco(1000000, fecha=self.dia(-1)).status_code, 200)
        self.mov_banco("entrada", 300000)      # el depósito, ya en el extracto

        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["efectivo_registradora"], 200000)
        self.assertEqual(caja["saldo_banco"], 1300000)
        self.assertEqual(caja["total"], 1500000)   # no 1.800.000

    def test_filtrando_por_sede_el_libro_del_banco_sigue_afuera(self):
        """La cuenta es de la EMPRESA. Que el saldo ahora venga del libro no la
        vuelve de la sede: sumarla completa contra solo una parte de las salidas
        es lo que convertía un quiebre real en un verde tranquilizador."""
        self.turno(tienda=self.tienda_1, abierto=True, base=50000)
        self.assertEqual(self.declarar_banco(1000000, fecha=self.dia(-1)).status_code, 200)
        self.mov_banco("entrada", 2000000)

        sede = self.flujo(tienda_id=self.tienda_1.id)["caja_hoy"]
        self.assertFalse(sede["saldo_banco_incluido"])
        self.assertEqual(sede["total"], 50000)

    def test_el_ancla_podrida_no_entra_a_la_proyeccion_por_la_puerta_del_libro(self):
        """Defensa en profundidad: `_leer_saldo_banco` sanea la fila de
        `configuracion` (inf/NaN/negativo/absurdo → 0) y el libro encadena sobre
        la CRUDA. Si las dos lecturas no coinciden, la fila está podrida y el
        saldo del libro estaría encadenado sobre basura: se cae al valor saneado
        en vez de propagar un `inf` al total del dueño."""
        self.db.add(Configuracion(clave="saldo_banco", valor="inf"))
        self.db.add(Configuracion(clave="saldo_banco_fecha", valor=str(self.hoy)))
        self.db.commit()
        self.mov_banco("entrada", 100000)

        caja = self.flujo()["caja_hoy"]
        self.assertEqual(caja["saldo_banco"], 0)
        self.assertEqual(caja["saldo_banco_origen"], "ancla")
        self.assertTrue(math.isfinite(caja["total"]))


if __name__ == "__main__":
    unittest.main()
