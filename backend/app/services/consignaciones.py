from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from fastapi import HTTPException
from app.models.models import (Consignacion, EstadoConsignacionEnum,
                                CajaTurno, MovimientoCaja, Tienda, EstadoTurnoEnum)

def registrar(db: Session, tienda_id: int, valor: float, imagen_url: str | None, usuario_id: int):
    if valor <= 0:
        raise HTTPException(status_code=400, detail="El valor de la consignación debe ser mayor a 0")
    c = Consignacion(tienda_id=tienda_id, valor=valor, imagen_url=imagen_url,
                     usuario_id=usuario_id, estado=EstadoConsignacionEnum.pendiente)
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
        }
        for c in rows
    ]

def get_resumen_admin(db: Session):
    """
    Por cada turno cerrado (todas las tiendas), calcula:
      esperado_consignar = total_efectivo + ingresos_movimientos - egresos_movimientos
    y cruza con las consignaciones registradas ese día.
    """
    tiendas = {t.id: t.nombre for t in db.query(Tienda).all()}
    turnos = (db.query(CajaTurno)
              .filter(CajaTurno.estado == EstadoTurnoEnum.cerrado)
              .order_by(CajaTurno.fecha_cierre.desc())
              .limit(60).all())

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

        # Consignaciones en la ventana: desde apertura hasta cierre + 20h
        ventana_fin = t.fecha_cierre + timedelta(hours=20)
        consigs = db.query(Consignacion).filter(
            Consignacion.tienda_id == t.tienda_id,
            Consignacion.fecha >= t.fecha_apertura,
            Consignacion.fecha <= ventana_fin,
        ).order_by(Consignacion.fecha).all()
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
                }
                for c in consigs
            ],
        })
    return result


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
