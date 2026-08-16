"""Impoconsumo y GMF, con vigencia. La misma disciplina que sus dos hermanas.

Acá no hay ni una tarifa quemada: las mueve una reforma tributaria y el sistema
tiene que poder recalcular un mes viejo con la tarifa de ESE mes.

═══════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO CAMBIA TODOS LOS MÁRGENES QUE EL SISTEMA MOSTRÓ HASTA HOY
═══════════════════════════════════════════════════════════════════════════════
El precio de la carta lleva el impoconsumo adentro. Una aromática de $5.900 son
$5.463 de venta y $437 que se le giran a la DIAN. `Ticket.total` guarda los
$5.900 —está bien, es lo que el cliente pagó y lo que entró al cajón— pero
`rentabilidad` los sumaba enteros como venta propia.

Consecuencia medida contra el flujo de caja real del dueño: 7,41% de cada peso
facturado es un impuesto que el sistema estaba contando como utilidad. En sus
números, $55,2 millones en siete meses.

El dueño ya lo hacía bien en su Excel —deriva la venta como impoconsumo/0,08—
y el sistema no. Esto lo empareja.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.models import ParametroTributario

# Cada fila es un SNAPSHOT COMPLETO. Repetir lo que no cambió es deliberado:
# leer una fila tiene que contestar sola, sin ir a buscar qué heredó de cuál.
SIEMBRA: list[dict] = [
    {
        "vigente_desde": date(2023, 1, 1),
        "impoconsumo": 0.08,
        "precio_incluye_impoconsumo": True,
        "gmf": 0.004,
        "nota": ("Impuesto nacional al consumo de bares y restaurantes: 8%. "
                 "GMF (4x1000): 0,4%. Los precios de la carta lo llevan "
                 "adentro. Confirmá con tu contador si el régimen cambia."),
    },
]


@dataclass(frozen=True)
class Tributos:
    """Snapshot congelado para un período entero, igual que `Tasa`."""
    vigente_desde: date
    impoconsumo: float
    precio_incluye_impoconsumo: bool
    gmf: float
    confirmar_contador: bool

    def separar(self, cobrado: float) -> tuple[float, float]:
        """(venta_neta, impuesto) a partir de lo que el cliente pagó.

        Con el precio CON impuesto adentro la venta neta es total/(1+tasa) y no
        total×(1−tasa): descontar el 8% del precio final da un número más chico
        que el correcto y deja el impuesto mal liquidado. Con la tarifa en 8%,
        el impuesto es el 7,41% del precio final, no el 8%.
        """
        t = float(cobrado or 0.0)
        tasa = float(self.impoconsumo or 0.0)
        if tasa <= 0:
            return round(t, 2), 0.0
        if not self.precio_incluye_impoconsumo:
            # El impuesto se suma aparte: lo cobrado YA es la venta neta.
            return round(t, 2), 0.0
        neta = t / (1.0 + tasa)
        return round(neta, 2), round(t - neta, 2)


def sembrar(db: Session) -> int:
    """Crea las vigencias que falten. NUNCA pisa una existente."""
    existentes = {p.vigente_desde for p in db.query(ParametroTributario).all()}
    creadas = 0
    for datos in SIEMBRA:
        if datos["vigente_desde"] in existentes:
            continue
        db.add(ParametroTributario(**datos))
        creadas += 1
    if creadas:
        db.commit()
    return creadas


def listar(db: Session) -> list[ParametroTributario]:
    return (db.query(ParametroTributario)
            .order_by(ParametroTributario.vigente_desde.asc()).all())


def para(db: Session, fecha: date) -> Tributos:
    """Snapshot vigente en esa fecha.

    NUNCA devuelve None: si no hay ninguna fila siembra y reintenta, y si aun
    así no hay, devuelve una tarifa en CERO. Un impoconsumo desconocido no puede
    inventarse: en cero, el sistema muestra la venta bruta como hasta ahora y la
    pantalla dice que falta el parámetro, en vez de restar un impuesto que quizá
    este negocio no cobra.
    """
    def _buscar():
        return (db.query(ParametroTributario)
                .filter(ParametroTributario.vigente_desde <= fecha)
                .order_by(ParametroTributario.vigente_desde.desc())
                .first())

    fila = _buscar()
    if fila is None and sembrar(db):
        fila = _buscar()
    if fila is None:
        fila = (db.query(ParametroTributario)
                .order_by(ParametroTributario.vigente_desde.asc()).first())
    if fila is None:
        return Tributos(vigente_desde=fecha, impoconsumo=0.0,
                        precio_incluye_impoconsumo=True, gmf=0.0,
                        confirmar_contador=True)
    return Tributos(
        vigente_desde=fila.vigente_desde,
        impoconsumo=float(fila.impoconsumo or 0.0),
        precio_incluye_impoconsumo=bool(fila.precio_incluye_impoconsumo),
        gmf=float(fila.gmf or 0.0),
        confirmar_contador=bool(fila.confirmar_contador),
    )


def a_dict(fila: ParametroTributario) -> dict:
    return {
        "id": fila.id,
        "vigente_desde": fila.vigente_desde.isoformat(),
        "impoconsumo": float(fila.impoconsumo or 0.0),
        "precio_incluye_impoconsumo": bool(fila.precio_incluye_impoconsumo),
        "gmf": float(fila.gmf or 0.0),
        "nota": fila.nota,
        "confirmar_contador": bool(fila.confirmar_contador),
    }
