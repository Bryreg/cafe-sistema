from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from datetime import datetime, date
from app.models.models import (ConteoFisico, ConteoFisicoItem, Inventario,
                                ChecklistDiario, CajaTurno, EstadoTurnoEnum,
                                Producto, ConteoVerificacion,
                                SolicitudConteoDesechables)
from app.services.caja import get_turno_activo, _tick_checklist
from app.services.inventario import registrar_movimiento
from app.services import audit
from app.core.tz import rango_col_utc
import logging

logger = logging.getLogger(__name__)


def aplicar_conteo_inventario(db: Session, conteo_id: int, usuario_id: int) -> dict:
    """Promueve un conteo físico a verdad del inventario (solo admin).

    Modelo de doble conteo: los conteos de apertura/cierre solo REGISTRAN y
    COMPARAN contra el stock teórico (que evoluciona por movimientos: ventas,
    ingresos, mermas, salidas). Este es el único camino masivo para que un
    conteo pise el stock — pensado para el conteo de fin de mes que siembra
    las cantidades con las que el sistema arranca, o la primera operación de
    una sede. Correcciones puntuales siguen yendo por verificación.
    """
    conteo = db.query(ConteoFisico).filter(ConteoFisico.id == conteo_id).first()
    if not conteo:
        raise HTTPException(status_code=404, detail="Conteo no encontrado")

    ajustados = 0
    for item in conteo.items:
        inv = db.query(Inventario).filter_by(
            producto_id=item.producto_id, tienda_id=conteo.tienda_id
        ).first()
        if not inv:
            continue
        if abs(float(inv.stock_actual) - float(item.cantidad_real)) < 0.001:
            continue
        registrar_movimiento(
            db, item.producto_id, conteo.tienda_id, "ajuste",
            float(item.cantidad_real),
            motivo=f"Conteo #{conteo.id} aplicado al inventario",
            usuario_id=usuario_id, commit=False,
        )
        ajustados += 1

    audit.registrar(
        db, accion="conteo_aplicado_inventario", tabla="conteos_fisicos",
        registro_id=conteo.id, usuario_id=usuario_id, tienda_id=conteo.tienda_id,
        datos_despues={"tipo": conteo.tipo.value if conteo.tipo else None,
                       "items": len(conteo.items), "ajustados": ajustados},
    )
    db.commit()
    return {"ok": True, "conteo_id": conteo.id, "ajustados": ajustados}


# ─── Conteo de desechables (a pedido del admin) ──────────────────────────────

def solicitar_conteo_desechables(db: Session, tienda_id: int, usuario_id: int):
    """Admin: pide a las baristas llenar el formato de desechables."""
    pendiente = db.query(SolicitudConteoDesechables).filter_by(
        tienda_id=tienda_id, estado="pendiente").first()
    if pendiente:
        raise HTTPException(status_code=400, detail="Ya hay una solicitud de conteo de desechables pendiente")
    s = SolicitudConteoDesechables(tienda_id=tienda_id, solicitada_por_id=usuario_id)
    db.add(s)
    audit.registrar(db, accion="conteo_desechables_solicitado", tabla="solicitudes_conteo_desechables",
                    registro_id=None, usuario_id=usuario_id, tienda_id=tienda_id)
    db.commit()
    db.refresh(s)
    return {"ok": True, "solicitud_id": s.id}


def get_solicitud_desechables(db: Session, tienda_id: int):
    """Kiosko: ¿hay un formato de desechables pendiente por llenar?"""
    s = (db.query(SolicitudConteoDesechables)
         .filter_by(tienda_id=tienda_id, estado="pendiente")
         .order_by(SolicitudConteoDesechables.fecha_solicitud.desc())
         .first())
    if not s:
        return {"pendiente": False}
    return {"pendiente": True, "solicitud_id": s.id,
            "fecha_solicitud": s.fecha_solicitud.isoformat() if s.fecha_solicitud else None}


