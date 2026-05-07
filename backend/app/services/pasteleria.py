from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from fastapi import HTTPException
from app.models.models import (PasteleriaDiaria, ChecklistDiario,
                                Inventario, MovimientoInventario, TipoMovInvEnum)
from app.services.caja import _tick_checklist
from app.services.inventario import consumir_fifo
import logging

logger = logging.getLogger(__name__)

DIAS_ROTACION = 5


def _fmt(r: PasteleriaDiaria) -> dict:
    venc = r.fecha_vencimiento or r.fecha_frescura
    ahora = datetime.utcnow()
    diff_h = (venc - ahora).total_seconds() / 3600 if venc else None
    if diff_h is None:
        estado = "sin_fecha"
    elif diff_h < 0:
        estado = "vencido"
    elif diff_h < 24:
        estado = "por_vencer"
    else:
        estado = "vigente"
    return {
        "id": r.id, "tienda_id": r.tienda_id,
        "tienda_nombre": r.tienda.nombre if r.tienda else None,
        "producto_id": r.producto_id,
        "producto_nombre": r.producto.nombre if r.producto else str(r.producto_id),
        "cantidad": r.cantidad,
        "numero_lote": r.numero_lote,
        "fecha_vencimiento": venc,
        "fecha_registro": r.fecha_registro,
        "activo": r.activo,
        "estado": estado,
    }
DIAS_ALERTA = 3

def registrar(db: Session, tienda_id: int, producto_id: int, cantidad: float,
               fecha_vencimiento: datetime, usuario_id: int, numero_lote: str | None = None):
    reg = PasteleriaDiaria(
        tienda_id=tienda_id, producto_id=producto_id, cantidad=cantidad,
        numero_lote=numero_lote,
        fecha_vencimiento=fecha_vencimiento,
        fecha_frescura=fecha_vencimiento,  # legado
        usuario_id=usuario_id, activo=True
    )
    db.add(reg)
    _tick_checklist(db, tienda_id, pasteleria_check=True)

    # Etapa 3: descontar del inventario si el producto existe ahí
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id,
        Inventario.tienda_id == tienda_id,
    ).first()
    if inv and inv.stock_actual >= cantidad:
        inv.stock_actual -= cantidad
        consumir_fifo(db, producto_id, tienda_id, cantidad)
        mov = MovimientoInventario(
            producto_id=producto_id, tienda_id=tienda_id,
            tipo=TipoMovInvEnum.salida, cantidad=cantidad,
            usuario_id=usuario_id, motivo="Preparación pastelería",
        )
        db.add(mov)
        logger.info(f"Inventario descontado por pastelería: {cantidad} de producto {producto_id}")

    db.commit()
    db.refresh(reg)
    return reg

def get_por_fecha(db: Session, tienda_id: int, fecha: date):
    regs = db.query(PasteleriaDiaria).filter(
        PasteleriaDiaria.tienda_id == tienda_id,
        func.date(PasteleriaDiaria.fecha_registro) == fecha
    ).all()
    return [_fmt(r) for r in regs]

def get_activos(db: Session, tienda_id: int):
    """Todos los lotes activos (no terminados) de los últimos DIAS_ROTACION días."""
    limite = datetime.utcnow() - timedelta(days=DIAS_ROTACION)
    regs = (
        db.query(PasteleriaDiaria)
        .filter(
            PasteleriaDiaria.tienda_id == tienda_id,
            PasteleriaDiaria.activo == True,
            PasteleriaDiaria.fecha_registro >= limite,
        )
        .order_by(PasteleriaDiaria.fecha_registro.asc())
        .all()
    )
    ahora = datetime.utcnow()
    result = []
    for r in regs:
        dias = (ahora - r.fecha_registro).total_seconds() / 86400
        row = _fmt(r)
        row["dias_en_stock"] = round(dias, 1)
        row["alerta_rotacion"] = dias >= DIAS_ALERTA
        result.append(row)
    return result


def get_admin_lotes(db: Session):
    """Todos los lotes activos de todas las tiendas — para el admin."""
    limite = datetime.utcnow() - timedelta(days=DIAS_ROTACION)
    regs = (
        db.query(PasteleriaDiaria)
        .filter(PasteleriaDiaria.activo == True, PasteleriaDiaria.fecha_registro >= limite)
        .order_by(PasteleriaDiaria.fecha_vencimiento.asc().nullslast(),
                  PasteleriaDiaria.fecha_frescura.asc())
        .all()
    )
    ahora = datetime.utcnow()
    result = []
    for r in regs:
        row = _fmt(r)
        dias = (ahora - r.fecha_registro).total_seconds() / 86400
        row["dias_en_stock"] = round(dias, 1)
        row["alerta_rotacion"] = dias >= DIAS_ALERTA
        result.append(row)
    return result

def cerrar_lote(db: Session, lote_id: int, tienda_id: int):
    """Marca un lote como terminado."""
    reg = db.query(PasteleriaDiaria).filter(
        PasteleriaDiaria.id == lote_id,
        PasteleriaDiaria.tienda_id == tienda_id,
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Lote no encontrado")
    reg.activo = False
    db.commit()
    return {"ok": True}
