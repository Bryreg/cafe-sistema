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
import math
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.tz import dia_col, fin_dia_col_utc, inicio_dia_col_utc
from app.models.models import (Consignacion, CostoCategoria, CuentaBancaria,
                               Configuracion, FacturaCompra, MovimientoBanco,
                               Obligacion, Pago, RecogidaEfectivo)

CLAVE_SALDO = "saldo_banco"
CLAVE_SALDO_FECHA = "saldo_banco_fecha"

# Desde qué día las CONSIGNACIONES entran solas al libro como entradas de
# Occidente (la excepción medida a la regla «no deduce» del encabezado: una
# consignación ES un hecho bancario — el comprobante es literalmente la boleta
# del depósito, sin rezago ni comisión que adivinar; Bold sigue tecleado).
# Guardada en `configuracion` como el ancla del saldo, y SE FIJA UNA VEZ:
# moverla hacia atrás duplicaría contra lo ya tecleado, hacia adelante haría
# desaparecer plata — la misma trampa que `desde_recogidas` cerró con su ancla.
# Sin fijar, el libro es 100% tecleado, como siempre.
CLAVE_CONSIG_DESDE = "libro_consignaciones_desde"

# Mismo tope que usa `costos._leer_saldo_banco`: un saldo más grande que esto
# es un typo, no plata.
SALDO_MAX = 1e12

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
    # SE SANEA ACÁ, no aguas abajo. `configuracion` es texto libre y un `inf`
    # o un NaN metido ahí viajaba adentro de `dias[].inicial/final`: FastAPI
    # serializa con allow_nan=False, así que /banco/libro y /banco/serie
    # devolvían 500 y la pestaña entera no cargaba. El flujo proyectado tenía
    # su propia red; el libro no tenía ninguna.
    #
    # Y UN ANCLA PODRIDA NO ES UN ANCLA DE $0: ES NO TENER ANCLA. Saneando solo
    # el monto pero conservando la fecha, la cadena arrancaba desde un cero
    # inventado y el libro afirmaba «ese día tenías $0» sobre un dato que nadie
    # cargó. Sin fecha, `cadena` queda en false en todos los días y la pantalla
    # pide el saldo del extracto, que es exactamente lo que falta.
    crudo_saldo = filas.get(CLAVE_SALDO)
    try:
        saldo = round(float(crudo_saldo if crudo_saldo not in (None, "") else 0), 2)
        usable = math.isfinite(saldo) and 0 <= saldo <= SALDO_MAX
    except (TypeError, ValueError):
        saldo, usable = 0.0, False
    if not usable:
        return 0.0, None
    crudo = (filas.get(CLAVE_SALDO_FECHA) or "").strip()
    try:
        fecha = date.fromisoformat(crudo) if crudo else None
    except ValueError:
        fecha = None
    return saldo, fecha


def consignaciones_desde(db: Session) -> date | None:
    """El corte del régimen de consignaciones-al-libro, o None si no se activó."""
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_CONSIG_DESDE).first()
    crudo = ((fila.valor if fila else "") or "").strip()
    try:
        return date.fromisoformat(crudo) if crudo else None
    except ValueError:
        # Un corte podrido no es un corte de «desde siempre»: es no tener corte.
        return None


def _consigs_en_rango(db: Session, desde_d: date, hasta_d: date) -> list:
    """Las consignaciones que el libro proyecta en [desde_d, hasta_d].

    Entran TODAS las que caen desde el corte, `pendiente` y `realizada` por
    igual: la pendiente es un depósito afirmado con comprobante que el admin no
    confirmó todavía, y su plata YA está en el banco — dejarla afuera del saldo
    la haría aparecer días después, el día de la confirmación, que no es el día
    del depósito. El estado viaja en la fila para que la pantalla lo diga.

    Las filas con `fecha` NULL no entran a NINGÚN día: no se les inventa uno
    (ver `consignaciones_sin_fecha` en `libro`). El filtro >= las descarta solo,
    igual que en SQL cualquier comparación contra NULL.
    """
    corte = consignaciones_desde(db)
    if corte is None:
        return []
    lo = max(desde_d, corte)
    if hasta_d < lo:
        return []
    return (db.query(Consignacion)
            .filter(Consignacion.fecha >= inicio_dia_col_utc(lo),
                    Consignacion.fecha <= fin_dia_col_utc(hasta_d))
            .order_by(Consignacion.fecha.asc(), Consignacion.id.asc())
            .all())


