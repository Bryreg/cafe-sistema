"""Descomposición de tiempo trabajado en TIPOS DE HORA. Cálculo PURO, sin DB.

Este módulo es el corazón del módulo de horarios: decide cuántas horas de cada
clase trabajó una persona y, por lo tanto, cuánto se le debe. Por eso:

1. NO conoce NINGUNA tasa. Todas —jornada máxima, franja nocturna, recargos—
   entran por el objeto `Tasa`, que a su vez sale de la tabla `tasas_laborales`
   resuelta por la FECHA del turno. Un cambio de ley es una fila, no un deploy.
2. NO toca la base de datos ni el reloj. Recibe datetimes y devuelve números.
3. Trabaja en HORA COLOMBIA (reloj de pared, datetime naive). El caller convierte
   los timestamps UTC de la base con `core/tz.py` ANTES de llamar acá. La franja
   nocturna, la medianoche y el domingo son conceptos de hora local: mezclarlos
   con UTC es exactamente el bug que este repo ya sufrió cuatro veces.

La identidad que no puede fallar: la suma de todas las categorías es EXACTAMENTE
la duración del tiempo trabajado. Si no cierra, alguien cobra de menos.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Sequence

# Las 4 categorías ORDINARIAS (las que produce descomponer/segmentar) y sus
# gemelas EXTRA (las que produce liquidar_semana al pasar la jornada máxima).
CATEGORIAS_ORDINARIAS = (
    "ordinaria_diurna",
    "ordinaria_nocturna",
    "dominical_diurna",
    "dominical_nocturna",
)

# ordinaria → su versión extra. La extra conserva SIEMPRE la franja (diurna /
# nocturna) y el carácter dominical: pasarse de la jornada no borra el recargo
# que ya se había ganado por trabajar de noche o en domingo.
EXTRA_DE = {
    "ordinaria_diurna": "extra_diurna",
    "ordinaria_nocturna": "extra_nocturna",
    "dominical_diurna": "extra_dominical_diurna",
    "dominical_nocturna": "extra_dominical_nocturna",
}

CATEGORIAS = CATEGORIAS_ORDINARIAS + tuple(EXTRA_DE[c] for c in CATEGORIAS_ORDINARIAS)

# Etiquetas para las pantallas y el export. Viven acá para que backend y front
# nombren lo mismo de una sola forma.
ETIQUETAS = {
    "ordinaria_diurna": "Ordinaria diurna",
    "ordinaria_nocturna": "Ordinaria nocturna",
    "dominical_diurna": "Dominical/festiva diurna",
    "dominical_nocturna": "Dominical/festiva nocturna",
    "extra_diurna": "Extra diurna",
    "extra_nocturna": "Extra nocturna",
    "extra_dominical_diurna": "Extra dominical/festiva diurna",
    "extra_dominical_nocturna": "Extra dominical/festiva nocturna",
}


@dataclass(frozen=True)
class Tasa:
    """Snapshot inmutable de los parámetros legales vigentes para una fecha.

    Espejo puro de una fila de `tasas_laborales`, sin ORM: así el cálculo se
    testea sin base de datos y no puede leer una tasa distinta a mitad de una
    liquidación.
    """
    jornada_max_semanal: float
    hora_inicio_nocturna: int
    hora_fin_nocturna: int
    recargo_nocturno: float
    recargo_dominical: float
    extra_diurna: float
    extra_nocturna: float
    divisor_hora_mensual: float
    # None = derivar (dominical + nocturno). Ver el comentario del modelo.
    recargo_dominical_nocturno: float | None = None
    vigente_desde: date | None = None

    @property
    def recargo_dom_noct(self) -> float:
        if self.recargo_dominical_nocturno is not None:
            return self.recargo_dominical_nocturno
        return self.recargo_dominical + self.recargo_nocturno


EsFestivo = Callable[[date], bool]


def _nunca(_d: date) -> bool:
    return False


def es_franja_nocturna(momento: datetime, tasa: Tasa) -> bool:
    """True si ese instante cae en la franja nocturna de la tasa.

    La franja normal CRUZA la medianoche (ej. 19:00 → 06:00), así que la
    pertenencia es `hora >= inicio OR hora < fin`. Si alguna vez una tasa
    definiera una franja que NO cruza (inicio < fin), se resuelve con el AND.
    """
    h = momento.hour
    ini, fin = tasa.hora_inicio_nocturna, tasa.hora_fin_nocturna
    if ini > fin:
        return h >= ini or h < fin
    return ini <= h < fin


def es_dominical(momento: datetime, es_festivo: EsFestivo) -> bool:
    """Domingo O festivo. Es UNA sola condición: un domingo que además es
    festivo no cobra dos veces el recargo — es el mismo día especial."""
    return momento.weekday() == 6 or es_festivo(momento.date())


def _categoria(momento: datetime, tasa: Tasa, es_festivo: EsFestivo) -> str:
    dom = es_dominical(momento, es_festivo)
    noc = es_franja_nocturna(momento, tasa)
    if dom:
        return "dominical_nocturna" if noc else "dominical_diurna"
    return "ordinaria_nocturna" if noc else "ordinaria_diurna"


def _cortes(inicio: datetime, fin: datetime, tasa: Tasa) -> list[datetime]:
    """Todos los instantes donde la categoría PUEDE cambiar, dentro del turno.

    Son las medianoches (cambia el día → puede cambiar domingo/festivo) y los
    dos bordes de la franja nocturna de cada día tocado. Entre dos cortes
    consecutivos la categoría es constante por construcción, así que basta
    clasificar el PUNTO MEDIO del tramo.
    """
    puntos = {inicio, fin}
    dia = inicio.date()
    ultimo = fin.date()
    while dia <= ultimo:
        base = datetime.combine(dia, datetime.min.time())
        puntos.add(base)                                            # medianoche
        puntos.add(base + timedelta(hours=tasa.hora_fin_nocturna))    # fin de la noche
        puntos.add(base + timedelta(hours=tasa.hora_inicio_nocturna))  # inicio de la noche
        dia += timedelta(days=1)
    puntos.add(datetime.combine(ultimo + timedelta(days=1), datetime.min.time()))
    return sorted(p for p in puntos if inicio <= p <= fin)


def segmentar(inicio: datetime, fin: datetime, tasa: Tasa,
              es_festivo: EsFestivo | None = None) -> list[tuple[str, float]]:
    """Parte el turno en tramos CRONOLÓGICOS `(categoria, horas)`.

    El orden importa: `liquidar_semana` necesita saber cuáles son las ÚLTIMAS
    horas de la semana para marcarlas como extra.
    """
    if fin <= inicio:
        return []
    ef = es_festivo or _nunca
    cortes = _cortes(inicio, fin, tasa)
    segmentos: list[tuple[str, float]] = []
    for a, b in zip(cortes, cortes[1:]):
        horas = (b - a).total_seconds() / 3600.0
        if horas <= 0:
            continue
        medio = a + (b - a) / 2
        cat = _categoria(medio, tasa, ef)
        if segmentos and segmentos[-1][0] == cat:
            # Fusiona tramos contiguos de la misma categoría (ej. dos noches
            # seguidas sin cambio de día especial): menos ruido, mismo total.
            segmentos[-1] = (cat, segmentos[-1][1] + horas)
        else:
            segmentos.append((cat, horas))
    return segmentos


def _cero(categorias: Sequence[str]) -> dict[str, float]:
    return {c: 0.0 for c in categorias}


def descomponer(inicio: datetime, fin: datetime, tasa: Tasa,
                es_festivo: EsFestivo | None = None) -> dict[str, float]:
    """Horas por categoría ORDINARIA de UN turno.

    No decide extras: la hora extra depende del ACUMULADO SEMANAL, no de este
    turno solo. Para eso está `liquidar_semana`.

    Garantía: `sum(resultado.values()) == (fin - inicio) en horas`, exacto.
    """
    out = _cero(CATEGORIAS_ORDINARIAS)
    for cat, horas in segmentar(inicio, fin, tasa, es_festivo):
        out[cat] += horas
    return out


def liquidar_semana(tramos: Iterable[tuple[datetime, datetime]], tasa: Tasa,
                    es_festivo: EsFestivo | None = None) -> dict[str, float]:
    """Liquida una semana entera: horas por categoría, ya con las extras.

    La hora extra se decide sobre el ACUMULADO de la semana: las horas que
    exceden `jornada_max_semanal` son extras, y son las ÚLTIMAS en el tiempo
    (por eso los tramos se ordenan cronológicamente antes de acumular).

    DECISIÓN DECLARADA: TODO el tiempo trabajado consume cupo de jornada, el
    dominical y el nocturno incluidos. La jornada máxima del art. 161 CST es un
    tope de tiempo de trabajo, no de "tiempo de trabajo ordinario diurno";
    excluir el domingo del acumulado escondería horas extra reales.

    Esta función RECLASIFICA horas (ordinaria → extra), nunca las crea ni las
    destruye: el total siempre coincide con el tiempo trabajado.
    """
    out = _cero(CATEGORIAS)
    for _, parcial in liquidar_semana_por_tramo(tramos, tasa, es_festivo):
        for cat, horas in parcial.items():
            out[cat] += horas
    return out


def liquidar_semana_por_tramo(
    tramos: Iterable[tuple[datetime, datetime]], tasa: Tasa,
    es_festivo: EsFestivo | None = None,
) -> list[tuple[datetime, dict[str, float]]]:
    """Como `liquidar_semana`, pero DESAGREGADO por tramo (orden cronológico).

    El resumen mensual necesita saber a qué día pertenece cada hora —para cruzar
    contra el horario planeado y para cortar el mes— pero la hora extra se decide
    por SEMANA. Liquidar la semana entera y devolver el detalle es la única forma
    de tener las dos cosas sin mentir en ninguna: el umbral sigue siendo semanal y
    cada hora conserva su día.

    Cada hora queda atribuida al día en que EMPEZÓ el tramo (mismo criterio que el
    día operativo del repo): un turno 18:00→02:00 es del día que arrancó.
    """
    ef = es_festivo or _nunca
    ordenados = sorted(((i, f) for i, f in tramos if f > i), key=lambda t: t[0])

    salida: list[tuple[datetime, dict[str, float]]] = []
    cupo = max(0.0, float(tasa.jornada_max_semanal))
    acumulado = 0.0
    for inicio, fin in ordenados:
        out = _cero(CATEGORIAS)
        for cat, horas in segmentar(inicio, fin, tasa, ef):
            restante = cupo - acumulado
            if restante >= horas:
                out[cat] += horas
            elif restante <= 0:
                out[EXTRA_DE[cat]] += horas
            else:
                out[cat] += restante
                out[EXTRA_DE[cat]] += horas - restante
            acumulado += horas
        salida.append((inicio, out))
    return salida


def factores(tasa: Tasa) -> dict[str, float]:
    """Multiplicador de cada categoría sobre el valor de la hora ordinaria.

    Todos salen de la tasa: acá no hay ningún porcentaje escrito a mano. Los
    recargos se SUMAN sobre el 1.0 de la hora ordinaria, que es como se liquida
    en Colombia (una extra dominical diurna = 1 + dominical + extra diurna).
    """
    return {
        "ordinaria_diurna": 1.0,
        "ordinaria_nocturna": 1.0 + tasa.recargo_nocturno,
        "dominical_diurna": 1.0 + tasa.recargo_dominical,
        "dominical_nocturna": 1.0 + tasa.recargo_dom_noct,
        "extra_diurna": 1.0 + tasa.extra_diurna,
        "extra_nocturna": 1.0 + tasa.extra_nocturna,
        "extra_dominical_diurna": 1.0 + tasa.recargo_dominical + tasa.extra_diurna,
        "extra_dominical_nocturna": 1.0 + tasa.recargo_dominical + tasa.extra_nocturna,
    }


def valorizar(horas: dict[str, float], tasa: Tasa, salario_mensual: float) -> dict:
    """ESTIMADO en pesos de un paquete de horas. No es una liquidación de nómina.

    Deliberadamente NO incluye auxilio de transporte, prestaciones, seguridad
    social ni deducciones: es la valorización del TIEMPO TRABAJADO con los
    recargos de la tasa vigente, para que el dueño vea el orden de magnitud y
    detecte un horario caro antes de enviarlo. La pantalla lo dice así y el
    número final lo pone el contador.
    """
    divisor = float(tasa.divisor_hora_mensual or 0)
    valor_hora = (float(salario_mensual or 0) / divisor) if divisor > 0 else 0.0
    f = factores(tasa)
    detalle = {c: round(valor_hora * f[c] * float(horas.get(c, 0.0) or 0.0), 2)
               for c in CATEGORIAS}
    return {
        "valor_hora_ordinaria": valor_hora,
        "detalle": detalle,
        "total": round(sum(detalle.values()), 2),
    }


def total_horas(horas: dict[str, float]) -> float:
    """Suma de todas las categorías presentes (el tiempo trabajado)."""
    return sum(float(horas.get(c, 0.0) or 0.0) for c in CATEGORIAS)


def lunes_de(fecha: date) -> date:
    """Lunes de la semana laboral de esa fecha. La semana corre lunes→domingo:
    es la que usa el art. 161 CST para el tope semanal, y además deja el domingo
    (el día de recargo) DENTRO de la semana que lo generó."""
    return fecha - timedelta(days=fecha.weekday())
