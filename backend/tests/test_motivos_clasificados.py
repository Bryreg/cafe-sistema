"""El guardián de los motivos: que el cuadre no pueda mentir en silencio.

TODA la conciliación clasifica por `motivo.startswith(prefijo)` sobre un campo de
TEXTO LIBRE. Ese diseño tiene un modo de falla feo y silencioso: si un motivo no
matchea, la identidad SIGUE CERRANDO —lo no reconocido cae a un cajón de sastre—
pero el renglón que el dueño lee le miente sobre la causa. Nada se rompe, nada
avisa, y el número equivocado se ve exactamente igual de creíble que el bueno.

Ya pasó, y costó caro: 23 movimientos escritos como `consumo_turno` (minúscula,
guion bajo) no matcheaban el prefijo «Consumo», caían en `otras_salidas` y la
pantalla los mostraba como fuga SIN EXPLICAR — $1.126.398, el 99,7% de todo lo
«sin causa» de Vida. Era consumo del personal, registrado y con nombre. Acusar
de faltante algo que sí se anotó es el peor error posible en esta pantalla,
porque manda a buscar un robo que no existe.

Dos guardas, y las dos importan por razones distintas:

  1. LOS SERVICIOS DE HOY. Cada operación real escribe su motivo y acá se
     verifica que caiga en un bucket CON NOMBRE, no en el genérico. El día que
     alguien renombre «Traslado a» o «Venta POS», este test se cae antes que la
     pantalla empiece a mentir.
  2. LOS MOTIVOS VIEJOS DE PRODUCCIÓN. Los formatos que ya están escritos en la
     base y no se pueden reescribir. Si alguien limpia la lista de prefijos por
     parecer redundante, vuelven a caer al cajón.
"""
import unittest

from app.services.conciliacion import _bucket

# Bucket al que va lo que NO matchea ningún prefijo. Que un motivo REAL termine
# acá es el bug que este archivo persigue.
#
# Solo dos tipos tienen cajón de sastre. En las ENTRADAS el default es
# `entradas` (compras y recepciones), y eso es DELIBERADO: la factura y la
# recepción —las dos formas normales de que entre mercadería— no tienen prefijo
# propio justamente porque son el caso común. Ahí caer en el default es el
# comportamiento correcto, no una falla, así que la entrada se verifica solo
# contra su bucket esperado.
_CAJON = {"salida": "otras_salidas", "ajuste": "ajustes"}


class MotivosDeLosServiciosTest(unittest.TestCase):
    """Lo que los servicios escriben HOY. Cotejado contra el código que lo emite."""

    # (tipo, motivo tal cual lo escribe el servicio, bucket esperado, de dónde sale)
    CASOS = [
        ("salida", "Venta POS", "ventas", "pos.py"),
        ("salida", "Venta POS — insumo de Cappuccino Tradicional", "ventas", "pos.py"),
        ("salida", "Venta POS — insumo de Café Latte (reserva de #1034)", "ventas", "inventario.consumir_insumo"),
        ("salida", "Consumo (Catherin): se lo tomó", "mermas", "mermas.py"),
        ("salida", "Daño: se cayó al piso", "mermas", "mermas.py"),
        ("salida", "Traslado a Palmetto: falta allá", "traslados", "mermas.py"),
        ("salida", "Preparación: MEZCLA GRANIZADO", "preparaciones", "inventario.preparar"),
        ("salida", "Preparación pastelería", "preparaciones", "pasteleria.py"),
        ("salida", "Anulación traslado #12 (revertir envío)", "reversas_salida", "mermas.py"),
        ("salida", "Eliminación factura #220 — Wilenses", "reversas_salida", "facturas.py"),
        ("salida", "Corrección factura #9715 — Calipulpas", "reversas_salida", "facturas.py"),
        ("entrada", "Factura #9144 — Cafexcoop", "entradas", "facturas.crear_factura"),
        ("entrada", "Recepción #7", "entradas", "recepciones.py"),
        ("entrada", "Preparación: MEZCLA GRANIZADO", "preparaciones_producidas", "inventario.preparar"),
        ("entrada", "Recibo traslado desde Vida", "traslados_recibidos", "mermas.py"),
        ("entrada", "Anulación de ticket #4821", "reversas", "pos.py"),
        ("entrada", "Nota crédito #33", "reversas", "notas_credito.py"),
        ("entrada", "Unificación de productos duplicados", "unificaciones", "inventario.py"),
        ("ajuste", "Conteo #348 aplicado al inventario", "ajustes_conteo", "conteos.py"),
        ("ajuste", "Verificación de conteo aprobada (conteo #12)", "ajustes_conteo", "conteos.py"),
        ("ajuste", "Inventario mensual 07/2026 aplicado (dif +13)", "ajustes_conteo", "inventario_mensual.py"),
        ("ajuste", "Ajuste por conteo de compras #3", "ajustes_conteo", "compras.py"),
    ]

    def test_ningun_motivo_real_cae_en_el_cajon_de_sastre(self):
        for tipo, motivo, esperado, origen in self.CASOS:
            with self.subTest(motivo=motivo):
                got = _bucket(tipo, motivo)
                if tipo in _CAJON:
                    self.assertNotEqual(
                        got, _CAJON[tipo],
                        f"«{motivo}» ({origen}) ya no matchea ningún prefijo: la cuenta va a "
                        f"seguir cerrando y el renglón va a mentir sobre la causa")
                self.assertEqual(got, esperado, f"«{motivo}» ({origen})")


