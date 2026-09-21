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

# Ventana para emparejar una merma con los movimientos que dejó en el libro.
# Nacen en la MISMA transacción, milisegundos después de `fecha_registro`, así
# que sobran unos pocos segundos — y tiene que ser CORTA: cuando una barista
# guarda el mismo formulario varias veces seguidas (pasó el 21-sep en Palmetto,
# cinco envíos con 11 segundos entre uno y otro), una ventana ancha se llevaría
# los movimientos del envío vecino y la anulación devolvería el doble.
VENTANA_REVERSA_SEG = 5

# Hueco máximo entre dos movimientos para considerarlos de la MISMA merma. Los
# de una merma salen de una sola transacción (milisegundos); dos envíos del
# formulario quedan a segundos de distancia.
CORTE_TANDA_SEG = 1.0


def _motivo_movimiento(tipo: str, motivo: str, quien: str | None,
                       tienda_destino_nombre: str | None = None) -> str:
    """El motivo que lleva el MovimientoInventario que genera una merma.

    Vive acá y no suelto dentro de `registrar_merma` porque `anular_merma` tiene
    que reconstruirlo EXACTO para encontrar qué revertir. Si las dos copias se
    separan, la anulación no encuentra nada y cae al camino por receta, que es
    justo el que se equivoca cuando hubo cascada al sustituto.
    """
    sufijo = f" ({quien})" if quien else ""
    if tipo == "consumo":
        return f"Consumo{sufijo}: {motivo}"
    if tipo == "daño":
        return f"Daño: {motivo}"
    return f"Traslado a {tienda_destino_nombre}: {motivo}"


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

    # OJO: `anular_merma` reconstruye este mismo string para saber qué revertir.
    mov_motivo = _motivo_movimiento(
        tipo, motivo, quien,
        tienda_destino.nombre if tipo == "traslado" else None,
    )

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
            merma_id=merma.id,   # para que `anular_merma` sepa qué revertir
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
                    merma_id=merma.id,   # la cascada lo propaga al sustituto
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


def tienda_de(db: Session, merma_id: int) -> int:
    """Sede de origen de una merma, para que el router pueda validar el acceso
    ANTES de tocar nada. Sin esto un admin con una sola sede asignada podía
    anular la merma de la otra: `require_admin` gatea el rol, no la sede."""
    merma = db.query(Merma).filter(Merma.id == merma_id).first()
    if not merma:
        raise HTTPException(404, "Merma no encontrada")
    return merma.tienda_id


