"""El libro del banco: una fila por día, como la hoja de tesorería del dueño.

    saldo_final(d) = saldo_inicial(d) + Σ entradas(d) − Σ salidas(d)
    saldo_inicial(d) = saldo_final(d − 1)

Es literalmente la fórmula de su Excel —`I = (B+C+D) − (H+E+F+G)`— y es la única
que contesta la pregunta que hace todos los días: ¿me alcanza el viernes?

═══════════════════════════════════════════════════════════════════════════════
DOS COSAS QUE ESTE MÓDULO NO HACE, A PROPÓSITO
═══════════════════════════════════════════════════════════════════════════════
1. NO DEDUCE lo que entró al banco. Podría sumar consignaciones y ventas con
   tarjeta, y daría un número que NUNCA coincide con el extracto: el datáfono
   liquida con rezago y con la comisión ya descontada. El dueño teclea, que es
   lo que hace hace años, y así el libro cuadra al peso contra el banco.
2. NO GUARDA el saldo de cada día. Se deriva del ancla más los movimientos.
   Guardarlo obligaría a reescribir la cadena entera al corregir un movimiento
   viejo, y un recálculo que falle a la mitad deja el libro partido sin que
   nadie lo note. Derivado, corregir un movimiento arregla todo aguas abajo
   solo — igual que arrastrar la fórmula en la hoja.

EL ANCLA. La cadena tiene que empezar en algún lado: `saldo_banco` y
`saldo_banco_fecha` en `configuracion`, que es el saldo que el dueño copió del
extracto ese día. Todo lo anterior al ancla no se conoce y no se inventa: la
serie arranca ahí y lo dice.
"""
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import CuentaBancaria, Configuracion, MovimientoBanco

CLAVE_SALDO = "saldo_banco"
CLAVE_SALDO_FECHA = "saldo_banco_fecha"

ENTRADA = "entrada"
SALIDA = "salida"
TIPOS = (ENTRADA, SALIDA)

# Las dos de MEDIUM CAFÉ, con los nombres de su hoja para que la columna del
# sistema y la del Excel se puedan leer una al lado de la otra.
CUENTAS_SEED = [
    {"nombre": "Occidente", "orden": 1,
     "nota": "Consignaciones en efectivo (Banco de Occidente)."},
    {"nombre": "Bold", "orden": 2,
     "nota": "Liquidaciones del datáfono. Llegan con rezago y con la comisión "
             "ya descontada: por eso se teclea lo que el banco depositó."},
]


def sembrar_cuentas(db: Session) -> int:
    """Crea las cuentas que falten. NUNCA pisa una existente ni la renombra."""
    existentes = {c.nombre for c in db.query(CuentaBancaria).all()}
    creadas = 0
    for datos in CUENTAS_SEED:
        if datos["nombre"] in existentes:
            continue
        db.add(CuentaBancaria(**datos))
        creadas += 1
    if creadas:
        db.commit()
    return creadas


def cuentas(db: Session, solo_activas: bool = True) -> list[CuentaBancaria]:
    q = db.query(CuentaBancaria)
    if solo_activas:
        q = q.filter(CuentaBancaria.activa.is_(True))
    return q.order_by(CuentaBancaria.orden.asc(), CuentaBancaria.id.asc()).all()


def ancla(db: Session) -> tuple[float, date | None]:
    """(saldo, fecha) del extracto que el dueño copió. Sin fecha no hay cadena.

    Devuelve fecha None cuando nunca se cargó: la serie lo declara en vez de
    arrancar de cero, porque un saldo de $0 inventado se lee como «no hay
    plata» y es la clase de mentira que dispara una decisión equivocada.
    """
    filas = {c.clave: c.valor for c in db.query(Configuracion).filter(
        Configuracion.clave.in_((CLAVE_SALDO, CLAVE_SALDO_FECHA))).all()}
    try:
        saldo = round(float(filas.get(CLAVE_SALDO) or 0), 2)
    except (TypeError, ValueError):
        saldo = 0.0
    crudo = (filas.get(CLAVE_SALDO_FECHA) or "").strip()
    try:
        fecha = date.fromisoformat(crudo) if crudo else None
    except ValueError:
        fecha = None
    return saldo, fecha


def _neto_hasta(db: Session, desde: date, hasta: date) -> float:
    """Σ(entradas − salidas) en [desde, hasta]. Una sola query, no un bucle."""
    if hasta < desde:
        return 0.0
    filas = (db.query(MovimientoBanco.tipo, func.sum(MovimientoBanco.monto))
             .filter(MovimientoBanco.fecha >= desde, MovimientoBanco.fecha <= hasta)
             .group_by(MovimientoBanco.tipo).all())
    neto = 0.0
    for tipo, total in filas:
        v = float(total or 0.0)
        neto += v if tipo == ENTRADA else -v
    return round(neto, 2)


