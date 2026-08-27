from sqlalchemy.orm import Session, joinedload
from sqlalchemy import update as sa_update, nulls_last
from fastapi import HTTPException
from app.models.models import Inventario, MovimientoInventario, LoteInventario, Producto, Tienda
from datetime import datetime
from app.services import audit


def clasificar_estado(stock_actual: float, stock_minimo: float,
                      stock_critico: float, stock_ideal: float = 0.0) -> str:
    """Clasificador de 4 estados de stock. Único punto de verdad.
    AGOTADO  si stock_actual <= 0
    CRITICO  si 0 < stock_actual <= stock_critico (solo si stock_critico está configurado)
    BAJO     si stock_critico < stock_actual <= stock_minimo
    NORMAL   si stock_actual > stock_minimo
    Nota: si stock_critico no está configurado (0), CRITICO no aplica y cae a BAJO/NORMAL."""
    if stock_actual <= 0:
        return "agotado"
    if stock_critico > 0 and stock_actual <= stock_critico:
        return "critico"
    if stock_actual <= stock_minimo:
        return "bajo"
    return "normal"


def get_inventario_desechables(db: Session, tienda_id: int):
    """Productos del formato de desechables (grupo_conteo='desechables'), agrupables
    por proveedor. NO entran en el conteo diario (incluir_en_conteo=False)."""
    items = (
        db.query(Inventario)
        .options(joinedload(Inventario.producto))
        .join(Inventario.producto)
        .filter(Inventario.tienda_id == tienda_id, Producto.grupo_conteo == "desechables")
        .order_by(Producto.proveedor.asc(), nulls_last(Producto.orden_conteo.asc()), Producto.nombre.asc())
        .all()
    )
    return [{
        "producto_id": i.producto_id,
        "producto_nombre": i.producto.nombre,
        "unidad_medida": i.producto.unidad_medida,
        "proveedor": i.producto.proveedor or "Sin proveedor",
        "stock_actual": round(i.stock_actual or 0, 2),
    } for i in items]


def get_inventario_tienda(db: Session, tienda_id: int):
    items = (
        db.query(Inventario)
        .options(joinedload(Inventario.producto))
        .join(Inventario.producto)
        .filter(Inventario.tienda_id == tienda_id, Producto.incluir_en_conteo.isnot(False))
        # Orden fijo de la planilla de conteo (orden_conteo); los que no tienen posición
        # van al final en alfabético. Antes no había ORDER BY: orden indefinido de la DB.
        .order_by(nulls_last(Producto.orden_conteo.asc()), Producto.nombre.asc())
        .all()
    )
    result = []
    for item in items:
        result.append({
            "id": item.id,
            "producto_id": item.producto_id,
            "tienda_id": item.tienda_id,
            # 2 decimales: los fraccionables pueden tener stock 3.5 (selladas + nivel abierta).
            "stock_actual": round(item.stock_actual or 0, 2),
            "stock_minimo": round(item.stock_minimo or 0, 2),
            "producto_nombre": item.producto.nombre,
            "categoria": item.producto.categoria.value,
            "unidad_medida": item.producto.unidad_medida,
            "fraccionable": bool(item.producto.fraccionable),
            "envase": item.producto.envase,
            "contenido_por_unidad": float(item.producto.contenido_por_unidad) if item.producto.contenido_por_unidad else None,
            # Posición en el recorrido físico del conteo. Viaja al cliente porque
            # las pantallas de conteo (apertura/cierre) ordenan EN CLIENTE y
            # dibujan el corte entre bloques; el ORDER BY de arriba ya las deja
            # en este mismo orden, así que los demás consumidores de este payload
            # (kiosko, panel POS) no cambian de comportamiento.
            "orden_conteo": item.producto.orden_conteo,
            "alerta": item.stock_actual <= item.stock_minimo,
        })
    return result


def _notificar_preparable_negativo(db: Session, producto_id: int, tienda_id: int,
                                   stock_resultante: float) -> None:
    """Si el producto que cruzó a negativo es un PREPARABLE (controla stock, tiene
    receta de preparación y no se vende), dispara la notificación al admin."""
    from app.models.models import ProductoInsumo
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p or not p.controla_stock or (p.precio_venta or 0) > 0:
        return
    tiene_receta = db.query(ProductoInsumo).filter_by(producto_id=producto_id).first()
    if not tiene_receta:
        return
    try:
        from app.services import notificaciones
        msg = (f"{p.nombre} quedó en {round(stock_resultante)} {p.unidad_medida}: "
               "se está vendiendo sin registrar la preparación")
        notificaciones.disparar(
            db, tienda_id=tienda_id, tipo="preparacion_sin_registrar",
            mensaje=msg, nivel="advertencia", referencia_id=producto_id,
            push_titulo="Preparación sin registrar", push_cuerpo=msg,
        )
    except Exception:   # noqa: BLE001 — una notificación nunca debe tumbar una venta
        logger = __import__("logging").getLogger(__name__)
        logger.warning("No se pudo disparar preparacion_sin_registrar", exc_info=True)


