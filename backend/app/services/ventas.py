from sqlalchemy.orm import Session
from fastapi import HTTPException
from datetime import datetime
from app.models.models import VentaDiaria, CajaTurno, EstadoTurnoEnum
from app.services.caja import get_turno_activo
from app.services import audit
import logging

logger = logging.getLogger(__name__)


def registrar_venta(db: Session, tienda_id: int, venta_total: float,
                    nota_credito: float, vales: float, tarjetas: float,
                    nota: str | None, usuario_id: int):
    turno = get_turno_activo(db, tienda_id)
    if not turno:
        raise HTTPException(status_code=400, detail="No hay turno abierto")

    if not turno.tiene_conteo_apertura:
        raise HTTPException(status_code=400, detail="Debes completar el conteo de apertura primero")

    if venta_total <= 0:
        raise HTTPException(status_code=400, detail="venta_total debe ser mayor a 0")
    if any(valor < 0 for valor in (nota_credito, vales, tarjetas)):
        raise HTTPException(status_code=400, detail="nota_credito, vales y tarjetas no pueden ser negativos")

    efectivo_calculado = venta_total - nota_credito - vales - tarjetas
    if efectivo_calculado < 0:
        raise HTTPException(
            status_code=400,
            detail="La suma de nota_credito, vales y tarjetas no puede superar la venta_total"
        )

    venta = VentaDiaria(
        tienda_id=tienda_id,
        turno_id=turno.id,
        venta_total=venta_total,
        nota_credito=nota_credito,
        vales=vales,
        tarjetas=tarjetas,
        efectivo_calculado=efectivo_calculado,
        nota=nota,
        usuario_id=usuario_id,
    )
    db.add(venta)
    db.flush()

    # Actualizar totales acumulados en el turno
    turno.total_ventas = (turno.total_ventas or 0) + venta_total
    turno.total_efectivo = (turno.total_efectivo or 0) + efectivo_calculado
    turno.total_tarjeta = (turno.total_tarjeta or 0) + tarjetas

    # Activar flag solo si venta_total > 0 (ya validado arriba)
    if not turno.tiene_ventas:
        turno.ts_primera_venta = datetime.utcnow()  # Etapa 6: timestamp
    turno.tiene_ventas = True

    audit.registrar(
        db, accion="registro_venta", tabla="ventas_diarias",
        registro_id=venta.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"venta_total": venta_total, "tarjetas": tarjetas,
                       "efectivo_calculado": efectivo_calculado, "turno_id": turno.id},
    )
    db.commit()
    db.refresh(venta)
    logger.info(f"Venta {venta.id} registrada en turno {turno.id}: total={venta_total}")
    return venta


def get_ventas_turno(db: Session, turno_id: int):
    return db.query(VentaDiaria).filter(VentaDiaria.turno_id == turno_id).all()