def saldo_al_cierre(db: Session, dia: date) -> tuple[float, bool]:
    """(saldo al final de ese día, si la cadena llega hasta ahí).

    El bool es la honestidad del número: con un día ANTERIOR al ancla no se
    sabe cuánto había, y devolver el ancla igual sería afirmar un saldo que
    nadie midió.
    """
    base, fecha = ancla(db)
    if fecha is None or dia < fecha:
        return 0.0, False
    return round(base + _neto_hasta(db, fecha, dia), 2), True


def apertura(db: Session, dia: date) -> tuple[float, bool]:
    """(saldo con el que ARRANCA ese día, si la cadena llega hasta ahí).

    EL ANCLA ES UN SALDO DE APERTURA, y no es una convención arbitraria: es la
    de la hoja del dueño, donde el primer día de agosto arranca con el cierre
    de julio (`B4 = +JUNIO!I34`) y donde los ajustes que él carga a mano son
    siempre «con cuánto arranco este día». Por eso el día del ancla abre con
    ella y sus propios movimientos se suman encima; leerla como un cierre
    haría desaparecer los movimientos de ese día.
    """
    _base, fecha = ancla(db)
    if fecha is not None and dia == fecha:
        return _base, True
    return saldo_al_cierre(db, dia - timedelta(days=1))


def dias_del_mes(anio: int, mes: int) -> tuple[date, date]:
    ini = date(anio, mes, 1)
    fin = (date(anio + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1))
    return ini, fin


def libro(db: Session, desde: date, hasta: date) -> dict:
    """Una fila por día del rango, con la forma de la hoja del dueño.

    Cada fila: saldo con el que arranca, lo que entra abierto por cuenta, lo
    que sale abierto por cuenta, y el saldo con el que queda. La invariante que
    el módulo entero sostiene y que hay que poder verificar a ojo en pantalla:

        inicial + Σ entradas − Σ salidas == final

    Los días SIN movimientos también van: en la hoja también están, y son los
    que dejan ver que el saldo se quedó abajo cuatro días seguidos. Un libro
    que solo muestra los días con movimiento esconde justo lo que preocupa.
    """
    base, fecha_ancla = ancla(db)
    cta = cuentas(db, solo_activas=False)
    nombres = {c.id: c.nombre for c in cta}

    movs = (db.query(MovimientoBanco)
            .filter(MovimientoBanco.fecha >= desde, MovimientoBanco.fecha <= hasta)
            .order_by(MovimientoBanco.fecha.asc(), MovimientoBanco.id.asc()).all())
    por_dia: dict[date, list[MovimientoBanco]] = {}
    for m in movs:
        por_dia.setdefault(m.fecha, []).append(m)

    # Con cuánto arranca el PRIMER día del rango. `apertura` ya resuelve el caso
    # del día del ancla y declara si la cadena llega hasta ahí.
    saldo, hay_cadena = apertura(db, desde)

    filas = []
    d = desde
    while d <= hasta:
        delta = timedelta(days=1)
        del_dia = por_dia.get(d, [])
        entradas: dict[str, float] = {}
        salidas: dict[str, float] = {}
        for m in del_dia:
            destino = entradas if m.tipo == ENTRADA else salidas
            nom = nombres.get(m.cuenta_id, "—")
            destino[nom] = round(destino.get(nom, 0.0) + float(m.monto or 0.0), 2)
        tot_e = round(sum(entradas.values()), 2)
        tot_s = round(sum(salidas.values()), 2)
        inicial = round(saldo, 2)
        final = round(inicial + tot_e - tot_s, 2)
        filas.append({
            "fecha": d.isoformat(),
            "inicial": inicial,
            "entradas": entradas,
            "total_entradas": tot_e,
            "salidas": salidas,
            "total_salidas": tot_s,
            "final": final,
            # Para que la pantalla pueda pintar en rojo sin recalcular nada.
            "en_rojo": final < 0,
            "movimientos": [_a_dict(m, nombres) for m in del_dia],
        })
        saldo = final
        d += delta

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "cuentas": [{"id": c.id, "nombre": c.nombre, "activa": bool(c.activa),
                     "nota": c.nota} for c in cta],
        "ancla": {"saldo": base,
                  "fecha": fecha_ancla.isoformat() if fecha_ancla else None},
        # Si es False, los saldos de la serie no se pueden creer: la cadena no
        # llega hasta acá porque falta el saldo del extracto. Se declara en vez
        # de mostrar números que parecen buenos.
        "cadena_completa": hay_cadena,
        "dias": filas,
        "totales": {
            "entradas": round(sum(f["total_entradas"] for f in filas), 2),
            "salidas": round(sum(f["total_salidas"] for f in filas), 2),
            "final": filas[-1]["final"] if filas else round(saldo, 2),
            "dias_en_rojo": sum(1 for f in filas if f["en_rojo"]),
            # Los días que cerraron con poco: es el número que hace ver que el
            # colchón se adelgaza antes de que llegue a cero.
            "dia_mas_bajo": min((f["final"] for f in filas), default=None),
        },
    }


