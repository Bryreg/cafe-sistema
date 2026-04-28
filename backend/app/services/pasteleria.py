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
DIAS_ALERTA = 3

def registrar(db: Session, tienda_id: int, producto_id: int, cantidad: float,
               fecha_frescura: datetime, usuario_id: int):
    reg = PasteleriaDiaria(
        tienda_id=tienda_id, producto_id=producto_id, cantidad=cantidad,
        fecha_frescura=fecha_frescura, usuario_id=usuario_id, activo=True
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
    return [
        {
            "id": r.id, "tienda_id": r.tienda_id, "producto_id": r.producto_id,
            "producto_nombre": r.producto.nombre, "cantidad": r.cantidad,
            "fecha_frescura": r.fecha_frescura, "fecha_registro": r.fecha_registro,
            "activo": r.activo,
        }
        for r in regs
    ]

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
        result.append({
            "id": r.id,
            "producto_id": r.producto_id,
            "producto_nombre": r.producto.nombre,
            "cantidad": r.cantidad,
            "fecha_frescura": r.fecha_frescura,
            "fecha_registro": r.fecha_registro,
            "dias_en_stock": round(dias, 1),
            "alerta_rotacion": dias >= DIAS_ALERTA,  # más de 3 días sin terminar
        })
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
