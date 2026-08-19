from bisect import bisect_right

from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from fastapi import HTTPException
from app.core.tz import fin_dia_col_utc, inicio_dia_col_utc
from app.models.models import (Consignacion, EstadoConsignacionEnum,
                                CajaTurno, MovimientoCaja, PrestamoCajaFuerte,
                                RecogidaEfectivo, Tienda, EstadoTurnoEnum)


# ── Precarga por sede ───────────────────────────────────────────────────────
#
# ACÁ NO CAMBIA NINGUNA CUENTA, CAMBIA CUÁNTAS VECES SE LE PREGUNTA A LA BASE.
# `_saldos_consignacion` recorre TODOS los turnos cerrados de la sede y pedía,
# por cada uno, sus movimientos, sus consignaciones y el saldo prestado de la
# caja fuerte: tres queries por turno. Se bancaba mientras el único que llamaba
# era la imputación —una vez por acción del dueño—, pero desde que la pantalla de
# Consignaciones lee de acá son miles de queries por pintar la tabla en una sede
# con un año de historia, en cada F5.
#
# Esto trae lo mismo en cuatro queries por sede y lo agrupa en memoria. Son los
# mismos registros sumados en el mismo orden: si algo de acá mueve un peso, está
# mal escrito, no es un ajuste.

def _precargar_sede(db: Session, tienda_id: int) -> dict:
    """Movimientos, consignaciones y traslados de caja fuerte de una sede, agrupados.

    Se filtra por SEDE y no por una lista de `turno_id`: un `IN (...)` con los
    turnos de un año revienta el tope de variables de SQLite (mismo motivo que
    documenta `_subquery_adoptados` en services/costos.py).
    """
    movs: dict[int, list] = {}
    filas_mov = (
        db.query(MovimientoCaja)
        .join(CajaTurno, MovimientoCaja.caja_turno_id == CajaTurno.id)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        )
        # `id` como desempate: dos movimientos con la misma hora tienen que salir
        # siempre en el mismo orden o el detalle de la pantalla salta entre cargas.
        .order_by(MovimientoCaja.fecha, MovimientoCaja.id)
        .all()
    )
    for m in filas_mov:
        movs.setdefault(m.caja_turno_id, []).append(m)

    consigs: dict[int, list] = {}
    filas_consig = (
        db.query(Consignacion)
        .join(CajaTurno, Consignacion.caja_turno_id == CajaTurno.id)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        )
        .all()
    )
    for c in filas_consig:
        consigs.setdefault(c.caja_turno_id, []).append(c)

    # Las legacy SIN FK van aparte y sin agrupar: se emparejan por ventana de
    # fecha, turno por turno (ver `_consigs_del_turno`), así que no hay clave por
    # la cual indexarlas.
    huerfanas = db.query(Consignacion).filter(
        Consignacion.tienda_id == tienda_id,
        Consignacion.caja_turno_id.is_(None),
    ).all()

    # Prefijos acumulados de la caja fuerte. `prestado_caja_fuerte` es
    # Σ('saca') − Σ('devuelve') hasta un instante, y preguntarlo turno por turno
    # era la tercera query por turno. Con las filas ordenadas por fecha ese saldo
    # sale de un `bisect` sobre dos acumulados.
    #
    # LOS DOS SENTIDOS SE ACUMULAN POR SEPARADO y se restan al final, igual que la
    # query original. Acumular un solo total con el signo ya aplicado daría el
    # mismo peso por otro camino, y en este módulo el camino es la prueba: la
    # función de allá también devuelve negativo a propósito cuando alguien cargó
    # un 'devuelve' que nunca salió, y ese absurdo tiene que seguir viéndose.
    fechas: list = []
    acum_saca: list = [0.0]
    acum_devuelve: list = [0.0]
    for fecha, sentido, monto in (
        db.query(PrestamoCajaFuerte.fecha, PrestamoCajaFuerte.sentido,
                 PrestamoCajaFuerte.monto)
        .filter(PrestamoCajaFuerte.tienda_id == tienda_id)
        .order_by(PrestamoCajaFuerte.fecha, PrestamoCajaFuerte.id)
        .all()
    ):
        valor = float(monto or 0)
        fechas.append(fecha)
        acum_saca.append(acum_saca[-1] + (valor if sentido == "saca" else 0.0))
        acum_devuelve.append(acum_devuelve[-1] + (valor if sentido == "devuelve" else 0.0))

    return {
        "movs": movs,
        "consigs": consigs,
        "consigs_huerfanas": huerfanas,
        "prestamo_fechas": fechas,
        "prestamo_saca": acum_saca,
        "prestamo_devuelve": acum_devuelve,
    }


def _prestado_hasta(pre: dict, hasta: datetime | None) -> float:
    """El saldo prestado de la caja fuerte a un instante, leído de la precarga.

    Devuelve el MISMO número que `prestado_caja_fuerte(db, tienda_id, hasta=...)`,
    negativos incluidos. `bisect_right` toma todas las filas con `fecha <= hasta`
    —también las empatadas en el mismo instante—, que es exactamente lo que hace
    el `<=` de aquella query.
    """
    fechas = pre["prestamo_fechas"]
    k = len(fechas) if hasta is None else bisect_right(fechas, hasta)
    return round(pre["prestamo_saca"][k] - pre["prestamo_devuelve"][k], 2)