def _a_dict(m: MovimientoBanco, nombres: dict[int, str]) -> dict:
    return {
        "id": m.id,
        "fecha": m.fecha.isoformat(),
        "cuenta_id": m.cuenta_id,
        "cuenta": nombres.get(m.cuenta_id, "—"),
        "tipo": m.tipo,
        "monto": float(m.monto or 0.0),
        "concepto": m.concepto,
        "automatico": bool(m.automatico),
        "obligacion_id": m.obligacion_id,
        "nota": m.nota,
    }


def serie_mensual(db: Session, anio: int) -> dict:
    """Los 12 meses del año: entra, sale y con cuánto cierra cada uno.

    Es la vista que su Excel resuelve hace años y que el sistema no tenía en
    ninguna parte: la que deja ver que la facturación viene cayendo y que el
    saldo cierra en rojo dos meses del año.
    """
    meses = []
    for mes in range(1, 13):
        ini, fin = dias_del_mes(anio, mes)
        neto_e = (db.query(func.sum(MovimientoBanco.monto))
                  .filter(MovimientoBanco.fecha >= ini, MovimientoBanco.fecha <= fin,
                          MovimientoBanco.tipo == ENTRADA).scalar() or 0.0)
        neto_s = (db.query(func.sum(MovimientoBanco.monto))
                  .filter(MovimientoBanco.fecha >= ini, MovimientoBanco.fecha <= fin,
                          MovimientoBanco.tipo == SALIDA).scalar() or 0.0)
        cierre, cadena = saldo_al_cierre(db, fin)
        meses.append({
            "mes": mes,
            "entradas": round(float(neto_e), 2),
            "salidas": round(float(neto_s), 2),
            "neto": round(float(neto_e) - float(neto_s), 2),
            "cierre": cierre if cadena else None,
        })
    return {"anio": anio, "meses": meses}


def registrar(db: Session, fecha: date, cuenta_id: int, tipo: str, monto: float,
              concepto: str, usuario_id: int | None = None,
              obligacion_id: int | None = None, nota: str | None = None,
              automatico: bool = False) -> MovimientoBanco:
    """Un movimiento. El monto va SIEMPRE positivo: el signo lo pone el tipo.

    Aceptar negativos dejaría que una salida de −$100.000 sume plata, y ese
    error no se ve hasta que el saldo del mes no cuadra contra el extracto.
    """
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo}. Tiene que ser 'entrada' o 'salida'.")
    m = round(float(monto or 0.0), 2)
    if m <= 0:
        raise ValueError("El monto va en positivo: el signo lo decide si es "
                         "entrada o salida.")
    if not (concepto or "").strip():
        raise ValueError("Un movimiento sin concepto no se puede conciliar "
                         "después contra el extracto.")
    if db.query(CuentaBancaria).filter(CuentaBancaria.id == cuenta_id).first() is None:
        raise ValueError("Esa cuenta no existe.")
    mov = MovimientoBanco(
        fecha=fecha, cuenta_id=cuenta_id, tipo=tipo, monto=m,
        concepto=concepto.strip(), usuario_id=usuario_id,
        obligacion_id=obligacion_id, nota=(nota or None), automatico=automatico)
    db.add(mov)
    db.commit()
    db.refresh(mov)
    return mov


def borrar(db: Session, movimiento_id: int) -> bool:
    """Se borra de verdad y el saldo se reacomoda solo.

    No hay «anulado» acá a propósito: en un libro derivado, un movimiento
    anulado que siguiera sumando sería un saldo mentiroso, y uno que no sumara
    es exactamente lo mismo que no existir. Lo que sí queda es el registro de
    quién lo cargó, en `usuario_id`.
    """
    mov = db.query(MovimientoBanco).filter(MovimientoBanco.id == movimiento_id).first()
    if mov is None:
        return False
    db.delete(mov)
    db.commit()
    return True
