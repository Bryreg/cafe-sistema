"""La recogida CUBRE el pendiente por consignar.

El agujero medido: el dueño pasaba por la sede, se llevaba el efectivo, y el día
seguía pidiendo «consigná $X». La recogida bajaba el cajón (services/costos.py)
pero `_saldos_consignacion` no la leía, así que la barista veía la deuda de una
plata que ya no estaba en la registradora — y la pantalla del dueño también.

Lo que fijan estos tests, y por qué cada regla importa:

- lo recogido cubre los días pendientes DEL MÁS VIEJO AL MÁS NUEVO: es él
  llevándose los fajos que más días llevan esperando el banco, el mismo criterio
  con el que `registrar` imputa una consignación nueva;
- una recogida solo cubre días que YA HABÍAN CERRADO cuando él pasó, y su
  sobrante se DESCARTA: sin esas dos reglas una recogida con sobrante dejaría
  pre-cubierto un día futuro, que nacería sin pedir consignación — pendiente
  subestimado, para el lado que tranquiliza;
- la consignación del DUEÑO (huérfana, bajo el régimen de recogidas) NO empareja
  turnos por ventana de fecha: esa plata ya salió del cajón en la recogida, y
  emparejarla cubriría el mismo día DOS veces;
- las huérfanas del MUNDO VIEJO (antes del régimen) siguen emparejando igual que
  siempre: son consignaciones de barista sin FK, no depósitos de la mano.
"""
import unittest
from datetime import timedelta

from app.models.models import EstadoConsignacionEnum

from tests.test_recogidas_efectivo import RecogidasBase