def _neto_hasta(db: Session, desde: date, hasta: date) -> float:
    """Σ(entradas − salidas) en [desde, hasta]. Una sola query, no un bucle.

    Las consignaciones proyectadas SUMAN ACÁ ADENTRO y no en cada llamador: por
    esta función pasa toda la cadena (`saldo_al_cierre` → `apertura` → el libro
    y la serie), así que sumarlas en un solo lugar es lo que garantiza que el
    saldo del libro, el de la serie y el del flujo digan lo mismo.
    """
    if hasta < desde:
        return 0.0
    filas = (db.query(MovimientoBanco.tipo, func.sum(MovimientoBanco.monto))
             .filter(MovimientoBanco.fecha >= desde, MovimientoBanco.fecha <= hasta)
             .group_by(MovimientoBanco.tipo).all())
    neto = 0.0
    for tipo, total in filas:
        v = float(total or 0.0)
        neto += v if tipo == ENTRADA else -v
    neto += sum(float(c.valor or 0.0) for c in _consigs_en_rango(db, desde, hasta))
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
    # El catálogo entero en una query: el libro etiqueta con categorías de
    # cualquier ámbito (café, personal, banco) y resolverlas fila por fila
    # serían N queries por pintar un mes.
    categorias = {c.id: c for c in db.query(CostoCategoria).all()}

    movs = (db.query(MovimientoBanco)
            .filter(MovimientoBanco.fecha >= desde, MovimientoBanco.fecha <= hasta)
            .order_by(MovimientoBanco.fecha.asc(), MovimientoBanco.id.asc()).all())
    por_dia: dict[date, list[MovimientoBanco]] = {}
    for m in movs:
        por_dia.setdefault(m.fecha, []).append(m)

    # Las consignaciones proyectadas, cada una en SU día Colombia. Van en una
    # lista aparte de `movimientos` a propósito: no son filas tecleadas, no se
    # borran desde el libro (se corrigen en Consignaciones), y un bundle viejo
    # que no conozca la clave simplemente no las dibuja — los totales del día
    # igual las suman, así que el saldo no depende de la versión del cliente.
    corte_consig = consignaciones_desde(db)
    consigs_por_dia: dict[date, list] = {}
    for c in _consigs_en_rango(db, desde, hasta):
        consigs_por_dia.setdefault(dia_col(c.fecha), []).append(c)
    sin_fecha = []
    if corte_consig is not None:
        # Las filas legacy sin fecha existen (el modelo las tolera) y no se
        # ubican en un día inventado: se cuentan y se dicen.
        sin_fecha = db.query(Consignacion).filter(Consignacion.fecha.is_(None)).all()

    # Los PAGOS EN EFECTIVO del rango, cada uno en su día — informativos, JAMÁS
    # sumados al saldo: esa plata salió del cajón o de la mano y nunca pasó por
    # una cuenta. El libro los muestra porque el sistema ya los sabe y el día
    # tiene que contar su plata completa; sumarlos rompería la invariante
    # inicial + entra − sale = final contra el extracto.
    pagos_por_dia: dict[date, list[dict]] = {}
    for p in (db.query(Pago)
              .filter(Pago.metodo == "efectivo",
                      Pago.anulado == False,  # noqa: E712
                      Pago.fecha_pago >= desde, Pago.fecha_pago <= hasta)
              .order_by(Pago.fecha_pago.asc(), Pago.id.asc()).all()):
        pagos_por_dia.setdefault(p.fecha_pago, []).append(_pago_a_dict(db, p))

    # ── LA MANO DEL DUEÑO: la tercera bolsa, ahora DENTRO del libro ────────────
    # El efectivo que el dueño RECOGE es plata que entró (recogí = entrada), y lo
    # que paga en efectivo desde esa mano es plata que salió. El sub-saldo de la
    # mano es 100% DERIVADO —Σ recogidas − Σ pagos en efectivo— así que no
    # necesita ancla: la bolsa arrancó vacía y cada recogida y cada pago quedan
    # registrados. El banco sigue con su propia cadena contra el extracto; el
    # total del libro es banco + mano, y solo se conoce donde el banco tiene cadena.
    recogidas_por_dia: dict[date, list] = {}
    for r in (db.query(RecogidaEfectivo)
              .filter(RecogidaEfectivo.fecha >= desde, RecogidaEfectivo.fecha <= hasta)
              .order_by(RecogidaEfectivo.fecha.asc(), RecogidaEfectivo.id.asc()).all()):
        recogidas_por_dia.setdefault(r.fecha, []).append(r)

    # La mano que viene de ANTES del rango: lo recogido menos lo pagado en
    # efectivo hasta la víspera. Sin esto, un mes mirado suelto arrancaría la mano
    # en cero y perdería el efectivo recogido en los meses anteriores.
    rec_antes = (db.query(func.coalesce(func.sum(RecogidaEfectivo.monto), 0.0))
                 .filter(RecogidaEfectivo.fecha < desde).scalar() or 0.0)
    pag_antes = (db.query(func.coalesce(func.sum(Pago.monto), 0.0))
                 .filter(Pago.metodo == "efectivo", Pago.anulado == False,  # noqa: E712
                         Pago.fecha_pago < desde).scalar() or 0.0)
    mano_saldo = round(float(rec_antes) - float(pag_antes), 2)

    # ── LA CADENA SE DECIDE POR DÍA, NO POR MES ───────────────────────────────
    # Antes había UNA bandera para todo el rango, calculada mirando solo el
    # primer día. Con el ancla a mitad de mes —que es el caso NORMAL, porque el
    # editor propone hoy y el sistema pide actualizar el extracto cada 7 días—
    # el mes entero quedaba marcado «sin saldos» aunque del ancla en adelante
    # el saldo sea exacto, y la pantalla le pedía al dueño que cargara lo que
    # acababa de cargar. Es la misma familia de siempre: la bandera se prendía
    # por la FORMA (dónde cae el día 1 respecto del ancla) y no por la pregunta
    # real, que es «¿se conoce el saldo de ESTE día?».
    #
    # Cada fila trae ahora su propio `cadena`. Antes del ancla no se sabe cuánta
    # plata había y los saldos van en null: un número ahí sería inventado.
    saldo = None
    filas = []
    d = desde
    while d <= hasta:
        delta = timedelta(days=1)
        del_dia = por_dia.get(d, [])
        consigs_del_dia = consigs_por_dia.get(d, [])
        entradas: dict[str, float] = {}
        salidas: dict[str, float] = {}
        for m in del_dia:
            destino = entradas if m.tipo == ENTRADA else salidas
            nom = nombres.get(m.cuenta_id, "—")
            destino[nom] = round(destino.get(nom, 0.0) + float(m.monto or 0.0), 2)
        # Lo consignado del día entra a la columna Occidente — es su definición
        # (efectivo que se consigna), con el nombre de la hoja del dueño.
        for c in consigs_del_dia:
            entradas["Occidente"] = round(
                entradas.get("Occidente", 0.0) + float(c.valor or 0.0), 2)
        tot_e = round(sum(entradas.values()), 2)
        tot_s = round(sum(salidas.values()), 2)

        if fecha_ancla is not None and d == fecha_ancla:
            # El ancla es una APERTURA: este día arranca con ella.
            saldo = base
        elif saldo is None and fecha_ancla is not None and desde > fecha_ancla:
            # El rango arranca DESPUÉS del ancla: el saldo del primer día se
            # trae encadenando desde el ancla hacia acá.
            saldo, _ok = apertura(db, d)

        con_cadena = saldo is not None
        inicial = round(saldo, 2) if con_cadena else None
        final = round(inicial + tot_e - tot_s, 2) if con_cadena else None

        # La mano del día: lo recogido entra, lo pagado en efectivo sale. El
        # sub-saldo corre solo (derivado), exista o no la cadena del banco.
        pagos_dia = pagos_por_dia.get(d, [])
        recog_dia = recogidas_por_dia.get(d, [])
        mano_e = round(sum(float(r.monto or 0.0) for r in recog_dia), 2)
        mano_s = round(sum(float(p["monto"] or 0.0) for p in pagos_dia), 2)
        mano_saldo = round(mano_saldo + mano_e - mano_s, 2)
        # El total (banco + mano) solo se conoce donde el banco tiene cadena: sin
        # el saldo del banco no hay total, y un número ahí sería inventado.
        total_final = round(final + mano_saldo, 2) if con_cadena else None

        filas.append({
            "fecha": d.isoformat(),
            "cadena": con_cadena,
            "inicial": inicial,
            "entradas": entradas,
            "total_entradas": tot_e,
            "salidas": salidas,
            "total_salidas": tot_s,
            "final": final,
            # Para pintar en rojo sin recalcular. Sin cadena no hay rojo posible:
            # un saldo que no se conoce no puede estar en negativo.
            "en_rojo": bool(con_cadena and final < 0),
            # La mano del dueño, DENTRO del libro: recogido (entradas), pagos en
            # efectivo (salidas) y el sub-saldo derivado. `total_final` = banco + mano.
            "recogido": [{"id": r.id, "tienda_id": r.tienda_id,
                          "monto": float(r.monto or 0.0), "nota": r.nota}
                         for r in recog_dia],
            "mano_entradas": mano_e,
            "mano_salidas": mano_s,
            "mano_saldo": mano_saldo,
            "total_final": total_final,
            "movimientos": [_a_dict(m, nombres, categorias) for m in del_dia],
            "pagos_efectivo": pagos_dia,
            "consignaciones": [{
                "consignacion_id": c.id,
                "tienda_id": c.tienda_id,
                "valor": float(c.valor or 0.0),
                "estado": (c.estado.value if hasattr(c.estado, "value")
                           else c.estado),
                "barista_nombre": c.barista_nombre,
                "imagen_url": c.imagen_url,
            } for c in consigs_del_dia],
        })
        saldo = final
        d += delta

    con_saldo = [f for f in filas if f["cadena"]]
    hay_cadena = len(con_saldo) == len(filas) and bool(filas)

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "cuentas": [{"id": c.id, "nombre": c.nombre, "activa": bool(c.activa),
                     "nota": c.nota} for c in cta],
        "ancla": {"saldo": base,
                  "fecha": fecha_ancla.isoformat() if fecha_ancla else None},
        # True solo si TODOS los días del rango tienen saldo. La pantalla no
        # debería decidir con esto: cada fila trae su `cadena` y los días
        # posteriores al ancla son exactos aunque el mes arranque antes.
        "cadena_completa": hay_cadena,
        # Los días del rango que sí tienen saldo. Con el ancla a mitad de mes
        # esto es lo que deja decir «los saldos arrancan el 16» en vez de
        # apagar el mes entero.
        "dias_con_saldo": len(con_saldo),
        "primer_dia_con_saldo": con_saldo[0]["fecha"] if con_saldo else None,
        # El régimen de consignaciones-al-libro: desde cuándo entran solas
        # (null = todavía tecleado, como siempre), y las filas legacy sin fecha
        # que NO están en ningún día — se dicen, no se ubican en uno inventado.
        "consignaciones_desde": (corte_consig.isoformat()
                                 if corte_consig is not None else None),
        "consignaciones_sin_fecha": {
            "n": len(sin_fecha),
            "total": round(sum(float(c.valor or 0.0) for c in sin_fecha), 2),
        },
        # La tasa del GMF (4×1000) con vigencia, para que la pantalla pueda
        # SUGERIR la fila al registrar una salida. Es el primer consumidor real
        # del parámetro: estaba sembrado desde el arranque y ningún cálculo lo
        # miraba, mientras el impuesto salía del banco igual — $3,4 millones en
        # siete meses que ningún reporte veía.
        "tasa_gmf": _tasa_gmf(db, hasta),
        "dias": filas,
        "totales": {
            "entradas": round(sum(f["total_entradas"] for f in filas), 2),
            "salidas": round(sum(f["total_salidas"] for f in filas), 2),
            "final": filas[-1]["final"] if filas else None,
            # La mano del dueño: lo que entró y salió en efectivo este mes, y con
            # cuánto queda la bolsa (derivada, siempre conocida). El total del
            # libro (banco + mano) solo se sabe donde el banco tiene cadena.
            "mano_entradas": round(sum(f["mano_entradas"] for f in filas), 2),
            "mano_salidas": round(sum(f["mano_salidas"] for f in filas), 2),
            "mano_final": filas[-1]["mano_saldo"] if filas else None,
            "total_final": filas[-1]["total_final"] if filas else None,
            "dias_en_rojo": sum(1 for f in filas if f["en_rojo"]),
            # Solo entre los días CON saldo: el mínimo de una lista que incluye
            # nulos no significa nada, y el día más bajo es justo el número que
            # hace ver que el colchón se adelgaza antes de llegar a cero.
            "dia_mas_bajo": min((f["final"] for f in con_saldo), default=None),
            "fecha_dia_mas_bajo": (
                min(con_saldo, key=lambda f: f["final"])["fecha"] if con_saldo else None),
        },
    }


