"""Inventario físico mensual + conciliación valorizada.

Relacional con el resto del sistema: cada conteo pertenece a una sede y un usuario;
cada ítem referencia un producto real. La existencia teórica se toma del Inventario
vigente; la diferencia se valoriza con el costo promedio de compra (FacturaCompraItem)
y, si el producto nunca se compró por factura, cae al precio de venta.
"""
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import (
    InventarioMensual, InventarioMensualItem, Inventario, Producto, FacturaCompraItem,
)
from app.services import audit


def _valor_unitario_map(db: Session) -> dict:
    """Costo unitario por producto = promedio de precio_unitario en facturas de compra."""
    rows = (
        db.query(FacturaCompraItem.producto_id, func.avg(FacturaCompraItem.precio_unitario))
        .group_by(FacturaCompraItem.producto_id)
        .all()
    )
    return {pid: float(avg or 0) for pid, avg in rows}


def _serializar(inv: InventarioMensual) -> dict:
    # Mismo orden que el conteo (planilla de pedidos): orden_conteo primero, resto
    # alfabético al final — para que revisar la conciliación siga el papel.
    items = sorted(
        inv.items,
        key=lambda x: (
            (x.producto.orden_conteo if x.producto else None) is None,
            (x.producto.orden_conteo if x.producto else 0) or 0,
            x.producto.nombre if x.producto else '',
        ),
    )
    return {
        "id": inv.id, "tienda_id": inv.tienda_id, "anio": inv.anio, "mes": inv.mes,
        "estado": inv.estado, "barista_nombre": inv.barista_nombre,
        "fecha_inicio": inv.fecha_inicio, "fecha_cierre": inv.fecha_cierre,
        # Con valor = este mes YA pasó por un cierre, aunque ahora figure "en
        # proceso" por una reabertura. La pantalla lo necesita para no prometer
        # una sincronización con el catálogo vivo que ya no va a ocurrir.
        "fecha_primer_cierre": inv.fecha_primer_cierre,
        "fecha_aplicado": inv.fecha_aplicado,
        "valor_diferencia_total": float(inv.valor_diferencia_total or 0),
        # Cobertura del conteo, arriba y no enterrada por ítem: un mes con 12 de 180
        # productos contados no puede leerse igual que uno contado completo, y la
        # diferencia total de un conteo parcial no significa lo mismo.
        "contados": sum(1 for it in items if it.fue_contado),
        "total_items": len(items),
        "items": [{
            "id": it.id, "producto_id": it.producto_id,
            "producto_nombre": it.producto.nombre if it.producto else "",
            "categoria": it.categoria, "unidad_medida": it.unidad_medida,
            "fraccionable": bool(it.producto.fraccionable) if it.producto else False,
            "envase": it.producto.envase if it.producto else None,
            "cantidad_sistema": it.cantidad_sistema,
            "cantidad_real": it.cantidad_real,
            # False = el número de al lado lo puso el cierre, no una persona.
            "fue_contado": bool(it.fue_contado),
            "diferencia": it.diferencia,
            "valor_unitario": float(it.valor_unitario or 0),
            "valor_diferencia": float(it.valor_diferencia or 0),
        } for it in items],
    }