def registrar_conteo_desechables(db: Session, tienda_id: int, items: list[dict], usuario_id: int,
                                 barista_id: int | None = None, barista_nombre: str | None = None):
    """Barista: llena el formato de desechables solicitado. Igual que un conteo normal,
    registra y compara contra el sistema sin tocar stock (doble conteo)."""
    solicitud = db.query(SolicitudConteoDesechables).filter_by(
        tienda_id=tienda_id, estado="pendiente").first()
    if not solicitud:
        raise HTTPException(status_code=400, detail="No hay solicitud de conteo de desechables pendiente")
    turno = get_turno_activo(db, tienda_id)
    if not turno:
        raise HTTPException(status_code=400, detail="No hay turno abierto")
    if not items:
        raise HTTPException(status_code=400, detail="Debes registrar al menos un item")

    conteo = ConteoFisico(
        tienda_id=tienda_id, turno_id=turno.id, tipo="desechables",
        fecha_registro=datetime.utcnow(), usuario_id=usuario_id,
        barista_id=barista_id, barista_nombre=barista_nombre,
    )
    db.add(conteo)
    db.flush()
    for item in items:
        if item["cantidad_real"] < 0:
            raise HTTPException(status_code=400, detail="cantidad_real no puede ser negativa")
        inv = db.query(Inventario).filter(
            Inventario.producto_id == item["producto_id"],
            Inventario.tienda_id == tienda_id).first()
        cantidad_sistema = inv.stock_actual if inv else 0.0
        db.add(ConteoFisicoItem(
            conteo_id=conteo.id, producto_id=item["producto_id"],
            cantidad_sistema=cantidad_sistema, cantidad_real=item["cantidad_real"],
            diferencia=item["cantidad_real"] - cantidad_sistema,
        ))
    solicitud.estado = "respondida"
    solicitud.conteo_id = conteo.id
    solicitud.fecha_respuesta = datetime.utcnow()
    solicitud.barista_id = barista_id
    solicitud.barista_nombre = barista_nombre
    db.commit()
    db.refresh(conteo)
    logger.info(f"Conteo desechables registrado (id={conteo.id}) tienda {tienda_id}")
    return conteo


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

    # Activar flags del turno. DOBLE CONTEO: el conteo físico NO pisa el stock —
    # solo registra cantidad_sistema/cantidad_real/diferencia para comparar contra
    # el conteo interno del sistema (movimientos). Las diferencias se ven en el
    # monitor de Conteos; se corrigen vía verificación (puntual) o aplicando el
    # conteo completo al inventario (fin de mes / primera operación).
    if tipo == "apertura":
        turno.tiene_conteo_apertura = True
        turno.ts_conteo_apertura = datetime.utcnow()
        _tick_checklist(db, tienda_id, inventario_check=True)
    elif tipo == "cierre":
        turno.tiene_conteo_cierre = True
        turno.ts_conteo_cierre = datetime.utcnow()

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


# ─── Conciliación diaria: la película del doble inventario ───────────────────

def get_conciliacion_diaria(db: Session, tienda_id: int, fecha: date | None = None) -> dict:
    """Panel del doble inventario para UN día operativo (Colombia):

    Por cada producto del conteo diario (los que las baristas cuentan en
    apertura/cierre): el stock del SISTEMA (su conteo interno por movimientos),
    lo que la barista contó al ABRIR, lo que ENTRÓ durante el día (facturas,
    preparaciones) y lo que la barista contó al CERRAR.

    La columna sistema usa el snapshot del conteo de cierre si el día ya cerró
    (honesto para días pasados); si no, el stock vivo actual.
    """
    from app.models.models import MovimientoInventario, TipoMovInvEnum
    from app.services.inventario import get_inventario_tienda
    from sqlalchemy import func as sa_func

    ini, fin = rango_col_utc(fecha, fecha)

    base = get_inventario_tienda(db, tienda_id)  # productos del conteo, en orden de planilla

    # Último conteo de apertura y de cierre del día
    conteos = (
        db.query(ConteoFisico)
        .options(joinedload(ConteoFisico.items))
        .filter(
            ConteoFisico.tienda_id == tienda_id,
            ConteoFisico.tipo.in_(["apertura", "cierre"]),
            ConteoFisico.fecha_registro >= ini,
            ConteoFisico.fecha_registro <= fin,
        )
        .order_by(ConteoFisico.fecha_registro.asc())
        .all()
    )
    apertura = next((c for c in reversed(conteos) if c.tipo == "apertura" or getattr(c.tipo, "value", None) == "apertura"), None)
    cierre = next((c for c in reversed(conteos) if c.tipo == "cierre" or getattr(c.tipo, "value", None) == "cierre"), None)
    ap_items = {i.producto_id: i for i in apertura.items} if apertura else {}
    ci_items = {i.producto_id: i for i in cierre.items} if cierre else {}

    # Entradas del día por producto (facturas recibidas, preparaciones, reposiciones)
    entradas = dict(
        db.query(MovimientoInventario.producto_id, sa_func.sum(MovimientoInventario.cantidad))
        .filter(
            MovimientoInventario.tienda_id == tienda_id,
            MovimientoInventario.tipo == TipoMovInvEnum.entrada,
            MovimientoInventario.fecha >= ini,
            MovimientoInventario.fecha <= fin,
        )
        .group_by(MovimientoInventario.producto_id)
        .all()
    )

    def _celda(it):
        if it is None:
            return None
        return {"real": it.cantidad_real, "diferencia": it.diferencia,
                "sistema": it.cantidad_sistema}

    items = []
    for row in base:
        pid = row["producto_id"]
        ci = ci_items.get(pid)
        items.append({
            "producto_id": pid,
            "nombre": row["producto_nombre"],
            "unidad": row["unidad_medida"],
            # Día cerrado → sistema del snapshot del cierre; día en curso → stock vivo
            "sistema": ci.cantidad_sistema if ci else row["stock_actual"],
            "apertura": _celda(ap_items.get(pid)),
            "entradas": round(float(entradas.get(pid, 0.0)), 2),
            "cierre": _celda(ci_items.get(pid)),
        })

    return {
        "fecha": str(fecha) if fecha else None,
        "tiene_apertura": apertura is not None,
        "tiene_cierre": cierre is not None,
        "apertura_barista": apertura.barista_nombre if apertura else None,
        "cierre_barista": cierre.barista_nombre if cierre else None,
        "items": items,
    }