def _pago_a_dict(db: Session, p: Pago) -> dict:
    """Un pago en efectivo, con el nombre de lo que pagó.

    El detalle se resuelve del padre (obligación o factura) porque `Pago` no
    tiene concepto propio; si el padre ya no existe (las facturas se borran de
    verdad), se dice el número y no se inventa un nombre.
    """
    detalle = None
    if p.obligacion_id is not None:
        o = db.get(Obligacion, p.obligacion_id)
        detalle = o.concepto if o is not None else f"Obligación #{p.obligacion_id}"
    elif p.factura_id is not None:
        f = db.get(FacturaCompra, p.factura_id)
        detalle = (f"Proveedor: {f.proveedor}" if f is not None
                   else f"Factura #{p.factura_id}")
    return {
        "pago_id": p.id,
        "monto": float(p.monto or 0.0),
        "detalle": detalle,
        "nota": p.nota,
    }


def _tasa_gmf(db: Session, al_dia: date) -> float | None:
    """La tasa vigente del 4×1000, o None si no se puede leer: la sugerencia
    del GMF se apaga antes que proponer un monto con una tasa inventada."""
    from app.services import parametros_tributarios as ptsvc   # local: sin ciclo
    try:
        tasa = float(ptsvc.para(db, al_dia).gmf or 0.0)
    except Exception:
        return None
    return tasa if 0 < tasa < 1 else None