def registrar_movimiento(db: Session, producto_id: int, tienda_id: int, tipo: str,
                          cantidad: float, motivo: str | None, usuario_id: int,
                          fecha_vencimiento: datetime | None = None, commit: bool = True,
                          allow_negative: bool = False,
                          numero_lote: str | None = None, proveedor: str | None = None,
                          fecha_fabricacion: datetime | None = None, factura_id: int | None = None,
                          barista_id: int | None = None, barista_nombre: str | None = None):
    if tipo not in {"entrada", "salida", "ajuste"}:
        raise HTTPException(status_code=400, detail="tipo debe ser entrada, salida o ajuste")
    if tipo in {"entrada", "salida"} and cantidad <= 0:
        raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0")
    if tipo == "ajuste" and cantidad < 0:
        raise HTTPException(status_code=400, detail="cantidad no puede ser negativa en ajuste")
    # Verify product exists first (needed for all branches)
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id,
        Inventario.tienda_id == tienda_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario de esta tienda")

    if tipo == "entrada":
        # Atomic increment — no read-modify-write race
        db.execute(
            sa_update(Inventario)
            .where(
                Inventario.producto_id == producto_id,
                Inventario.tienda_id == tienda_id,
            )
            .values(stock_actual=Inventario.stock_actual + cantidad)
        )
        agregar_lote(db, producto_id, tienda_id, cantidad, usuario_id, fecha_vencimiento,
                     numero_lote=numero_lote, proveedor=proveedor,
                     fecha_fabricacion=fecha_fabricacion, factura_id=factura_id)
    elif tipo == "salida":
        stock_antes_salida = float(inv.stock_actual or 0)
        if allow_negative:
            # POS mode: permitir stock negativo (proveedor llega después)
            db.execute(
                sa_update(Inventario)
                .where(Inventario.producto_id == producto_id, Inventario.tienda_id == tienda_id)
                .values(stock_actual=Inventario.stock_actual - cantidad)
            )
        else:
            # Modo normal: bloquear si no hay suficiente stock
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
                raise HTTPException(status_code=400, detail="Stock insuficiente")
        consumir_fifo(db, producto_id, tienda_id, cantidad)
        # Un PREPARABLE (mezcla de granizado) que CRUZA a negativo = se está
        # vendiendo sin registrar la preparación. Avisar al admin (dedupe diario
        # del motor de notificaciones — no spamea por cada venta).
        if stock_antes_salida >= 0 and stock_antes_salida - cantidad < 0:
            _notificar_preparable_negativo(db, producto_id, tienda_id,
                                           stock_antes_salida - cantidad)
    elif tipo == "ajuste":
        # Read current stock to compute FIFO delta, then set atomically
        stock_antes = inv.stock_actual
        db.execute(
            sa_update(Inventario)
            .where(
                Inventario.producto_id == producto_id,
                Inventario.tienda_id == tienda_id,
            )
            .values(stock_actual=cantidad)
        )
        # Etapa 2: sincronizar lotes FIFO al ajustar stock
        diferencia = cantidad - stock_antes
        if diferencia > 0:
            # Stock aumentó → lote de ajuste positivo
            agregar_lote(db, producto_id, tienda_id, diferencia, usuario_id)
        elif diferencia < 0:
            # Stock disminuyó → consumir diferencia de lotes más antiguos
            consumir_fifo(db, producto_id, tienda_id, abs(diferencia))

    # Re-fetch to get the updated value for audit and return
    db.flush()
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id,
        Inventario.tienda_id == tienda_id
    ).first()

    mov = MovimientoInventario(
        producto_id=producto_id, tienda_id=tienda_id, tipo=tipo,
        cantidad=cantidad, usuario_id=usuario_id, motivo=motivo,
        barista_id=barista_id, barista_nombre=barista_nombre,
    )
    db.add(mov)

    _tick_checklist_inventario(db, tienda_id)
    audit.registrar(
        db, accion=f"inventario_{tipo}", tabla="movimientos_inventario",
        registro_id=None, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"producto_id": producto_id, "tipo": tipo,
                       "cantidad": cantidad, "motivo": motivo,
                       "stock_resultante": inv.stock_actual},
    )

    # Motor de notificaciones: alerta de stock al consumir. Nunca rompe el flujo.
    if tipo == "salida":
        try:
            from app.services import notificaciones
            nombre = inv.producto.nombre if inv.producto else None
            stock_final = float(inv.stock_actual or 0)
            # NEGATIVO ≠ AGOTADO, y la diferencia no es de grado. Agotado es «se
            # acabó, hay que pedir». Negativo es «este número es imposible»: o
            # entró mercadería sin registrar, o una receta descuenta lo que no
            # es. `clasificar_estado` los mete a los dos en «agotado» —correcto
            # para decidir un pedido, inútil para encontrar el error— así que el
            # aviso se separa acá.
            if stock_final < 0:
                notificaciones.evaluar_stock_negativo(
                    db, tienda_id, producto_id, nombre, stock_final)
            else:
                estado = clasificar_estado(
                    inv.stock_actual, inv.stock_minimo or 0.0,
                    inv.stock_critico or 0.0, inv.stock_ideal or 0.0,
                )
                if estado in ("critico", "agotado"):
                    notificaciones.evaluar_stock(db, tienda_id, producto_id, nombre, estado)
        except Exception:
            pass

    if commit:
        db.commit()
        db.refresh(inv)
    return inv