def iniciar(db: Session, tienda_id: int, anio: int, mes: int, usuario_id: int,
            barista_id: int | None = None, barista_nombre: str | None = None) -> dict:
    """Obtiene el conteo del período o lo crea pre-poblando los productos que controlan
    stock con su existencia teórica actual. Idempotente (1 por sede/mes por UniqueConstraint)."""
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    if inv:
        return _serializar(inv)
    inv = InventarioMensual(tienda_id=tienda_id, anio=anio, mes=mes, usuario_id=usuario_id,
                            barista_id=barista_id, barista_nombre=barista_nombre)
    db.add(inv)
    db.flush()
    val = _valor_unitario_map(db)
    rows = (
        db.query(Inventario, Producto)
        .join(Producto, Producto.id == Inventario.producto_id)
        .filter(Inventario.tienda_id == tienda_id, Producto.controla_stock == True)  # noqa: E712
        .all()
    )
    for invrow, prod in rows:
        db.add(InventarioMensualItem(
            inventario_id=inv.id, producto_id=prod.id,
            categoria=prod.categoria.value, unidad_medida=prod.unidad_medida,
            cantidad_sistema=invrow.stock_actual or 0,
            cantidad_real=None, diferencia=0,
            valor_unitario=val.get(prod.id, float(prod.precio_venta or 0)),
            valor_diferencia=0,
        ))
    db.commit()
    db.refresh(inv)
    return _serializar(inv)


def reiniciar(db: Session, tienda_id: int, anio: int, mes: int, usuario_id: int) -> dict:
    """Borra el conteo mensual EN PROCESO y lo re-siembra con el conteo del sistema
    actual. Pensado para cuando cambia el modelo/las unidades (p.ej. la conversión a
    gramos del 3-jul dejó cantidad_sistema en unidades viejas). Los meses que YA
    PASARON POR UN CIERRE son históricos intocables.

    El estado actual no alcanza como guarda: `reabrir` deja el mes en 'en_proceso'
    conservando la foto del período, así que mirar solo `estado == 'cerrado'`
    dejaba la misma destrucción a dos clics de distancia (reabrir + reiniciar).
    Lo que manda es si hubo cierre alguna vez."""
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    if inv:
        if inv.estado == "cerrado" or inv.fecha_primer_cierre is not None:
            raise HTTPException(
                400, "Este mes ya se cerró — su conteo es la medición del período y no se "
                     "re-siembra con el stock de hoy. Si hay que seguir contando, reabrilo.")
        audit.registrar(
            db, accion="inventario_mensual_reiniciado", tabla="inventarios_mensuales",
            registro_id=inv.id, usuario_id=usuario_id, tienda_id=tienda_id,
            datos_antes={"anio": anio, "mes": mes, "items": len(inv.items)},
        )
        db.delete(inv)   # cascade borra los items
        db.commit()
    return iniciar(db, tienda_id, anio, mes, usuario_id)