def _a_dict(m: MovimientoBanco, nombres: dict[int, str],
            categorias: dict | None = None) -> dict:
    cat = (categorias or {}).get(m.categoria_id)
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
        # La categoría, resuelta a display: null = «sin clasificar», que es un
        # estado válido del libro, no un error.
        "categoria_id": m.categoria_id,
        "categoria": cat.nombre if cat else None,
        "categoria_clave": cat.clave if cat else None,
        "categoria_ambito": (getattr(cat, "ambito", None) if cat else None),
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
        # Las consignaciones proyectadas son entradas del mes igual que en el
        # libro: sin esta suma la serie y el libro dirían dos totales distintos
        # para el mismo mes (el cierre ya las trae — viaja por la cadena).
        neto_e += sum(float(c.valor or 0.0) for c in _consigs_en_rango(db, ini, fin))
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


# Cuántos meses completos de historial hacen falta para animarse a proyectar.
# Con menos, cualquier número es una casualidad disfrazada de tendencia: mejor
# decir «todavía no hay base» que inventar una calma (o un susto) que no se midió.
_MIN_MESES_PROYECCION = 3
# El techo de la ventana: se mira a lo sumo este tanto de meses hacia atrás. Un
# café cambia —sube el arriendo, se va un empleado— y arrastrar dos años de
# historia haría que lo viejo pese igual que lo de ahora.
_MESES_VENTANA_PROYECCION = 6