def anular_merma(db: Session, merma_id: int, usuario_id: int):
    """Anula un consumo o un daño devolviendo EXACTAMENTE lo que descontó, y
    borra el registro. Si la merma es un traslado delega en `anular_traslado`,
    que además tiene que deshacer el recibo en la sede destino.

    Es la respuesta a la única forma que tenía el sistema de perder stock sin
    vuelta: una merma mal registrada no se podía deshacer por ningún lado —ni
    endpoint ni botón—, así que un doble toque quedaba descontado para siempre y
    el conteo aparecía con un faltante que nadie podía explicar.

    Revierte los MOVIMIENTOS que la merma dejó en el libro, NO la receta del
    producto. La diferencia no es cosmética: para una bebida sin stock propio el
    descuento pasa por `consumir_insumo`, que cae al sustituto cuando el insumo
    principal está en cero. Devolver por receta le sumaría al insumo que nunca
    se tocó y dejaría al sustituto corto para siempre. Pasó exactamente así con
    los diez consumos duplicados del 21-sep en Palmetto: la receta dice leche
    entera y los veinticinco movimientos fueron a DESLACTOSADA.

    Los movimientos nuevos vienen SELLADOS con `merma_id`, así que la reversa es
    exacta. Para las mermas anteriores a esa columna quedan dos respaldos, y la
    respuesta dice cuál se usó (`sellados`, `por_receta`): emparejar por motivo y
    hora, y si eso tampoco encuentra nada, devolver por receta. Devolver
    aproximado es mejor que no devolver nada, pero el llamador tiene que poder
    distinguir los tres casos.
    """
    merma = db.query(Merma).filter(Merma.id == merma_id).first()
    if not merma:
        raise HTTPException(404, "Merma no encontrada")

    tipo = merma.tipo.value if hasattr(merma.tipo, "value") else str(merma.tipo)
    if tipo == "traslado":
        return anular_traslado(db, merma_id, usuario_id)

    # Capturar antes de borrar: la fila queda expirada tras el delete/commit.
    pid, cant, tienda_id = merma.producto_id, merma.cantidad, merma.tienda_id
    producto = db.query(Producto).filter_by(id=pid).first()
    controla = bool(producto and producto.controla_stock)
    mov_motivo = _motivo_movimiento(tipo, merma.motivo, merma.quien)

    # Camino exacto: los movimientos que la merma SELLÓ con su id. Sin ventanas,
    # sin adivinar y sin riesgo de devolver dos veces.
    movs = (
        db.query(MovimientoInventario)
        .filter(
            MovimientoInventario.merma_id == merma_id,
            MovimientoInventario.tipo == TipoMovInvEnum.salida,
        )
        .all()
    )
    if movs:
        return _devolver_y_borrar(db, merma, movs, usuario_id, sellados=True)

    # Camino de compatibilidad: mermas registradas ANTES de que existiera
    # `movimientos_inventario.merma_id`. Hay que emparejarlas por motivo y hora.
    #
    # `merma_id IS NULL` no es un detalle: al revertir, el movimiento queda
    # SELLADO con la merma que lo reclamó (abajo), así que un movimiento no puede
    # devolverse dos veces ni aunque el emparejamiento se equivoque. Sin ese
    # candado el 21-sep devolví el doble en producción.
    desde = merma.fecha_registro - timedelta(seconds=VENTANA_REVERSA_SEG)
    hasta = merma.fecha_registro + timedelta(seconds=VENTANA_REVERSA_SEG)
    candidatos = (
        db.query(MovimientoInventario)
        .filter(
            MovimientoInventario.tienda_id == tienda_id,
            MovimientoInventario.tipo == TipoMovInvEnum.salida,
            MovimientoInventario.merma_id.is_(None),
            MovimientoInventario.fecha >= desde,
            MovimientoInventario.fecha <= hasta,
        )
        .all()
    )

    # El motivo se compara COMPLETO, con el nombre del producto incluido, no por
    # el prefijo común. Un envío del formulario registra VARIAS mermas en el
    # mismo instante —2 mokaccinos y 2 cappuccinos van juntos— y sus movimientos
    # comparten prefijo ("Consumo (jueces): visita de los jueces") pero no el
    # sufijo "— insumo de <bebida>". Emparejar por prefijo le daba a cada una de
    # las dos mermas los cinco movimientos del envío: devolvía el doble. Pasó en
    # producción el 21-sep, con estas mismas diez.
    if controla:
        # Producto con stock propio: un solo movimiento, con el motivo pelado.
        def coincide(m):
            return (m.motivo or "") == mov_motivo
    else:
        # Bebida preparada: un movimiento por insumo. La cascada al sustituto le
        # agrega " (reserva de #N)" al final, así que el nombre va como prefijo.
        esperado = f"{mov_motivo} — insumo de {producto.nombre if producto else ''}"

        def coincide(m):
            return (m.motivo or "").startswith(esperado)

    # `coincide` en Python y no LIKE en SQL: el motivo lo escribe la barista y un
    # `%` o un `_` suelto ensancharían el LIKE. La ventana es de segundos, así que
    # traer los candidatos y filtrarlos acá no cuesta nada.
    movs = [m for m in candidatos if coincide(m)]

    # Todavía puede haber DOS mermas del MISMO producto dentro de la ventana (la
    # barista guardó dos veces el mismo formulario). Ahí sí se separan por tanda:
    # los movimientos de una merma nacen en la misma transacción, con
    # milisegundos entre uno y otro, mientras que dos envíos distintos quedan a
    # segundos. No se cuentan renglones de receta porque una cascada parcial —el
    # insumo alcanza para la mitad y el resto sale del sustituto— deja DOS
    # movimientos para un solo renglón.
    movs.sort(key=lambda m: m.fecha)
    tandas: list[list[MovimientoInventario]] = []
    for m in movs:
        if tandas and (m.fecha - tandas[-1][-1].fecha).total_seconds() <= CORTE_TANDA_SEG:
            tandas[-1].append(m)
        else:
            tandas.append([m])
    if len(tandas) > 1:
        movs = min(tandas, key=lambda t: min(
            abs((x.fecha - merma.fecha_registro).total_seconds()) for x in t))

    # Y todavía queda el caso que el tiempo NO puede separar: dos mermas del
    # mismo producto, con el mismo motivo y en el mismo instante (doble toque de
    # medio segundo). Las dos caen en la misma tanda, así que la tanda se reparte
    # en partes iguales y cada merma se lleva la suya. Cierra solo: anular borra
    # la merma y sella sus movimientos, así que en la llamada siguiente hay una
    # hermana menos y exactamente esa parte menos para repartir.
    q_hermanas = db.query(Merma).filter(
        Merma.id != merma_id,
        Merma.tienda_id == tienda_id,
        Merma.producto_id == pid,
        Merma.cantidad == cant,
        Merma.motivo == merma.motivo,
        Merma.fecha_registro >= desde,
        Merma.fecha_registro <= hasta,
    )
    # `== None` no compara en SQL: NULL nunca es igual a nada, ni a NULL.
    q_hermanas = q_hermanas.filter(
        Merma.quien.is_(None) if merma.quien is None else Merma.quien == merma.quien
    )
    hermanas = 1 + q_hermanas.count()
    if hermanas > 1 and movs and len(movs) % hermanas == 0:
        movs = movs[: len(movs) // hermanas]

    if movs:
        return _devolver_y_borrar(db, merma, movs, usuario_id, sellados=False)

    # Ni sello ni movimientos: no queda de dónde leer lo que salió, así que se
    # devuelve por receta (o el producto mismo) y la respuesta lo avisa.
    if controla:
        fallback = [(pid, cant)]
    else:
        fallback = [
            (r.insumo_id, r.cantidad * cant)
            for r in db.query(ProductoInsumo).filter(ProductoInsumo.producto_id == pid).all()
        ]
    return _devolver_y_borrar(db, merma, None, usuario_id, sellados=False,
                              por_receta=fallback)


def _devolver_y_borrar(db: Session, merma: Merma, movs, usuario_id: int, *,
                       sellados: bool, por_receta: list[tuple[int, float]] | None = None):
    """Compensa con entradas lo que la merma descontó, borra el registro y audita.
    `movs` son los movimientos a revertir uno por uno; `por_receta` es el plan de
    respaldo (producto, cantidad) cuando no hay movimientos de dónde leer."""
    merma_id, tienda_id = merma.id, merma.tienda_id
    pid, cant = merma.producto_id, merma.cantidad
    tipo = merma.tipo.value if hasattr(merma.tipo, "value") else str(merma.tipo)
    motivo_reversa = f"Anulación {tipo} #{merma_id}: devuelve lo descontado"
    plan = por_receta if movs is None else [(m.producto_id, m.cantidad) for m in movs]

    # Reclamar los movimientos: quedan sellados con esta merma, así que ninguna
    # otra anulación puede volver a devolverlos. El sello sobrevive al borrado de
    # la fila de `mermas` —la columna es plana, sin FK— y eso es justo lo que lo
    # hace un candado y no un apunte más.
    for m in (movs or []):
        m.merma_id = merma_id

    devuelto: list[dict] = []
    for producto_id, cantidad in plan:
        if cantidad <= 0:
            continue
        try:
            registrar_movimiento(
                db, producto_id=producto_id, tienda_id=tienda_id,
                tipo="entrada", cantidad=cantidad,
                motivo=motivo_reversa, usuario_id=usuario_id, commit=False,
            )
            devuelto.append({"producto_id": producto_id, "cantidad": cantidad})
        except HTTPException as e:
            # 404 = el insumo no tiene fila de inventario en esta sede, igual que
            # cuando se salteó al descontar. No es motivo para abortar la reversa.
            if e.status_code != 404:
                raise
            logger.warning(
                f"Anular merma {merma_id}: producto {producto_id} sin inventario "
                f"en tienda {tienda_id}, devolución salteada"
            )

    audit.registrar(
        db, accion="anular_merma", tabla="mermas",
        registro_id=merma_id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_antes={"producto_id": pid, "cantidad": cant, "tipo": tipo,
                     "motivo": merma.motivo, "quien": merma.quien},
        datos_despues={"devuelto": devuelto, "sellados": sellados,
                       "por_receta": por_receta is not None},
    )
    db.delete(merma)
    db.commit()
    return {"anulado": merma_id, "producto_id": pid, "cantidad": cant, "tipo": tipo,
            "devuelto": devuelto, "sellados": sellados,
            "por_receta": por_receta is not None}


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