def consumir_insumo(db: Session, producto_id: int, tienda_id: int, cantidad: float,
                    motivo: str, usuario_id: int, barista_id: int | None = None,
                    barista_nombre: str | None = None, _visitados=None):
    """Descuenta `cantidad` de un insumo por receta con CASCADA a su sustituto.
    Si el insumo tiene sustituto_id y su stock no alcanza, saca lo disponible
    (hasta 0) y el resto lo descuenta del sustituto (que puede tener el suyo →
    cascada, con guard anti-ciclo). Sin sustituto, o si alcanza, o si no tiene
    fila, se comporta como una salida normal con allow_negative (igual que antes).
    NO hace commit."""
    _visitados = _visitados or set()
    prod = db.query(Producto).filter_by(id=producto_id).first()
    sustituto_id = getattr(prod, "sustituto_id", None) if prod else None
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id, Inventario.tienda_id == tienda_id
    ).first()
    stock = float(inv.stock_actual) if inv else None

    # Salida normal si: no hay sustituto, ciclo detectado, no hay fila, o alcanza.
    if not sustituto_id or sustituto_id in _visitados or stock is None or stock >= cantidad:
        registrar_movimiento(db, producto_id=producto_id, tienda_id=tienda_id,
                             tipo="salida", cantidad=cantidad, motivo=motivo,
                             usuario_id=usuario_id, commit=False, allow_negative=True,
                             barista_id=barista_id, barista_nombre=barista_nombre)
        return

    # No alcanza: tomar lo disponible (hasta 0) y el resto del sustituto.
    _visitados.add(producto_id)
    tomar = max(0.0, stock)
    if tomar > 0:
        registrar_movimiento(db, producto_id=producto_id, tienda_id=tienda_id,
                             tipo="salida", cantidad=tomar, motivo=motivo,
                             usuario_id=usuario_id, commit=False, allow_negative=True,
                             barista_id=barista_id, barista_nombre=barista_nombre)
    resto = round(cantidad - tomar, 4)
    if resto > 0:
        consumir_insumo(db, sustituto_id, tienda_id, resto,
                        f"{motivo} (reserva de #{producto_id})", usuario_id,
                        barista_id=barista_id, barista_nombre=barista_nombre,
                        _visitados=_visitados)


def agregar_lote(db: Session, producto_id: int, tienda_id: int,
                 cantidad: float, usuario_id: int,
                 fecha_vencimiento: datetime | None = None,
                 numero_lote: str | None = None, proveedor: str | None = None,
                 fecha_fabricacion: datetime | None = None, factura_id: int | None = None):
    """Crea un lote FIFO con su trazabilidad. NO hace commit — dentro de una transacción."""
    lote = LoteInventario(
        producto_id=producto_id,
        tienda_id=tienda_id,
        cantidad_inicial=cantidad,
        cantidad_restante=cantidad,
        usuario_id=usuario_id,
        fecha_vencimiento=fecha_vencimiento,
        numero_lote=numero_lote,
        proveedor=proveedor,
        fecha_fabricacion=fecha_fabricacion,
        factura_id=factura_id,
    )
    db.add(lote)


def consumir_fifo(db: Session, producto_id: int, tienda_id: int, cantidad: float):
    """Descuenta cantidad de los lotes más antiguos (FIFO). NO hace commit.
    Marca fecha_agotado cuando un lote llega a 0 (trazabilidad de consumo)."""
    lotes = db.query(LoteInventario).filter(
        LoteInventario.producto_id == producto_id,
        LoteInventario.tienda_id == tienda_id,
        LoteInventario.cantidad_restante > 0,
    ).order_by(LoteInventario.fecha_entrada.asc()).all()

    restante = cantidad
    for lote in lotes:
        if restante <= 0:
            break
        consumido = min(lote.cantidad_restante, restante)
        lote.cantidad_restante -= consumido
        restante -= consumido
        if lote.cantidad_restante <= 0 and lote.fecha_agotado is None:
            lote.fecha_agotado = datetime.utcnow()
    # Si restante > 0, los lotes no cubren (stock registrado antes del FIFO).
    # Se ignora silenciosamente para no bloquear operaciones.


def get_lotes(db: Session, tienda_id: int, producto_id: int):
    """Lotes FIFO activos (con stock) de un producto. Solo para admin."""
    return db.query(LoteInventario).filter(
        LoteInventario.tienda_id == tienda_id,
        LoteInventario.producto_id == producto_id,
    ).order_by(LoteInventario.fecha_entrada.asc()).all()