def _sobrante_explicado_por_la_base(db: Session, t, prestado: float | None = None,
                                    ingresos: float = 0.0) -> float:
    """Cuánto del sobrante YA CONGELADO de un turno lo explica la base prestada.

    `diferencia_cierre` y `sobrante_consignable` se escriben AL CERRAR y quedan
    quietos. Con el cuadre arreglado ya no se fabrican solos, pero los turnos que
    cerraron ANTES de que se registrara el préstamo los tienen adentro: Palmetto,
    sábado 15-ago, cerró con $500.000 de sobrante congelado. Registrar el traslado
    hoy no reescribe esa columna, así que sin esta función el sábado seguiría
    pidiendo $697.900 — o sea, el arreglo serviría para los sábados que vienen y
    no para el que el dueño necesita.

    SE COMPARA CONTRA LOS TRES TÉRMINOS QUE NO SON VENTA, no contra dos. La
    primera versión miraba solo `diferencia_cierre + sobrante_consignable`, y con
    eso el sábado de Palmetto seguía pidiendo $697.900: la base había entrado como
    un INGRESO DE CAJA, que la fórmula suma y esta función no miraba. La plata que
    entra de la caja fuerte puede aparecer por cualquiera de los tres caminos
    según cómo la haya cargado la barista, así que se compara contra la suma.

    LOS DOS TOPES SON EL DISEÑO, y son lo que hace que esto no reste dos veces:

      · solo cancela lo que NO es venta y es positivo (`extra <= 0` devuelve 0).
        Un faltante no lo explica una base que entró, y la venta del día nunca se
        toca: el tope la deja siempre afuera;
      · nunca cancela más de lo que había prestado al cierre.

    De ahí sale que se regule solo: un turno que cierra CON el préstamo ya
    registrado no fabrica sobrante —el cuadre lo esperaba— así que `extra` es 0 y
    esto devuelve 0. La resta ocurre exactamente una vez, en el mundo viejo o en
    el nuevo, nunca en los dos.

    Se acota contra el saldo VIGENTE al cierre y no contra lo movido en ESE turno:
    la base puede haber salido el viernes y el sobrante aparecer el sábado, y en
    ese caso el delta del sábado es cero pero la plata está igual de prestada.

    `prestado` es el saldo al cierre YA CALCULADO por el que llama (lo trae la
    precarga de la sede, para no pedir una query por turno). Cuando no viene se
    consulta acá, que es el camino que usa cualquier llamador suelto.
    """
    from app.services.caja import prestado_caja_fuerte   # local: evita el ciclo

    extra = (float(ingresos or 0)
             + float(t.diferencia_cierre or 0)
             + float(t.sobrante_consignable or 0))
    if extra <= 0 or t.fecha_cierre is None:
        return 0.0
    if prestado is None:
        prestado = prestado_caja_fuerte(db, t.tienda_id, hasta=t.fecha_cierre)
    return round(min(extra, max(prestado, 0.0)), 2)


def _esperado_del_turno(t, ingresos: float, egresos: float,
                        sobrante_de_la_base: float) -> float:
    """La fórmula CRUDA del consignable de un turno, sin cascada. Escrita UNA vez.

    Vivía duplicada —acá y adentro de `get_resumen_admin`—, y esa duplicación es
    la grieta por la que la pantalla y la imputación empezaron a decir cosas
    distintas sobre la misma plata. Dos copias idénticas hoy son dos copias
    distintas el día que alguien toque una sola.

    esperado = ventas en efectivo + ingresos de caja − egresos en efectivo (contado)
    + diferencia del cierre. Incluir la diferencia hace que "por consignar" del
    turno sea EXACTAMENTE la base con la que arranca el día siguiente
    (efectivo_final − base_real): la plata física que queda en el cajón es la que
    viaja al banco. Solo el efectivo mueve esto: crédito y bancos no crean egreso
    de caja, así que no entran.

    + SOBRANTE de apertura (sobrante_consignable, solo turnos post-fix): plata
    extra encontrada al abrir que no pertenece a ningún día anterior — se banca
    con este turno. Sin este término se absorbía en la base y se arrastraba
    indefinidamente (Palmetto +$24.600). El faltante NO entra (novedad).

    LA BASE DE LA CAJA FUERTE SE ARREGLA EN EL CUADRE, NO ACÁ. Cuando la sede
    saca los $500.000 para completar el día, esa plata entra al cajón pero NO es
    venta: no hay nada que bancar. Con el cuadre esperándola (services/caja.py,
    `prestado_caja_fuerte`), `diferencia_cierre` vuelve a 0 y
    `sobrante_consignable` no se fija, así que esta fórmula da bien sola.

    El único término que se resta es `sobrante_de_la_base`
    (`_sobrante_explicado_por_la_base`), y es para los turnos que YA HABÍAN
    CERRADO cuando se registró el traslado: esas dos columnas quedan congeladas al
    cierre y nadie las reescribe. Está acotado para que no pueda restar dos veces
    — leé su docstring antes de tocarlo. Palmetto, sábado 15-ago: pedía $697.900,
    ahora $197.900.
    """
    return ((t.total_efectivo or 0) + ingresos - egresos
            + (t.diferencia_cierre or 0) + float(t.sobrante_consignable or 0)
            - sobrante_de_la_base)