def _mes_menos(anio: int, mes: int, n: int) -> tuple[int, int]:
    """El (año, mes) que queda `n` meses ANTES de (anio, mes). Aritmética pura."""
    total = (anio * 12 + (mes - 1)) - n
    return total // 12, (total % 12) + 1


def _mes_mas(anio: int, mes: int, n: int) -> tuple[int, int]:
    """El (año, mes) que queda `n` meses DESPUÉS de (anio, mes)."""
    total = (anio * 12 + (mes - 1)) + n
    return total // 12, (total % 12) + 1


def proyeccion(db: Session, hoy: date, meses: int = 3) -> dict:
    """«LO QUE VIENE»: con cuánto van a cerrar los próximos meses, ESTIMADO.

    Es una guía para prepararse, no una promesa —y la pantalla lo dice—: sale
    del ritmo que el libro ya vivió, no de un deseo. La cuenta, a propósito, es
    modesta y se puede explicar en una línea:

      · Se miran los meses COMPLETOS anteriores a este (el mes en curso está a
        medias y mentiría el promedio), a lo sumo los últimos seis.
      · De esos meses se toma la MEDIANA del neto (entró − salió), no el
        promedio: un mes con una compra grande de café no arrastra la tendencia
        entera hacia abajo. La mediana es lo que este módulo entiende por
        «un mes normal».
      · Desde el saldo que HOY se conoce, se le suma ese neto normal una vez por
        cada mes que viene.

    DOS PUERTAS, y ninguna inventa un número:
      · Sin ancla del extracto no hay desde dónde arrancar la cadena → `sin_base`.
      · Con menos de tres meses completos con movimiento, cualquier tendencia es
        casualidad → `sin_base`, diciendo cuántos meses hay.

    Devuelve SIEMPRE las mismas claves (`base`, `meses`, `motivo`) para que la
    pantalla distinga «no hay con qué proyectar» de «no pude preguntar» sin
    adivinar por la forma de la respuesta.
    """
    meses = max(1, min(int(meses or 3), 12))
    anio_hoy, mes_hoy = hoy.year, hoy.month

    saldo_hoy, hay_cadena = saldo_al_cierre(db, hoy)
    if not hay_cadena:
        return {"base": None, "meses": [],
                "motivo": "Todavía no cargaste el saldo del extracto, así que no "
                          "hay desde dónde proyectar."}

    # Los meses completos anteriores a este, del más viejo al más nuevo, y solo
    # los que tuvieron movimiento: un mes sin un peso movido no es un «mes
    # normal», es un mes sin datos, y meterlo tira la mediana hacia el cero.
    netos = []
    for atras in range(_MESES_VENTANA_PROYECCION, 0, -1):
        a, m = _mes_menos(anio_hoy, mes_hoy, atras)
        ini, fin = dias_del_mes(a, m)
        ent = (db.query(func.sum(MovimientoBanco.monto))
               .filter(MovimientoBanco.fecha >= ini, MovimientoBanco.fecha <= fin,
                       MovimientoBanco.tipo == ENTRADA).scalar() or 0.0)
        ent += sum(float(c.valor or 0.0) for c in _consigs_en_rango(db, ini, fin))
        sal = (db.query(func.sum(MovimientoBanco.monto))
               .filter(MovimientoBanco.fecha >= ini, MovimientoBanco.fecha <= fin,
                       MovimientoBanco.tipo == SALIDA).scalar() or 0.0)
        if float(ent) > 0 or float(sal) > 0:
            netos.append(round(float(ent) - float(sal), 2))

    if len(netos) < _MIN_MESES_PROYECCION:
        return {"base": None, "meses": [],
                "motivo": f"Hacen falta al menos {_MIN_MESES_PROYECCION} meses "
                          f"con movimiento para estimar; hay {len(netos)}."}

    neto_normal = round(_mediana(netos), 2)

    filas = []
    acumulado = saldo_hoy
    for i in range(1, meses + 1):
        a, m = _mes_mas(anio_hoy, mes_hoy, i)
        acumulado = round(acumulado + neto_normal, 2)
        filas.append({"anio": a, "mes": m, "cierre_estimado": acumulado})

    return {
        "base": {
            "saldo_hoy": round(saldo_hoy, 2),
            "neto_normal": neto_normal,
            "meses_de_historial": len(netos),
        },
        "meses": filas,
        "motivo": None,
    }


