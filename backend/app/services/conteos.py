from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from datetime import datetime, date
from app.models.models import (ConteoFisico, ConteoFisicoItem, Inventario,
                                ChecklistDiario, CajaTurno, EstadoTurnoEnum,
                                MovimientoInventario, Producto, ConteoVerificacion,
                                SolicitudConteoDesechables, Configuracion, RolEnum,
                                Tienda, Usuario)
from app.services.caja import get_turno_activo, _tick_checklist
from app.services.inventario import registrar_movimiento
from app.services import audit
from app.core.tz import (ahora_utc, fin_dia_col_utc, hoy_col, inicio_dia_col_utc,
                         local_col, rango_col_utc)


def _tipo(m) -> str:
    """El tipo del movimiento como texto. El enum viaja como objeto en Postgres y
    como str en SQLite; comparar contra el objeto crudo falla en uno de los dos."""
    return m.tipo.value if hasattr(m.tipo, "value") else str(m.tipo)
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

    EL CONTEO ES LA VERDAD DE UN INSTANTE, NO DE AHORA. Lo que la barista contó
    vale para el momento en que lo contó, y entre ese momento y el clic de
    «Aplicar» el local no se detiene: sigue vendiendo, mermando y recibiendo. La
    versión anterior escribía `stock = lo contado` a secas, y con eso BORRABA del
    saldo todo lo que había pasado en el medio. Pasó de verdad y está medido: el
    conteo #348 de Palmetto se contó a las 13:07 y se aplicó a las 15:42, y esas
    2 h 35 se llevaron por delante 145 gr de mezcla de granizado y 30 gr de salsa
    de caramelo de un Granizado Caramelo vendido a las 14:51, más el consumo de
    tres baristas. Los movimientos seguían en el libro —se veían en la ficha—
    pero el stock había vuelto a antes de que ocurrieran, así que el inventario
    quedaba ALTO y el siguiente conteo acusaba de faltante algo que sí se vendió
    y sí se anotó. Ese es el peor error posible acá: manda a buscar un robo que
    no existe.

    La cuenta correcta suma las dos fuentes en vez de dejar que una pise a la
    otra:

        stock = lo contado + (lo que entró − lo que salió DESDE el conteo)

    SI ALGUIEN YA AJUSTÓ EL PRODUCTO DESPUÉS DEL CONTEO, no se toca. Un ajuste
    posterior —otra aplicación, un inventario mensual, una verificación— es
    alguien que ya volvió a anclar ese producto a lo que contó físicamente, y es
    más reciente que este conteo. Pisarlo con un dato viejo sería deshacer una
    corrección buena. Se salta y se informa: la respuesta los devuelve por nombre
    para que la pantalla los muestre en vez de dejar un silencio.
    """
    conteo = db.query(ConteoFisico).filter(ConteoFisico.id == conteo_id).first()
    if not conteo:
        raise HTTPException(status_code=404, detail="Conteo no encontrado")
    if conteo.fecha_aplicado:
        # Sin este candado, aplicar dos veces volvía a rebobinar el stock a un
        # valor viejo. El error no rompía nada visible, que es lo que lo hacía
        # caro: la segunda pasada se llevaba puesto todo lo vendido desde la
        # primera.
        raise HTTPException(status_code=400, detail=(
            f"Este conteo ya se aplicó al inventario el "
            f"{local_col(conteo.fecha_aplicado):%d/%m/%Y a las %H:%M}. "
            "Para volver a corregir el stock, registrá un conteo nuevo."))

    desde = conteo.fecha_registro
    ajustados, sin_cambio, protegidos = 0, 0, []
    for item in conteo.items:
        inv = db.query(Inventario).filter_by(
            producto_id=item.producto_id, tienda_id=conteo.tienda_id
        ).first()
        if not inv:
            continue

        # Lo que le pasó al producto DESPUÉS de que lo contaran.
        posteriores = (
            db.query(MovimientoInventario)
            .filter(MovimientoInventario.producto_id == item.producto_id,
                    MovimientoInventario.tienda_id == conteo.tienda_id,
                    MovimientoInventario.fecha > desde)
            .all()
        ) if desde else []

        # Un ajuste posterior manda: es un anclaje al físico más nuevo que este
        # conteo. Este producto no se toca.
        if any(_tipo(m) == "ajuste" for m in posteriores):
            protegidos.append(item.producto_id)
            continue

        movido = sum((float(m.cantidad or 0) if _tipo(m) == "entrada"
                      else -float(m.cantidad or 0))
                     for m in posteriores if _tipo(m) in ("entrada", "salida"))
        # El stock no puede quedar negativo: si lo movido se lleva más de lo que
        # se contó, el piso es cero y la diferencia queda como lo que es —una
        # inconsistencia entre el papel y el libro— para el siguiente conteo.
        objetivo = max(0.0, round(float(item.cantidad_real) + movido, 4))

        if abs(float(inv.stock_actual) - objetivo) < 0.001:
            sin_cambio += 1
            continue
        registrar_movimiento(
            db, item.producto_id, conteo.tienda_id, "ajuste", objetivo,
            motivo=f"Conteo #{conteo.id} aplicado al inventario",
            usuario_id=usuario_id, commit=False,
        )
        ajustados += 1

    conteo.fecha_aplicado = datetime.utcnow()
    nombres_protegidos = [
        n for (n,) in db.query(Producto.nombre)
        .filter(Producto.id.in_(protegidos)).all()
    ] if protegidos else []

    audit.registrar(
        db, accion="conteo_aplicado_inventario", tabla="conteos_fisicos",
        registro_id=conteo.id, usuario_id=usuario_id, tienda_id=conteo.tienda_id,
        datos_despues={"tipo": conteo.tipo.value if conteo.tipo else None,
                       "items": len(conteo.items), "ajustados": ajustados,
                       "protegidos": nombres_protegidos},
    )
    db.commit()
    return {"ok": True, "conteo_id": conteo.id, "ajustados": ajustados,
            "sin_cambio": sin_cambio,
            # Los que NO se tocaron porque alguien ya los ajustó después. Van por
            # nombre y no por id: es lo que el dueño necesita leer en pantalla.
            "protegidos": nombres_protegidos}


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
    """Kiosko: ¿hay un formato de desechables pendiente por llenar?

    Acá se materializa la solicitud programada (lunes y viernes). Es el punto
    justo: el kiosko ya pregunta esto solo, así que el formato aparece con la
    primera consulta del día en vez de depender de que el servidor esté
    despierto a una hora fija. Ver `asegurar_solicitud_programada`."""
    asegurar_solicitud_programada(db, tienda_id)
    s = (db.query(SolicitudConteoDesechables)
         .filter_by(tienda_id=tienda_id, estado="pendiente")
         .order_by(SolicitudConteoDesechables.fecha_solicitud.desc())
         .first())
    if not s:
        return {"pendiente": False}
    return {"pendiente": True, "solicitud_id": s.id,
            "automatica": bool(s.automatica),
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


def registrar_existencia(db: Session, tienda_id: int, items: list[dict], usuario_id: int,
                         barista_id: int | None = None, barista_nombre: str | None = None):
    """Existencia ad-hoc iniciada por la barista (sin solicitud del admin): cuenta
    cuánto hay de productos que NO entran al conteo diario (vasos, tapas, helado…).
    Registra y compara contra el sistema SIN tocar stock (doble conteo). El admin lo
    ve en el monitor de conteos y decide si aplicarlo — para no reintroducir la
    edición libre de stock por parte de la barista."""
    turno = get_turno_activo(db, tienda_id)
    if not turno:
        raise HTTPException(status_code=400, detail="No hay turno abierto")
    if not items:
        raise HTTPException(status_code=400, detail="Debes contar al menos un producto")

    conteo = ConteoFisico(
        tienda_id=tienda_id, turno_id=turno.id, tipo="existencia",
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

    n = len(items)
    msg = f"Existencia contada desde el kiosko: {n} producto{'s' if n != 1 else ''}"
    if barista_nombre:
        msg += f" — {barista_nombre}"
    try:
        from app.services import notificaciones
        notificaciones.disparar(
            db, tienda_id=tienda_id, tipo="solicitud_barista",
            mensaje=msg, nivel="info", referencia_id=conteo.id,
            push_titulo="Existencia contada", push_cuerpo=msg,
        )
    except Exception:   # noqa: BLE001 — una notificación no debe tumbar el registro
        logger.warning("No se pudo notificar existencia", exc_info=True)
    db.commit()
    db.refresh(conteo)
    logger.info(f"Conteo existencia registrado (id={conteo.id}) tienda {tienda_id}")
    return conteo


def registrar_conteo(db: Session, tienda_id: int, tipo: str,
                     items: list[dict], usuario_id: int,
                     barista_id: int | None = None, barista_nombre: str | None = None,
                     es_atajo: bool = False):
    if es_atajo:
        # El atajo "Todo coincide" copiaba el stock del SISTEMA como conteo real y
        # borró faltantes ya detectados (auditoría 8d: -10.065 gr el 5-jul). La UI
        # actual ya no lo manda; esto bloquea kioskos con la app vieja en caché.
        raise HTTPException(status_code=400, detail=(
            "El atajo 'Todo coincide' fue eliminado: recargá la app del kiosko "
            "(Ctrl+Shift+R) y registrá el conteo con la referencia por producto."))
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
        es_atajo=es_atajo,
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
        for p in (db.query(Producto.id, Producto.nombre, Producto.unidad_medida,
                           Producto.orden_conteo)
                  .filter(Producto.id.in_(prod_ids)).all()):
            nombres[p.id] = (p.nombre, p.unidad_medida, p.orden_conteo)

    result = []
    for c in conteos:
        items = []
        n_dif = 0
        for i in sorted(c.items, key=lambda x: abs(x.diferencia or 0), reverse=True):
            nombre, unidad, orden = nombres.get(i.producto_id, (f"#{i.producto_id}", "", None))
            dif = float(i.diferencia or 0)
            if round(dif, 3) != 0:
                n_dif += 1
            items.append({
                "producto_id": i.producto_id, "nombre": nombre, "unidad": unidad,
                "sistema": float(i.cantidad_sistema or 0),
                "real": float(i.cantidad_real or 0),
                "diferencia": dif,
                # Posición en el recorrido del conteo: deja al hub admin revisar
                # en el mismo orden en que la barista caminó el local (comparar
                # contra el papel sin saltar filas). El orden de esta lista NO
                # cambia — sigue siendo por diferencia; el cliente reordena.
                "orden_conteo": orden,
            })
        tipo = c.tipo.value if hasattr(c.tipo, "value") else str(c.tipo)
        result.append({
            "id": c.id, "turno_id": c.turno_id, "tipo": tipo,
            "fecha_registro": c.fecha_registro.isoformat() if c.fecha_registro else None,
            # Cuándo se promovió a verdad del inventario (None = nunca). La
            # pantalla lo necesita para no volver a ofrecer «Aplicar» sobre un
            # conteo ya aplicado: antes no había forma de saberlo desde la
            # pantalla y aplicarlo de nuevo rebobinaba el stock.
            "fecha_aplicado": c.fecha_aplicado.isoformat() if c.fecha_aplicado else None,
            "barista_nombre": c.barista_nombre,
            "es_atajo": bool(c.es_atajo),
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

    # ── Cierres de días anteriores (7 días hacia atrás, para el scroll de la tabla) ──
    from datetime import timedelta
    from app.core.tz import hoy_col
    base_fecha = fecha or hoy_col()
    cierres_previos = []
    for n in range(1, 8):
        d = base_fecha - timedelta(days=n)
        di, df = rango_col_utc(d, d)
        c = (
            db.query(ConteoFisico)
            .options(joinedload(ConteoFisico.items))
            .filter(ConteoFisico.tienda_id == tienda_id,
                    ConteoFisico.tipo == "cierre",
                    ConteoFisico.fecha_registro >= di,
                    ConteoFisico.fecha_registro <= df)
            .order_by(ConteoFisico.fecha_registro.desc())
            .first()
        )
        if c:
            cierres_previos.append({
                "fecha": str(d),
                "barista": c.barista_nombre,
                "atajo": bool(c.es_atajo),
                "por_producto": {i.producto_id: {"real": i.cantidad_real, "diferencia": i.diferencia}
                                 for i in c.items},
            })

    # ── Señales de decisión: faltante/sobrante del día valorizados + reincidentes ──
    from app.services.inventario_mensual import _valor_unitario_map
    valor_de = _valor_unitario_map(db)
    nombres = {row["producto_id"]: (row["producto_nombre"], row["unidad_medida"]) for row in base}

    def _valorado(conteo_items):
        faltante_v = sobrante_v = 0.0
        n_falt = n_sobr = 0
        for i in conteo_items:
            v = valor_de.get(i.producto_id, 0.0)
            if i.diferencia < -0.01:
                faltante_v += -i.diferencia * v
                n_falt += 1
            elif i.diferencia > 0.01:
                sobrante_v += i.diferencia * v
                n_sobr += 1
        return round(faltante_v), n_falt, round(sobrante_v), n_sobr

    resumen = None
    if cierre:
        fv, nf, sv, ns = _valorado(cierre.items)
        resumen = {"faltante_valor": fv, "faltante_productos": nf,
                   "sobrante_valor": sv, "sobrante_productos": ns}

    # Reincidentes: productos con faltante en varios cierres de la ventana (hoy + 7 previos).
    # La repetición es LA señal de fuga: un día es ruido, tres días es un patrón.
    ventana = ([{"por_producto": {i.producto_id: {"diferencia": i.diferencia} for i in cierre.items},
                 "atajo": bool(cierre.es_atajo)}] if cierre else []) + cierres_previos
    ventana_real = [c for c in ventana if not c["atajo"]]   # los atajos no son conteos: no cuentan
    acumulado: dict[int, dict] = {}
    for c in ventana_real:
        for pid, d in c["por_producto"].items():
            if d["diferencia"] < -0.01:
                a = acumulado.setdefault(pid, {"dias": 0, "total": 0.0})
                a["dias"] += 1
                a["total"] += d["diferencia"]
    reincidentes = sorted(
        ({"producto_id": pid,
          "nombre": nombres.get(pid, (str(pid), ""))[0],
          "unidad": nombres.get(pid, ("", ""))[1],
          "dias_con_faltante": a["dias"],
          "total_faltante": round(a["total"], 2),
          "valor_faltante": round(-a["total"] * valor_de.get(pid, 0.0))}
         for pid, a in acumulado.items()),
        key=lambda x: (-x["dias_con_faltante"], -x["valor_faltante"], x["total_faltante"]),
    )[:8]
    atajos_semana = sum(1 for c in ventana if c["atajo"])

    return {
        "fecha": str(fecha) if fecha else None,
        "tiene_apertura": apertura is not None,
        "tiene_cierre": cierre is not None,
        "apertura_barista": apertura.barista_nombre if apertura else None,
        "cierre_barista": cierre.barista_nombre if cierre else None,
        "apertura_atajo": bool(apertura.es_atajo) if apertura else False,
        "cierre_atajo": bool(cierre.es_atajo) if cierre else False,
        "items": items,
        "cierres_previos": cierres_previos,
        "resumen": resumen,
        "reincidentes": reincidentes,
        "cierres_en_ventana": len(ventana_real),
        "atajos_en_ventana": atajos_semana,
    }


def get_referencia_conteo(db: Session, tienda_id: int, tipo: str) -> dict:
    """Valores de referencia para la pantalla del conteo (diseño del dueño, 5-jul):

    - apertura → el ÚLTIMO conteo de CIERRE (anoche no debió moverse nada:
      cualquier diferencia es novedad nocturna).
    - cierre   → el ÚLTIMO conteo de APERTURA (lo que había al arrancar el día).

    La barista ve la referencia y tiene "Coincide" POR PRODUCTO; el valor del
    sistema NO viaja acá: se compara al registrar (conteo a ciegas). Copiar la
    referencia no puede esconder faltantes — si el producto se movió, el sistema
    lo sabe y la diferencia aparece sola.
    """
    if tipo not in {"apertura", "cierre"}:
        raise HTTPException(status_code=400, detail="tipo debe ser apertura o cierre")
    tipo_ref = "cierre" if tipo == "apertura" else "apertura"
    c = (
        db.query(ConteoFisico)
        .options(joinedload(ConteoFisico.items))
        .filter(ConteoFisico.tienda_id == tienda_id, ConteoFisico.tipo == tipo_ref)
        .order_by(ConteoFisico.fecha_registro.desc())
        .first()
    )
    if not c:
        return {"tipo_referencia": tipo_ref, "fecha": None, "barista": None,
                "es_atajo": False, "por_producto": {}}
    return {
        "tipo_referencia": tipo_ref,
        "fecha": c.fecha_registro.isoformat() if c.fecha_registro else None,
        "barista": c.barista_nombre,
        "es_atajo": bool(c.es_atajo),
        "por_producto": {i.producto_id: i.cantidad_real for i in c.items},
    }

# ─── Programación del formato de desechables ─────────────────────────────────
#
# El formato salía SOLO si el admin se acordaba de apretar «Pedir conteo de
# desechables». Los vasos y las tapas no se cuentan a diario (están fuera del
# conteo por `grupo_conteo='desechables'`), así que si nadie lo pide no se
# cuentan nunca y el faltante aparece recién cuando se acaba algo en plena venta.
#
# QUIÉN LO ARRANCA. Decisión del dueño: lo arranca la BARISTA desde su hub,
# cuando tiene un hueco. El razonamiento es que un conteo hecho a las corridas
# entre clientes son números inventados, y eso es peor que no contar; ella sabe
# cuándo hay calma y el admin no.
#
# El costo asumido, dicho para que quede escrito: el conteo pasa a ser
# voluntario. Los desechables están FUERA del conteo diario, así que la semana
# que nadie lo arranque no queda medición de esos días, y eso no se nota —la
# pantalla se ve igual con o sin conteo.
#
# La programación sigue existiendo como RED, apagada por defecto: si algún día
# se quiere un piso («si el lunes nadie lo hizo, que salga solo»), se prenden los
# días desde la pantalla del formato, sin deploy y sin código nuevo.
#
# POR QUÉ NO ES UN SCHEDULER, cuando se prende. El proyecto no tiene ninguno y es
# deliberado (ver `services/costos.py`). Acá además habría fallado: el backend
# vive en un contenedor que se duerme sin tráfico, así que un job a las 6am no
# dispara si nadie entró todavía — y cuando despierta, la hora ya pasó y el lunes
# se perdió sin que nadie se enterara. Peor con más de un worker: cada uno
# crearía la suya. En vez de eso la solicitud se MATERIALIZA en la primera
# consulta del día, que el kiosko ya hace sola.
CLAVE_DIAS_DESECHABLES = "desechables_dias"
# Apagada: la arranca la barista. Prenderla es marcar días en la pantalla.
DIAS_DESECHABLES_DEFECTO: list[int] = []
NOMBRE_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def dias_programados(db: Session) -> list[int]:
    """Días en que el formato sale solo. Vacío = solo lo arranca la barista.

    SIN FILA y FILA VACÍA se tratan distinto a propósito. Hoy el default también
    es vacío, así que da lo mismo; pero si mañana se cambia el default, «ningún
    día» tiene que seguir significando ninguno. Cuando el default era lunes y
    viernes, tratarlos igual hacía que apagar la programación no apagara nada:
    la cadena vacía caía al default y el formato seguía saliendo los lunes."""
    row = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_DIAS_DESECHABLES).first()
    if row is None:
        return list(DIAS_DESECHABLES_DEFECTO)
    crudo = (row.valor or "").strip()
    if not crudo:
        return []
    try:
        dias = sorted({int(x) for x in crudo.split(",") if x.strip() != ""})
    except ValueError:
        return list(DIAS_DESECHABLES_DEFECTO)
    return [d for d in dias if 0 <= d <= 6]


def set_dias_programados(db: Session, dias: list[int], usuario_id: int) -> dict:
    """Cambia los días. Lista vacía = apagar la programación (queda solo el
    botón manual), que es distinto de no haberla configurado nunca: por eso se
    guarda la cadena vacía en vez de borrar la fila, que volvería al default."""
    limpios = sorted({int(d) for d in dias})
    fuera = [d for d in limpios if d < 0 or d > 6]
    if fuera:
        raise HTTPException(400, f"Días fuera de rango (0=lunes … 6=domingo): {fuera}")
    row = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_DIAS_DESECHABLES).first()
    antes = row.valor if row else None
    if row is None:
        row = Configuracion(clave=CLAVE_DIAS_DESECHABLES, valor=",".join(str(d) for d in limpios))
        db.add(row)
    else:
        row.valor = ",".join(str(d) for d in limpios)
    audit.registrar(db, accion="desechables_dias_programados", tabla="configuracion",
                    registro_id=None, usuario_id=usuario_id, tienda_id=None,
                    datos_antes={"dias": antes},
                    datos_despues={"dias": row.valor})
    db.commit()
    return {"dias": limpios, "nombres": [NOMBRE_DIAS[d] for d in limpios]}


def _ya_hubo_solicitud_hoy(db: Session, tienda_id: int) -> bool:
    """¿Ya se pidió el formato hoy en esta sede? Cuenta CUALQUIER estado.

    Mirar solo las pendientes volvería a crear una en cuanto la barista responde
    la de la mañana: el formato reaparecería el mismo lunes una y otra vez.
    El día es el de Colombia, no el UTC: entre las 19:00 y la medianoche local
    el UTC ya está en el día siguiente, y con la fecha UTC el formato del viernes
    saldría de nuevo el viernes a las 19:01."""
    hoy = hoy_col()
    return db.query(SolicitudConteoDesechables).filter(
        SolicitudConteoDesechables.tienda_id == tienda_id,
        SolicitudConteoDesechables.fecha_solicitud >= inicio_dia_col_utc(hoy),
        SolicitudConteoDesechables.fecha_solicitud <= fin_dia_col_utc(hoy),
    ).first() is not None


def asegurar_solicitud_programada(db: Session, tienda_id: int) -> bool:
    """Si hoy es día programado y todavía no salió, crea la solicitud. Devuelve
    si creó una.

    Nunca revienta: la llama el poll del kiosko, y dejar la pantalla de la
    barista sin respuesta por un problema de la programación sería cambiar un
    formato que no salió por un turno que no arranca."""
    try:
        if hoy_col().weekday() not in dias_programados(db):
            return False
        if _ya_hubo_solicitud_hoy(db, tienda_id):
            return False
        # YA HAY UNO PENDIENTE (de cualquier fecha): no se crea otro. El formato
        # ya está en la pantalla del kiosko, que es todo el objetivo, y el resto
        # del módulo asume UN pendiente por sede —`solicitar` a mano lo rechaza
        # explícitamente, y `registrar` marca como respondida solo la primera
        # que encuentra. Con dos pendientes, la barista llena el formato, se
        # cierra una y la otra queda viva: el formato reaparece y no se va más.
        #
        # Caso real que lo destapó: Palmetto tenía un formato pedido a mano el
        # lunes y sin responder. Sin esta guarda, el lunes siguiente le caía un
        # segundo pendiente encima.
        pendiente = db.query(SolicitudConteoDesechables).filter_by(
            tienda_id=tienda_id, estado="pendiente").first()
        if pendiente is not None:
            return False
        # La fila exige un usuario y acá no hay nadie apretando: se firma con un
        # admin real y `automatica=True` deja dicho que no lo pidió esa persona.
        admin = (db.query(Usuario)
                 .filter(Usuario.rol == RolEnum.admin, Usuario.activo == True)  # noqa: E712
                 .order_by(Usuario.id).first())
        if admin is None:
            logger.warning("Desechables programado: no hay admin activo, no se crea la solicitud")
            return False
        # La fecha se pone EXPLÍCITA, con el mismo reloj que decidió el día. El
        # default de la columna usa otro `utcnow` y ahí la guarda de «ya salió
        # hoy» compara contra un instante que no es el que se guardó.
        s = SolicitudConteoDesechables(tienda_id=tienda_id, solicitada_por_id=admin.id,
                                       automatica=True, fecha_solicitud=ahora_utc())
        db.add(s)
        audit.registrar(db, accion="conteo_desechables_programado",
                        tabla="solicitudes_conteo_desechables", registro_id=None,
                        usuario_id=admin.id, tienda_id=tienda_id,
                        datos_despues={"dia": NOMBRE_DIAS[hoy_col().weekday()]})
        db.commit()
        logger.info(f"Formato de desechables programado creado (tienda {tienda_id})")
        return True
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("No se pudo crear el formato programado de desechables: %s", e)
        return False


# ─── Qué items lleva el formato ──────────────────────────────────────────────
#
# El formato son los productos con `grupo_conteo='desechables'`, pero la lista
# que ve cada sede sale de CRUZARLOS con su tabla de inventario: un desechable
# sin fila en una sede simplemente no aparece en su formato, y nadie se enteraba
# porque las dos pantallas se ven bien por separado. Por eso agregar un item
# crea la fila en TODAS las sedes y `formato()` reporta la cobertura por sede.

def formato(db: Session) -> dict:
    """Los items del formato + en qué sedes está cada uno."""
    tiendas = db.query(Tienda).order_by(Tienda.id).all()
    productos = (db.query(Producto)
                 .filter(Producto.grupo_conteo == "desechables")
                 .order_by(Producto.proveedor.asc(), Producto.nombre.asc()).all())
    ids = [p.id for p in productos]
    filas = (db.query(Inventario)
             .filter(Inventario.producto_id.in_(ids)).all()) if ids else []
    por_prod: dict[int, set] = {}
    for f in filas:
        por_prod.setdefault(f.producto_id, set()).add(f.tienda_id)
    return {
        "tiendas": [{"id": t.id, "nombre": t.nombre} for t in tiendas],
        "dias": dias_programados(db),
        "nombres_dias": NOMBRE_DIAS,
        "items": [{
            "producto_id": p.id,
            "nombre": p.nombre,
            "unidad_medida": p.unidad_medida,
            "proveedor": p.proveedor or "Sin proveedor",
            "tienda_ids": sorted(por_prod.get(p.id, set())),
            # Si esto es False el formato NO es el mismo en las dos sedes
            "en_todas": len(por_prod.get(p.id, set())) == len(tiendas),
        } for p in productos],
    }


def agregar_item(db: Session, producto_id: int, usuario_id: int) -> dict:
    """Mete un producto al formato y le asegura fila de inventario en TODAS las
    sedes: si falta en una, el formato de esa sede sale sin el item y las dos
    sedes dejan de contar lo mismo sin que nadie lo note."""
    p = db.query(Producto).filter(Producto.id == producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    if p.grupo_conteo == "desechables":
        raise HTTPException(400, f"«{p.nombre}» ya está en el formato")
    p.grupo_conteo = "desechables"
    # Los desechables no entran al conteo diario: es la razón de que exista este
    # formato aparte. Marcarlo acá evita que el mismo producto aparezca en los
    # dos conteos y se cuente dos veces.
    p.incluir_en_conteo = False
    creadas = []
    for t in db.query(Tienda).order_by(Tienda.id).all():
        existe = db.query(Inventario).filter_by(producto_id=p.id, tienda_id=t.id).first()
        if not existe:
            db.add(Inventario(producto_id=p.id, tienda_id=t.id, stock_actual=0))
            creadas.append(t.nombre)
    audit.registrar(db, accion="desechables_item_agregado", tabla="productos",
                    registro_id=p.id, usuario_id=usuario_id, tienda_id=None,
                    datos_despues={"producto": p.nombre, "sedes_creadas": creadas})
    db.commit()
    return formato(db)


def quitar_item(db: Session, producto_id: int, usuario_id: int) -> dict:
    """Saca un producto del formato.

    NO borra su fila de inventario ni sus movimientos: el stock y el histórico
    del producto siguen siendo ciertos, lo único que cambia es que deja de
    pedirse en este conteo. Borrar el inventario perdería la existencia real de
    algo que sigue en la bodega."""
    p = db.query(Producto).filter(Producto.id == producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    if p.grupo_conteo != "desechables":
        raise HTTPException(400, f"«{p.nombre}» no está en el formato")
    p.grupo_conteo = None
    audit.registrar(db, accion="desechables_item_quitado", tabla="productos",
                    registro_id=p.id, usuario_id=usuario_id, tienda_id=None,
                    datos_antes={"producto": p.nombre, "grupo_conteo": "desechables"})
    db.commit()
    return formato(db)


def sincronizar_sedes(db: Session, usuario_id: int) -> dict:
    """Le crea fila de inventario en las sedes que le falten a CADA item del
    formato. Es el arreglo de un formato que ya divergió."""
    tiendas = db.query(Tienda).order_by(Tienda.id).all()
    productos = db.query(Producto).filter(Producto.grupo_conteo == "desechables").all()
    creadas = []
    for p in productos:
        for t in tiendas:
            if not db.query(Inventario).filter_by(producto_id=p.id, tienda_id=t.id).first():
                db.add(Inventario(producto_id=p.id, tienda_id=t.id, stock_actual=0))
                creadas.append(f"{p.nombre} → {t.nombre}")
    if creadas:
        audit.registrar(db, accion="desechables_formato_sincronizado", tabla="productos",
                        registro_id=None, usuario_id=usuario_id, tienda_id=None,
                        datos_despues={"filas_creadas": creadas[:50],
                                       "total": len(creadas)})
    db.commit()
    return {**formato(db), "filas_creadas": creadas}

def iniciar_por_barista(db: Session, tienda_id: int, usuario_id: int,
                        barista_id: int | None = None,
                        barista_nombre: str | None = None) -> dict:
    """La barista arranca ella misma el conteo de desechables desde su hub.

    Antes el formato solo aparecía si el admin lo pedía, y los desechables están
    fuera del conteo diario: si nadie se acordaba, no se contaban nunca. Ahora el
    arranque es de quien tiene el hueco para contar.

    Se permite siempre que no haya OTRO pendiente abierto. En particular se
    permite un segundo conteo el mismo día: un recuento es legítimo —encontraron
    un descuadre y volvieron a contar— y no se pierde nada, porque cada conteo
    queda en el historial con su hora y el admin ve los dos. Bloquearlo obligaría
    a dejar como bueno un conteo que la propia barista sabe que está mal.
    """
    pendiente = db.query(SolicitudConteoDesechables).filter_by(
        tienda_id=tienda_id, estado="pendiente").first()
    if pendiente is not None:
        # No es un error: ya está abierto, que es lo que ella quería.
        return {"ok": True, "solicitud_id": pendiente.id, "ya_estaba": True}
    s = SolicitudConteoDesechables(
        tienda_id=tienda_id, solicitada_por_id=usuario_id, automatica=False,
        fecha_solicitud=ahora_utc(), barista_id=barista_id, barista_nombre=barista_nombre)
    db.add(s)
    audit.registrar(db, accion="conteo_desechables_iniciado_barista",
                    tabla="solicitudes_conteo_desechables", registro_id=None,
                    usuario_id=usuario_id, tienda_id=tienda_id,
                    datos_despues={"barista": barista_nombre})
    db.commit()
    db.refresh(s)
    logger.info(f"Conteo desechables iniciado por barista (tienda {tienda_id})")
    return {"ok": True, "solicitud_id": s.id, "ya_estaba": False}