def get_trazabilidad(db: Session, tienda_id: int | None = None, producto_id: int | None = None,
                     proveedor: str | None = None, estado: str | None = None):
    """Trazabilidad de lotes: qué lote entró, cuándo, qué proveedor, vencimiento,
    cuánto queda / % consumido, estado (activo/por_vencer/vencido/agotado) y cuándo se
    agotó. Filtrable por sede, producto, proveedor y estado."""
    from datetime import timedelta
    q = db.query(LoteInventario).options(
        joinedload(LoteInventario.producto), joinedload(LoteInventario.tienda),
    )
    if tienda_id is not None:
        q = q.filter(LoteInventario.tienda_id == tienda_id)
    if producto_id is not None:
        q = q.filter(LoteInventario.producto_id == producto_id)
    if proveedor:
        q = q.filter(LoteInventario.proveedor == proveedor)
    lotes = q.order_by(LoteInventario.fecha_entrada.desc()).limit(800).all()

    ahora = datetime.utcnow()
    pronto = ahora + timedelta(days=7)
    out = []
    for l in lotes:
        # Productos archivados (duplicados de la limpieza) fuera de la vista: su
        # historial queda en la DB pero no ensucia la trazabilidad (caso agua con gas).
        p = l.producto
        if p and not p.controla_stock and p.incluir_en_conteo is False and not (p.precio_venta or 0):
            continue
        ini = l.cantidad_inicial or 0
        rest = l.cantidad_restante or 0
        if rest <= 0:
            est = "agotado"
        elif l.fecha_vencimiento and l.fecha_vencimiento < ahora:
            est = "vencido"
        elif l.fecha_vencimiento and l.fecha_vencimiento <= pronto:
            est = "por_vencer"
        else:
            est = "activo"
        out.append({
            "id": l.id,
            "producto_id": l.producto_id,
            "producto_nombre": l.producto.nombre if l.producto else "",
            "unidad_medida": l.producto.unidad_medida if l.producto else "",
            "tienda_id": l.tienda_id,
            "tienda_nombre": l.tienda.nombre if l.tienda else None,
            "proveedor": l.proveedor,
            "numero_lote": l.numero_lote,
            "factura_id": l.factura_id,
            "cantidad_inicial": round(ini, 2),
            "cantidad_restante": round(rest, 2),
            "consumido_pct": round((1 - rest / ini) * 100, 1) if ini else 0,
            "fecha_entrada": l.fecha_entrada,
            "fecha_fabricacion": l.fecha_fabricacion,
            "fecha_vencimiento": l.fecha_vencimiento,
            "fecha_agotado": l.fecha_agotado,
            "estado": est,
        })
    if estado:
        out = [o for o in out if o["estado"] == estado]
    return out


def get_alertas(db: Session, tienda_id: int):
    """Alertas de stock con 4 estados. Filtra todo lo que no es NORMAL.
    Compat: mantiene 'nivel' (agotado|bajo) para AdminHub; agrega 'estado' de 4 estados
    y 'cantidad_sugerida' calculada hacia stock_ideal (o el doble del mínimo si no hay ideal).
    Agrega 'accion' (comprar|preparar): la barista pide reposición desde acá y la
    mezcla de granizado no se le pide a nadie, se prepara."""
    from app.services import preparables as preparables_svc
    items = db.query(Inventario).options(joinedload(Inventario.producto)).filter(
        Inventario.tienda_id == tienda_id,
        Inventario.stock_actual <= Inventario.stock_minimo,
    ).order_by(Inventario.stock_actual.asc()).all()
    # Solo inventario GESTIONADO (controla stock + en el conteo): sin este filtro los
    # archivados y lo no-contado inflaban la alarma con "agotados" falsos.
    items = [i for i in items if i.producto and i.producto.controla_stock
             and i.producto.incluir_en_conteo is not False]
    prep_ids = preparables_svc.ids_preparables(db)
    out = []
    for i in items:
        estado = clasificar_estado(
            i.stock_actual, i.stock_minimo,
            i.stock_critico or 0.0, i.stock_ideal or 0.0,
        )
        objetivo = i.stock_ideal if (i.stock_ideal and i.stock_ideal > 0) else (i.stock_minimo * 2)
        out.append({
            "producto_id": i.producto_id,
            "producto": i.producto.nombre,
            "unidad": i.producto.unidad_medida,
            "stock_actual": round(i.stock_actual),
            "stock_minimo": round(i.stock_minimo),
            "stock_critico": round(i.stock_critico or 0),
            "stock_ideal": round(i.stock_ideal or 0),
            "estado": estado,                                        # nuevo: agotado|critico|bajo
            "nivel": "agotado" if estado == "agotado" else "bajo",  # COMPAT AdminHub actual
            "cantidad_sugerida": max(1, round(objetivo - i.stock_actual)),
            "accion": "preparar" if i.producto_id in prep_ids else "comprar",
        })
    return out


