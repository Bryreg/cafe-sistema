from sqlalchemy.orm import Session
from fastapi import HTTPException
from datetime import datetime
from app.models.models import (ConteoFisico, ConteoFisicoItem, Inventario,
                                ChecklistDiario, CajaTurno, EstadoTurnoEnum,
                                MovimientoInventario, TipoMovInvEnum, TipoConteoEnum)
from app.services.caja import get_turno_activo, _tick_checklist
import logging

logger = logging.getLogger(__name__)


def _registrar_consumo_turno(
    db: Session,
    tienda_id: int,
    turno_id: int,
    items_cierre: list[dict],
    usuario_id: int,
) -> None:
    """
    Al cerrar el turno: deriva el consumo real comparando apertura vs cierre.
    Crea un MovimientoInventario tipo=salida con motivo='consumo_turno' por
    la parte del consumo que no fue registrada explícitamente (mermas, etc.).
    También reconcilia stock_actual con el conteo físico real.
    """
    apertura = (
        db.query(ConteoFisico)
        .filter_by(turno_id=turno_id, tipo=TipoConteoEnum.apertura)
        .first()
    )
    if not apertura:
        return  # Sin conteo de apertura no hay baseline

    apertura_map: dict[int, float] = {
        item.producto_id: item.cantidad_real for item in apertura.items
    }
    t_apertura = apertura.fecha_registro
    ahora = datetime.utcnow()

    for cierre_item in items_cierre:
        pid = cierre_item["producto_id"]
        cierre_real = float(cierre_item["cantidad_real"])
        apertura_real = apertura_map.get(pid)

        if apertura_real is None:
            continue  # Producto no contado en apertura → no se puede calcular

        # Movimientos registrados durante el turno (entre apertura y ahora)
        movimientos = (
            db.query(MovimientoInventario)
            .filter(
                MovimientoInventario.producto_id == pid,
                MovimientoInventario.tienda_id == tienda_id,
                MovimientoInventario.fecha > t_apertura,
                MovimientoInventario.fecha <= ahora,
            )
            .all()
        )
        ingresos = sum(m.cantidad for m in movimientos if m.tipo == TipoMovInvEnum.entrada)
        salidas_registradas = sum(m.cantidad for m in movimientos if m.tipo == TipoMovInvEnum.salida)

        # Consumo no registrado = lo que "desapareció" sin una merma explícita
        consumo_derivado = round(
            apertura_real + ingresos - salidas_registradas - cierre_real, 3
        )

        if consumo_derivado > 0.001:
            db.add(MovimientoInventario(
                producto_id=pid,
                tienda_id=tienda_id,
                tipo=TipoMovInvEnum.salida,
                cantidad=consumo_derivado,
                motivo="consumo_turno",
                usuario_id=usuario_id,
                fecha=ahora,
            ))

        # Reconciliar stock_actual con la realidad física
        inv = db.query(Inventario).filter_by(
            producto_id=pid, tienda_id=tienda_id
        ).first()
        if inv:
            inv.stock_actual = cierre_real


def registrar_conteo(db: Session, tienda_id: int, tipo: str,
                     items: list[dict], usuario_id: int):
    turno = get_turno_activo(db, tienda_id)
    if not turno:
        raise HTTPException(status_code=400, detail="No hay turno abierto")
    if tipo not in {"apertura", "cierre"}:
        raise HTTPException(status_code=400, detail="tipo debe ser apertura o cierre")
    if not items:
        raise HTTPException(status_code=400, detail="Debes registrar al menos un item en el conteo")
    if tipo == "apertura" and turno.tiene_conteo_apertura:
        raise HTTPException(status_code=400, detail="El conteo de apertura ya fue registrado")
    if tipo == "cierre" and turno.tiene_conteo_cierre:
        raise HTTPException(status_code=400, detail="El conteo de cierre ya fue registrado")

    if tipo == "cierre" and not turno.tiene_ventas:
        raise HTTPException(status_code=400, detail="Debes registrar las ventas primero")

    conteo = ConteoFisico(
        tienda_id=tienda_id,
        turno_id=turno.id,
        tipo=tipo,
        fecha_registro=datetime.utcnow(),
        usuario_id=usuario_id,
    )
    db.add(conteo)
    db.flush()

    for item in items:
        if item["cantidad_real"] < 0:
            raise HTTPException(status_code=400, detail="cantidad_real no puede ser negativa")
        inv = db.query(Inventario).filter(
            Inventario.producto_id == item["producto_id"],
            Inventario.tienda_id == tienda_id
        ).first()
        cantidad_sistema = inv.stock_actual if inv else 0.0
        cantidad_real = item["cantidad_real"]
        diferencia = cantidad_real - cantidad_sistema

        conteo_item = ConteoFisicoItem(
            conteo_id=conteo.id,
            producto_id=item["producto_id"],
            cantidad_sistema=cantidad_sistema,
            cantidad_real=cantidad_real,
            diferencia=diferencia,
        )
        db.add(conteo_item)

    db.flush()

    # Activar flags del turno
    if tipo == "apertura":
        turno.tiene_conteo_apertura = True
        turno.ts_conteo_apertura = datetime.utcnow()
        _tick_checklist(db, tienda_id, inventario_check=True)
    elif tipo == "cierre":
        turno.tiene_conteo_cierre = True
        turno.ts_conteo_cierre = datetime.utcnow()
        # Calcular consumo real del turno y reconciliar stock
        _registrar_consumo_turno(db, tienda_id, turno.id, items, usuario_id)

    db.commit()
    db.refresh(conteo)
    logger.info(f"Conteo {tipo} registrado (id={conteo.id}) en turno {turno.id}")
    return conteo


def get_conteos_turno(db: Session, turno_id: int):
    return db.query(ConteoFisico).filter(ConteoFisico.turno_id == turno_id).all()
