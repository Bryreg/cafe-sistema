from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from fastapi import HTTPException
from app.models.models import (Consignacion, EstadoConsignacionEnum,
                                CajaTurno, MovimientoCaja, RecogidaEfectivo,
                                Tienda, EstadoTurnoEnum)


def _sobrante_explicado_por_la_base(db: Session, t) -> float:
    """Cuánto del sobrante YA CONGELADO de un turno lo explica la base prestada.

    `diferencia_cierre` y `sobrante_consignable` se escriben AL CERRAR y quedan
    quietos. Con el cuadre arreglado ya no se fabrican solos, pero los turnos que
    cerraron ANTES de que se registrara el préstamo los tienen adentro: Palmetto,
    sábado 15-ago, cerró con $500.000 de sobrante congelado. Registrar el traslado
    hoy no reescribe esa columna, así que sin esta función el sábado seguiría
    pidiendo $697.900 — o sea, el arreglo serviría para los sábados que vienen y
    no para el que el dueño necesita.

    LOS DOS TOPES SON EL DISEÑO, y son lo que hace que esto no reste dos veces:

      · solo cancela sobrante, nunca faltante (`extra <= 0` devuelve 0). Un
        faltante no lo explica una base que entró;
      · nunca cancela más de lo que había prestado al cierre.

    De ahí sale que se regule solo: un turno que cierra CON el préstamo ya
    registrado no fabrica sobrante —el cuadre lo esperaba— así que `extra` es 0 y
    esto devuelve 0. La resta ocurre exactamente una vez, en el mundo viejo o en
    el nuevo, nunca en los dos.

    Se acota contra el saldo VIGENTE al cierre y no contra lo movido en ESE turno:
    la base puede haber salido el viernes y el sobrante aparecer el sábado, y en
    ese caso el delta del sábado es cero pero la plata está igual de prestada.
    """
    from app.services.caja import prestado_caja_fuerte   # local: evita el ciclo

    extra = float(t.diferencia_cierre or 0) + float(t.sobrante_consignable or 0)
    if extra <= 0 or t.fecha_cierre is None:
        return 0.0
    prestado = prestado_caja_fuerte(db, t.tienda_id, hasta=t.fecha_cierre)
    return round(min(extra, max(prestado, 0.0)), 2)


def _saldos_consignacion(db: Session, tienda_id: int) -> list[dict]:
    """Saldo pendiente por consignar por turno cerrado, con CASCADA hacia días anteriores.

    Por turno: esperado = ventas en efectivo + ingresos de caja − egresos en efectivo (contado)
    + diferencia del cierre. Incluir la diferencia hace que "por consignar" del turno sea
    EXACTAMENTE la base con la que arranca el día siguiente (efectivo_final − base_real):
    la plata física que queda en caja es la que viaja al banco.
    saldo = esperado − consignado. Si el saldo de un turno es negativo (p.ej. el pago a
    proveedor de contado superó las ventas en efectivo del día), ese déficit consume el saldo
    de los turnos ANTERIORES (más viejos primero). Solo el efectivo mueve esto: crédito y bancos
    no crean egreso de caja, así que no entran. Devuelve la lista en orden cronológico (asc)."""
    turnos = (
        db.query(CajaTurno)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        )
        .order_by(CajaTurno.fecha_cierre.asc())
        .all()
    )
    saldos = []
    for t in turnos:
        movs = db.query(MovimientoCaja).filter(MovimientoCaja.caja_turno_id == t.id).all()
        egresos = sum(m.valor for m in movs if m.tipo == "egreso")
        ingresos = sum(m.valor for m in movs if m.tipo == "ingreso")
        # + SOBRANTE de apertura (sobrante_consignable, solo turnos post-fix): plata
        # extra encontrada al abrir que no pertenece a ningún día anterior — se banca
        # con este turno. Sin este término se absorbía en la base y se arrastraba
        # indefinidamente (Palmetto +$24.600). El faltante NO entra (novedad).
        #
        # LA BASE DE LA CAJA FUERTE SE ARREGLA EN EL CUADRE, NO ACÁ. Cuando la sede
        # saca los $500.000 para completar el día, esa plata entra al cajón pero NO
        # es venta: no hay nada que bancar. Con el cuadre esperándola
        # (services/caja.py, `prestado_caja_fuerte`), `diferencia_cierre` vuelve a 0
        # y `sobrante_consignable` no se fija, así que esta fórmula da bien sola.
        #
        # El único término que se resta es `_sobrante_explicado_por_la_base`, y es
        # para los turnos que YA HABÍAN CERRADO cuando se registró el traslado: esas
        # dos columnas quedan congeladas al cierre y nadie las reescribe. Está
        # acotado para que no pueda restar dos veces — leé su docstring antes de
        # tocarlo. Palmetto, sábado 15-ago: pedía $697.900, ahora $197.900.
        esperado = ((t.total_efectivo or 0) + ingresos - egresos
                    + (t.diferencia_cierre or 0) + float(t.sobrante_consignable or 0)
                    - _sobrante_explicado_por_la_base(db, t))
        consignado = sum(c.valor for c in _consigs_del_turno(db, t))
        saldos.append({"turno": t, "esperado": esperado, "consignado": consignado,
                       "saldo": esperado - consignado})

    # Cascada: el déficit de un turno (saldo<0) consume el saldo de turnos anteriores (más viejos primero).
    for i in range(len(saldos)):
        if saldos[i]["saldo"] < 0:
            deficit = -saldos[i]["saldo"]
            saldos[i]["saldo"] = 0.0
            for j in range(i):
                if deficit <= 0:
                    break
                take = min(saldos[j]["saldo"], deficit)
                saldos[j]["saldo"] -= take
                deficit -= take
            # déficit remanente sin saldo viejo que consumir = sobrepago histórico; se ignora.
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