def _aplicar_cascada(saldos: list[dict]) -> None:
    """El déficit de un turno se cobra del saldo de los ANTERIORES, y queda dicho de cuál.

    El caso que la originó: el lunes 17 la sede pagó de la registradora más de lo
    que entró en efectivo y cerró con $177.700 EN CONTRA. Esa plata no salió del
    aire — salió de la venta del domingo, que todavía estaba en el cajón. La
    cascada es lo que hace que el lunes quede en cero y el domingo pida $177.700
    menos, o sea que el sistema diga lo mismo que pasó físicamente.

    MÁS NUEVO PRIMERO, y el orden importa tanto como la aritmética. La versión
    original cobraba del turno más VIEJO con saldo, y el dueño lo corrigió con la
    semana en la mano: el lunes 17 la sede tenía el sábado 15 sin consignar y el
    domingo 16 también, y la plata con la que se tapó el hueco fue la del DOMINGO.
    No es una preferencia contable: es lo que pasó físicamente. La plata que hay
    en el cajón un lunes a la mañana es la venta del día anterior; la del sábado
    ya está separada esperando el viaje al banco.

    Cobrarle al más viejo tenía además un efecto perverso: iba comiendo justo la
    plata que lleva más días sin ir al banco, o sea que un día en contra podía
    hacer «desaparecer» una deuda vieja en vez de la que de verdad se usó.

    LO QUE ESTE PASO AGREGA ES LA PROCEDENCIA. Antes solo mutaba `saldo`: el
    domingo bajaba $177.700 y no había forma de decir por qué. Un número que baja
    sin poder explicarse es indistinguible de un bug, y el dueño no le va a creer
    a una pantalla que no sabe contestarle "¿y esa plata dónde está?". Ahora cada
    turno registra a quién le tapó el hueco (`cubrio`) y quién le tapó el suyo
    (`cubierto_por`), con fecha y monto, y esas dos listas son espejo: cada peso
    que sale de un turno entra en otro.

    `faltante_sin_cubrir` es el resto del déficit cuando ya no queda saldo viejo
    que consumir. LA ARITMÉTICA NO CAMBIA —se sigue ignorando para el saldo, como
    siempre—, pero deja de ser invisible: es plata que falta y que nadie estaba
    viendo. Que se ignore en la cuenta es defendible; que no se pueda mirar, no.

    Muta la lista in-place y no devuelve nada: los llamadores ya tienen la lista.
    """
    for i in range(len(saldos)):
        if saldos[i]["saldo"] >= 0:
            continue
        deficit = -saldos[i]["saldo"]
        saldos[i]["saldo"] = 0.0
        nuevo = saldos[i]["turno"]
        # De i-1 hacia atrás: el ANTERIOR primero, y solo si no alcanza se sigue
        # hacia los más viejos. Recorrer `range(i)` cobraba al revés.
        for j in range(i - 1, -1, -1):
            if deficit <= 0:
                break
            take = min(saldos[j]["saldo"], deficit)
            if take <= 0:
                continue           # ese turno ya no tiene nada que dar
            viejo = saldos[j]["turno"]
            saldos[j]["saldo"] -= take
            saldos[j]["cubrio_faltante"] += take
            deficit -= take
            # La FILA de procedencia es para que un humano la lea, así que no se
            # escribe por menos de un centavo: el saldo ya se movió arriba, esto
            # solo decide si la explicación merece una línea en la pantalla.
            monto = round(take, 2)
            if monto > 0:
                saldos[j]["cubrio"].append({
                    "turno_id": nuevo.id, "fecha_cierre": nuevo.fecha_cierre,
                    "monto": monto,
                })
                saldos[i]["cubierto_por"].append({
                    "turno_id": viejo.id, "fecha_cierre": viejo.fecha_cierre,
                    "monto": monto,
                })
        # Sobrepago histórico: el déficit que no encontró de dónde cobrarse.
        saldos[i]["faltante_sin_cubrir"] = round(deficit, 2)


