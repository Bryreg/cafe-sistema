"""LA PRUEBA DE ACEPTACIÓN: julio de 2026 reproduce la hoja del dueño.

La fuente de verdad del diseño del libro es FLUJO DE CAJA FSC 2026.xlsx, la
hoja que el dueño llena a mano hace años. `julio_2026_hoja.json` son sus 146
movimientos REALES, extraídos celda por celda de la hoja de JULIO (el último
mes completo): cada sumando de la columna OCCIDENTE es una consignación, cada
débito una salida, con su día.

Si el libro no reproduce el mes que él ya vivió, el modelo está mal — y por
eso este archivo carga esos movimientos por los caminos del sistema (las
consignaciones como filas de `Consignacion` que el libro proyecta solo; el
resto tecleado) y exige LOS NÚMEROS DE LA HOJA, al centavo:

    efectivo (Occidente)  $37.058.450
    tarjetas (Bold)       $23.873.437
    ENTRÓ                 $60.931.887
    SALIÓ                 $58.553.883,19
    quedó                  $2.378.003,81
    cerró el mes en        $4.403.027,25
    días en rojo: 17, 18, 19 y 20 de julio

Cualquier cambio del libro, de la cadena o de la proyección que rompa uno de
estos números está rompiendo la hoja del dueño, no un test.
"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import inicio_dia_col_utc
from app.database import Base
from app.models.models import (Consignacion, EstadoConsignacionEnum, RolEnum,
                               Tienda, Usuario)
from app.services import banco as banco_svc
from app.services import costos as costos_svc
from app.services.banco import (activar_consignaciones, libro, registrar,
                                sembrar_cuentas, serie_mensual)

ANIO, MES = 2026, 7
FIXTURE = os.path.join(os.path.dirname(__file__), "julio_2026_hoja.json")


class JulioReproduceLaHojaTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """El mes entero se carga UNA vez: son 146 movimientos y el escenario
        es de solo lectura — cada test mira un número distinto de la misma
        hoja."""
        fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.db = sessionmaker(bind=cls.engine)()

        vida = Tienda(nombre="Vida", direccion="x")
        cls.db.add(vida)
        cls.db.flush()
        admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                        rol=RolEnum.admin, tienda_id=vida.id, activo=True)
        cls.db.add(admin)
        cls.db.commit()
        sembrar_cuentas(cls.db)
        costos_svc.sembrar_categorias(cls.db)
        occ = cls.db.query(banco_svc.CuentaBancaria).filter_by(nombre="Occidente").first()
        bold = cls.db.query(banco_svc.CuentaBancaria).filter_by(nombre="Bold").first()
        cats = {c.clave: c.id for c in cls.db.query(costos_svc.CostoCategoria).all()}

        data = json.load(open(FIXTURE))
        # El ancla: julio arranca con el cierre de junio de la hoja
        # (B4 = +JUNIO!I34 = 2.025.023,44).
        costos_svc.guardar_saldo_banco(cls.db, data["inicial"],
                                       date(ANIO, MES, 1), admin.id)
        # El régimen: las consignaciones entran solas desde el 1 de julio.
        activar_consignaciones(cls.db, date(ANIO, MES, 1))

        for m in data["movimientos"]:
            dia = date(ANIO, MES, int(m["dia"]))
            if m["cuenta"] == "occidente" and m["tipo"] == "entrada":
                # Cada sumando de la columna OCCIDENTE es UNA consignación: el
                # libro la proyecta solo, sin que nadie la teclee.
                cls.db.add(Consignacion(
                    tienda_id=vida.id, caja_turno_id=None, valor=m["monto"],
                    usuario_id=admin.id, estado=EstadoConsignacionEnum.realizada,
                    fecha=inicio_dia_col_utc(dia) + timedelta(hours=12)))
                continue
            if m["tipo"] == "gmf":
                args = (occ.id, "salida", cats.get("gmf"), "GMF (4×1000)")
            elif m["tipo"] == "comision":
                args = (bold.id, "salida", cats.get("comision_banco"),
                        "Comisión bancaria")
            else:
                cuenta = occ.id if m["cuenta"] == "occidente" else bold.id
                args = (cuenta, m["tipo"], None,
                        (m.get("item") or "Movimiento")[:160])
            registrar(cls.db, dia, args[0], args[1], m["monto"], args[3],
                      usuario_id=admin.id, categoria_id=args[2], commit=False)
        cls.db.commit()

        cls.julio = libro(cls.db, date(ANIO, MES, 1), date(ANIO, MES, 31))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    # ── Los números de la hoja, al centavo ───────────────────────────────────

    def test_entro_60_931_887(self):
        self.assertEqual(self.julio["totales"]["entradas"], 60_931_887.00)

    def test_salio_58_553_883_19(self):
        self.assertEqual(self.julio["totales"]["salidas"], 58_553_883.19)

    def test_el_mes_cierra_en_4_403_027_25(self):
        self.assertEqual(self.julio["totales"]["final"], 4_403_027.25)

    def test_el_dia_1_arranca_con_el_cierre_de_junio(self):
        d1 = self.julio["dias"][0]
        self.assertTrue(d1["cadena"])
        self.assertEqual(d1["inicial"], 2_025_023.44)

    def test_los_dias_en_rojo_son_17_18_19_y_20(self):
        rojos = [d["fecha"] for d in self.julio["dias"] if d["en_rojo"]]
        self.assertEqual(rojos, ["2026-07-17", "2026-07-18",
                                 "2026-07-19", "2026-07-20"])
        self.assertEqual(self.julio["totales"]["dias_en_rojo"], 4)

    def test_el_efectivo_es_occidente_y_las_tarjetas_bold(self):
        """El 61/39 de la hoja: $37.058.450 consignados y $23.873.437 de Bold."""
        occ = sum(d["entradas"].get("Occidente", 0.0) for d in self.julio["dias"])
        bold = sum(d["entradas"].get("Bold", 0.0) for d in self.julio["dias"])
        self.assertEqual(round(occ, 2), 37_058_450.00)
        self.assertEqual(round(bold, 2), 23_873_437.00)

    def test_quedo_2_378_003_81(self):
        """Lo que el mes DEJÓ (entró − salió), separado del cierre: el cierre
        además arrastra el arranque."""
        t = self.julio["totales"]
        self.assertEqual(round(t["entradas"] - t["salidas"], 2), 2_378_003.81)

    def test_el_dia_mas_bajo_es_el_20(self):
        self.assertEqual(self.julio["totales"]["fecha_dia_mas_bajo"], "2026-07-20")
        self.assertEqual(self.julio["totales"]["dia_mas_bajo"], -436_734.49)

    def test_la_serie_anual_dice_lo_mismo_que_el_libro(self):
        """La misma pregunta por el otro camino no puede dar otro número."""
        mes = next(m for m in serie_mensual(self.db, ANIO)["meses"]
                   if m["mes"] == MES)
        self.assertEqual(mes["entradas"], 60_931_887.00)
        self.assertEqual(mes["salidas"], 58_553_883.19)
        self.assertEqual(mes["cierre"], 4_403_027.25)

    def test_las_consignaciones_proyectadas_son_55(self):
        """Los 55 sumandos de la columna OCCIDENTE, cada uno en su día — el
        día 1 tiene seis, como la celda C4 de la hoja."""
        n = sum(len(d.get("consignaciones") or []) for d in self.julio["dias"])
        self.assertEqual(n, 55)
        d1 = self.julio["dias"][0]
        self.assertEqual(len(d1["consignaciones"]), 6)
        self.assertEqual(d1["entradas"]["Occidente"], 3_701_250.00)


if __name__ == "__main__":
    unittest.main()
