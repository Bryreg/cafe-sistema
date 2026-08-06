"""Contrato agenda <-> flujo que la grilla de Plata.Calendario espeja.

El calendario de Plata pinta DOS numeros por celda: lo que sale ese dia y el saldo
con el que quedas. Los dos tienen que salir de la misma cuenta, o la pantalla
miente: la primera version los calculaba por separado (la celda sumaba los items
que vencian ESE dia exacto, el saldo venia del flujo) y hoy+1 podia mostrar cero
pagos mientras su saldo caia por toda la mora acumulada. Una celda roja y sin nada
que abrir.

Lo que estos tests fijan, porque es lo que la UI ahora asume:

  - `serie[0]` es hoy+1 y ahi cae TODO lo que se debe hasta hoy: lo vencido
    (fecha < hoy) Y lo que vence hoy (fecha == hoy). El frontend arma su bloque
    "arrastre" con la misma condicion `fecha <= hoy`, no con el flag `vencida`
    —que es solo `fecha < hoy`— y con `vencida` dejaria lo de hoy afuera del
    desglose de una celda que si lo esta cobrando;
  - para cualquier dia del horizonte, `salidas` == la suma de los items de la
    agenda que caen ahi bajo esa misma regla. Es la invariante que permite que la
    UI use `salidas` como numero de la celda y la agenda como su explicacion;
  - lo que no tiene fecha no entra por ningun lado: ni en la celda ni en el saldo.

Los tests son de LECTURA (no tocan ninguna formula): reusan el router real de
costos igual que el resto de la suite.
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
from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base, get_db
from app.models.models import (CostoCategoria, FacturaCompra, RolEnum, Tienda,
                               TipoPagoEnum, Usuario)
from app.routers import costos as costos_router


class PlataCalendarioContratoTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda = Tienda(nombre="Vida", direccion="Sede Vida")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.cat = CostoCategoria(clave="arriendo", nombre="Arriendo", grupo="fijo", orden=0)
        self.db.add(self.cat)
        self.db.commit()

        self.hoy = hoy_col()

        app = FastAPI(title="Test plata calendario")
        app.include_router(costos_router.router, prefix="/api/v1")
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
        return self.hoy + timedelta(days=delta)

    def obligacion(self, *, concepto, monto, vencimiento=None):
        body = {"categoria_id": self.cat.id, "concepto": concepto, "monto": monto,
                "fecha_devengo": str(self.dia(0))}
        if vencimiento is not None:
            body["fecha_vencimiento"] = str(vencimiento)
        r = self.client.post("/api/v1/costos/obligaciones", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def factura(self, *, proveedor, total, vencimiento):
        f = FacturaCompra(tienda_id=self.tienda.id, proveedor=proveedor,
                          valor_total=total, valor_pagado=0,
                          tipo_pago=TipoPagoEnum.credito, usuario_id=self.admin.id,
                          fecha_vencimiento=inicio_dia_col_utc(vencimiento))
        self.db.add(f)
        self.db.commit()

    def agenda(self) -> dict:
        r = self.client.get("/api/v1/costos/agenda")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def flujo(self, dias=30) -> dict:
        r = self.client.get("/api/v1/costos/flujo", params={"dias": dias})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def salidas_esperadas(self, agenda: dict, dias: int) -> dict:
        """La regla del calendario, escrita como la escribe el frontend: todo lo
        que se debe hasta hoy cae en hoy+1; el resto, en su propio dia."""
        hoy, manana = str(self.dia(0)), str(self.dia(1))
        por_dia: dict = {}
        for item in agenda["items"]:
            fecha = manana if item["fecha"] <= hoy else item["fecha"]
            if fecha > str(self.dia(dias)):
                continue
            por_dia[fecha] = round(por_dia.get(fecha, 0.0) + item["monto"], 2)
        return por_dia

    # ── El arrastre de hoy+1 ─────────────────────────────────────────────────

    def test_la_serie_arranca_en_manana(self):
        """La celda de hoy nunca tiene saldo proyectado: la UI lo declara en vez
        de pintar un saldo que no existe."""
        serie = self.flujo()["serie"]
        self.assertEqual(serie[0]["fecha"], str(self.dia(1)))
        self.assertNotIn(str(self.dia(0)), [p["fecha"] for p in serie])

    def test_lo_que_vence_hoy_cae_en_manana_aunque_no_este_vencido(self):
        """El caso que rompia la grilla. Una obligacion que vence HOY no viene
        marcada `vencida` (eso es `fecha < hoy`), asi que no salia en el bloque de
        vencidos, seguia en la celda de hoy... y ademas hacia caer el saldo de
        hoy+1, una celda que mostraba cero pagos."""
        self.obligacion(concepto="Nomina de hoy", monto=400000, vencimiento=self.dia(0))

        item = next(i for i in self.agenda()["items"] if i["concepto"] == "Nomina de hoy")
        self.assertFalse(item["vencida"], "vence hoy: todavia no esta vencida")

        serie = {p["fecha"]: p for p in self.flujo()["serie"]}
        self.assertEqual(serie[str(self.dia(1))]["salidas"], 400000)
        self.assertEqual(serie[str(self.dia(2))]["salidas"], 0)

    def test_vencido_y_lo_de_hoy_se_suman_en_la_misma_celda(self):
        """El bloque "arrastre" del detalle es exactamente este conjunto:
        `fecha <= hoy`. Filtrarlo por `vencida` dejaria los 400k afuera."""
        self.factura(proveedor="Atrasada", total=60000, vencimiento=self.dia(-5))
        self.obligacion(concepto="Energia vencida", monto=40000, vencimiento=self.dia(-3))
        self.obligacion(concepto="Nomina de hoy", monto=400000, vencimiento=self.dia(0))
        self.obligacion(concepto="Arriendo", monto=10000, vencimiento=self.dia(1))

        hoy = str(self.dia(0))
        arrastre = sum(i["monto"] for i in self.agenda()["items"] if i["fecha"] <= hoy)
        self.assertEqual(arrastre, 500000)

        serie = {p["fecha"]: p for p in self.flujo()["serie"]}
        # 60k + 40k + 400k de arrastre + 10k que vence manana: un solo numero.
        self.assertEqual(serie[str(self.dia(1))]["salidas"], 510000)

    def test_el_total_vencido_de_la_agenda_no_incluye_lo_de_hoy(self):
        """La otra mitad del mismo contrato: el bloque rojo "Vencido - pagalo ya"
        usa `totales.vencido`, que es estrictamente `fecha < hoy`. Los dos numeros
        conviven y por eso la UI no puede usar uno donde va el otro."""
        self.obligacion(concepto="Energia vencida", monto=40000, vencimiento=self.dia(-3))
        self.obligacion(concepto="Nomina de hoy", monto=400000, vencimiento=self.dia(0))

        self.assertEqual(self.agenda()["totales"]["vencido"], 40000)

    # ── La invariante celda a celda ──────────────────────────────────────────

    def test_cada_dia_del_horizonte_cuadra_con_la_agenda(self):
        """Lo que la UI necesita para usar `salidas` como el numero de la celda y
        la agenda como su desglose: para TODO dia del horizonte los dos coinciden."""
        self.factura(proveedor="Atrasada", total=60000, vencimiento=self.dia(-5))
        self.obligacion(concepto="Nomina de hoy", monto=400000, vencimiento=self.dia(0))
        self.obligacion(concepto="Arriendo", monto=10000, vencimiento=self.dia(1))
        self.obligacion(concepto="Servicios", monto=25000, vencimiento=self.dia(9))
        self.obligacion(concepto="Seguro", monto=70000, vencimiento=self.dia(29))
        self.factura(proveedor="Lacteos", total=33000, vencimiento=self.dia(15))

        data = self.flujo(dias=30)
        esperado = self.salidas_esperadas(self.agenda(), 30)
        for punto in data["serie"]:
            self.assertAlmostEqual(
                punto["salidas"], esperado.get(punto["fecha"], 0.0),
                msg=f"la celda {punto['fecha']} no cuadra con la agenda")
        self.assertAlmostEqual(data["totales"]["salidas"], sum(esperado.values()))

    def test_lo_sin_fecha_no_entra_ni_en_la_celda_ni_en_el_saldo(self):
        """La seccion "Sin fecha de pago" es aparte a proposito: no se le inventa
        un dia. Si entrara en alguna celda, el calendario estaria fabricando un
        vencimiento que nadie pacto."""
        self.obligacion(concepto="Contador sin fecha", monto=800000)

        agenda = self.agenda()
        self.assertEqual(agenda["items"], [])
        self.assertEqual(agenda["totales"]["sin_fecha"], 800000)

        data = self.flujo()
        self.assertEqual(sum(p["salidas"] for p in data["serie"]), 0)
        self.assertIsNone(data["punto_de_quiebre"])

    def test_lo_que_vence_despues_del_horizonte_no_se_adelanta(self):
        """Fuera del horizonte la celda muestra el pago pero NO hay saldo: la
        proyeccion no puede cobrar algo que su serie no llega a mostrar."""
        self.obligacion(concepto="Impuesto lejano", monto=900000, vencimiento=self.dia(45))
        data = self.flujo(dias=30)
        self.assertEqual(sum(p["salidas"] for p in data["serie"]), 0)
        # La agenda si lo tiene: es lo que pinta la celda de ese mes, sin saldo.
        self.assertEqual(len(self.agenda()["items"]), 1)


if __name__ == "__main__":
    unittest.main()
