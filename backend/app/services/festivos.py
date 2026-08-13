"""Festivos colombianos CALCULADOS, no una lista pegada.

Una lista de fechas se vence: alguien la carga hasta 2027 y en 2028 el sistema
liquida un festivo como día normal, sin avisar. Acá el código deriva el año
entero a partir de dos cosas:

  - los festivos de fecha fija,
  - el Domingo de Pascua (algoritmo de Butcher/Meeus), del que cuelgan los
    móviles.

Y aplica la **Ley 51 de 1983 («Ley Emiliani»)**, que corre al LUNES siguiente los
festivos que no son de fecha protegida.

La tabla `festivos` NO reemplaza esto: solo agrega un día cívico local o quita
uno calculado. La base siempre la pone el código.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

# ── Fecha fija: se celebran el día que caen, aunque sea domingo ──────────────
FIJOS = [
    ((1, 1), "Año Nuevo"),
    ((5, 1), "Día del Trabajo"),
    ((7, 20), "Grito de Independencia"),
    ((8, 7), "Batalla de Boyacá"),
    ((12, 8), "Inmaculada Concepción"),
    ((12, 25), "Navidad"),
]

# ── Trasladables por la Ley Emiliani: se corren al lunes siguiente ───────────
EMILIANI = [
    ((1, 6), "Reyes Magos"),
    ((3, 19), "San José"),
    ((6, 29), "San Pedro y San Pablo"),
    ((8, 15), "Asunción de la Virgen"),
    ((10, 12), "Día de la Raza"),
    ((11, 1), "Todos los Santos"),
    ((11, 11), "Independencia de Cartagena"),
]

# ── Móviles atados a la Pascua, como desplazamiento en días ──────────────────
# Jueves y Viernes Santo NO se trasladan (caen jueves y viernes por definición).
# Los otros tres ya vienen con el traslado a lunes incorporado en el offset:
#   Ascensión       = Pascua +39 (jueves) → lunes = +43
#   Corpus Christi  = Pascua +60 (jueves) → lunes = +64
#   Sagrado Corazón = Pascua +68 (viernes) → lunes = +71
MOVILES = [
    (-3, "Jueves Santo"),
    (-2, "Viernes Santo"),
    (43, "Ascensión del Señor"),
    (64, "Corpus Christi"),
    (71, "Sagrado Corazón de Jesús"),
]


def domingo_pascua(anio: int) -> date:
    """Domingo de Pascua (cómputo gregoriano — algoritmo de Butcher/Meeus)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    mes, dia = divmod(h + lam - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def siguiente_lunes(d: date) -> date:
    """Ley Emiliani: si ya es lunes se queda; si no, corre al lunes siguiente."""
    if d.weekday() == 0:
        return d
    return d + timedelta(days=7 - d.weekday())


def festivos_col(anio: int) -> dict[date, str]:
    """Todos los festivos del año, `{fecha: nombre}`.

    Devuelve un dict porque lo que importa es SI un día es festivo, no cuántos
    festivos caen ese día. Dos festivos pueden coincidir en la misma fecha —pasa
    de verdad: en 2025 el Sagrado Corazón y San Pedro y San Pablo caen los dos el
    lunes 30 de junio— y en ese caso los nombres se juntan y la fecha es una sola.
    """
    out: dict[date, str] = {}

    def poner(fecha: date, nombre: str) -> None:
        if fecha in out and nombre not in out[fecha]:
            out[fecha] = f"{out[fecha]} / {nombre}"
        else:
            out.setdefault(fecha, nombre)

    for (mes, dia), nombre in FIJOS:
        poner(date(anio, mes, dia), nombre)
    for (mes, dia), nombre in EMILIANI:
        poner(siguiente_lunes(date(anio, mes, dia)), nombre)
    pascua = domingo_pascua(anio)
    for offset, nombre in MOVILES:
        poner(pascua + timedelta(days=offset), nombre)
    return out


# ---------------------------------------------------------------------------
# Capa con DB: los overrides de la tabla `festivos` mandan sobre el cálculo
# ---------------------------------------------------------------------------

def _overrides(db: Session, desde: date, hasta: date) -> dict[date, bool]:
    from app.models.models import Festivo
    filas = db.query(Festivo).filter(
        Festivo.fecha >= desde, Festivo.fecha <= hasta
    ).all()
    return {f.fecha: bool(f.es_festivo) for f in filas}


def es_festivo(db: Session, fecha: date) -> bool:
    """¿Es festivo ese día? Override de la tabla si existe; si no, el cálculo."""
    ov = _overrides(db, fecha, fecha)
    if fecha in ov:
        return ov[fecha]
    return fecha in festivos_col(fecha.year)


def fechas_festivas(db: Session, desde: date, hasta: date) -> set[date]:
    """Set de fechas festivas del rango, ya con overrides aplicados.

    Se resuelve de una sola vez y se le pasa al cálculo como `lambda d: d in set`:
    así una liquidación mensual hace UNA query, no una por día.
    """
    fechas: set[date] = set()
    for anio in range(desde.year, hasta.year + 1):
        for f in festivos_col(anio):
            if desde <= f <= hasta:
                fechas.add(f)
    for fecha, activo in _overrides(db, desde, hasta).items():
        if activo:
            fechas.add(fecha)
        else:
            fechas.discard(fecha)
    return fechas


def calendario(db: Session, anio: int) -> list[dict]:
    """Vista de pantalla: el año entero con el origen de cada día.

    `origen` distingue lo calculado de lo que tocó una persona — para que el
    dueño pueda auditar de dónde salió cada festivo.
    """
    calculados = festivos_col(anio)
    ov = _overrides(db, date(anio, 1, 1), date(anio, 12, 31))
    out: list[dict] = []
    for fecha in sorted(set(calculados) | set(ov)):
        activo = ov.get(fecha, fecha in calculados)
        if fecha in calculados and fecha in ov:
            origen = "calculado (editado a mano)"
        elif fecha in calculados:
            origen = "calculado"
        else:
            origen = "agregado a mano"
        out.append({
            "fecha": fecha.isoformat(),
            "nombre": calculados.get(fecha) or _nombre_override(db, fecha) or "Festivo",
            "es_festivo": activo,
            "origen": origen,
        })
    return out


def _nombre_override(db: Session, fecha: date) -> str | None:
    from app.models.models import Festivo
    fila = db.query(Festivo).filter(Festivo.fecha == fecha).first()
    return fila.nombre if fila else None