def _saldos_consignacion(db: Session, tienda_id: int, pre: dict | None = None) -> list[dict]:
    """Saldo pendiente por consignar por turno cerrado, con CASCADA hacia días anteriores.

    LA ÚNICA CUENTA DE LA PLATA POR CONSIGNAR. La imputación (`recoger`,
    `get_pendiente`, `_turno_pendiente_mas_antiguo`, el cuadre de apertura) y la
    pantalla de admin leen todas de acá; que la pantalla tuviera su propia copia
    era el bug que hacía que el dueño no viera el descuento del domingo.

    Recorre SIEMPRE la historia completa de la sede, nunca un rango: ver la
    advertencia larga en `get_resumen_admin`.

    Por turno devuelve:
      turno, esperado, consignado          — la cuenta cruda (ver `_esperado_del_turno`)
      saldo                                — lo que de verdad falta consignar, post-cascada
      cubrio / cubierto_por                — la procedencia (ver `_aplicar_cascada`)
      cubrio_faltante                      — cuánto de este turno se comió otro día
      faltante_sin_cubrir                  — el déficit que no encontró de dónde cobrarse

    `pre` es la precarga de la sede; si no viene se arma acá. La recibe quien ya
    la tiene (la pantalla la reusa para pintar los detalles) para no pedir las
    mismas cuatro queries dos veces.

    Devuelve la lista en orden cronológico (asc).
    """
    pre = pre if pre is not None else _precargar_sede(db, tienda_id)
    turnos = (
        db.query(CajaTurno)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        )
        # `id` como desempate de `fecha_cierre`: dos turnos cerrados en el mismo
        # instante dejaban el orden a criterio del motor, y la cascada cobra al
        # PRIMERO de la lista. Ahora que este orden decide lo que el dueño ve en
        # pantalla, no puede depender de con qué base se corra.
        .order_by(CajaTurno.fecha_cierre.asc(), CajaTurno.id.asc())
        .all()
    )
    saldos = []
    for t in turnos:
        movs = pre["movs"].get(t.id, [])
        egresos = sum(m.valor for m in movs if m.tipo == "egreso")
        ingresos = sum(m.valor for m in movs if m.tipo == "ingreso")
        esperado = _esperado_del_turno(
            t, ingresos, egresos,
            # La base de la caja fuerte se descuenta ACÁ, sobre el esperado crudo.
            # La cascada corre DESPUÉS, sobre el esperado ya corregido: primero se
            # define cuánta plata había que bancar ese día, recién ahí se decide
            # quién le presta a quién. Invertirlo haría que un día cubriera un
            # hueco con plata que después resulta que no era suya.
            _sobrante_explicado_por_la_base(db, t, _prestado_hasta(pre, t.fecha_cierre),
                                            ingresos),
        )
        consignado = sum(c.valor for c in _consigs_del_turno(db, t, pre))
        saldos.append({
            "turno": t, "esperado": esperado, "consignado": consignado,
            "saldo": esperado - consignado,
            "cubrio": [], "cubierto_por": [],
            "cubrio_faltante": 0.0, "faltante_sin_cubrir": 0.0,
        })

    _aplicar_cascada(saldos)
    return saldos


def _turno_pendiente_mas_antiguo(db: Session, tienda_id: int) -> int | None:
    """Id del turno cerrado más antiguo que aún tiene saldo pendiente (tras la cascada)."""
    for s in _saldos_consignacion(db, tienda_id):   # ya viene en orden cronológico asc
        if round(s["saldo"], 2) > 0:
            return s["turno"].id
    return None


def registrar(db: Session, tienda_id: int, valor: float, imagen_url: str | None,
              usuario_id: int, turno_id: int | None = None,
              barista_id: int | None = None, barista_nombre: str | None = None):
    if valor <= 0:
        raise HTTPException(status_code=400, detail="El valor de la consignación debe ser mayor a 0")
    caja_turno_id = turno_id or _turno_pendiente_mas_antiguo(db, tienda_id)
    c = Consignacion(tienda_id=tienda_id, caja_turno_id=caja_turno_id,
                     valor=valor, imagen_url=imagen_url,
                     usuario_id=usuario_id, estado=EstadoConsignacionEnum.pendiente,
                     barista_id=barista_id, barista_nombre=barista_nombre)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c

def get_por_tienda(db: Session, tienda_id: int, fecha: date | None = None):
    q = db.query(Consignacion).filter(Consignacion.tienda_id == tienda_id)
    if fecha:
        q = q.filter(func.date(Consignacion.fecha) == fecha)
    rows = q.order_by(Consignacion.fecha.desc()).all()
    return [
        {
            "id": c.id,
            "tienda_id": c.tienda_id,
            "fecha": c.fecha,
            "valor": c.valor,
            "imagen_url": c.imagen_url,
            "estado": c.estado,
            "usuario_id": c.usuario_id,
            "usuario_nombre": c.usuario.nombre if c.usuario else None,
            # Barista real (display): la que operó; cae a usuario_nombre del dispositivo si no hay
            "barista_nombre": c.barista_nombre or (c.usuario.nombre if c.usuario else None),
        }
        for c in rows
    ]


def _consigs_del_turno(db: Session, turno: CajaTurno, pre: dict | None = None) -> list:
    """FK-based matching con fallback a ventana de fecha para registros legacy.

    Con `pre` (la precarga de la sede) no toca la base: las mismas filas ya están
    en memoria y el emparejamiento es el mismo, incluido el orden de precedencia
    —si el turno tiene consignaciones con FK, las legacy no se miran—.
    """
    if pre is not None:
        fk = pre["consigs"].get(turno.id, [])
        if fk:
            return fk
        if turno.fecha_cierre is None or turno.fecha_apertura is None:
            return []
        ventana_fin = turno.fecha_cierre + timedelta(hours=20)
        # `c.fecha is None` se descarta igual que en SQL, donde una comparación
        # contra NULL no matchea: en Python compararla reventaría con TypeError.
        return [c for c in pre["consigs_huerfanas"]
                if c.fecha is not None
                and turno.fecha_apertura <= c.fecha <= ventana_fin]

    fk = db.query(Consignacion).filter(Consignacion.caja_turno_id == turno.id).all()
    if fk:
        return fk
    # Fallback: registros sin FK — sólo posible en turnos cerrados con fecha_cierre
    if turno.fecha_cierre is None:
        return []
    ventana_fin = turno.fecha_cierre + timedelta(hours=20)
    return db.query(Consignacion).filter(
        Consignacion.tienda_id == turno.tienda_id,
        Consignacion.caja_turno_id.is_(None),
        Consignacion.fecha >= turno.fecha_apertura,
        Consignacion.fecha <= ventana_fin,
    ).all()