def reabrir(db: Session, tienda_id: int, anio: int, mes: int, usuario_id: int) -> dict:
    """Reabre un conteo mensual para poder seguir contando. Dos comportamientos
    MUY distintos, según si el mes ya se había cerrado o no.

    La condición NO es "está cerrado ahora", es "este mes YA PASÓ POR UN CIERRE
    alguna vez" (`fecha_primer_cierre`). Preguntarle al estado actual protegía
    solo la PRIMERA reabertura: la segunda llamada al mismo endpoint veía un mes
    'en_proceso', entraba por la rama destructiva y re-fotografiaba la foto del
    período igual que antes. Dos clics del mismo botón y la evidencia se perdía.

    CONTEO EN PROCESO (nadie cerró NUNCA): re-sincroniza con el catálogo VIVO.
    El conteo congela unidad, categoría y existencia teórica al abrirse, y un mes
    abierto temprano queda con la foto vieja (caso real: apertura 1-jul,
    conversión a gramos 3-jul):
    - agrega los productos con controla_stock que entraron después de iniciarlo;
    - refresca unidad, categoría, costo y cantidad_sistema desde el producto y el
      stock actuales;
    - si la UNIDAD cambió (botella→gr), borra cantidad_real: lo contado estaba en
      la unidad vieja y no significa nada en la nueva — hay que recontarlo.
    Nada de eso destruye información: mientras no hay cierre, no hay foto que
    proteger, solo un conteo a medio hacer que conviene poner al día.

    MES YA CERRADO ALGUNA VEZ: NO se re-fotografía NADA. `cantidad_sistema`, `cantidad_real`,
    `diferencia` y `valor_diferencia` quedan EXACTAMENTE como estaban; lo único
    que cambia es el estado, para poder seguir contando. Hacer lo otro era
    destrucción silenciosa de datos: reabrir julio en agosto reemplazaba la
    existencia teórica de julio por el stock de HOY —que ya incorporó las ventas
    de agosto— y ponía todas las diferencias en 0. La fuga de julio, que es
    justamente lo que el conteo existía para medir, desaparecía sin traza y sin
    forma de recuperarla. Solo se AGREGAN los productos que le falten al conteo:
    sumar renglones no borra nada.

    (Re-sembrar desde el stock de hoy es `reiniciar`, y sobre un mes que pasó por
    un cierre NO existe: sería la misma pérdida por otra puerta.)"""
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    if not inv:
        raise HTTPException(404, "No hay conteo mensual para ese período")
    if inv.fecha_aplicado:
        raise HTTPException(400, "Este conteo ya se aplicó al inventario — es histórico y no se reabre")

    # `estado` cuenta la reabertura ACTUAL; `fecha_primer_cierre` cuenta la
    # historia. Basta con que alguna vez haya habido un cierre para que exista una
    # medición del período que ninguna reabertura posterior puede pisar.
    cerrado = inv.estado == "cerrado" or inv.fecha_primer_cierre is not None
    estado_previo = inv.estado
    val = _valor_unitario_map(db)
    rows = (
        db.query(Inventario, Producto)
        .join(Producto, Producto.id == Inventario.producto_id)
        .filter(Inventario.tienda_id == tienda_id)
        .all()
    )
    vivo = {prod.id: (invrow, prod) for invrow, prod in rows}

    # 1) Sincronizar los renglones existentes con el producto/stock vivos.
    #    Los retirados salen del conteo — sin fila Inventario en la sede O con
    #    controla_stock=False (unificación/retiro por bandera): en ambos casos ya
    #    no hay contra qué contarlos (mismo criterio de siembra que iniciar()).
    #
    #    TODO este bloque se salta sobre un mes CERRADO: cada línea de acá pisa un
    #    dato del período (existencia teórica, unidad, costo) o borra un renglón
    #    contado. Sobre un cierre eso no es sincronizar, es perder la medición.
    unidades_cambiadas = 0
    eliminados = 0
    for it in (list(inv.items) if not cerrado else []):
        par = vivo.get(it.producto_id)
        if par is None or not par[1].controla_stock:
            inv.items.remove(it)   # delete-orphan: borra la fila del conteo
            eliminados += 1
            continue
        invrow, prod = par
        u_vieja = (it.unidad_medida or "").strip().lower()
        u_nueva = (prod.unidad_medida or "").strip().lower()
        if u_vieja != u_nueva:
            it.cantidad_real = None
            it.fue_contado = False   # lo contado en la unidad vieja ya no cuenta
            unidades_cambiadas += 1
        it.unidad_medida = prod.unidad_medida
        it.categoria = prod.categoria.value
        it.cantidad_sistema = invrow.stock_actual or 0
        it.valor_unitario = val.get(prod.id, float(prod.precio_venta or 0))

    # 2) Agregar los productos que faltan (creados después de abrir el conteo).
    existentes = {it.producto_id for it in inv.items}
    agregados = 0
    for invrow, prod in rows:
        if prod.id in existentes or not prod.controla_stock:
            continue
        db.add(InventarioMensualItem(
            inventario_id=inv.id, producto_id=prod.id,
            categoria=prod.categoria.value, unidad_medida=prod.unidad_medida,
            cantidad_sistema=invrow.stock_actual or 0,
            cantidad_real=None, diferencia=0,
            valor_unitario=val.get(prod.id, float(prod.precio_venta or 0)),
            valor_diferencia=0,
        ))
        agregados += 1

    if cerrado:
        # Se reabre el estado y NADA MÁS. Las diferencias NO se ponen en 0: son la
        # medición del período y `cerrar()` las va a recalcular igual cuando el mes
        # se vuelva a cerrar de verdad. Borrarlas mientras tanto solo lograba que,
        # si alguien reabría y no volvía a cerrar, la fuga quedara en cero para
        # siempre.
        #
        # `fecha_primer_cierre` NO se toca: es la marca permanente de que acá hay
        # una medición. Limpiarla devolvería el mes a "virgen" y la próxima
        # reabertura volvería a pisar la foto — que es exactamente el bug.
        inv.estado = "en_proceso"
        inv.fecha_cierre = None
    else:
        # Conteo en curso: las diferencias no significan nada todavía (las escribe
        # el cierre), así que se limpian para que un cierre prematuro no deje ruido.
        inv.valor_diferencia_total = 0
        for it in inv.items:
            it.diferencia = 0
            it.valor_diferencia = 0

    audit.registrar(
        db, accion="reabrir_inventario_mensual", tabla="inventarios_mensuales",
        registro_id=inv.id, usuario_id=usuario_id, tienda_id=tienda_id,
        # El estado CRUDO, no el derivado: una segunda reabertura arranca de
        # 'en_proceso' y la traza tiene que poder distinguirla de la primera.
        datos_antes={"estado": estado_previo,
                     "valor_diferencia_total": float(inv.valor_diferencia_total or 0),
                     "contados": sum(1 for it in inv.items if it.fue_contado),
                     "total_items": len(inv.items)},
        datos_despues={"anio": anio, "mes": mes, "reabierto": cerrado,
                       # Reaberturas 2ª, 3ª… del mismo mes: sin esto, en la traza
                       # se leen igual que la primera.
                       "reabierto_de_nuevo": cerrado and estado_previo != "cerrado",
                       # Sobre un mes cerrado esto queda en 0/0 por diseño: es la
                       # prueba en la traza de que la foto del período no se tocó.
                       "productos_agregados": agregados, "unidades_cambiadas": unidades_cambiadas,
                       "huerfanos_eliminados": eliminados,
                       "foto_conservada": cerrado},
    )
    db.commit()
    db.refresh(inv)
    return _serializar(inv)