def get_alertas_consolidadas(db: Session, tienda_id: int | None = None):
    """Alertas de stock consolidadas. Si se pasa tienda_id, delega a get_alertas
    (una sola sede). Si no, agrega las alertas de TODAS las sedes activas, incluyendo
    tienda_id/tienda_nombre en cada fila para que el frontend sepa de qué sede es.
    Mantiene exactamente la misma forma de fila que get_alertas."""
    if tienda_id is not None:
        return get_alertas(db, tienda_id)

    tiendas = db.query(Tienda).filter_by(activa=True).all()
    nombres = {t.id: t.nombre for t in tiendas}
    tienda_ids = list(nombres.keys())
    if not tienda_ids:
        return []

    items = (
        db.query(Inventario)
        .options(joinedload(Inventario.producto))
        .filter(
            Inventario.tienda_id.in_(tienda_ids),
            Inventario.stock_actual <= Inventario.stock_minimo,
        )
        .order_by(Inventario.stock_actual.asc())
        .all()
    )
    # Solo inventario GESTIONADO — misma regla que get_alertas.
    items = [i for i in items if i.producto and i.producto.controla_stock
             and i.producto.incluir_en_conteo is not False]
    # Orden estable: primero por estado (agotado < critico < bajo), luego stock asc.
    orden_estado = {"agotado": 0, "critico": 1, "bajo": 2, "normal": 3}
    from app.services import preparables as preparables_svc
    prep_ids = preparables_svc.ids_preparables(db)
    out = []
    for i in items:
        estado = clasificar_estado(
            i.stock_actual, i.stock_minimo,
            i.stock_critico or 0.0, i.stock_ideal or 0.0,
        )
        objetivo = i.stock_ideal if (i.stock_ideal and i.stock_ideal > 0) else (i.stock_minimo * 2)
        out.append({
            "producto_id": i.producto_id,
            "producto": i.producto.nombre,
            "unidad": i.producto.unidad_medida,
            "stock_actual": round(i.stock_actual),
            "stock_minimo": round(i.stock_minimo),
            "stock_critico": round(i.stock_critico or 0),
            "stock_ideal": round(i.stock_ideal or 0),
            "estado": estado,
            "nivel": "agotado" if estado == "agotado" else "bajo",
            "cantidad_sugerida": max(1, round(objetivo - i.stock_actual)),
            "accion": "preparar" if i.producto_id in prep_ids else "comprar",
            "tienda_id": i.tienda_id,
            "tienda_nombre": nombres.get(i.tienda_id, ""),
        })
    out.sort(key=lambda o: (orden_estado.get(o["estado"], 9), o["stock_actual"]))
    return out


def _tick_checklist_inventario(db: Session, tienda_id: int):
    from app.services.caja import _tick_checklist
    _tick_checklist(db, tienda_id, inventario_check=True)


# ─── Preparaciones: transformar materia prima en producto intermedio ─────────
# Un producto es "preparable" si controla stock, tiene receta (producto_insumos)
# y NO se vende en el POS (precio_venta 0) — ej. la mezcla de granizado. Su
# contenido_por_unidad es el RENDIMIENTO de una preparación (gr que produce).
# La regla vive en `services/preparables.py`; acá se importa, no se repite.

def get_preparables(db: Session, tienda_id: int) -> list:
    from app.models.models import ProductoInsumo
    from app.services import preparables as preparables_svc
    ids = preparables_svc.ids_preparables(db)
    rows = db.query(Producto).filter(Producto.id.in_(ids)).all() if ids else []
    stocks = {
        i.producto_id: i.stock_actual
        for i in db.query(Inventario).filter(
            Inventario.tienda_id == tienda_id,
            Inventario.producto_id.in_([p.id for p in rows]),
        ).all()
    } if rows else {}
    out = []
    for p in rows:
        receta = (
            db.query(ProductoInsumo, Producto)
            .join(Producto, Producto.id == ProductoInsumo.insumo_id)
            .filter(ProductoInsumo.producto_id == p.id)
            .all()
        )
        out.append({
            "producto_id": p.id,
            "nombre": p.nombre,
            "unidad_medida": p.unidad_medida,
            "rendimiento": p.contenido_por_unidad,
            "stock_actual": stocks.get(p.id, 0.0),
            "insumos": [{"insumo_id": pi.insumo_id, "nombre": prod.nombre,
                         "cantidad": pi.cantidad, "unidad_medida": prod.unidad_medida}
                        for pi, prod in receta],
        })
    return out