def get_resumen_admin(db: Session, tienda_id: int | None = None, desde=None, hasta=None):
    """Lo que la pantalla de Consignaciones le muestra al dueño, turno por turno.

    LOS NÚMEROS DE PLATA NO SE CALCULAN ACÁ, SE LEEN de `_saldos_consignacion` —
    la misma función que usa la imputación (`recoger`, `get_pendiente`, el cuadre
    de apertura). Hasta este cambio esta pantalla tenía su propia copia de la
    fórmula y NO corría la cascada: el lunes 17, que cerró con $177.700 en
    contra, aparecía en cero, y al domingo 16 no se le veía el descuento aunque
    la plata del lunes hubiera salido de su cajón. Dos cuentas distintas sobre la
    misma plata, y la que el dueño miraba era justamente la que no mandaba.

    LA CASCADA SE CALCULA SOBRE LA HISTORIA COMPLETA DE LA SEDE, NUNCA SOBRE EL
    RANGO FILTRADO. Esto es lo que un lector futuro va a querer "optimizar" —
    `_saldos_consignacion` recorre todos los turnos cerrados de la sede aunque la
    pantalla muestre 60 o una semana— y es lo que volvería a partir la cuenta en
    dos. Si la cascada corriera sobre lo filtrado, el déficit del lunes se
    cobraría del turno más viejo QUE HAYA ENTRADO AL FILTRO: mirando "últimos 60"
    se lo cobraría al domingo y mirando "solo esta semana" al martes. El mismo
    día valdría dos cosas según por dónde se entró, y encima ninguna de las dos
    coincidiría con lo que `recoger()` le cobra de verdad. El filtro decide QUÉ
    FILAS SE MUESTRAN; jamás a quién se le cobra la plata.

    Si se pasa tienda_id, filtra por esa sede.
    desde/hasta (date) filtran por fecha de cierre del turno (inclusive).
    """
    tiendas = {t.id: t.nombre for t in db.query(Tienda).all()}
    q = db.query(CajaTurno).filter(CajaTurno.estado == EstadoTurnoEnum.cerrado)
    if tienda_id:
        q = q.filter(CajaTurno.tienda_id == tienda_id)
    # EL RANGO SE CONVIERTE A UTC, y no es cosmético: `fecha_cierre` guarda
    # instantes en UTC y Colombia va CINCO HORAS ATRÁS, así que armar el rango con
    # `datetime(desde.year, ...)` lo comparaba contra medianoche UTC — o sea las
    # 19:00 del día anterior en Cali.
    #
    # Palmetto cierra 19:42. Eso son las 00:42 UTC del día SIGUIENTE, así que
    # todos sus días caían del lado equivocado: pedir «del 15 al 15» no devolvía
    # el sábado, y el sábado aparecía al filtrar el domingo. Todo un mes corrido
    # un día, y el peor caso —un día que no aparece en su propia fecha— es el que
    # hace pensar que el sistema perdió la información.
    if desde is not None:
        q = q.filter(CajaTurno.fecha_cierre >= inicio_dia_col_utc(desde))
    if hasta is not None:
        q = q.filter(CajaTurno.fecha_cierre <= fin_dia_col_utc(hasta))
    # Sin rango explícito mantenemos el tope histórico de 60 turnos; con rango no limitamos.
    q = q.order_by(CajaTurno.fecha_cierre.desc())
    turnos = q.all() if (desde is not None or hasta is not None) else q.limit(60).all()

    # La cascada es POR SEDE —la plata está en el cajón de una sede, no en el de
    # la cadena—, así que se resuelve una vez por cada sede que aparezca en el
    # filtro y se indexa por turno. La precarga se guarda porque esta función la
    # vuelve a usar para pintar los detalles (movimientos y consignaciones) sin
    # repetir las queries. `sorted` para que el orden sea estable entre cargas.
    precargas: dict[int, dict] = {}
    cascada: dict[int, dict] = {}
    for tid in sorted({t.tienda_id for t in turnos}):
        precargas[tid] = _precargar_sede(db, tid)
        for s in _saldos_consignacion(db, tid, precargas[tid]):
            cascada[s["turno"].id] = s

    result = []
    for t in turnos:
        pre = precargas[t.tienda_id]
        # Movimientos de caja del turno, ya ordenados por fecha en la precarga.
        movs = pre["movs"].get(t.id, [])

        egresos = [m for m in movs if m.tipo == "egreso"]
        ingresos_mov = [m for m in movs if m.tipo == "ingreso"]
        total_egresos = sum(m.valor for m in egresos)
        total_ingresos_mov = sum(m.valor for m in ingresos_mov)

        consigs = sorted(_consigs_del_turno(db, t, pre), key=lambda c: c.fecha)
        total_consignado = sum(c.valor for c in consigs)

        # Se indexa DIRECTO y sin `.get`: `_saldos_consignacion` recorre todos los
        # turnos cerrados de la sede y acá solo hay turnos cerrados de esas sedes,
        # así que una clave faltante sería un invariante roto. Un default silencioso
        # sería la puerta por la que esta pantalla volvería a calcular por su cuenta.
        s = cascada[t.id]
        esperado = s["esperado"]
        diferencia = total_consignado - esperado
        # Lo que el traslado de la caja fuerte ya canceló de este turno. Se
        # recalcula con la misma función y la misma precarga que usó `_saldos_
        # consignacion`: dos formas de obtener el mismo número se desincronizan
        # en el primer caso raro, y este va a la pantalla al lado del esperado.
        base_prestada = _sobrante_explicado_por_la_base(
            db, t, _prestado_hasta(pre, t.fecha_cierre), total_ingresos_mov)

        result.append({
            "turno_id": t.id,
            "tienda_id": t.tienda_id,
            "tienda_nombre": tiendas.get(t.tienda_id, ""),
            "fecha_apertura": t.fecha_apertura,
            "fecha_cierre": t.fecha_cierre,
            "total_efectivo": t.total_efectivo or 0,
            "efectivo_final_real": t.efectivo_final_real or 0,
            "base_real": t.base_real or 0,
            "total_egresos": total_egresos,
            "total_ingresos_mov": total_ingresos_mov,
            "diferencia_cierre": round(float(t.diferencia_cierre or 0), 2),
            # ── LO QUE NO ES VENTA, desglosado ────────────────────────────────
            # La fórmula del consignable suma cinco términos y hasta acá SOLO SE
            # PODÍAN VER CUATRO: `sobrante_consignable` no se exponía en ninguna
            # parte. El dueño miraba un martes que pedía $416.800 con $260.115 de
            # venta y no tenía cómo averiguar de dónde salían los $156.685 de
            # diferencia — ni abriendo la fila. Un número que no se puede auditar
            # es un número al que no se le puede creer.
            #
            # Ninguno de estos campos cambia la cuenta: son los sumandos que ya
            # estaban adentro, puestos a la vista.
            "sobrante_apertura": round(float(t.sobrante_consignable or 0), 2),
            "base_prestada": round(base_prestada, 2),
            "en_cajon_no_es_venta": round(
                total_ingresos_mov + float(t.diferencia_cierre or 0)
                + float(t.sobrante_consignable or 0) - base_prestada, 2),
            # La cuenta CRUDA del día, sin cascada: lo que ese turno generó y
            # tendría que haber ido al banco si nadie le hubiera sacado nada.
            "esperado_consignar": round(esperado, 2),
            "total_consignado": round(total_consignado, 2),
            "diferencia": round(diferencia, 2),
            # ── Cascada FIFO: de acá sale por qué el número que se cobra no es
            # el esperado crudo. Todo viene de `_saldos_consignacion`, o sea de la
            # MISMA cuenta que usa la imputación — esa es la garantía de que la
            # pantalla y lo que se cobra dejaron de discrepar.
            #
            # cubrio_faltante: cuánto de ESTE turno se comió otro día que cerró
            #   en contra. Es el descuento que el dueño no veía.
            # cubrio / cubierto_por: la procedencia con fecha y monto. Sin esto la
            #   pantalla puede mostrar el descuento pero no explicarlo, y un número
            #   que baja sin decir por qué se lee como un bug.
            # faltante_sin_cubrir: el déficit que no encontró saldo viejo del cual
            #   cobrarse. Se sigue ignorando en la aritmética (como siempre), pero
            #   deja de ser invisible: es plata que falta.
            # saldo_pendiente: EL número. Lo que de verdad falta consignar de ese
            #   día. Vale exactamente el `saldo` post-cascada de
            #   `_saldos_consignacion`, que es lo que `recoger()` cobra.
            "cubrio_faltante": round(s["cubrio_faltante"], 2),
            "cubrio": s["cubrio"],
            "cubierto_por": s["cubierto_por"],
            "faltante_sin_cubrir": s["faltante_sin_cubrir"],
            "saldo_pendiente": round(s["saldo"], 2),
            "egresos_detalle": [
                {"concepto": m.concepto, "valor": m.valor, "fecha": m.fecha}
                for m in egresos
            ],
            "ingresos_detalle": [
                {"concepto": m.concepto, "valor": m.valor, "fecha": m.fecha}
                for m in ingresos_mov
            ],
            "consignaciones": [
                {
                    "id": c.id, "valor": c.valor, "estado": c.estado,
                    "fecha": c.fecha, "imagen_url": c.imagen_url,
                    "usuario_nombre": c.usuario.nombre if c.usuario else None,
                    "barista_nombre": c.barista_nombre or (c.usuario.nombre if c.usuario else None),
                }
                for c in consigs
            ],
        })
    return result


