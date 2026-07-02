from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from datetime import datetime, date
from app.models.models import (ConteoFisico, ConteoFisicoItem, Inventario,
                                ChecklistDiario, CajaTurno, EstadoTurnoEnum,
                                MovimientoInventario, TipoMovInvEnum, TipoConteoEnum,
                                Producto)
from app.services.caja import get_turno_activo, _tick_checklist
from app.services.inventario import consumir_fifo
from app.core.tz import rango_col_utc
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
    def _reconciliar(pid: int, cierre_real: float) -> None:
        inv = db.query(Inventario).filter_by(
            producto_id=pid, tienda_id=tienda_id
        ).first()
        if inv:
            inv.stock_actual = cierre_real

    apertura = (
        db.query(ConteoFisico)
        .filter_by(turno_id=turno_id, tipo=TipoConteoEnum.apertura)
        .first()
    )
    if not apertura:
        # Sin conteo de apertura no hay baseline para derivar consumo, pero el
        # stock SÍ se reconcilia con lo contado (el conteo físico es la verdad).
        for cierre_item in items_cierre:
            _reconciliar(cierre_item["producto_id"], float(cierre_item["cantidad_real"]))
        return

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
            # Producto sin baseline (creado durante el día): no se puede derivar
            # consumo, pero el stock igual se reconcilia — antes se salteaba y el
            # conteo de cierre quedaba sin aplicar (bug detectado el 1-jul).
            _reconciliar(pid, cierre_real)
            continue

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
            # Consumir tambien los LOTES (FIFO): sin esto la trazabilidad queda
            # desfasada del stock y la banda de frescura anuncia lotes que el
            # conteo ya dijo que no existen (caso Pastel de Pollo 1-jul).
            consumir_fifo(db, pid, tienda_id, consumo_derivado)

        # Reconciliar stock_actual con la realidad física
        inv = db.query(Inventario).filter_by(
            producto_id=pid, tienda_id=tienda_id
        ).first()
        if inv:
            inv.stock_actual = cierre_real


def registrar_conteo(db: Session, tienda_id: int, tipo: str,
                     items: list[dict], usuario_id: int,
                     barista_id: int | None = None, barista_nombre: str | None = None):
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

    conteo = ConteoFisico(
        tienda_id=tienda_id,
        turno_id=turno.id,
        tipo=tipo,
        fecha_registro=datetime.utcnow(),
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
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


def get_conteos_tienda(db: Session, tienda_id: int,
                       fecha_desde: date | None = None,
                       fecha_hasta: date | None = None) -> list[dict]:
    """Monitor de conteos para el hub admin: todos los conteos físicos de la tienda
    en el rango de días Colombia, con items enriquecidos (nombre de producto) y
    resumen de diferencias. Orden: más reciente primero."""
    desde, hasta = rango_col_utc(fecha_desde, fecha_hasta)
    conteos = (
        db.query(ConteoFisico)
        .options(joinedload(ConteoFisico.items))
        .filter(
            ConteoFisico.tienda_id == tienda_id,
            ConteoFisico.fecha_registro >= desde,
            ConteoFisico.fecha_registro <= hasta,
        )
        .order_by(ConteoFisico.fecha_registro.desc())
        .all()
    )
    prod_ids = {i.producto_id for c in conteos for i in c.items}
    nombres = {}
    if prod_ids:
        for p in db.query(Producto.id, Producto.nombre, Producto.unidad_medida).filter(Producto.id.in_(prod_ids)).all():
            nombres[p.id] = (p.nombre, p.unidad_medida)

    result = []
    for c in conteos:
        items = []
        n_dif = 0
        for i in sorted(c.items, key=lambda x: abs(x.diferencia or 0), reverse=True):
            nombre, unidad = nombres.get(i.producto_id, (f"#{i.producto_id}", ""))
            dif = float(i.diferencia or 0)
            if round(dif, 3) != 0:
                n_dif += 1
            items.append({
                "producto_id": i.producto_id, "nombre": nombre, "unidad": unidad,
                "sistema": float(i.cantidad_sistema or 0),
                "real": float(i.cantidad_real or 0),
                "diferencia": dif,
            })
        tipo = c.tipo.value if hasattr(c.tipo, "value") else str(c.tipo)
        result.append({
            "id": c.id, "turno_id": c.turno_id, "tipo": tipo,
            "fecha_registro": c.fecha_registro.isoformat() if c.fecha_registro else None,
            "barista_nombre": c.barista_nombre,
            "n_items": len(items), "n_diferencias": n_dif,
            "items": items,
        })
    return result