def get_actual(db: Session, tienda_id: int, anio: int, mes: int):
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    return _serializar(inv) if inv else None


def guardar(db: Session, inv_id: int, items: list) -> dict:
    """Guarda la existencia física (cantidad_real) de los ítems. items: [{id, cantidad_real}]."""
    inv = db.query(InventarioMensual).filter_by(id=inv_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")
    if inv.estado == "cerrado":
        raise HTTPException(400, "El inventario ya está cerrado")
    by_id = {it.id: it for it in inv.items}
    for upd in items:
        it = by_id.get(upd.get("id"))
        if it is not None and upd.get("cantidad_real") is not None:
            it.cantidad_real = float(upd["cantidad_real"])
            # Acá es donde una PERSONA pone el número: es el único momento del
            # flujo en que "contado" significa contado. El cierre solo lo hereda.
            it.fue_contado = True
    db.commit()
    return _serializar(inv)


def cerrar(db: Session, inv_id: int, usuario_id: int) -> dict:
    """Finaliza el conteo: calcula diferencia (física − sistema) y su valor económico por
    ítem y el neto total. Los no contados se asumen iguales al sistema (sin diferencia).

    Ese relleno es deliberado —así lo no contado no ensucia el neto con una
    diferencia inventada— pero deja `cantidad_real` idéntica en dos casos que NO
    son lo mismo: "lo conté y dio exacto" y "nadie lo contó". `fue_contado`
    congela la distinción; sin ella, el mes contado a medias reporta las mismas
    cero diferencias que el contado completo y la fuga real queda escondida por
    definición.

    Por eso el cierre NO ESCRIBE `fue_contado`, ni siquiera para derivarlo de
    `cantidad_real`: esa columna la escribe únicamente quien cuenta de verdad
    (`guardar`, `corregir_item`). Derivarla acá se autodestruía en el segundo
    cierre — el cierre anterior ya había rellenado `cantidad_real` en TODOS los
    renglones, así que al reabrir y volver a cerrar el mes reportaba 180 de 180
    contados y la cobertura parcial desaparecía para siempre."""
    inv = db.query(InventarioMensual).filter_by(id=inv_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")
    if inv.estado == "cerrado":
        return _serializar(inv)
    total = 0.0
    contados = 0
    for it in inv.items:
        if it.fue_contado:
            contados += 1
        real = it.cantidad_real if it.cantidad_real is not None else (it.cantidad_sistema or 0)
        it.cantidad_real = real
        it.diferencia = round(real - (it.cantidad_sistema or 0), 3)
        it.valor_diferencia = round(it.diferencia * float(it.valor_unitario or 0), 2)
        total += it.valor_diferencia
    inv.valor_diferencia_total = round(total, 2)
    inv.estado = "cerrado"
    inv.fecha_cierre = datetime.utcnow()
    # Se sella una sola vez y no se limpia nunca: es la marca de que este mes tiene
    # una medición del período que ninguna reabertura puede volver a fotografiar.
    if inv.fecha_primer_cierre is None:
        inv.fecha_primer_cierre = inv.fecha_cierre
    audit.registrar(
        db, accion="cerrar_inventario_mensual", tabla="inventarios_mensuales",
        registro_id=inv.id, usuario_id=usuario_id, tienda_id=inv.tienda_id,
        datos_despues={"anio": inv.anio, "mes": inv.mes,
                       "valor_diferencia": inv.valor_diferencia_total,
                       # En la traza queda de cuánto del inventario habla ese número.
                       "contados": contados, "total_items": len(inv.items)},
    )
    db.commit()
    db.refresh(inv)
    return _serializar(inv)


def _plan_aplicacion(db: Session, inv: InventarioMensual) -> dict:
    """Qué pasaría al aplicar, SIN tocar nada: producto por producto, en qué stock
    queda, cuántos caen en 0, cuántos se irían a negativo y el impacto en pesos.

    Existe porque `aplicar` es irreversible (`fecha_aplicado`) y opera con una
    diferencia CONGELADA en el cierre contra un stock que pudo haberse movido
    desde entonces. Un solo clic podía dejar decenas de productos en 0 sin que
    nadie hubiera visto venir el número."""
    items = []
    ajustados = en_cero = negativos = 0
    valor_total = 0.0
    for it in inv.items:
        dif = float(it.diferencia or 0)
        if abs(dif) < 0.001:
            continue
        invrow = db.query(Inventario).filter_by(
            producto_id=it.producto_id, tienda_id=inv.tienda_id).first()
        if not invrow:
            continue   # sin fila de inventario no hay qué ajustar (mismo criterio que aplicar)
        actual = float(invrow.stock_actual or 0)
        nuevo = round(actual + dif, 3)
        negativo = nuevo < 0
        if negativo:
            negativos += 1
        elif nuevo == 0:
            en_cero += 1
        ajustados += 1
        valor_total += float(it.valor_diferencia or 0)
        items.append({
            "item_id": it.id,
            "producto_id": it.producto_id,
            "producto_nombre": it.producto.nombre if it.producto else "",
            "unidad_medida": it.unidad_medida,
            "stock_actual": actual,
            "diferencia": dif,
            # El número CRUDO, sin recortar en 0: recortarlo acá escondería
            # justamente la señal de que la foto del conteo ya está vieja.
            "stock_nuevo": nuevo,
            "negativo": negativo,
            "fue_contado": bool(it.fue_contado),
            "valor_diferencia": float(it.valor_diferencia or 0),
        })
    items.sort(key=lambda i: (not i["negativo"], i["stock_nuevo"]))
    return {
        "dry_run": True,
        "inventario_id": inv.id,
        "items": items,
        "ajustados": ajustados,
        "en_cero": en_cero,
        "negativos": negativos,
        "valor_total": round(valor_total, 2),
        "contados": sum(1 for it in inv.items if it.fue_contado),
        "total_items": len(inv.items),
        "bloqueado": negativos > 0,
    }


def aplicar(db: Session, inv_id: int, usuario_id: int, dry_run: bool = False,
            omitir_negativos: bool = False) -> dict:
    """Promueve el conteo mensual CERRADO a verdad del inventario. Por cada ítem
    con diferencia, ajusta stock_actual sumándole la DIFERENCIA del conteo (no el
    físico absoluto): si se aplica días después del cierre, las ventas posteriores
    ya descontadas por el sistema no se pisan. Equivale a haber corregido el stock
    en el momento del cierre. Una sola vez por mes; deja movimiento de ajuste por
    producto y marca fecha_aplicado (el mes queda histórico).

    `dry_run=True` devuelve el PLAN y no escribe nada — es lo que la pantalla
    muestra antes de pedir confirmación.

    Un producto que quedaría NEGATIVO no se ajusta nunca: no es un caso raro a
    redondear a 0 (que era el bug viejo, silencioso e irreversible), es la prueba
    de que la diferencia congelada en el cierre ya no aplica al stock de hoy — se
    vendió más de lo que el conteo creía que había.

    Qué hacer con el RESTO del conteo cuando aparece uno así lo decide quien
    aplica, y son dos caminos explícitos:

    - por defecto se frena en seco sin tocar una sola fila, para que nadie aplique
      medio conteo sin haberlo pedido;
    - con `omitir_negativos=True` se aplican los renglones sanos y se EXCLUYEN los
      trabados, dejando constancia de cuáles y por qué.

    La segunda existe porque el todo-o-nada paralizaba el módulo: un solo producto
    de alta rotación frenaba los otros 179, y la única salida que ofrecía la
    pantalla era corregir ese físico a mano — o sea, escribir un número que nadie
    contó y que `corregir_item` marca como CONTADO, ensuciando la cobertura del
    mes justo para poder destrabarse. El admin tiene que poder avanzar sin
    mentirle al sistema.

    Lo excluido NO queda pendiente de una segunda aplicación: el mes se marca
    aplicado igual. Su diferencia es vieja POR CONSTRUCCIÓN (por eso da negativa),
    así que arrastrarla para meterla después sería aplicar un dato todavía más
    desactualizado. Queda en la traza y en la respuesta para poder revisarlo."""
    from app.services.inventario import registrar_movimiento

    inv = db.query(InventarioMensual).filter_by(id=inv_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")
    if inv.estado != "cerrado":
        raise HTTPException(400, "Solo un conteo cerrado se aplica al inventario")
    if inv.fecha_aplicado:
        raise HTTPException(400, "Este conteo ya fue aplicado al inventario")

    plan = _plan_aplicacion(db, inv)
    if dry_run:
        return plan

    culpables = [i for i in plan["items"] if i["negativo"]]
    if culpables and not omitir_negativos:
        detalle = ", ".join(
            f"{i['producto_nombre']} ({i['stock_actual']:g} {i['diferencia']:+g} = {i['stock_nuevo']:g})"
            for i in culpables[:5])
        resto = f" y {len(culpables) - 5} más" if len(culpables) > 5 else ""
        raise HTTPException(
            400,
            f"No se aplicó nada: {len(culpables)} producto(s) quedarían en NEGATIVO — "
            f"{detalle}{resto}. La diferencia del conteo es más grande que el stock que "
            f"queda hoy, así que la foto del cierre ya no calza con el inventario actual. "
            f"Corregí esos renglones en la conciliación del mes, o aplicá el resto "
            f"excluyéndolos.")

    # Solo se excluye lo que el plan RECIÉN calculado marca como negativo: la lista
    # no viaja desde el cliente, así que entre ver la previsualización y confirmar
    # no se puede colar un renglón sano ni quedar afuera uno que se trabó después.
    excluidos = culpables if omitir_negativos else []
    aplicables = [i for i in plan["items"] if not i["negativo"]]
    if excluidos and not aplicables:
        raise HTTPException(
            400,
            "No se aplicó nada: TODOS los renglones con diferencia quedarían en negativo. "
            "Excluirlos a todos dejaría el mes marcado como aplicado sin haber ajustado un "
            "solo producto. La foto del cierre ya no calza con el inventario: revisá el "
            "conteo del mes antes de aplicarlo.")

    for i in aplicables:
        registrar_movimiento(
            db, i["producto_id"], inv.tienda_id, "ajuste", i["stock_nuevo"],
            motivo=f"Inventario mensual {inv.mes:02d}/{inv.anio} aplicado (dif {i['diferencia']:+g})",
            usuario_id=usuario_id, commit=False,
        )

    # Los totales cuentan lo que SE ESCRIBIÓ, no lo que el plan proponía: si el
    # resumen incluyera lo excluido, el número diría que se movió plata que no se
    # movió. `fue_contado` no se toca acá — aplicar no es contar.
    items_excluidos = [{**i, "motivo": "stock_negativo"} for i in excluidos]
    ajustados = len(aplicables)
    en_cero = sum(1 for i in aplicables if i["stock_nuevo"] == 0)
    valor_total = round(sum(i["valor_diferencia"] for i in aplicables), 2)

    inv.fecha_aplicado = datetime.utcnow()
    audit.registrar(
        db, accion="aplicar_inventario_mensual", tabla="inventarios_mensuales",
        registro_id=inv.id, usuario_id=usuario_id, tienda_id=inv.tienda_id,
        datos_despues={"anio": inv.anio, "mes": inv.mes,
                       "ajustados": ajustados, "en_cero": en_cero,
                       "valor_total": valor_total,
                       # De cuánto del inventario habla el ajuste que se acaba de
                       # escribir: un mes contado a medias mueve stock igual.
                       "contados": plan["contados"], "total_items": plan["total_items"],
                       # Qué se dejó afuera y por qué. Sin esto, "se aplicaron 179
                       # de 180" es una diferencia que nadie puede reconstruir.
                       "excluidos": [
                           {"producto": i["producto_nombre"],
                            "stock_actual": i["stock_actual"],
                            "diferencia": i["diferencia"],
                            "stock_nuevo": i["stock_nuevo"],
                            "motivo": "stock_negativo"} for i in excluidos]},
    )
    db.commit()
    return {"ok": True, "inventario_id": inv.id, "ajustados": ajustados,
            "en_cero": en_cero, "valor_total": valor_total,
            "excluidos": len(items_excluidos), "items_excluidos": items_excluidos,
            # Se conserva la clave vieja para no romper a quien la lea: ya nunca
            # hay recortes, porque el caso que los producía ahora bloquea o excluye.
            "clampeados": 0}


def corregir_item(db: Session, item_id: int, cantidad_real: float, usuario_id: int) -> dict:
    """Corrige un renglón de un conteo CERRADO (dedazo detectado en la revisión)
    sin reabrir el mes — reabrir re-sincroniza el sistema al stock de HOY y
    arruina la foto del período. Recalcula la diferencia del ítem y el total.
    Bloqueado si el mes ya se aplicó al inventario."""
    it = db.query(InventarioMensualItem).filter_by(id=item_id).first()
    if not it:
        raise HTTPException(404, "Ítem no encontrado")
    inv = it.inventario
    if inv.estado != "cerrado":
        raise HTTPException(400, "El conteo está en proceso — corregí desde el kiosko")
    if inv.fecha_aplicado:
        raise HTTPException(400, "Este conteo ya fue aplicado al inventario — es histórico")

    antes = it.cantidad_real
    it.cantidad_real = float(cantidad_real)
    # Alguien puso este número a mano: pasa a contar como contado aunque el cierre
    # lo hubiera rellenado antes con el sistema.
    it.fue_contado = True
    it.diferencia = round(it.cantidad_real - (it.cantidad_sistema or 0), 3)
    it.valor_diferencia = round(it.diferencia * float(it.valor_unitario or 0), 2)
    inv.valor_diferencia_total = round(
        sum(float(x.valor_diferencia or 0) for x in inv.items), 2)
    audit.registrar(
        db, accion="corregir_item_inventario_mensual", tabla="inventarios_mensuales_items",
        registro_id=it.id, usuario_id=usuario_id, tienda_id=inv.tienda_id,
        datos_antes={"cantidad_real": antes},
        datos_despues={"cantidad_real": it.cantidad_real, "diferencia": it.diferencia},
    )
    db.commit()
    db.refresh(inv)
    return _serializar(inv)


def get_conciliacion(db: Session, tienda_id: int, anio: int, mes: int):
    """Pantalla de conciliación (admin): teórico vs físico vs diferencia valorizada,
    clasificación, totales por categoría y ranking de mayores diferencias."""
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    if not inv:
        return None
    base = _serializar(inv)
    items = base["items"]
    positivas = [i for i in items if (i["diferencia"] or 0) > 0]
    negativas = [i for i in items if (i["diferencia"] or 0) < 0]
    sin = [i for i in items if (i["diferencia"] or 0) == 0]

    por_cat: dict = {}
    for i in items:
        c = i["categoria"] or "—"
        g = por_cat.setdefault(c, {"categoria": c, "valor_diferencia": 0.0, "items": 0, "con_diferencia": 0})
        g["valor_diferencia"] += i["valor_diferencia"]
        g["items"] += 1
        if (i["diferencia"] or 0) != 0:
            g["con_diferencia"] += 1
    for g in por_cat.values():
        g["valor_diferencia"] = round(g["valor_diferencia"], 2)

    ranking = sorted(
        [i for i in items if (i["diferencia"] or 0) != 0],
        key=lambda x: abs(x["valor_diferencia"]), reverse=True,
    )[:15]

    return {
        **base,
        "resumen": {
            "positivas": len(positivas), "negativas": len(negativas), "sin_diferencia": len(sin),
            "valor_positivo": round(sum(i["valor_diferencia"] for i in positivas), 2),
            "valor_negativo": round(sum(i["valor_diferencia"] for i in negativas), 2),
            "valor_neto": base["valor_diferencia_total"],
            # Cobertura: `sin_diferencia` mezcla lo que dio exacto con lo que nadie
            # contó. Sin este par, un conteo del 7% del inventario se presenta con
            # el mismo aire de conclusión que uno completo.
            "contados": base["contados"],
            "no_contados": base["total_items"] - base["contados"],
        },
        "por_categoria": sorted(por_cat.values(), key=lambda x: x["valor_diferencia"]),
        "ranking": ranking,
    }


def get_historial(db: Session, tienda_id: int | None = None) -> list:
    q = db.query(InventarioMensual)
    if tienda_id is not None:
        q = q.filter_by(tienda_id=tienda_id)
    rows = q.order_by(InventarioMensual.anio.desc(), InventarioMensual.mes.desc()).all()
    return [{
        "id": r.id, "tienda_id": r.tienda_id,
        "tienda_nombre": r.tienda.nombre if r.tienda else None,
        "anio": r.anio, "mes": r.mes, "estado": r.estado,
        "valor_diferencia_total": float(r.valor_diferencia_total or 0),
        "barista_nombre": r.barista_nombre, "fecha_cierre": r.fecha_cierre,
    } for r in rows]