def get_pendiente(db: Session, tienda_id: int):
    # Saldo con cascada FIFO: un egreso en efectivo que supera el día baja el pendiente
    # de turnos anteriores. Solo se listan turnos con saldo > 0 tras la cascada.
    saldos = _saldos_consignacion(db, tienda_id)
    items = []
    for s in saldos:                    # orden cronológico asc
        pendiente = round(s["saldo"], 2)
        if pendiente > 0:
            t = s["turno"]
            items.append({
                "turno_id": t.id,
                "fecha_apertura": t.fecha_apertura,
                "fecha_cierre": t.fecha_cierre,
                "esperado": round(s["esperado"], 2),
                "consignado": round(s["consignado"], 2),
                "pendiente": pendiente,
            })
    items.reverse()                     # más reciente primero para la UI
    return {
        "items": items,
        "total_pendiente": round(sum(i["pendiente"] for i in items), 2),
    }


def confirmar(db: Session, consignacion_id: int):
    c = db.query(Consignacion).filter(Consignacion.id == consignacion_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Consignación no encontrada")
    if c.estado == EstadoConsignacionEnum.realizada:
        raise HTTPException(status_code=400, detail="La consignación ya fue confirmada")
    c.estado = EstadoConsignacionEnum.realizada
    db.commit()
    db.refresh(c)
    return c


def recoger(db: Session, tienda_id: int, turno_ids: list[int], usuario_id: int):
    """El admin pasó por la tienda y se llevó el efectivo pendiente de esos días.

    Reemplaza al flujo viejo (la barista sube la foto del comprobante bancario y
    el admin la aprueba): ahora la plata la recoge el admin en persona, así que
    no hay comprobante que fotografiar y la consignación nace ya `realizada`.

    El valor NUNCA llega del cliente: se recalcula acá con `_saldos_consignacion`
    (mismo criterio que todo el módulo, con la cascada FIFO ya aplicada). Si un
    turno dejó de tener saldo entre que se pintó la pantalla y se apretó el botón,
    se omite en silencio en vez de duplicar plata.
    """
    from app.services import audit

    if not turno_ids:
        raise HTTPException(status_code=400, detail="No se indicó ningún turno")

    pendientes = {
        s["turno"].id: round(s["saldo"], 2)
        for s in _saldos_consignacion(db, tienda_id)
        if round(s["saldo"], 2) > 0
    }

    creadas: list[dict] = []
    for tid in turno_ids:
        saldo = pendientes.get(tid)
        if not saldo:
            continue
        db.add(Consignacion(
            tienda_id=tienda_id, caja_turno_id=tid, valor=saldo,
            imagen_url=None, usuario_id=usuario_id,
            estado=EstadoConsignacionEnum.realizada,
        ))
        creadas.append({"turno_id": tid, "valor": saldo})

    if not creadas:
        raise HTTPException(status_code=400,
                            detail="Esos turnos ya no tienen saldo pendiente")

    total = round(sum(c["valor"] for c in creadas), 2)
    audit.registrar(
        db, accion="recoger_efectivo", tabla="consignaciones",
        usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"turnos": creadas, "total": total},
    )
    db.commit()
    return {"recogidas": creadas, "total": total}