class MotivosViejosDeProduccionTest(unittest.TestCase):
    """Formatos que YA están escritos en la base y no se pueden reescribir.

    Salen de un censo real de los movimientos de las dos sedes (jul–ago 2026).
    Si alguien poda la lista de prefijos por parecer redundante, estos vuelven a
    caer al cajón y la pantalla vuelve a acusar fugas que no existen.
    """

    CASOS = [
        # 23 movimientos, $1.126.398 en Vida. El caso que motivó este archivo.
        ("salida", "consumo_turno", "mermas"),
        # Conteos cargados a mano en la puesta en marcha: SON conteos, no
        # ajustes manuales sueltos. 55 movimientos, $1.545.642 en Palmetto.
        ("ajuste", "Carga inicial Palmetto: conteo de apertura", "ajustes_conteo"),
        ("ajuste", "Conteo fisico real (admin) tras correccion", "ajustes_conteo"),
        ("ajuste", "Aplicar conteo de cierre 1-jul (reconciliación)", "ajustes_conteo"),
    ]

    def test_los_motivos_viejos_siguen_reconociendose(self):
        for tipo, motivo, esperado in self.CASOS:
            with self.subTest(motivo=motivo):
                self.assertEqual(_bucket(tipo, motivo), esperado)


class LoQueNoSePuedeClasificarTest(unittest.TestCase):
    """El cajón de sastre tiene que seguir existiendo, y tiene que ser honesto."""

    def test_un_motivo_desconocido_cae_al_cajon_y_no_revienta(self):
        # No se inventa una causa: se declara que no se sabe. Eso es correcto.
        self.assertEqual(_bucket("salida", "cualquier cosa que nadie previó"), "otras_salidas")
        self.assertEqual(_bucket("ajuste", "Tenemos una bolsa entera."), "ajustes")

    def test_sin_motivo_tampoco_revienta(self):
        # 39 movimientos reales de producción tienen el motivo VACÍO. No hay con
        # qué clasificarlos y la pantalla los muestra como lo que son: sin causa.
        for tipo in ("salida", "ajuste"):
            with self.subTest(tipo=tipo):
                self.assertEqual(_bucket(tipo, None), _CAJON[tipo])
                self.assertEqual(_bucket(tipo, "   "), _CAJON[tipo])
        # Una entrada sin motivo se lee como compra: es lo más probable y lo
        # menos alarmista, y de todos modos el renglón «llegó» de la ficha
        # separa lo que tiene factura de lo que entró sin papel.
        self.assertEqual(_bucket("entrada", None), "entradas")

    def test_el_prefijo_no_matchea_en_el_medio_de_la_frase(self):
        # startswith, no `in`: «... y de paso Venta POS» no es una venta. Si esto
        # cambiara a `in`, cualquier nota que mencione la palabra se reclasifica.
        self.assertEqual(_bucket("salida", "se perdió algo, no fue Venta POS"), "otras_salidas")


if __name__ == "__main__":
    unittest.main()