def registrar_preparacion(db: Session, producto_id: int, tienda_id: int, cantidad: float,
                          usuario_id: int, barista_id: int | None = None,
                          barista_nombre: str | None = None,
                          idempotency_key: str | None = None) -> dict:
    """Registra que se preparó `cantidad` tandas de un producto intermedio:
    descuenta los insumos de su receta y suma el rendimiento al stock del producto.
    Atómico: todo en una transacción. Idempotente: si `idempotency_key` ya se usó,
    es un doble-disparo (doble tap, reintento de red) → devuelve el resultado previo
    SIN volver a mover inventario."""
    import json as _json
    from app.models.models import ProductoInsumo, IdempotencyKey
    from sqlalchemy.exc import IntegrityError

    # Replay directo: la llave ya está registrada → no re-aplicamos nada.
    if idempotency_key:
        prev = db.query(IdempotencyKey).filter_by(key=idempotency_key).first()
        if prev is not None:
            try:
                return {**_json.loads(prev.resultado or "{}"), "duplicada": True}
            except Exception:
                return {"producto_id": producto_id, "duplicada": True}

    if cantidad <= 0:
        raise HTTPException(400, "La cantidad de preparaciones debe ser mayor a 0")
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    if not p.controla_stock or (p.precio_venta or 0) > 0:
        raise HTTPException(400, "Este producto no es preparable")
    if not p.contenido_por_unidad or p.contenido_por_unidad <= 0:
        raise HTTPException(400, "El producto no tiene rendimiento configurado (contenido por unidad)")
    receta = db.query(ProductoInsumo).filter_by(producto_id=producto_id).all()
    if not receta:
        raise HTTPException(400, "El producto no tiene receta de preparación")

    # Reserva la llave DENTRO de la transacción de los movimientos: el UNIQUE del
    # índice es la garantía real — una carrera entre dos requests idénticos choca
    # acá y solo uno pasa. Si después algo falla y se hace rollback, la llave se
    # libera y el reintento legítimo con la misma llave vuelve a aplicarse.
    idem_row = None
    if idempotency_key:
        idem_row = IdempotencyKey(key=idempotency_key, scope="preparacion")
        db.add(idem_row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            prev = db.query(IdempotencyKey).filter_by(key=idempotency_key).first()
            if prev is not None and prev.resultado:
                return {**_json.loads(prev.resultado), "duplicada": True}
            return {"producto_id": producto_id, "duplicada": True}

    quien = f" ({barista_nombre})" if barista_nombre else ""
    motivo = f"Preparación: {p.nombre}{quien}"
    for r in receta:
        registrar_movimiento(
            db, producto_id=r.insumo_id, tienda_id=tienda_id, tipo="salida",
            cantidad=r.cantidad * cantidad, motivo=motivo, usuario_id=usuario_id,
            commit=False, allow_negative=True,
            barista_id=barista_id, barista_nombre=barista_nombre,
        )
    producido = p.contenido_por_unidad * cantidad
    registrar_movimiento(
        db, producto_id=producto_id, tienda_id=tienda_id, tipo="entrada",
        cantidad=producido, motivo=motivo, usuario_id=usuario_id, commit=False,
        barista_id=barista_id, barista_nombre=barista_nombre,
    )
    audit.registrar(
        db, accion="preparacion", tabla="productos", registro_id=producto_id,
        usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"producto": p.nombre, "tandas": cantidad, "producido": producido,
                       "barista": barista_nombre,
                       "insumos": [{"id": r.insumo_id, "cantidad": r.cantidad * cantidad} for r in receta]},
    )
    inv = db.query(Inventario).filter_by(producto_id=producto_id, tienda_id=tienda_id).first()
    resultado = {"producto_id": producto_id, "producido": float(producido),
                 "stock_actual": float(inv.stock_actual) if inv else float(producido)}
    # Guardar el resultado en la llave para que el replay devuelva lo mismo.
    if idem_row is not None:
        idem_row.resultado = _json.dumps(resultado)
    db.commit()
    return resultado