def editar(db: Session, consignacion_id: int, usuario_id: int,
           valor: float | None = None, turno_id: int | None = None):
    """Corrige una consignación mal registrada (solo admin): valor y/o el turno
    (día) al que corresponde. El saldo por consignar es derivado, así que basta
    con corregir la fila; el cambio queda en auditoría."""
    from app.services import audit

    c = db.query(Consignacion).filter(Consignacion.id == consignacion_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Consignación no encontrada")
    antes = {"valor": float(c.valor), "caja_turno_id": c.caja_turno_id}
    if valor is not None:
        if valor <= 0:
            raise HTTPException(status_code=400, detail="El valor debe ser mayor a 0")
        c.valor = round(valor, 2)
    if turno_id is not None:
        turno = db.query(CajaTurno).filter_by(id=turno_id, tienda_id=c.tienda_id).first()
        if not turno:
            raise HTTPException(status_code=404, detail="Turno no encontrado en esta sede")
        c.caja_turno_id = turno_id
    audit.registrar(
        db, accion="editar_consignacion", tabla="consignaciones",
        registro_id=c.id, usuario_id=usuario_id, tienda_id=c.tienda_id,
        datos_antes=antes,
        datos_despues={"valor": float(c.valor), "caja_turno_id": c.caja_turno_id},
    )
    db.commit()
    db.refresh(c)
    return {"id": c.id, "valor": c.valor, "caja_turno_id": c.caja_turno_id,
            "estado": c.estado.value if hasattr(c.estado, "value") else c.estado}


def eliminar(db: Session, consignacion_id: int, usuario_id: int):
    """Revierte una consignación registrada por error (solo admin).

    El saldo por consignar del turno es derivado (esperado - consignaciones),
    así que basta con borrar la fila; los datos quedan en auditoría."""
    from app.services import audit

    c = db.query(Consignacion).filter(Consignacion.id == consignacion_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Consignación no encontrada")
    audit.registrar(
        db, accion="eliminar_consignacion", tabla="consignaciones",
        registro_id=c.id, usuario_id=usuario_id, tienda_id=c.tienda_id,
        datos_antes={
            "valor": float(c.valor),
            "estado": c.estado.value if c.estado else None,
            "caja_turno_id": c.caja_turno_id,
            "fecha": str(c.fecha),
            "barista_nombre": c.barista_nombre,
            "imagen_url": c.imagen_url,
        },
    )
    db.delete(c)
    db.commit()
    return {"ok": True, "id": consignacion_id}


# ── Recogidas de efectivo ───────────────────────────────────────────────────
#
# Vive acá y no en un módulo aparte porque es la ACCIÓN ESPEJO de la consignación:
# las dos mueven efectivo fuera del cajón y las dos alimentan el mismo número del
# dueño. Lo que cambia es a dónde va la plata — la consignación la deja en el
# banco, la recogida la deja en su MANO, y desde ahí puede salir a pagar
# proveedores de contado sin pasar nunca por una cuenta.
#
# OJO CON `recoger()`, ARRIBA: se llama parecido y NO es lo mismo. Aquella función
# es el flujo viejo —salda los turnos pendientes creando `Consignacion` con su
# `caja_turno_id`, o sea afirmando que la plata llegó al banco— y ya descuenta el
# cajón por su cuenta. Registrar la MISMA pasada por los dos caminos descontaría
# el cajón dos veces. Son excluyentes: o el dueño usa el flujo viejo, o registra
# recogidas.


def _serializar_recogida(r: RecogidaEfectivo) -> dict:
    return {
        "id": r.id,
        "tienda_id": r.tienda_id,
        "tienda_nombre": r.tienda.nombre if r.tienda else None,
        "fecha": r.fecha,
        "monto": float(r.monto or 0),
        "nota": r.nota,
        "usuario_id": r.usuario_id,
        "usuario_nombre": r.usuario.nombre if r.usuario else None,
        "creado_en": r.creado_en,
    }


def registrar_recogida(db: Session, tienda_id: int, fecha: date, monto: float,
                       usuario_id: int, nota: str | None = None) -> dict:
    """«Recogí $X de la sede Y el día Z». El registro que le faltaba al sistema.

    Sin esto la plata recogida seguía contando en el cajón: el cajón mostraba la
    venta entera del día aunque el dueño ya se hubiera llevado el efectivo, y el
    sobrante era exactamente lo que él pagaba de contado a los proveedores.

    Las validaciones (monto positivo, fecha no futura, sede activa, largo de la
    nota) las hace el HANDLER, no este servicio ni el schema: el `detail` de un
    422 de pydantic es una LISTA y el cliente solo sabe renderizar strings, así
    que el dueño terminaba viendo "Reintenta" en vez del motivo real.
    """
    from app.services import audit   # import local, como el resto del módulo
    from app.services.costos import fijar_desde_recogidas

    # El ancla del régimen se deja puesta con la PRIMERA recogida y no se mueve
    # más. Va antes del INSERT para que la fecha que se fija sea la de esta misma
    # fila cuando es la primera. Ver `desde_recogidas` en costos.py: derivar esta
    # fecha del mínimo de las filas hacía aparecer plata al borrar la más vieja.
    fijar_desde_recogidas(db, fecha)

    r = RecogidaEfectivo(
        tienda_id=tienda_id,
        fecha=fecha,
        monto=round(float(monto), 2),
        usuario_id=usuario_id,
        # "" y "   " se guardan como NULL: una nota vacía no es una nota, y así el
        # frontend puede preguntar `nota ? ... : ...` sin casos especiales.
        nota=((nota or "").strip() or None),
    )
    db.add(r)
    db.flush()   # necesita el id para la auditoría, que se escribe en el mismo commit
    audit.registrar(
        db, accion="registrar_recogida_efectivo", tabla="recogidas_efectivo",
        registro_id=r.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"fecha": str(fecha), "monto": float(r.monto), "nota": r.nota},
    )
    db.commit()
    db.refresh(r)
    return _serializar_recogida(r)


def listar_recogidas(db: Session, desde: date | None = None,
                     hasta: date | None = None,
                     tienda_id: int | None = None) -> dict:
    """Las pasadas del dueño en un rango, con su total.

    Se filtra por `fecha` (el día en que recogió) y no por `creado_en` (el día en
    que lo tecleó): él registra la pasada de ayer, y un reporte que la ubicara en
    el día del teclado no cuadraría contra el cierre de esa sede.
    """
    q = db.query(RecogidaEfectivo)
    if tienda_id is not None:
        q = q.filter(RecogidaEfectivo.tienda_id == tienda_id)
    if desde is not None:
        q = q.filter(RecogidaEfectivo.fecha >= desde)
    if hasta is not None:
        q = q.filter(RecogidaEfectivo.fecha <= hasta)
    rows = q.order_by(RecogidaEfectivo.fecha.desc(),
                      RecogidaEfectivo.id.desc()).all()
    items = [_serializar_recogida(r) for r in rows]
    return {"items": items, "total": round(sum(i["monto"] for i in items), 2)}


def eliminar_recogida(db: Session, recogida_id: int, usuario_id: int) -> dict:
    """Revierte una recogida mal registrada (solo admin).

    Se borra la fila en vez de marcarla anulada porque nada cuelga de ella: tanto
    el efectivo del cajón como el efectivo en mano se DERIVAN de la suma de
    recogidas vivas, así que sacar la fila alcanza. Los datos quedan en auditoría.
    """
    from app.services import audit   # import local, como el resto del módulo

    r = db.query(RecogidaEfectivo).filter(RecogidaEfectivo.id == recogida_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Recogida no encontrada")
    audit.registrar(
        db, accion="eliminar_recogida_efectivo", tabla="recogidas_efectivo",
        registro_id=r.id, usuario_id=usuario_id, tienda_id=r.tienda_id,
        datos_antes={"fecha": str(r.fecha), "monto": float(r.monto or 0),
                     "nota": r.nota, "creado_en": str(r.creado_en)},
    )
    db.delete(r)
    db.commit()
    return {"ok": True, "id": recogida_id}
