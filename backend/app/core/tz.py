"""Timezone helpers for Colombia (America/Bogota = UTC-5, sin horario de verano).

Los timestamps se ALMACENAN siempre en UTC (datetime.utcnow). El negocio, en
cambio, opera en hora Colombia. Para agrupar/filtrar por "día" u "hora" hay que
convertir el instante UTC a hora local Colombia.

Matemática: un instante de reloj de pared W en Colombia corresponde a
UTC = W + 5h. Por lo tanto:
  - El día calendario D de Colombia abarca en UTC
      [ combine(D, 00:00) + 5h , combine(D, 23:59:59.999999) + 5h ].
  - La hora Colombia de un datetime UTC = (utc_dt - 5h).hour
  - "Hoy" en Colombia = (datetime.utcnow() - 5h).date()

Pure-Python, DB-agnóstico: funciona igual en SQLite y PostgreSQL sin funciones
de fecha SQL-específicas.
"""
from datetime import datetime, date, timedelta

COL_OFFSET = timedelta(hours=5)  # Colombia UTC-5, sin horario de verano


def ahora_utc() -> datetime:
    """El instante actual en UTC, que es como se ALMACENA todo.

    Existe para que el instante que se guarda y el día Colombia que se calcula
    salgan del MISMO reloj. Usar `datetime.utcnow()` suelto en cada lado los
    desacopla, y ahí una guarda de tipo «¿ya pasó hoy?» compara una fecha
    contra un timestamp que vino de otra parte.
    """
    return datetime.utcnow()


def hoy_col() -> date:
    """Fecha de 'hoy' en hora Colombia."""
    return (datetime.utcnow() - COL_OFFSET).date()


def inicio_dia_col_utc(d: date) -> datetime:
    """Instante UTC del inicio (00:00:00) del día Colombia `d`."""
    return datetime.combine(d, datetime.min.time()) + COL_OFFSET


def fin_dia_col_utc(d: date) -> datetime:
    """Instante UTC del fin (23:59:59.999999) del día Colombia `d`."""
    return datetime.combine(d, datetime.max.time()) + COL_OFFSET


def local_col(dt: datetime) -> datetime:
    """El mismo instante expresado como RELOJ DE PARED de Colombia (naive).

    Es la conversión que hay que hacer ANTES de partir una jornada en franjas
    (nocturna, medianoche, domingo): todas esas fronteras son locales. `hora_col`
    y `dia_col` son casos particulares de esto.
    """
    return dt - COL_OFFSET


def hora_col(dt: datetime) -> int:
    """Hora del día (0-23) en Colombia de un datetime almacenado en UTC."""
    return (dt - COL_OFFSET).hour


def dia_col(dt: datetime) -> date:
    """Fecha del día Colombia de un datetime almacenado en UTC."""
    return (dt - COL_OFFSET).date()


def rango_col_utc(fecha_desde: date | None, fecha_hasta: date | None) -> tuple[datetime, datetime]:
    """Rango [inicio, fin] en UTC que cubre los días Colombia [fecha_desde, fecha_hasta].

    Ambos parámetros pueden ser None -> default = día Colombia de hoy.
    """
    fd = fecha_desde or hoy_col()
    fh = fecha_hasta or hoy_col()
    return inicio_dia_col_utc(fd), fin_dia_col_utc(fh)