class RecogidaCubrePendienteTest(RecogidasBase):

    def _turno_cerrado(self, dias_atras: int, efectivo: float):
        ap = self.mediodia(self.dia(-dias_atras))
        return self.turno(tienda=self.vida, abierto=False, base=0,
                          efectivo_ventas=efectivo,
                          apertura=ap, cierre=ap + timedelta(hours=6))

    def pendiente(self):
        r = self.client.get(f"/api/v1/consignaciones/pendiente/{self.vida.id}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_recoger_todo_deja_el_pendiente_en_cero(self):
        """El caso del hallazgo: dos días por consignar, él se lleva todo, y el
        sistema tiene que dejar de pedir esa plata."""
        self._turno_cerrado(3, 500000)
        self._turno_cerrado(2, 300000)
        self.assertEqual(self.pendiente()["total_pendiente"], 800000)

        self.recogida(800000, tienda=self.vida, fecha=self.dia(-1))

        body = self.pendiente()
        self.assertEqual(body["total_pendiente"], 0)
        self.assertEqual(body["items"], [])

    def test_recogida_parcial_cubre_el_dia_mas_viejo_primero(self):
        self._turno_cerrado(3, 500000)
        self._turno_cerrado(2, 300000)

        self.recogida(500000, tienda=self.vida, fecha=self.dia(-1))

        body = self.pendiente()
        # Queda pidiendo solo el día nuevo: los fajos viejos son los que él se
        # llevó, no una preferencia contable.
        self.assertEqual(body["total_pendiente"], 300000)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["esperado"], 300000)
        self.assertEqual(body["items"][0]["recogido"], 0)

    def test_cubrir_a_medias_un_dia_deja_el_resto_pidiendose(self):
        self._turno_cerrado(3, 500000)
        self.recogida(200000, tienda=self.vida, fecha=self.dia(-1))

        item = self.pendiente()["items"][0]
        self.assertEqual(item["recogido"], 200000)
        self.assertEqual(item["pendiente"], 300000)

    def test_el_sobrante_de_una_recogida_no_precubre_un_dia_futuro(self):
        """La recogida del martes no puede cubrir la venta del jueves: cuando él
        pasó, ese día no existía. Sin este tope, un sobrante (la base contada de
        más, un conteo impreciso) haría nacer días que no piden consignación."""
        self._turno_cerrado(4, 500000)
        # Se lleva 600.000: los 500.000 del día viejo y 100.000 de sobrante.
        self.recogida(600000, tienda=self.vida, fecha=self.dia(-3))
        # Recién DESPUÉS cierra otro día con 300.000.
        self._turno_cerrado(1, 300000)

        body = self.pendiente()
        # El día nuevo pide sus 300.000 completos: el sobrante se descartó.
        self.assertEqual(body["total_pendiente"], 300000)
        self.assertEqual(body["items"][0]["recogido"], 0)

    def test_el_resumen_admin_explica_el_descuento_con_recogido(self):
        """El saldo que baja tiene que poder explicarse en la misma fila, igual
        que la procedencia de la cascada: un número que baja sin decir por qué
        se lee como un bug."""
        self._turno_cerrado(3, 500000)
        self.recogida(500000, tienda=self.vida, fecha=self.dia(-1))

        r = self.client.get("/api/v1/consignaciones/resumen-admin",
                            params={"tienda_id": self.vida.id})
        self.assertEqual(r.status_code, 200, r.text)
        fila = r.json()[0]
        self.assertEqual(fila["recogido"], 500000)
        self.assertEqual(fila["saldo_pendiente"], 0)
        # La cuenta cruda del día no cambia: lo que el turno generó sigue siendo
        # lo que generó. Lo que cambia es cuánto falta.
        self.assertEqual(fila["esperado_consignar"], 500000)

    def test_la_consignacion_del_dueno_no_cubre_el_dia_dos_veces(self):
        """Él recoge $500.000 y al otro día los deposita. Si el depósito además
        emparejara el turno por ventana de fecha, el día quedaría cubierto dos
        veces y el pendiente de otros días se evaporaría en silencio."""
        t = self._turno_cerrado(3, 500000)
        self.recogida(500000, tienda=self.vida, fecha=self.dia(-2))
        # Su depósito, dentro de la ventana de emparejamiento del turno
        # (cierre + 20h): sin el candado, esto lo cubriría por segunda vez.
        self.consignacion(500000, tienda=self.vida, turno=None,
                          fecha=t.fecha_cierre + timedelta(hours=15))

        r = self.client.get("/api/v1/consignaciones/resumen-admin",
                            params={"tienda_id": self.vida.id})
        fila = r.json()[0]
        self.assertEqual(fila["recogido"], 500000)
        self.assertEqual(fila["total_consignado"], 0)
        self.assertEqual(fila["saldo_pendiente"], 0)

    def test_en_el_mundo_viejo_la_huerfana_sigue_emparejando_por_ventana(self):
        """Antes del régimen no hay mano del dueño: una huérfana es una
        consignación de barista sin FK (registros legacy) y la ventana la
        devuelve a su turno, como siempre. El candado solo existe DESDE la
        primera recogida."""
        t = self._turno_cerrado(3, 500000)
        # Sin ninguna recogida registrada: `desde_recogidas` es None.
        self.consignacion(500000, tienda=self.vida, turno=None,
                          fecha=t.fecha_cierre + timedelta(hours=2))

        body = self.pendiente()
        self.assertEqual(body["total_pendiente"], 0)

    def test_recoger_no_toca_la_cuenta_cruda_del_dia(self):
        """`esperado` y `consignado` son hechos; la recogida solo cambia cuánto
        FALTA. Si la cobertura mutara la cuenta cruda, el desglose de la
        pantalla dejaría de cuadrar contra los sumandos que muestra."""
        self._turno_cerrado(3, 500000)
        self.recogida(500000, tienda=self.vida, fecha=self.dia(-1))

        r = self.client.get("/api/v1/consignaciones/resumen-admin",
                            params={"tienda_id": self.vida.id})
        fila = r.json()[0]
        self.assertEqual(fila["esperado_consignar"], 500000)
        self.assertEqual(fila["total_consignado"], 0)

    def test_la_barista_que_consigna_despues_de_una_recogida_no_resta_de_mas(self):
        """Caso mixto: un día ya cubierto por recogida y otro que la barista
        consigna con FK. Cada peso cubre exactamente un día."""
        self._turno_cerrado(3, 500000)
        t2 = self._turno_cerrado(2, 300000)
        self.recogida(500000, tienda=self.vida, fecha=self.dia(-1))
        self.consignacion(300000, tienda=self.vida, turno=t2,
                          estado=EstadoConsignacionEnum.pendiente)

        body = self.pendiente()
        self.assertEqual(body["total_pendiente"], 0)


if __name__ == "__main__":
    unittest.main()