def unificar_productos(db: Session, keeper_id: int, archive_ids: list[int],
                       usuario_id: int, dry_run: bool = True) -> dict:
    """Consolida productos DUPLICADOS en uno (keeper). Lee la tabla REAL de
    Inventario (no las vistas filtradas). Por cada archivado y cada sede:
      - stock POSITIVO → se mueve al keeper (creando su fila si falta) y el
        archivado queda en 0.
      - stock NEGATIVO (fantasma) → se descarta (archivado a 0), sin ensuciar al keeper.
    Luego archiva cada duplicado: incluir_en_conteo=False + controla_stock=False.
    Con dry_run=True NO escribe: devuelve el plan exacto para revisar. Solo admin."""
    keeper = db.query(Producto).filter_by(id=keeper_id).first()
    if not keeper:
        raise HTTPException(404, f"Keeper {keeper_id} no encontrado")
    if keeper_id in archive_ids:
        raise HTTPException(400, "El keeper no puede estar en la lista de archivados")
    tiendas = db.query(Tienda).all()

    plan = []
    for aid in archive_ids:
        arch = db.query(Producto).filter_by(id=aid).first()
        if not arch:
            plan.append({"archive_id": aid, "warning": "producto no existe, se ignora"})
            continue
        for t in tiendas:
            a_inv = db.query(Inventario).filter_by(producto_id=aid, tienda_id=t.id).first()
            if not a_inv:
                continue
            cant = round(float(a_inv.stock_actual or 0), 3)
            if cant > 0:
                plan.append({"archive_id": aid, "nombre": arch.nombre, "tienda_id": t.id,
                             "mover_al_keeper": cant})
            elif cant < 0:
                plan.append({"archive_id": aid, "nombre": arch.nombre, "tienda_id": t.id,
                             "descartar_negativo": cant})
        plan.append({"archive_id": aid, "nombre": arch.nombre,
                     "accion": "archivar (incluir_en_conteo=False, controla_stock=False)"})

    if dry_run:
        return {"dry_run": True, "keeper_id": keeper_id, "keeper_nombre": keeper.nombre, "plan": plan}

    # ── EJECUTAR ────────────────────────────────────────────────────────────────
    movidos = []
    for aid in archive_ids:
        arch = db.query(Producto).filter_by(id=aid).first()
        if not arch:
            continue
        motivo = f"Unificación: {arch.nombre} (#{aid}) → {keeper.nombre} (#{keeper_id})"
        for t in tiendas:
            a_inv = db.query(Inventario).filter_by(producto_id=aid, tienda_id=t.id).first()
            if not a_inv:
                continue
            cant = round(float(a_inv.stock_actual or 0), 3)
            if cant > 0:
                # Asegurar fila del keeper en esta sede (registrar_movimiento la exige).
                k_inv = db.query(Inventario).filter_by(producto_id=keeper_id, tienda_id=t.id).first()
                if not k_inv:
                    k_inv = Inventario(producto_id=keeper_id, tienda_id=t.id,
                                       stock_actual=0.0, stock_minimo=0.0)
                    db.add(k_inv)
                    db.flush()
                # Entrada al keeper (+stock +lote) y salida del archivado (→0, consume FIFO).
                registrar_movimiento(db, producto_id=keeper_id, tienda_id=t.id, tipo="entrada",
                                     cantidad=cant, motivo=motivo, usuario_id=usuario_id, commit=False)
                registrar_movimiento(db, producto_id=aid, tienda_id=t.id, tipo="salida",
                                     cantidad=cant, motivo=motivo, usuario_id=usuario_id,
                                     commit=False, allow_negative=True)
                movidos.append({"archive_id": aid, "tienda_id": t.id, "cantidad": cant})
            elif cant < 0:
                # Descartar el negativo fantasma: ajuste a 0 (no toca al keeper).
                registrar_movimiento(db, producto_id=aid, tienda_id=t.id, tipo="ajuste",
                                     cantidad=0, motivo=f"{motivo} — descartar negativo",
                                     usuario_id=usuario_id, commit=False)
        arch.incluir_en_conteo = False
        arch.controla_stock = False
        # También sacarlo del bucket de desechables (esa lista filtra por
        # grupo_conteo, NO por incluir_en_conteo): sin esto el duplicado seguía
        # apareciendo en el conteo de desechables.
        arch.grupo_conteo = None

    audit.registrar(
        db, accion="unificar_productos", tabla="productos", registro_id=keeper_id,
        usuario_id=usuario_id, tienda_id=None,
        datos_despues={"keeper_id": keeper_id, "archivados": archive_ids, "movidos": movidos},
    )
    db.commit()
    return {"dry_run": False, "keeper_id": keeper_id, "archivados": archive_ids, "movidos": movidos}


def get_insumos_de_producto(db: Session, producto_id: int) -> list[dict]:
    """Receta de consumo: insumos que se descuentan del inventario por cada
    unidad vendida del producto. Sin relationships (dos FKs a productos), se
    consulta con join explícito."""
    from app.models.models import ProductoInsumo
    rows = (
        db.query(ProductoInsumo, Producto)
        .join(Producto, Producto.id == ProductoInsumo.insumo_id)
        .filter(ProductoInsumo.producto_id == producto_id)
        .order_by(Producto.nombre)
        .all()
    )
    return [{"insumo_id": pi.insumo_id, "nombre": prod.nombre,
             "unidad_medida": prod.unidad_medida, "cantidad": pi.cantidad}
            for pi, prod in rows]


def get_productos_que_consumen(db: Session, insumo_id: int) -> list[dict]:
    """El sentido inverso de la receta: qué productos gastan este insumo. Es la
    pregunta que se hace el admin cuando un insumo baja sin explicación."""
    from app.models.models import ProductoInsumo
    rows = (
        db.query(ProductoInsumo, Producto)
        .join(Producto, Producto.id == ProductoInsumo.producto_id)
        .filter(ProductoInsumo.insumo_id == insumo_id)
        .order_by(Producto.nombre)
        .all()
    )
    return [{"producto_id": pi.producto_id, "nombre": prod.nombre,
             "unidad_medida": prod.unidad_medida, "cantidad": pi.cantidad}
            for pi, prod in rows]


