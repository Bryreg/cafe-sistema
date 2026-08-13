"""Tasas legales de liquidación, resueltas POR FECHA.

La ley laboral colombiana está en transición: la jornada máxima semanal baja por
etapas (Ley 2101 de 2021) y los recargos dominicales suben por etapas, además de
que la franja nocturna se corrió (Ley 2466 de 2025). Cualquier porcentaje escrito
en el código envejece en silencio y obliga a un deploy por cada cambio de norma.

Por eso las tasas viven en la tabla `tasas_laborales`, con `vigente_desde`, y el
cálculo SIEMPRE resuelve por la fecha del turno: un turno de junio se liquida con
la tasa de junio aunque hoy rija otra.

SOBRE LOS VALORES SEMBRADOS: son un PUNTO DE PARTIDA, no una afirmación legal.
Cada fila trae su `nota` con la norma de la que sale y arranca con
`confirmar_contador=True`, que significa «todavía nadie lo validó». El contador
lo revisa, lo corrige si hace falta y baja esa bandera desde la pantalla. La
siembra NUNCA pisa una fila existente, así que confirmar o corregir es definitivo.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.models import TasaLaboral
from app.services.horas import Tasa

# Cada entrada es un SNAPSHOT COMPLETO: repetir los valores que no cambiaron es
# a propósito. Resolver una fecha es entonces «la última fila con vigente_desde
# <= fecha», sin herencia ni merges entre filas — un solo lugar para mirar.
SIEMBRA: list[dict] = [
    {
        "vigente_desde": date(2021, 1, 1),
        "jornada_max_semanal": 48.0,
        "hora_inicio_nocturna": 21, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.75,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Línea de base anterior a las reformas. Jornada 48 h/semana (art. 161 CST "
            "antes de la Ley 2101/2021); franja nocturna 21:00–06:00 (art. 160 CST antes "
            "de la Ley 2466/2025); recargo nocturno 35% y extras 25%/75% (art. 168 CST); "
            "dominical/festivo 75% (art. 179 CST antes de la Ley 2466/2025). "
            "CONFIRMAR: el divisor 240 (30 días × 8 h) es una CONVENCIÓN de liquidación, "
            "no un artículo — preguntá cuál usa tu contador."
        ),
    },
    {
        "vigente_desde": date(2023, 7, 16),
        "jornada_max_semanal": 47.0,
        "hora_inicio_nocturna": 21, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.75,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Ley 2101/2021 — primera etapa de reducción de jornada: 48 → 47 h/semana. "
            "CONFIRMAR el día exacto del escalón (la ley lo ata a los dos años de su "
            "promulgación, 15-jul-2021): acá se tomó el 16-jul-2023."
        ),
    },
    {
        "vigente_desde": date(2024, 7, 16),
        "jornada_max_semanal": 46.0,
        "hora_inicio_nocturna": 21, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.75,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Ley 2101/2021 — segunda etapa: 47 → 46 h/semana. CONFIRMAR el día exacto "
            "del escalón."
        ),
    },
    {
        "vigente_desde": date(2025, 7, 1),
        "jornada_max_semanal": 46.0,
        "hora_inicio_nocturna": 21, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.80,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Ley 2466/2025 (reforma laboral) — el recargo dominical/festivo sube de 75% "
            "a 80%. CONFIRMAR la fecha de entrada en vigencia de este escalón."
        ),
    },
    {
        "vigente_desde": date(2025, 7, 16),
        "jornada_max_semanal": 44.0,
        "hora_inicio_nocturna": 21, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.80,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Ley 2101/2021 — tercera etapa: 46 → 44 h/semana. CONFIRMAR el día exacto "
            "del escalón."
        ),
    },
    {
        "vigente_desde": date(2025, 12, 25),
        "jornada_max_semanal": 44.0,
        "hora_inicio_nocturna": 19, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.80,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Ley 2466/2025 — la jornada diurna pasa a 06:00–19:00, o sea el recargo "
            "nocturno arranca a las 19:00 (antes 21:00). Es el cambio que más plata mueve "
            "en una cafetería que cierra tarde. CONFIRMAR la fecha de entrada en vigencia "
            "(la ley la ató a un plazo posterior a la sanción): acá se tomó el 25-dic-2025."
        ),
    },
    {
        "vigente_desde": date(2026, 7, 1),
        "jornada_max_semanal": 44.0,
        "hora_inicio_nocturna": 19, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.90,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Ley 2466/2025 — el recargo dominical/festivo sube de 80% a 90% "
            "(el escalón siguiente lleva a 100%). CONFIRMAR la fecha del escalón."
        ),
    },
    {
        "vigente_desde": date(2026, 7, 16),
        "jornada_max_semanal": 42.0,
        "hora_inicio_nocturna": 19, "hora_fin_nocturna": 6,
        "recargo_nocturno": 0.35, "recargo_dominical": 0.90,
        "extra_diurna": 0.25, "extra_nocturna": 0.75,
        "divisor_hora_mensual": 240.0,
        "nota": (
            "Ley 2101/2021 — etapa FINAL: 44 → 42 h/semana. Es la tasa vigente hoy. "
            "CONFIRMAR el día exacto del escalón."
        ),
    },
]


def sembrar_tasas(db: Session) -> int:
    """Inserta las vigencias que falten. IDEMPOTENTE y NO destructivo.

    Si el contador ya editó una fila, la siembra la respeta: solo agrega las
    `vigente_desde` que todavía no existen. Devuelve cuántas creó.
    """
    existentes = {t.vigente_desde for t in db.query(TasaLaboral).all()}
    creadas = 0
    for datos in SIEMBRA:
        if datos["vigente_desde"] in existentes:
            continue
        db.add(TasaLaboral(confirmar_contador=True, **datos))
        creadas += 1
    if creadas:
        db.commit()
    return creadas


def listar(db: Session) -> list[TasaLaboral]:
    """Todas las vigencias, de la más vieja a la más nueva (sembrando si hace falta)."""
    sembrar_tasas(db)
    return db.query(TasaLaboral).order_by(TasaLaboral.vigente_desde.asc()).all()


def tasa_vigente(db: Session, fecha: date) -> TasaLaboral:
    """Fila vigente para esa FECHA: la última con `vigente_desde <= fecha`.

    Si la fecha es anterior a toda vigencia cargada, cae en la más antigua en vez
    de reventar: para un turno viejísimo es mejor liquidar con la tasa más vieja
    conocida —y decirlo en pantalla— que dejar la nómina sin número.
    """
    def _buscar():
        return db.query(TasaLaboral).filter(
            TasaLaboral.vigente_desde <= fecha
        ).order_by(TasaLaboral.vigente_desde.desc()).first()

    fila = _buscar()
    if fila is not None:
        return fila
    # Nada resuelve: puede ser una base virgen (nunca se sembró) o una fecha
    # anterior a toda vigencia. Se siembra y se vuelve a intentar ANTES de caer
    # en la más antigua — si no, una base recién creada liquidaría todo con la
    # tasa de 2021 sin que nadie lo note.
    if sembrar_tasas(db):
        fila = _buscar()
        if fila is not None:
            return fila
    return db.query(TasaLaboral).order_by(TasaLaboral.vigente_desde.asc()).first()


def tasa_para(db: Session, fecha: date) -> Tasa:
    """La tasa de esa fecha como objeto PURO, listo para `services/horas`.

    Convertir la fila ORM en un dataclass congelado hace que una liquidación
    entera use el mismo snapshot: no puede leer una tasa distinta a mitad de
    camino si alguien edita la tabla mientras corre.
    """
    fila = tasa_vigente(db, fecha)
    return a_tasa(fila)


def a_tasa(fila: TasaLaboral) -> Tasa:
    return Tasa(
        jornada_max_semanal=float(fila.jornada_max_semanal),
        hora_inicio_nocturna=int(fila.hora_inicio_nocturna),
        hora_fin_nocturna=int(fila.hora_fin_nocturna),
        recargo_nocturno=float(fila.recargo_nocturno),
        recargo_dominical=float(fila.recargo_dominical),
        recargo_dominical_nocturno=(
            float(fila.recargo_dominical_nocturno)
            if fila.recargo_dominical_nocturno is not None else None
        ),
        extra_diurna=float(fila.extra_diurna),
        extra_nocturna=float(fila.extra_nocturna),
        divisor_hora_mensual=float(fila.divisor_hora_mensual),
        vigente_desde=fila.vigente_desde,
    )


def a_dict(fila: TasaLaboral) -> dict:
    """Serialización para la pantalla (incluye el derivado, marcado como tal)."""
    t = a_tasa(fila)
    return {
        "id": fila.id,
        "vigente_desde": fila.vigente_desde.isoformat(),
        "jornada_max_semanal": float(fila.jornada_max_semanal),
        "hora_inicio_nocturna": int(fila.hora_inicio_nocturna),
        "hora_fin_nocturna": int(fila.hora_fin_nocturna),
        "recargo_nocturno": float(fila.recargo_nocturno),
        "recargo_dominical": float(fila.recargo_dominical),
        "recargo_dominical_nocturno": (
            float(fila.recargo_dominical_nocturno)
            if fila.recargo_dominical_nocturno is not None else None
        ),
        "recargo_dominical_nocturno_efectivo": t.recargo_dom_noct,
        "extra_diurna": float(fila.extra_diurna),
        "extra_nocturna": float(fila.extra_nocturna),
        "divisor_hora_mensual": float(fila.divisor_hora_mensual),
        "nota": fila.nota,
        "confirmar_contador": bool(fila.confirmar_contador),
    }


CAMPOS_EDITABLES = (
    "jornada_max_semanal", "hora_inicio_nocturna", "hora_fin_nocturna",
    "recargo_nocturno", "recargo_dominical", "recargo_dominical_nocturno",
    "extra_diurna", "extra_nocturna", "divisor_hora_mensual",
    "nota", "confirmar_contador",
)


def actualizar(db: Session, tasa_id: int, cambios: dict) -> TasaLaboral | None:
    """Edición desde la pantalla. `vigente_desde` NO se toca: cambiar la fecha de
    una vigencia reescribiría en silencio meses ya liquidados. Para corregir una
    fecha se crea otra vigencia."""
    fila = db.query(TasaLaboral).filter(TasaLaboral.id == tasa_id).first()
    if fila is None:
        return None
    for campo in CAMPOS_EDITABLES:
        if campo in cambios:
            setattr(fila, campo, cambios[campo])
    db.commit()
    db.refresh(fila)
    return fila


def crear(db: Session, datos: dict) -> TasaLaboral:
    """Nueva vigencia (cuando cambia la ley). Copia la vigente como base para que
    el usuario solo tenga que tocar lo que cambió."""
    vigente_desde = datos["vigente_desde"]
    if isinstance(vigente_desde, str):
        vigente_desde = date.fromisoformat(vigente_desde)
    base = tasa_vigente(db, vigente_desde)
    fila = TasaLaboral(
        vigente_desde=vigente_desde,
        jornada_max_semanal=datos.get("jornada_max_semanal", base.jornada_max_semanal),
        hora_inicio_nocturna=datos.get("hora_inicio_nocturna", base.hora_inicio_nocturna),
        hora_fin_nocturna=datos.get("hora_fin_nocturna", base.hora_fin_nocturna),
        recargo_nocturno=datos.get("recargo_nocturno", base.recargo_nocturno),
        recargo_dominical=datos.get("recargo_dominical", base.recargo_dominical),
        recargo_dominical_nocturno=datos.get("recargo_dominical_nocturno"),
        extra_diurna=datos.get("extra_diurna", base.extra_diurna),
        extra_nocturna=datos.get("extra_nocturna", base.extra_nocturna),
        divisor_hora_mensual=datos.get("divisor_hora_mensual", base.divisor_hora_mensual),
        nota=datos.get("nota"),
        confirmar_contador=bool(datos.get("confirmar_contador", True)),
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return fila
