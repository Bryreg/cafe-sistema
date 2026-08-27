from sqlalchemy.orm import Session
from sqlalchemy import update as sa_update
from fastapi import HTTPException
from datetime import datetime, timedelta
from app.models.models import (Merma, Inventario, MovimientoInventario, TipoMovInvEnum,
                                Tienda, Producto, ProductoInsumo)
from app.services.inventario import consumir_fifo, consumir_insumo, registrar_movimiento
from app.services import audit
import logging

logger = logging.getLogger(__name__)

TIPOS_VALIDOS = {"consumo", "traslado", "daño"}


def registrar_merma(db: Session, tienda_id: int, producto_id: int,
                    cantidad: float, motivo: str, usuario_id: int,
                    tipo: str = "consumo", tienda_destino_id: int | None = None,
                    barista_id: int | None = None, barista_nombre: str | None = None,
                    quien: str | None = None, confirmar: bool = False,
                    permitir_negativo: bool = False):

    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"Tipo inválido. Usa: {', '.join(TIPOS_VALIDOS)}")

    if tipo == "traslado":
        if not tienda_destino_id:
            raise HTTPException(400, "Debes indicar la sede destino para un traslado")
        if tienda_destino_id == tienda_id:
            raise HTTPException(400, "La sede destino debe ser diferente a la sede origen")
        tienda_destino = db.query(Tienda).filter_by(id=tienda_destino_id).first()
        if not tienda_destino:
            raise HTTPException(404, "Sede destino no encontrada")

        # Guard anti-doble-envío: mismo producto+cantidad al mismo destino en los
        # últimos 5 min y aún sin recibir => probable doble toque. Pide confirmar.
        if not confirmar:
            reciente = db.query(Merma).filter(
                Merma.tipo == "traslado",
                Merma.tienda_id == tienda_id,
                Merma.tienda_destino_id == tienda_destino_id,
                Merma.producto_id == producto_id,
                Merma.cantidad == cantidad,
                Merma.recibido == False,
                Merma.fecha_registro >= datetime.utcnow() - timedelta(minutes=5),
            ).first()
            if reciente:
                raise HTTPException(
                    409,
                    f"Ya enviaste {cantidad:g} de este producto a {tienda_destino.nombre} "
                    f"hace un momento y sigue sin recibirse. ¿Confirmás enviarlo de nuevo?",
                )

    producto = db.query(Producto).filter_by(id=producto_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")

    merma = Merma(
        tienda_id=tienda_id,
        producto_id=producto_id,
        cantidad=cantidad,
        motivo=motivo,
        tipo=tipo,
        quien=quien,
        tienda_destino_id=tienda_destino_id if tipo == "traslado" else None,
        recibido=False,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(merma)
    db.flush()   # obtener merma.id para referenciarlo en la auditoría

    sufijo_quien = f" ({quien})" if quien else ""
    if tipo == "consumo":
        mov_motivo = f"Consumo{sufijo_quien}: {motivo}"
    elif tipo == "daño":
        mov_motivo = f"Daño: {motivo}"
    else:  # traslado — usar el nombre de la sede destino, no el id
        mov_motivo = f"Traslado a {tienda_destino.nombre}: {motivo}"

    if producto.controla_stock:
        # Producto con stock propio: salida directa + FIFO (camino clásico).
        inv = db.query(Inventario).filter(
            Inventario.producto_id == producto_id,
            Inventario.tienda_id == tienda_id,
        ).first()
        if not inv:
            if permitir_negativo:
                # Reparación admin: si el origen no tiene fila, la creamos en 0 y
                # dejamos que el descuento la lleve a negativo (base a re-contar).
                inv = Inventario(producto_id=producto_id, tienda_id=tienda_id, stock_actual=0)
                db.add(inv)
                db.flush()
            else:
                raise HTTPException(404, "Producto no encontrado en inventario")

        mov = MovimientoInventario(
            producto_id=producto_id,
            tienda_id=tienda_id,
            tipo=TipoMovInvEnum.salida,
            cantidad=cantidad,
            usuario_id=usuario_id,
            motivo=mov_motivo,
        )
        db.add(mov)

        if permitir_negativo:
            # Override admin (reparación de datos): descuenta aunque quede negativo.
            db.execute(
                sa_update(Inventario)
                .where(
                    Inventario.producto_id == producto_id,
                    Inventario.tienda_id == tienda_id,
                )
                .values(stock_actual=Inventario.stock_actual - cantidad)
            )
        else:
            # Atomic decrement with stock sufficiency check
            rows = db.execute(
                sa_update(Inventario)
                .where(
                    Inventario.producto_id == producto_id,
                    Inventario.tienda_id == tienda_id,
                    Inventario.stock_actual >= cantidad,
                )
                .values(stock_actual=Inventario.stock_actual - cantidad)
            ).rowcount
            if rows == 0:
                raise HTTPException(400, "Stock insuficiente.")
        consumir_fifo(db, producto_id, tienda_id, cantidad)
    else:
        # Bebida preparada / producto sin stock propio: descuenta sus INSUMOS por
        # receta. Es el MISMO mecanismo que la venta POS, y por eso llama a la
        # MISMA función: `consumir_insumo`, que aplica la cascada al sustituto.
        #
        # Antes llamaba a `registrar_movimiento` directo, y esa diferencia —que
        # el comentario viejo decía que no existía— tenía una consecuencia
        # concreta: un cappuccino VENDIDO caía a la leche deslactosada cuando se
        # acababa la entera, y el MISMO cappuccino REGALADO (consumo del
        # personal, descarga de tarjeta virtual) salía de la entera igual, la
        # cruzaba por cero y seguía cavando. La leche entera de Palmetto llegó a
        # −4 und así, en 16 movimientos de agosto y TODOS de consumo: una vez en
        # negativo, el POS ya no la tocaba —la cascada mandaba todo a la
        # deslactosada— y solo los consumos seguían restando.
        #
        # El sistema no sabe con qué leche se hizo la bebida, y ese es
        # precisamente el motivo de que la cascada exista. Un regalo no se hace
        # con otra leche que una venta.
        receta = db.query(ProductoInsumo).filter(
            ProductoInsumo.producto_id == producto_id
        ).all()
        for r in receta:
            try:
                consumir_insumo(
                    db, producto_id=r.insumo_id, tienda_id=tienda_id,
                    cantidad=r.cantidad * cantidad,
                    motivo=f"{mov_motivo} — insumo de {producto.nombre}",
                    usuario_id=usuario_id,
                    barista_id=barista_id, barista_nombre=barista_nombre,
                )
            except HTTPException as e:
                if e.status_code == 404:
                    logger.warning(f"Insumo {r.insumo_id} sin inventario, merma registrada de todas formas")
                else:
                    raise

    audit.registrar(
        db, accion="registro_merma", tabla="mermas",
        registro_id=merma.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"producto_id": producto_id, "cantidad": cantidad,
                       "motivo": motivo, "tipo": tipo,
                       "tienda_destino_id": tienda_destino_id},
    )

    # Avisar a la sede DESTINO que tiene un traslado por recibir (campana + push).
    # Sin esto el pendiente quedaba invisible salvo que alguien abriera la pantalla
    # de Merma en la sede correcta. Transacción-safe: la fila se ata a este commit.
    if tipo == "traslado":
        from app.services import notificaciones
        origen = db.query(Tienda).filter_by(id=tienda_id).first()
        origen_nombre = origen.nombre if origen else "otra sede"
        msg = f"{producto.nombre}: {cantidad:g} en camino desde {origen_nombre}"
        notificaciones.disparar(
            db, tienda_id=tienda_destino_id, tipo="traslado_entrante",
            mensaje=msg, nivel="info", referencia_id=merma.id,
            push_titulo="Traslado por recibir", push_cuerpo=msg,
        )

    db.commit()
    db.refresh(merma)
    logger.info(f"Merma [{tipo}] registrada: {cantidad} de producto {producto_id} en tienda {tienda_id}")
    return merma


def recibir_traslado(db: Session, merma_id: int, tienda_destino_id: int, usuario_id: int):
    merma = db.query(Merma).filter(
        Merma.id == merma_id,
        Merma.tipo == "traslado",
        Merma.tienda_destino_id == tienda_destino_id,
        Merma.recibido == False,
    ).first()
    if not merma:
        raise HTTPException(404, "Traslado no encontrado o ya confirmado")

    # Ingresar al inventario de la sede destino — atomic increment
    inv = db.query(Inventario).filter(
        Inventario.producto_id == merma.producto_id,
        Inventario.tienda_id == tienda_destino_id,
    ).first()
    if inv:
        db.execute(
            sa_update(Inventario)
            .where(
                Inventario.producto_id == merma.producto_id,
                Inventario.tienda_id == tienda_destino_id,
            )
            .values(stock_actual=Inventario.stock_actual + merma.cantidad)
        )
    else:
        inv = Inventario(
            producto_id=merma.producto_id,
            tienda_id=tienda_destino_id,
            stock_actual=merma.cantidad,
        )
        db.add(inv)

    origen = db.query(Tienda).filter_by(id=merma.tienda_id).first()
    origen_nombre = origen.nombre if origen else f"tienda {merma.tienda_id}"
    mov = MovimientoInventario(
        producto_id=merma.producto_id,
        tienda_id=tienda_destino_id,
        tipo=TipoMovInvEnum.entrada,
        cantidad=merma.cantidad,
        usuario_id=usuario_id,
        motivo=f"Recibo traslado desde {origen_nombre}",
    )
    db.add(mov)

    # Crear el lote FIFO en la sede destino. Sin esto el stock sube pero consumir_fifo
    # no encuentra lotes y sub-drena en silencio (la trazabilidad/vencimientos divergen).
    from app.services.inventario import agregar_lote
    agregar_lote(db, merma.producto_id, tienda_destino_id, merma.cantidad, usuario_id)

    merma.recibido = True
    merma.fecha_recibido = datetime.utcnow()
    db.commit()
    db.refresh(merma)
    return merma


def anular_traslado(db: Session, merma_id: int, usuario_id: int):
    """Anula un traslado revirtiendo su efecto EXACTO en ambas sedes y borra el
    registro. Reversa por movimiento (usa la cantidad guardada, sin adivinar):
      - Si estaba recibido: saca del inventario DESTINO lo que había entrado.
      - Si el producto controla stock: devuelve al inventario ORIGEN lo que el
        envío había descontado.
    Solo-admin (gate en el router). Sirve para limpiar traslados duplicados o
    con cantidades erradas sin dejar stock fantasma."""
    from app.services.inventario import registrar_movimiento
    merma = db.query(Merma).filter(
        Merma.id == merma_id,
        Merma.tipo == "traslado",
    ).first()
    if not merma:
        raise HTTPException(404, "Traslado no encontrado")

    # Capturar antes de borrar (la fila queda expirada tras el delete/commit).
    pid, cant = merma.producto_id, merma.cantidad
    origen_id, destino_id, estaba_recibido = merma.tienda_id, merma.tienda_destino_id, merma.recibido

    producto = db.query(Producto).filter_by(id=pid).first()
    controla = bool(producto and producto.controla_stock)

    # 1) Revertir el recibo en el DESTINO (solo si se había recibido).
    if estaba_recibido and destino_id:
        registrar_movimiento(
            db, producto_id=pid, tienda_id=destino_id,
            tipo="salida", cantidad=cant,
            motivo=f"Anulación traslado #{merma_id} (revertir recibo)",
            usuario_id=usuario_id, commit=False, allow_negative=True,
        )

    # 2) Revertir el envío en el ORIGEN, reflejando lo que el envío realmente
    #    descontó según el tipo de producto:
    if controla:
        # Producto con stock propio: el envío descontó el producto → devolverlo.
        registrar_movimiento(
            db, producto_id=pid, tienda_id=origen_id,
            tipo="entrada", cantidad=cant,
            motivo=f"Anulación traslado #{merma_id} (revertir envío)",
            usuario_id=usuario_id, commit=False,
        )
    else:
        # Bebida preparada sin stock propio: el envío descontó los INSUMOS por
        # receta → devolverlos. Si un insumo no tiene fila, se saltea (como el envío).
        for r in db.query(ProductoInsumo).filter(ProductoInsumo.producto_id == pid).all():
            try:
                registrar_movimiento(
                    db, producto_id=r.insumo_id, tienda_id=origen_id,
                    tipo="entrada", cantidad=r.cantidad * cant,
                    motivo=f"Anulación traslado #{merma_id} (revertir insumos)",
                    usuario_id=usuario_id, commit=False,
                )
            except HTTPException as e:
                if e.status_code != 404:
                    raise
                logger.warning(f"Insumo {r.insumo_id} sin inventario, reversa de insumo salteada")

    audit.registrar(
        db, accion="anular_traslado", tabla="mermas",
        registro_id=merma_id, usuario_id=usuario_id, tienda_id=origen_id,
        datos_antes={"producto_id": pid, "cantidad": cant,
                     "recibido": estaba_recibido, "tienda_destino_id": destino_id},
    )
    db.delete(merma)
    db.commit()
    return {"anulado": merma_id, "producto_id": pid, "cantidad": cant,
            "revirtio_recibo": bool(estaba_recibido and destino_id),
            "revirtio_envio": controla}


def get_mermas_tienda(db: Session, tienda_id: int):
    return (
        db.query(Merma)
        .filter(Merma.tienda_id == tienda_id)
        .order_by(Merma.fecha_registro.desc())
        .all()
    )


def get_traslados_pendientes(db: Session, tienda_id: int):
    """Traslados enviados hacia esta tienda aún no confirmados."""
    return (
        db.query(Merma)
        .filter(
            Merma.tipo == "traslado",
            Merma.tienda_destino_id == tienda_id,
            Merma.recibido == False,
        )
        .order_by(Merma.fecha_registro.desc())
        .all()
    )
