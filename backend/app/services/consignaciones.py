from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from fastapi import HTTPException
from app.models.models import (Consignacion, EstadoConsignacionEnum,
                                CajaTurno, MovimientoCaja, Tienda, EstadoTurnoEnum)


def _turno_pendiente_mas_antiguo(db: Session, tienda_id: int) -> int | None:
    """Devuelve el id del turno cerrado más antiguo que aún tiene consignación pendiente."""
    turnos = (
        db.query(CajaTurno)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        )
        .order_by(CajaTurno.fecha_cierre.asc())
        .all()
    )
    for t in turnos:
        movs = db.query(MovimientoCaja).filter(MovimientoCaja.caja_turno_id == t.id).all()
        total_egresos = sum(m.valor for m in movs if m.tipo == "egreso")
        total_ingresos_mov = sum(m.valor for m in movs if m.tipo == "ingreso")
        esperado = (t.total_efectivo or 0) + total_ingresos_mov - total_egresos
        if esperado <= 0:
            continue
        consignado = db.query(func.sum(Consignacion.valor)).filter(
            Consignacion.caja_turno_id == t.id
        ).scalar() or 0
        if round(consignado, 2) < round(esperado, 2):
            return t.id
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

        # Fórmula: lo que se vendió en cash ± movimientos = lo que debe consignarse
        esperado = (t.total_efectivo or 0) + total_ingresos_mov - total_egresos
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
    turnos = (
        db.query(CajaTurno)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        )
        .order_by(CajaTurno.fecha_cierre.desc())
        .all()
    )

    items = []
    for t in turnos:
        movs = db.query(MovimientoCaja).filter(MovimientoCaja.caja_turno_id == t.id).all()
        total_egresos = sum(m.valor for m in movs if m.tipo == "egreso")
        total_ingresos_mov = sum(m.valor for m in movs if m.tipo == "ingreso")
        esperado = (t.total_efectivo or 0) + total_ingresos_mov - total_egresos

        consigs = _consigs_del_turno(db, t)
        total_consignado = sum(c.valor for c in consigs)
        pendiente = max(0, round(esperado - total_consignado, 2))

        # Solo turnos con saldo pendiente real (antes `esperado > 0` colaba turnos ya saldados
        # como filas fantasma de $0 e inflaba el conteo de turnos pendientes).
        if pendiente > 0:
            items.append({
                "turno_id": t.id,
                "fecha_apertura": t.fecha_apertura,
                "fecha_cierre": t.fecha_cierre,
                "esperado": round(esperado, 2),
                "consignado": round(total_consignado, 2),
                "pendiente": pendiente,
            })

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
