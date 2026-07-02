from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from datetime import datetime, date
from app.models.models import (ConteoFisico, ConteoFisicoItem, Inventario,
                                ChecklistDiario, CajaTurno, EstadoTurnoEnum,
                                MovimientoInventario, TipoMovInvEnum, TipoConteoEnum,
                                Producto, ConteoVerificacion)
from app.services.caja import get_turno_activo, _tick_checklist
from app.services.inventario import consumir_fifo, registrar_movimiento
from app.services import audit
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
        # El conteo físico es la verdad TAMBIÉN al abrir: reconciliar el stock a lo
        # contado. Cubre la primera operación de una sede (el conteo de apertura ES
        # el inventario inicial — caso Palmetto 2-jul) y cualquier discrepancia
        # matutina. La diferencia queda registrada en el item, visible en el monitor
        # de Conteos y disputable vía verificación.
        for item in items:
            inv = db.query(Inventario).filter(
                Inventario.producto_id == item["producto_id"],
                Inventario.tienda_id == tienda_id,
            ).first()
            if inv:
                inv.stock_actual = item["cantidad_real"]
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


def solicitar_verificacion(db: Session, conteo_id: int, producto_id: int, usuario_id: int):
    """Admin: pide a las baristas recontar un producto cuyo conteo mostró diferencia."""
    conteo = db.query(ConteoFisico).filter(ConteoFisico.id == conteo_id).first()
    if not conteo:
        raise HTTPException(status_code=404, detail="Conteo no encontrado")
    item = db.query(ConteoFisicoItem).filter(
        ConteoFisicoItem.conteo_id == conteo_id,
        ConteoFisicoItem.producto_id == producto_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Ese producto no está en el conteo")
    existente = db.query(ConteoVerificacion).filter(
        ConteoVerificacion.conteo_id == conteo_id,
        ConteoVerificacion.producto_id == producto_id,
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ya hay una verificación para ese producto en este conteo")

    v = ConteoVerificacion(
        tienda_id=conteo.tienda_id, conteo_id=conteo_id, producto_id=producto_id,
        cantidad_sistema=float(item.cantidad_sistema or 0),
        cantidad_conteo=float(item.cantidad_real or 0),
        solicitada_por_id=usuario_id,
    )
    db.add(v)
    audit.registrar(db, accion="verificacion_solicitada", tabla="conteo_verificaciones",
                    registro_id=None, usuario_id=usuario_id, tienda_id=conteo.tienda_id,
                    datos_despues={"conteo_id": conteo_id, "producto_id": producto_id})
    db.commit()
    db.refresh(v)
    return v


def responder_verificacion(db: Session, verificacion_id: int, cantidad: float,
                           nota: str | None, usuario_id: int,
                           barista_id: int | None = None, barista_nombre: str | None = None):
    """Barista (kiosko): responde con el recuento físico del producto."""
    v = db.query(ConteoVerificacion).filter(ConteoVerificacion.id == verificacion_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Verificación no encontrada")
    if v.estado != "solicitada":
        raise HTTPException(status_code=400, detail="Esta verificación ya fue respondida")
    if cantidad < 0:
        raise HTTPException(status_code=400, detail="La cantidad no puede ser negativa")
    v.estado = "respondida"
    v.cantidad_verificada = cantidad
    v.nota_barista = nota
    v.barista_id = barista_id
    v.barista_nombre = barista_nombre
    v.fecha_respuesta = datetime.utcnow()
    audit.registrar(db, accion="verificacion_respondida", tabla="conteo_verificaciones",
                    registro_id=v.id, usuario_id=usuario_id, tienda_id=v.tienda_id,
                    datos_despues={"cantidad_verificada": cantidad, "nota": nota,
                                   "barista_nombre": barista_nombre})
    db.commit()
    db.refresh(v)
    return v


def resolver_verificacion(db: Session, verificacion_id: int, aprobar: bool,
                          usuario_id: int, nota: str | None = None):
    """Admin: aprueba (el recuento pasa a ser el stock, con ajuste auditado si difiere)
    o rechaza (queda el registro, sin tocar stock)."""
    v = db.query(ConteoVerificacion).filter(ConteoVerificacion.id == verificacion_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Verificación no encontrada")
    if v.estado not in ("solicitada", "respondida"):
        raise HTTPException(status_code=400, detail="Esta verificación ya fue resuelta")
    if aprobar and v.estado != "respondida":
        raise HTTPException(status_code=400, detail="Falta la respuesta de la barista para aprobar")

    v.nota_admin = nota
    v.fecha_resolucion = datetime.utcnow()
    ajustado = False
    if aprobar:
        v.estado = "aprobada"
        inv = db.query(Inventario).filter_by(producto_id=v.producto_id, tienda_id=v.tienda_id).first()
        stock_actual = float(inv.stock_actual or 0) if inv else 0.0
        if round(stock_actual - float(v.cantidad_verificada or 0), 3) != 0:
            # El recuento verificado pasa a ser el stock oficial (movimiento tipo ajuste).
            registrar_movimiento(
                db, producto_id=v.producto_id, tienda_id=v.tienda_id,
                tipo="ajuste", cantidad=float(v.cantidad_verificada or 0),
                motivo=f"Verificación de conteo aprobada (conteo #{v.conteo_id})",
                usuario_id=usuario_id, commit=False,
            )
            ajustado = True
    else:
        v.estado = "rechazada"
    audit.registrar(db, accion="verificacion_resuelta", tabla="conteo_verificaciones",
                    registro_id=v.id, usuario_id=usuario_id, tienda_id=v.tienda_id,
                    datos_despues={"estado": v.estado, "ajusto_stock": ajustado, "nota": nota})
    db.commit()
    db.refresh(v)
    return v


def get_verificaciones(db: Session, tienda_id: int, estado: str | None = None) -> list[dict]:
    q = db.query(ConteoVerificacion, Producto).join(
        Producto, Producto.id == ConteoVerificacion.producto_id
    ).filter(ConteoVerificacion.tienda_id == tienda_id)
    if estado:
        q = q.filter(ConteoVerificacion.estado == estado)
    rows = q.order_by(ConteoVerificacion.fecha_solicitud.desc()).limit(100).all()
    return [{
        "id": v.id, "conteo_id": v.conteo_id, "producto_id": v.producto_id,
        "producto_nombre": p.nombre, "unidad": p.unidad_medida,
        "estado": v.estado,
        "cantidad_sistema": v.cantidad_sistema, "cantidad_conteo": v.cantidad_conteo,
        "cantidad_verificada": v.cantidad_verificada,
        "nota_barista": v.nota_barista, "nota_admin": v.nota_admin,
        "barista_nombre": v.barista_nombre,
        "fecha_solicitud": v.fecha_solicitud.isoformat() if v.fecha_solicitud else None,
        "fecha_respuesta": v.fecha_respuesta.isoformat() if v.fecha_respuesta else None,
    } for v, p in rows]


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