def _mediana(xs: list[float]) -> float:
    """La mediana, sin `import statistics`: son a lo sumo seis números y así el
    módulo no suma una dependencia por una cuenta de dos líneas."""
    ys = sorted(xs)
    n = len(ys)
    medio = n // 2
    if n % 2 == 1:
        return ys[medio]
    return (ys[medio - 1] + ys[medio]) / 2.0


def registrar(db: Session, fecha: date, cuenta_id: int, tipo: str, monto: float,
              concepto: str, usuario_id: int | None = None,
              obligacion_id: int | None = None, nota: str | None = None,
              automatico: bool = False, commit: bool = True,
              categoria_id: int | None = None) -> MovimientoBanco:
    """Un movimiento. El monto va SIEMPRE positivo: el signo lo pone el tipo.

    Aceptar negativos dejaría que una salida de −$100.000 sume plata, y ese
    error no se ve hasta que el saldo del mes no cuadra contra el extracto.

    `commit=False` es para quien compone el movimiento DENTRO de su propia
    transacción (el pago que descuenta del banco en el mismo gesto): un commit
    acá partiría esa operación en dos mitades que pueden quedar desparejas —
    exactamente lo que la composición viene a evitar.
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
    if (categoria_id is not None and
            db.query(CostoCategoria).filter(
                CostoCategoria.id == categoria_id).first() is None):
        raise ValueError("Esa categoría no existe — recargá la pantalla y "
                         "volvé a elegir.")
    mov = MovimientoBanco(
        fecha=fecha, cuenta_id=cuenta_id, tipo=tipo, monto=m,
        concepto=concepto.strip(), usuario_id=usuario_id,
        obligacion_id=obligacion_id, categoria_id=categoria_id,
        nota=(nota or None), automatico=automatico)
    db.add(mov)
    if commit:
        db.commit()
        db.refresh(mov)
    else:
        db.flush()
    return mov


def por_categoria_anual(db: Session, anio: int) -> dict:
    """«Cuánto nos estamos gastando en cada cosa», MES A MES.

    La pregunta del dueño es la SERIE a lo largo de los meses, no un total del
    mes suelto: el arriendo que sube, la casa que pesa cada vez más, el GMF que
    nadie veía. Sale de las SALIDAS del libro agrupadas por su categoría; lo
    tecleado sin categoría va en «Sin clasificar» — un estado dicho, nunca un
    cero escondido ni una categoría inventada.

    La agregación por mes corre en Python a propósito: extraer el mes de una
    fecha en SQL es distinto en SQLite y en Postgres, y un año de salidas son
    cientos de filas, no millones.
    """
    filas = (db.query(MovimientoBanco.categoria_id, MovimientoBanco.fecha,
                      MovimientoBanco.monto)
             .filter(MovimientoBanco.tipo == SALIDA,
                     MovimientoBanco.fecha >= date(anio, 1, 1),
                     MovimientoBanco.fecha <= date(anio, 12, 31)).all())
    cats = {c.id: c for c in db.query(CostoCategoria).all()}

    acum: dict[int | None, list[float]] = {}
    for cat_id, fecha, monto in filas:
        clave = cat_id if cat_id in cats else None
        meses = acum.setdefault(clave, [0.0] * 12)
        meses[fecha.month - 1] += float(monto or 0.0)

    salida = []
    for cat_id, meses in acum.items():
        c = cats.get(cat_id)
        salida.append({
            "categoria_id": cat_id,
            "clave": c.clave if c else None,
            "nombre": c.nombre if c else "Sin clasificar",
            "ambito": (getattr(c, "ambito", None) if c else None),
            "meses": [round(m, 2) for m in meses],
            "total": round(sum(meses), 2),
        })
    # Por plata, que es como se lee: «qué me está costando más este año».
    salida.sort(key=lambda x: (-x["total"], x["nombre"]))
    return {"anio": anio, "categorias": salida}


def preview_consignaciones(db: Session, desde: date) -> dict:
    """Qué pasaría si las consignaciones entraran al libro desde `desde`.

    La activación no puede ser un default silencioso: si el dueño ya venía
    tecleando las entradas de Occidente, proyectar encima las cuenta DOS veces.
    Esta vista previa trae las dos mitades con sus números — lo que entraría
    solo, y lo tecleado en ese rango que habría que revisar — para que él
    active viendo exactamente qué cambia. Es el patrón del impoconsumo: la
    decisión con las cifras en pantalla, nunca un interruptor a ciegas.
    """
    consigs = (db.query(Consignacion)
               .filter(Consignacion.fecha >= inicio_dia_col_utc(desde)).all())
    occ = db.query(CuentaBancaria).filter(CuentaBancaria.nombre == "Occidente").first()
    tecleadas = []
    if occ is not None:
        tecleadas = (db.query(MovimientoBanco)
                     .filter(MovimientoBanco.fecha >= desde,
                             MovimientoBanco.tipo == ENTRADA,
                             MovimientoBanco.cuenta_id == occ.id)
                     .order_by(MovimientoBanco.fecha.asc()).all())
    return {
        "desde": desde.isoformat(),
        "consignaciones": {
            "n": len(consigs),
            "total": round(sum(float(c.valor or 0.0) for c in consigs), 2),
        },
        "tecleadas_en_rango": {
            "n": len(tecleadas),
            "total": round(sum(float(m.monto or 0.0) for m in tecleadas), 2),
            "movimientos": [{"id": m.id, "fecha": m.fecha.isoformat(),
                             "monto": float(m.monto or 0.0),
                             "concepto": m.concepto} for m in tecleadas],
        },
        "ya_activado_desde": (consignaciones_desde(db).isoformat()
                              if consignaciones_desde(db) else None),
    }


def activar_consignaciones(db: Session, desde: date) -> dict:
    """Fija el corte del régimen. UNA vez, como el ancla de las recogidas:
    un corte que se mueve es plata que aparece o desaparece sola."""
    vigente = consignaciones_desde(db)
    if vigente is not None:
        raise ValueError(
            f"Las consignaciones ya entran solas al libro desde el "
            f"{vigente.isoformat()}. El corte no se mueve: hacia atrás "
            "duplicaría contra lo ya tecleado y hacia adelante haría "
            "desaparecer plata del libro.")
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_CONSIG_DESDE).first()
    if fila is None:
        db.add(Configuracion(clave=CLAVE_CONSIG_DESDE, valor=desde.isoformat()))
    else:
        fila.valor = desde.isoformat()
    db.commit()
    return {"consignaciones_desde": desde.isoformat()}


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
