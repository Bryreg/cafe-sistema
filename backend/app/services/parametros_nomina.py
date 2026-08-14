"""Salario mínimo, auxilio de transporte y aportes de ley, CON VIGENCIA.

Hermano de `tasas_laborales.py` y con la misma disciplina: acá no hay ni una
constante de plata. El mínimo y el auxilio se decretan cada diciembre y rigen
desde el 1 de enero; escribirlos en el código significaría que en enero el
sistema empieza a liquidar con el número del año pasado sin avisarle a nadie.

Resolver una fecha es «la última fila con vigente_desde <= fecha», así que
recalcular marzo de 2025 usa el mínimo de 2025 y da siempre el mismo resultado.

Agregar el año que viene = agregar un dict a SIEMBRA y desplegar. El seed nunca
pisa una fila existente: si el dueño corrigió un porcentaje desde la pantalla,
un deploy no se lo revierte.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.models import ParametroNomina

# ─── Vigencias sembradas ──────────────────────────────────────────────────────
# Cada entrada es un SNAPSHOT COMPLETO: repetir los porcentajes que no cambiaron
# es deliberado, para que leer una fila conteste sola y no haya que ir a buscar
# qué heredó de cuál. Ninguno de los porcentajes de aportes cambió para 2026;
# lo que cambia todos los años es el mínimo y el auxilio.
SIEMBRA: list[dict] = [
    {
        "vigente_desde": date(2025, 1, 1),
        "smmlv": 1_423_500.0,
        "auxilio_transporte": 200_000.0,
        "nota": ("SMMLV y auxilio 2025 (Decretos 1572 y 1573 de 2024, +9,54%). "
                 "Aportes y prestaciones: sin cambios respecto de 2024."),
    },
    {
        "vigente_desde": date(2026, 1, 1),
        "smmlv": 1_750_905.0,
        "auxilio_transporte": 249_095.0,
        "nota": ("SMMLV y auxilio 2026 (Decretos 1469 y 1470 del 29-dic-2025). "
                 "Suman $2.000.000 exactos. Un trabajador de 1 SMMLV con derecho "
                 "a auxilio recibe $1.859.928 netos tras salud y pensión. "
                 "Ningún porcentaje de aportes cambió para 2026."),
    },
]

# Valores por defecto de todo lo que NO cambia año a año. Viven acá y no en el
# modelo para que una vigencia nueva no tenga que repetirlos, pero el snapshot
# guardado en la base SÍ los lleva completos.
DEFAULTS: dict = {
    "dias_base_auxilio": 30,
    "tope_auxilio_smmlv": 2.0,
    "salud_empleado": 0.04,
    "pension_empleado": 0.04,
    "fsp_desde_smmlv": 4.0,
    "fsp_tarifa": 0.01,
    "salud_empleador": 0.085,
    "pension_empleador": 0.12,
    "arl": 0.00522,
    "caja_compensacion": 0.04,
    "sena": 0.02,
    "icbf": 0.03,
    # PRENDIDA: MEDIUM CAFÉ opera como PERSONA NATURAL con ~5 baristas, y el
    # art. 114-1 ET exonera a la persona natural empleadora que tenga DOS O MÁS
    # trabajadores (por cada uno que gane menos de 10 SMMLV). Lo que dejaría
    # afuera es tener un solo empleado. Apaga salud patronal 8,5% + SENA 2% +
    # ICBF 3%; la caja de compensación (4%) se sigue pagando siempre.
    #
    # Vale $236.372 por barista por mes, así que es editable y por sede-año:
    # si el negocio se constituye como sociedad, o si alguna vez queda con un
    # solo trabajador, esta fila es la que hay que corregir.
    "exonerado_114_1": True,
    "prima": 0.0833333,
    "cesantias": 0.0833333,
    "intereses_cesantias": 0.01,
    "vacaciones": 0.0416667,
    "confirmar_contador": True,
}


@dataclass(frozen=True)
class Parametros:
    """Snapshot CONGELADO para una liquidación entera.

    Igual que `tasas_laborales.Tasa`: se resuelve una vez por período y se pasa
    a las funciones puras, para que ningún cálculo pueda quedar mezclando dos
    vigencias distintas a mitad de camino.
    """
    vigente_desde: date
    smmlv: float
    auxilio_transporte: float
    dias_base_auxilio: int
    tope_auxilio_smmlv: float
    salud_empleado: float
    pension_empleado: float
    fsp_desde_smmlv: float
    fsp_tarifa: float
    salud_empleador: float
    pension_empleador: float
    arl: float
    caja_compensacion: float
    sena: float
    icbf: float
    exonerado_114_1: bool
    prima: float
    cesantias: float
    intereses_cesantias: float
    vacaciones: float
    confirmar_contador: bool

    @property
    def auxilio_por_dia(self) -> float:
        """El auxilio se prorratea con divisor 30 FIJO, no por días del mes."""
        base = int(self.dias_base_auxilio or 30) or 30
        return float(self.auxilio_transporte or 0.0) / base

    @property
    def tope_auxilio_pesos(self) -> float:
        """Sueldo máximo con derecho a auxilio, derivado del mínimo vigente."""
        return float(self.smmlv or 0.0) * float(self.tope_auxilio_smmlv or 0.0)


def sembrar(db: Session) -> int:
    """Crea las vigencias de SIEMBRA que falten. NUNCA pisa una existente."""
    existentes = {p.vigente_desde for p in db.query(ParametroNomina).all()}
    creadas = 0
    for datos in SIEMBRA:
        if datos["vigente_desde"] in existentes:
            continue
        db.add(ParametroNomina(**{**DEFAULTS, **datos}))
        creadas += 1
    if creadas:
        db.commit()
    return creadas


def listar(db: Session) -> list[ParametroNomina]:
    return db.query(ParametroNomina).order_by(ParametroNomina.vigente_desde.asc()).all()


def fila_vigente(db: Session, fecha: date) -> ParametroNomina | None:
    """Última fila con `vigente_desde <= fecha`.

    Si no resuelve, siembra y reintenta ANTES de caer en la más antigua: una
    base recién creada no puede liquidar con parámetros que no existen todavía.
    """
    def _buscar():
        return (db.query(ParametroNomina)
                .filter(ParametroNomina.vigente_desde <= fecha)
                .order_by(ParametroNomina.vigente_desde.desc())
                .first())

    fila = _buscar()
    if fila is not None:
        return fila
    if sembrar(db):
        fila = _buscar()
        if fila is not None:
            return fila
    # Fecha anterior a toda vigencia conocida: se usa la más antigua y se deja
    # que `confirmar_contador` haga el ruido. Inventar un mínimo sería peor.
    return db.query(ParametroNomina).order_by(ParametroNomina.vigente_desde.asc()).first()


def para(db: Session, fecha: date) -> Parametros | None:
    """Snapshot congelado vigente en esa fecha. None si no hay ninguna fila."""
    fila = fila_vigente(db, fecha)
    if fila is None:
        return None
    return Parametros(
        vigente_desde=fila.vigente_desde,
        smmlv=float(fila.smmlv or 0.0),
        auxilio_transporte=float(fila.auxilio_transporte or 0.0),
        dias_base_auxilio=int(fila.dias_base_auxilio or 30),
        tope_auxilio_smmlv=float(fila.tope_auxilio_smmlv or 0.0),
        salud_empleado=float(fila.salud_empleado or 0.0),
        pension_empleado=float(fila.pension_empleado or 0.0),
        fsp_desde_smmlv=float(fila.fsp_desde_smmlv or 0.0),
        fsp_tarifa=float(fila.fsp_tarifa or 0.0),
        salud_empleador=float(fila.salud_empleador or 0.0),
        pension_empleador=float(fila.pension_empleador or 0.0),
        arl=float(fila.arl or 0.0),
        caja_compensacion=float(fila.caja_compensacion or 0.0),
        sena=float(fila.sena or 0.0),
        icbf=float(fila.icbf or 0.0),
        exonerado_114_1=bool(fila.exonerado_114_1),
        prima=float(fila.prima or 0.0),
        cesantias=float(fila.cesantias or 0.0),
        intereses_cesantias=float(fila.intereses_cesantias or 0.0),
        vacaciones=float(fila.vacaciones or 0.0),
        confirmar_contador=bool(fila.confirmar_contador),
    )


def salario_del_contrato(contrato, params: Parametros | None) -> float:
    """Sueldo mensual de una persona para la fecha de esos parámetros.

    `salario_en_smmlv` MANDA sobre `salario_mensual`: si el contrato dice «1
    SMMLV», el sueldo es el mínimo vigente en la fecha liquidada, no el número
    que alguien tecleó alguna vez. Esa es la diferencia entre que en enero el
    sueldo suba solo y que alguien tenga que acordarse.
    """
    if contrato is None:
        return 0.0
    en_smmlv = getattr(contrato, "salario_en_smmlv", None)
    if en_smmlv and params is not None and params.smmlv:
        return round(float(en_smmlv) * float(params.smmlv), 2)
    return float(contrato.salario_mensual or 0.0)


MINIMO_TRABAJADORES_EXONERACION = 2


def alerta_exoneracion(db: Session, params: Parametros | None) -> str | None:
    """Avisa si la exoneración prendida podría no corresponder.

    La condición que la sostiene para una PERSONA NATURAL es tener DOS O MÁS
    trabajadores, y esa condición se puede perder sin que nadie toque el
    sistema: alcanza con que se vaya gente. El día que quede un solo empleado,
    la exoneración se cae y vuelven a deberse salud patronal, SENA e ICBF —
    retroactivamente para ese período, no desde que alguien se dé cuenta.

    OJO CON EL CONTEO: acá se cuentan los contratos cargados en ESTE sistema,
    que pueden ser menos que los trabajadores reales (un cocinero, alguien de
    aseo, un administrador que no usa la app). Por eso el mensaje no afirma que
    la exoneración esté mal: dice lo que el sistema ve y deja la conclusión al
    dueño. Un aviso que se equivoca seguido termina ignorado, y éste tiene que
    seguir doliendo el día que importe.
    """
    if params is None or not params.exonerado_114_1:
        return None
    from app.models.models import ContratoBarista
    n = db.query(ContratoBarista).filter(ContratoBarista.activo.is_(True)).count()
    if n >= MINIMO_TRABAJADORES_EXONERACION:
        return None
    return (
        f"La exoneración de aportes está prendida y exige "
        f"{MINIMO_TRABAJADORES_EXONERACION} trabajadores o más. El sistema ve "
        f"{n} contrato{'s' if n != 1 else ''} activo{'s' if n != 1 else ''}. "
        "Si en total tenés menos de dos empleados, no aplica y hay que pagar "
        "salud patronal, SENA e ICBF."
    )


def a_dict(fila: ParametroNomina) -> dict:
    return {
        "id": fila.id,
        "vigente_desde": fila.vigente_desde.isoformat(),
        "smmlv": float(fila.smmlv or 0.0),
        "auxilio_transporte": float(fila.auxilio_transporte or 0.0),
        "dias_base_auxilio": int(fila.dias_base_auxilio or 30),
        "tope_auxilio_smmlv": float(fila.tope_auxilio_smmlv or 0.0),
        "salud_empleado": float(fila.salud_empleado or 0.0),
        "pension_empleado": float(fila.pension_empleado or 0.0),
        "fsp_desde_smmlv": float(fila.fsp_desde_smmlv or 0.0),
        "fsp_tarifa": float(fila.fsp_tarifa or 0.0),
        "salud_empleador": float(fila.salud_empleador or 0.0),
        "pension_empleador": float(fila.pension_empleador or 0.0),
        "arl": float(fila.arl or 0.0),
        "caja_compensacion": float(fila.caja_compensacion or 0.0),
        "sena": float(fila.sena or 0.0),
        "icbf": float(fila.icbf or 0.0),
        "exonerado_114_1": bool(fila.exonerado_114_1),
        "prima": float(fila.prima or 0.0),
        "cesantias": float(fila.cesantias or 0.0),
        "intereses_cesantias": float(fila.intereses_cesantias or 0.0),
        "vacaciones": float(fila.vacaciones or 0.0),
        "nota": fila.nota,
        "confirmar_contador": bool(fila.confirmar_contador),
    }