def _consigs_del_turno(db: Session, turno: CajaTurno) -> list:
    """FK-based matching con fallback a ventana de fecha para registros legacy."""
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
    """
    Por cada turno cerrado, calcula:
      esperado_consignar = total_efectivo + ingresos_movimientos - egresos_movimientos
    y cruza con las consignaciones registradas ese día.
    Si se pasa tienda_id, filtra por esa sede.
    desde/hasta (date) filtran por fecha de cierre del turno (inclusive).
    """
    tiendas = {t.id: t.nombre for t in db.query(Tienda).all()}
    q = db.query(CajaTurno).filter(CajaTurno.estado == EstadoTurnoEnum.cerrado)
    if tienda_id:
        q = q.filter(CajaTurno.tienda_id == tienda_id)
    if desde is not None:
        q = q.filter(CajaTurno.fecha_cierre >= datetime(desde.year, desde.month, desde.day))
    if hasta is not None:
        q = q.filter(CajaTurno.fecha_cierre <= datetime(hasta.year, hasta.month, hasta.day, 23, 59, 59))
    # Sin rango explícito mantenemos el tope histórico de 60 turnos; con rango no limitamos.
    q = q.order_by(CajaTurno.fecha_cierre.desc())
    turnos = q.all() if (desde is not None or hasta is not None) else q.limit(60).all()

    result = []
    for t in turnos:
        # Movimientos de caja del turno
        movs = db.query(MovimientoCaja).filter(
            MovimientoCaja.caja_turno_id == t.id
        ).order_by(MovimientoCaja.fecha).all()

        egresos = [m for m in movs if m.tipo == "egreso"]
        ingresos_mov = [m for m in movs if m.tipo == "ingreso"]
        total_egresos = sum(m.valor for m in egresos)
        total_ingresos_mov = sum(m.valor for m in ingresos_mov)

        consigs = sorted(_consigs_del_turno(db, t), key=lambda c: c.fecha)
        total_consignado = sum(c.valor for c in consigs)

        # Fórmula: cash vendido ± movimientos + diferencia del cierre + sobrante de
        # apertura (sobrante_consignable, solo turnos post-fix) = lo que debe
        # consignarse (= la base del día siguiente). El sobrante es plata extra sin
        # dueño de días anteriores: se banca con este turno — sin él se arrastraba
        # en el cajón (caso Palmetto +$24.600).
        #
        # LA BASE DE LA CAJA FUERTE NO ENTRA ACÁ (misma razón que en
        # `_saldos_consignacion`, arriba): que la sede saque sus $500.000 al cajón no
        # es venta y no se banca. El arreglo vive en el CUADRE —el esperado de la
        # registradora suma `prestado_caja_fuerte`— y desde ahí `diferencia_cierre`
        # deja de inventar el sobrante. Restarla también acá la descontaría dos veces.
        esperado = ((t.total_efectivo or 0) + total_ingresos_mov - total_egresos
                    + (t.diferencia_cierre or 0) + float(t.sobrante_consignable or 0)
                    - _sobrante_explicado_por_la_base(db, t))
        diferencia = total_consignado - esperado

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
            "esperado_consignar": round(esperado, 2),
            "total_consignado": round(total_consignado, 2),
            "diferencia": round(diferencia, 2),
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