def get_ficha_producto(db: Session, tienda_id: int, producto_id: int,
                       n_movimientos: int = 20, n_conteos: int = 5) -> dict:
    """Ficha de UN producto en UNA sede: junta en una sola lectura lo que hoy
    obliga a recorrer cuatro pantallas (stock, lotes, conteos, rotación) más la
    receta en los dos sentidos.

    Es una vista AGREGADA: no recalcula nada que ya tenga dueño. El estado y el
    % consumido de los lotes salen de get_trazabilidad (la misma verdad que la
    pantalla de Lotes) y sistema/real/diferencia salen del conteo guardado."""
    from app.models.models import ConteoFisico, ConteoFisicoItem

    inv = (
        db.query(Inventario)
        .options(joinedload(Inventario.producto))
        .filter_by(tienda_id=tienda_id, producto_id=producto_id)
        .first()
    )
    # Mismo criterio que los vecinos que operan sobre el par producto+sede
    # (actualizar_minimo / actualizar_umbrales): sin fila de inventario no hay
    # nada que fichar en esa sede.
    if not inv:
        raise HTTPException(404, "Registro de inventario no encontrado")
    p = inv.producto

    movimientos = (
        db.query(MovimientoInventario)
        .filter(MovimientoInventario.producto_id == producto_id,
                MovimientoInventario.tienda_id == tienda_id)
        # Desempate por id: varios movimientos del mismo segundo (venta que
        # descuenta receta) quedarían en orden indefinido solo con la fecha.
        .order_by(MovimientoInventario.fecha.desc(), MovimientoInventario.id.desc())
        .limit(n_movimientos)
        .all()
    )

    conteos = (
        db.query(ConteoFisicoItem, ConteoFisico)
        .join(ConteoFisico, ConteoFisico.id == ConteoFisicoItem.conteo_id)
        .filter(ConteoFisicoItem.producto_id == producto_id,
                ConteoFisico.tienda_id == tienda_id)
        .order_by(ConteoFisico.fecha_registro.desc(), ConteoFisico.id.desc())
        .limit(n_conteos)
        .all()
    )

    lotes = get_trazabilidad(db, tienda_id=tienda_id, producto_id=producto_id)

    return {
        "producto": {
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value if hasattr(p.categoria, "value") else str(p.categoria),
            "unidad_medida": p.unidad_medida,
            "controla_stock": bool(p.controla_stock),
            "fraccionable": bool(p.fraccionable),
            "envase": p.envase,
            "proveedor": p.proveedor,
            "lead_time_dias": p.lead_time_dias,
            "contenido_por_empaque": p.contenido_por_empaque,
            "precio_venta": p.precio_venta or 0.0,
        },
        "stock": {
            "stock_actual": round(inv.stock_actual or 0, 2),
            "stock_critico": round(inv.stock_critico or 0, 2),
            "stock_minimo": round(inv.stock_minimo or 0, 2),
            "stock_ideal": round(inv.stock_ideal or 0, 2),
        },
        # Proyección recortada de la trazabilidad: se descartan los campos que la
        # ficha ya sabe (producto, sede, unidad), nunca los calculados.
        "lotes": [{
            "id": l["id"],
            "numero_lote": l["numero_lote"],
            "proveedor": l["proveedor"],
            "cantidad_inicial": l["cantidad_inicial"],
            "cantidad_restante": l["cantidad_restante"],
            "consumido_pct": l["consumido_pct"],
            "fecha_entrada": l["fecha_entrada"],
            "fecha_vencimiento": l["fecha_vencimiento"],
            "estado": l["estado"],
        } for l in lotes],
        "movimientos": [{
            "id": m.id,
            "fecha": m.fecha.isoformat() if m.fecha else None,
            "tipo": m.tipo.value if hasattr(m.tipo, "value") else str(m.tipo),
            "cantidad": m.cantidad,
            "motivo": m.motivo,
            "barista": m.barista_nombre,
        } for m in movimientos],
        "conteos": [{
            "conteo_id": c.id,
            "turno_id": c.turno_id,
            "tipo": c.tipo.value if hasattr(c.tipo, "value") else str(c.tipo),
            "fecha": c.fecha_registro.isoformat() if c.fecha_registro else None,
            "cantidad_sistema": float(i.cantidad_sistema or 0),
            "cantidad_real": float(i.cantidad_real or 0),
            "diferencia": float(i.diferencia or 0),
            "barista_nombre": c.barista_nombre,
            # Atajo "todo coincide": el conteo es un eco del stock, no un conteo
            # físico. Sin esta bandera una diferencia 0 se lee como confirmación.
            "es_atajo": bool(c.es_atajo),
        } for i, c in conteos],
        "receta": {
            "insumos": get_insumos_de_producto(db, producto_id),
            "usado_en": get_productos_que_consumen(db, producto_id),
        },
    }


def get_movimientos_inventario(db: Session, tienda_id: int, tipo: str | None = None,
                               fecha=None, limite: int = 300) -> list:
    """Revisión de movimientos de inventario (admin): quién movió qué, cuándo y por qué.
    Pensado para auditar ajustes, pero sirve para cualquier tipo."""
    from app.core.tz import rango_col_utc
    q = (
        db.query(MovimientoInventario, Producto)
        .join(Producto, Producto.id == MovimientoInventario.producto_id)
        .filter(MovimientoInventario.tienda_id == tienda_id)
    )
    if tipo:
        q = q.filter(MovimientoInventario.tipo == tipo)
    if fecha:
        ini, fin = rango_col_utc(fecha, fecha)
        q = q.filter(MovimientoInventario.fecha >= ini, MovimientoInventario.fecha <= fin)
    rows = q.order_by(MovimientoInventario.fecha.desc()).limit(limite).all()
    return [{
        "id": m.id,
        "fecha": m.fecha.isoformat() if m.fecha else None,
        "tipo": m.tipo.value if hasattr(m.tipo, "value") else str(m.tipo),
        "producto_id": m.producto_id,
        "producto": p.nombre,
        "unidad": p.unidad_medida,
        "cantidad": m.cantidad,
        "motivo": m.motivo,
        "barista": m.barista_nombre,
        "usuario_id": m.usuario_id,
    } for m, p in rows]
