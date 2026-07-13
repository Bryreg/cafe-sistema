from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from fastapi import HTTPException
from datetime import datetime
from app.core.tz import inicio_dia_col_utc
from app.models.models import (FacturaCompra, FacturaCompraItem, TipoPagoEnum,
                               CajaTurno, MovimientoCaja, EstadoTurnoEnum,
                               LoteInventario, Producto, Inventario)
from app.services import inventario as inv_svc
from app.services import audit


def eliminar_factura(db: Session, factura_id: int, usuario_id: int) -> dict:
    """Elimina una factura recibida REVIRTIENDO todos sus efectos (solo admin).
    Pensada para recepciones erróneas o de prueba:
      1. Salida de inventario por cada item (revierte la entrada).
      2. Lotes creados por la factura → a cero y desvinculados.
      3. Egresos de caja del pago en efectivo/contado: se borran si su turno sigue
         abierto; si ya cerró (el cuadre histórico es intocable) se compensan con un
         ingreso en el turno activo. El total revertido se limita a lo realmente
         pagado, para no tocar egresos de otra factura del mismo proveedor.
      4. Borra los items y la factura, con auditoría."""
    f = db.query(FacturaCompra).filter(FacturaCompra.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    items = db.query(FacturaCompraItem).filter(FacturaCompraItem.factura_id == factura_id).all()

    # 1) Revertir inventario
    for it in items:
        inv_svc.registrar_movimiento(
            db, producto_id=it.producto_id, tienda_id=f.tienda_id,
            tipo="salida", cantidad=float(it.cantidad),
            motivo=f"Eliminación factura #{f.numero_factura or f.id} — {f.proveedor}",
            usuario_id=usuario_id, commit=False, allow_negative=True,
        )

    # 2) Lotes propios a cero
    for lote in db.query(LoteInventario).filter(LoteInventario.factura_id == factura_id).all():
        lote.cantidad_restante = 0
        lote.fecha_agotado = datetime.utcnow()
        lote.factura_id = None

    # 3) Egresos de caja de esta factura: por factura_id (vínculo estructural) y,
    #    como fallback para movimientos anteriores a esa columna, el concepto
    #    exacto. Solo con el texto, renombrar el proveedor o corregir el número
    #    dejaba el egreso huérfano y la plata desaparecía de los reportes.
    concepto = f"Pago proveedor: {f.proveedor}"
    if f.numero_factura:
        concepto += f" — Fact. {f.numero_factura}"
    movs = (
        db.query(MovimientoCaja)
        .join(CajaTurno, CajaTurno.id == MovimientoCaja.caja_turno_id)
        .filter(MovimientoCaja.tipo == "egreso",
                or_(MovimientoCaja.factura_id == f.id,
                    MovimientoCaja.concepto == concepto),
                CajaTurno.tienda_id == f.tienda_id)
        .order_by(MovimientoCaja.fecha.desc())
        .all()
    )
    restante = float(f.valor_pagado or 0)
    revertidos = 0.0
    for mov in movs:
        if restante <= 0.01:
            break
        if float(mov.valor) > restante + 0.01:
            continue
        restante -= float(mov.valor)
        revertidos += float(mov.valor)
        turno_mov = db.query(CajaTurno).filter(CajaTurno.id == mov.caja_turno_id).first()
        estado = getattr(turno_mov.estado, "value", turno_mov.estado) if turno_mov else None
        if estado == "abierto":
            db.delete(mov)
        else:
            activo = db.query(CajaTurno).filter(
                CajaTurno.tienda_id == f.tienda_id,
                CajaTurno.estado == EstadoTurnoEnum.abierto,
            ).first()
            if activo:
                db.add(MovimientoCaja(
                    caja_turno_id=activo.id, tipo="ingreso",
                    concepto=f"Reverso {concepto}", valor=mov.valor,
                    usuario_id=usuario_id, factura_id=f.id,
                ))

    audit.registrar(
        db, accion="eliminar_factura", tabla="facturas_compra",
        registro_id=factura_id, usuario_id=usuario_id, tienda_id=f.tienda_id,
        datos_antes={"proveedor": f.proveedor, "numero_factura": f.numero_factura,
                     "valor_total": float(f.valor_total or 0),
                     "valor_pagado": float(f.valor_pagado or 0),
                     "items": len(items), "egresos_revertidos": revertidos},
    )
    for it in items:
        db.delete(it)
    db.delete(f)
    db.commit()
    return {"ok": True, "items_revertidos": len(items), "egresos_revertidos": revertidos}


def crear_factura(db: Session, data, imagen_url: str | None, usuario_id: int,
                  barista_id: int | None = None, barista_nombre: str | None = None) -> FacturaCompra:
    tipo_map = {
        "contado": TipoPagoEnum.contado,
        "credito": TipoPagoEnum.credito,
        "transferencia": TipoPagoEnum.transferencia,
    }
    if data.tipo_pago not in tipo_map:
        raise HTTPException(400, "tipo_pago inválido: contado | credito | transferencia")
    if not data.items:
        raise HTTPException(400, "Debes agregar al menos un producto")

    # Contado/transferencia se paga al recibir; crédito queda pendiente (valor_pagado=0).
    pagado_inicial = data.valor_total if data.tipo_pago in ("contado", "transferencia") else 0
    factura = FacturaCompra(
        tienda_id=data.tienda_id,
        proveedor=data.proveedor,
        numero_factura=data.numero_factura,
        numero_lote=data.numero_lote,
        fecha_recibido=data.fecha_recibido,
        valor_total=data.valor_total,
        tipo_pago=tipo_map[data.tipo_pago],
        imagen_url=imagen_url,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
        valor_pagado=pagado_inicial,
        forma_pago_real=(data.tipo_pago if pagado_inicial > 0 else None),
    )
    db.add(factura)
    db.flush()

    UNIDADES_GRANEL = {"gr", "g", "gramos", "ml"}
    for item in data.items:
        # Per-item lote takes precedence; fall back to factura-level for legacy clients
        numero_lote_item = item.numero_lote or data.numero_lote
        prod = db.query(Producto).filter_by(id=item.producto_id).first()

        # ── Conversión empaques → gr/ml ──────────────────────────────────────
        # La fuga #1 de la auditoría: botella de Baileys registrada como "1 gr".
        cantidad = item.cantidad
        if getattr(item, "en_empaques", False):
            cpe = float(prod.contenido_por_empaque or 0) if prod else 0
            if cpe <= 0:
                raise HTTPException(400, f"{prod.nombre if prod else 'El producto'} no tiene "
                                          "configurado el contenido por empaque — registrá en gramos totales")
            cantidad = round(item.cantidad * cpe, 2)
        elif (prod and (prod.unidad_medida or "").lower() in UNIDADES_GRANEL
              and (prod.contenido_por_empaque or 0) > 0 and item.cantidad < 50):
            # Guard anti-unidades: producto en gramos con empaque configurado y una
            # cantidad diminuta => casi seguro escribieron botellas/frascos.
            raise HTTPException(400, (
                f"{prod.nombre} se registra en {prod.unidad_medida} y pusiste {item.cantidad:g}. "
                f"¿Eran empaques? Usá el campo de empaques (1 empaque = "
                f"{prod.contenido_por_empaque:g} {prod.unidad_medida}) o escribí los gramos totales."))

        db.add(FacturaCompraItem(
            factura_id=factura.id,
            producto_id=item.producto_id,
            cantidad=cantidad,
            precio_unitario=item.precio_unitario,
            numero_lote=numero_lote_item,
            fecha_vencimiento=item.fecha_vencimiento,
        ))
        # El proveedor de la compra alimenta al producto (si no tiene uno asignado):
        # así los pedidos se agrupan solos con los proveedores que las baristas
        # registran al Recibir. La asignación manual del admin nunca se pisa.
        if prod is not None and not (prod.proveedor or "").strip() and (data.proveedor or "").strip():
            prod.proveedor = data.proveedor.strip()
        # Asegurar la fila de inventario en esta tienda: un producto nuevo para la
        # sede puede no tenerla, y una ENTRADA debe poder crearla (igual que la
        # recepción de mercancía). Sin esto, registrar_movimiento(entrada) tira
        # "Producto no encontrado en inventario de esta tienda" y traba la factura.
        inv = db.query(Inventario).filter(
            Inventario.producto_id == item.producto_id,
            Inventario.tienda_id == data.tienda_id,
        ).first()
        if not inv:
            db.add(Inventario(producto_id=item.producto_id, tienda_id=data.tienda_id,
                              stock_actual=0.0, stock_minimo=0.0))
            db.flush()
        inv_svc.registrar_movimiento(
            db,
            producto_id=item.producto_id,
            tienda_id=data.tienda_id,
            tipo="entrada",
            cantidad=cantidad,
            motivo=f"Factura #{data.numero_factura or factura.id} — {data.proveedor}",
            usuario_id=usuario_id,
            fecha_vencimiento=item.fecha_vencimiento,
            commit=False,  # toda la factura en UNA transacción (db.commit final, línea ~88)
            # Trazabilidad: el lote conserva de dónde vino.
            numero_lote=numero_lote_item, proveedor=data.proveedor, factura_id=factura.id,
        )

    # Si el pago es en efectivo, registrar el egreso en el turno activo
    if data.tipo_pago == "contado" and data.valor_total > 0:
        turno_activo = db.query(CajaTurno).filter(
            CajaTurno.tienda_id == data.tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.abierto,
        ).first()
        if turno_activo:
            concepto = f"Pago proveedor: {data.proveedor}"
            if data.numero_factura:
                concepto += f" — Fact. {data.numero_factura}"
            db.add(MovimientoCaja(
                caja_turno_id=turno_activo.id,
                tipo="egreso",
                concepto=concepto,
                valor=data.valor_total,
                usuario_id=usuario_id,
                barista_id=barista_id,
                barista_nombre=barista_nombre,
                factura_id=factura.id,
            ))

    audit.registrar(
        db, accion="crear_factura_compra", tabla="facturas_compra",
        registro_id=factura.id, usuario_id=usuario_id, tienda_id=data.tienda_id,
        datos_despues={
            "proveedor": data.proveedor,
            "numero_factura": data.numero_factura,
            "valor_total": data.valor_total,
            "tipo_pago": data.tipo_pago,
            "items_count": len(data.items),
        },
    )
    db.commit()
    db.refresh(factura)
    return factura


def get_proveedores_tienda(db: Session, tienda_id: int) -> list:
    """Devuelve proveedores únicos ordenados por gasto total descendente."""
    rows = (
        db.query(
            FacturaCompra.proveedor,
            func.count().label("frecuencia"),
            func.sum(FacturaCompra.valor_total).label("total_gastado"),
            func.max(FacturaCompra.fecha_recibido).label("ultima"),
        )
        .filter(FacturaCompra.tienda_id == tienda_id)
        .group_by(FacturaCompra.proveedor)
        .order_by(func.sum(FacturaCompra.valor_total).desc())
        .all()
    )
    return [
        {
            "proveedor": r.proveedor,
            "frecuencia": r.frecuencia,
            "total_gastado": r.total_gastado or 0,
            "ultima": r.ultima,
        }
        for r in rows
    ]


def get_facturas_tienda(db: Session, tienda_id: int) -> list:
    facturas = (
        db.query(FacturaCompra)
        .filter(FacturaCompra.tienda_id == tienda_id)
        .order_by(FacturaCompra.fecha_recibido.desc())
        .all()
    )
    return [_serializar(f) for f in facturas]


def get_factura(db: Session, factura_id: int) -> dict:
    f = db.query(FacturaCompra).filter_by(id=factura_id).first()
    if not f:
        raise HTTPException(404, "Factura no encontrada")
    return _serializar(f)


def _serializar(f: FacturaCompra) -> dict:
    return {
        "id": f.id,
        "tienda_id": f.tienda_id,
        "proveedor": f.proveedor,
        "numero_factura": f.numero_factura,
        "numero_lote": f.numero_lote,
        "fecha_recibido": f.fecha_recibido,
        "valor_total": f.valor_total,
        "tipo_pago": f.tipo_pago.value,
        "imagen_url": f.imagen_url,
        "fecha_registro": f.fecha_registro,
        "usuario_nombre": f.usuario.nombre if f.usuario else "",
        # Barista real (display): la que operó; cae a usuario_nombre del dispositivo si no hay
        "barista_nombre": f.barista_nombre or (f.usuario.nombre if f.usuario else ""),
        "tienda_nombre": f.tienda.nombre if f.tienda else None,
        # Pagos a proveedores
        "valor_pagado": round(float(f.valor_pagado or 0), 2),
        "saldo": round(float(f.valor_total) - float(f.valor_pagado or 0), 2),
        "estado_pago": ("pagado" if float(f.valor_pagado or 0) >= float(f.valor_total)
                        else ("parcial" if float(f.valor_pagado or 0) > 0 else "pendiente")),
        "forma_pago_real": f.forma_pago_real,
        "imagen_soporte_url": f.imagen_soporte_url,
        "items": [
            {
                "id": i.id,
                "producto_id": i.producto_id,
                "producto_nombre": i.producto.nombre if i.producto else "",
                "unidad_medida": i.producto.unidad_medida if i.producto else "",
                "cantidad": i.cantidad,
                "precio_unitario": i.precio_unitario,
                "numero_lote": i.numero_lote,
                "fecha_vencimiento": i.fecha_vencimiento,
            }
            for i in f.items
        ],
    }


def editar_factura(db: Session, factura_id: int, usuario_id: int, *,
                   valor_total: float | None = None, valor_pagado: float | None = None,
                   numero_factura: str | None = None, proveedor: str | None = None,
                   fecha_recibido=None, tipo_pago: str | None = None,
                   forma_pago_real: str | None = None,
                   items: list[dict] | None = None) -> dict:
    """Editor COMPLETO de una factura (solo admin, con auditoría). Corrige metadata,
    montos y productos. Cambiar la cantidad de un producto ajusta el inventario y su
    lote por la diferencia (para que el conteo del sistema no se descuadre); quitar un
    producto revierte su entrada. El egreso de caja se ajusta si el pago fue en efectivo."""
    f = db.query(FacturaCompra).filter_by(id=factura_id).first()
    if not f:
        raise HTTPException(404, "Factura no encontrada")

    # Estado de caja ANTES de tocar nada: solo efectivo/contado tiene egreso en caja.
    forma_antes = (f.forma_pago_real or "").lower()
    pagado_antes = float(f.valor_pagado or 0)
    caja_antes = pagado_antes if forma_antes in ("efectivo", "contado") else 0.0

    antes = {"valor_total": float(f.valor_total or 0), "valor_pagado": pagado_antes,
             "numero_factura": f.numero_factura, "proveedor": f.proveedor,
             "forma_pago_real": f.forma_pago_real, "items": len(f.items)}

    tipo_map = {"contado": TipoPagoEnum.contado, "credito": TipoPagoEnum.credito,
                "transferencia": TipoPagoEnum.transferencia}

    # ── Metadata ──────────────────────────────────────────────────────────────
    if proveedor is not None:
        f.proveedor = proveedor.strip() or f.proveedor
    if numero_factura is not None:
        f.numero_factura = numero_factura.strip() or None
    if fecha_recibido is not None:
        # Llega como date (solo día). Guardar el instante UTC de la medianoche
        # COLOMBIA de ese día, igual que el alta. Asignar el date pelado creaba
        # las 00:00 UTC (19:00 del día anterior en Colombia), corriendo la
        # compra un día hacia atrás en rentabilidad y los reportes por mes.
        f.fecha_recibido = inicio_dia_col_utc(fecha_recibido)
    if tipo_pago is not None:
        if tipo_pago not in tipo_map:
            raise HTTPException(400, "tipo_pago inválido: contado | credito | transferencia")
        f.tipo_pago = tipo_map[tipo_pago]
        # Cambiar el tipo de pago cambia CÓMO se pagó realmente: sincronizar
        # forma_pago_real salvo que el llamador la haya fijado explícitamente.
        # (contado→"contado", transferencia→"transferencia"; crédito no toca la forma
        # porque el pago se rastrea aparte.)
        if forma_pago_real is None and tipo_pago in ("contado", "transferencia"):
            f.forma_pago_real = tipo_pago
    if forma_pago_real is not None:
        f.forma_pago_real = forma_pago_real.strip() or None

    # ── Productos: ajustar inventario + lote por la diferencia ────────────────
    if items is not None:
        existentes = {it.id: it for it in f.items}
        vistos = set()
        motivo = f"Corrección factura #{f.numero_factura or f.id} — {f.proveedor}"
        for upd in items:
            it = existentes.get(upd.get("id"))
            if not it:
                continue
            vistos.add(it.id)
            nueva_cant = upd.get("cantidad")
            if nueva_cant is not None and abs(float(nueva_cant) - float(it.cantidad)) > 0.001:
                delta = float(nueva_cant) - float(it.cantidad)
                # registrar_movimiento maneja stock Y lotes (entrada=agrega lote,
                # salida=consume FIFO). No tocar los lotes a mano: se descontaría doble.
                inv_svc.registrar_movimiento(
                    db, producto_id=it.producto_id, tienda_id=f.tienda_id,
                    tipo="entrada" if delta > 0 else "salida", cantidad=abs(delta),
                    motivo=motivo, usuario_id=usuario_id, commit=False, allow_negative=True,
                    factura_id=(f.id if delta > 0 else None), proveedor=f.proveedor,
                )
                it.cantidad = float(nueva_cant)
            if upd.get("precio_unitario") is not None:
                it.precio_unitario = float(upd["precio_unitario"])

        # Productos quitados de la edición → revertir su entrada (FIFO) y borrarlos.
        for it in list(f.items):
            if it.id not in vistos:
                inv_svc.registrar_movimiento(
                    db, producto_id=it.producto_id, tienda_id=f.tienda_id,
                    tipo="salida", cantidad=float(it.cantidad),
                    motivo=f"{motivo} (producto quitado)", usuario_id=usuario_id,
                    commit=False, allow_negative=True,
                )
                db.delete(it)

    # ── Montos ────────────────────────────────────────────────────────────────
    if valor_total is not None:
        if valor_total <= 0:
            raise HTTPException(400, "El valor total debe ser mayor a 0")
        f.valor_total = valor_total

    if valor_pagado is not None:
        if valor_pagado < 0:
            raise HTTPException(400, "El valor pagado no puede ser negativo")
        nuevo_pagado = min(valor_pagado, float(f.valor_total))
    else:
        nuevo_pagado = min(float(f.valor_pagado or 0), float(f.valor_total))
    f.valor_pagado = nuevo_pagado

    # ── Reconciliación de caja HOLÍSTICA ──────────────────────────────────────
    # El egreso que la factura DEBE tener en caja hoy es su pago solo si fue en
    # efectivo/contado (transferencia/crédito NO tocan el cajón). Comparamos el
    # estado nuevo contra el anterior y compensamos la diferencia con UN solo
    # movimiento. Así, pasar de contado→transferencia devuelve la plata al cajón
    # (ingreso), y transferencia→contado la saca (egreso) — el cuadre queda bien.
    forma_despues = (f.forma_pago_real or "").lower()
    caja_despues = nuevo_pagado if forma_despues in ("efectivo", "contado") else 0.0
    delta_caja = round(caja_despues - caja_antes, 2)
    if abs(delta_caja) > 0.001:
        turno_activo = db.query(CajaTurno).filter(
            CajaTurno.tienda_id == f.tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.abierto,
        ).first()
        if turno_activo:
            concepto = f"Ajuste factura {f.numero_factura or f.id}: corrección de forma/monto de pago"
            db.add(MovimientoCaja(
                caja_turno_id=turno_activo.id,
                tipo="egreso" if delta_caja > 0 else "ingreso",
                concepto=concepto, valor=abs(delta_caja), usuario_id=usuario_id,
                factura_id=f.id,
            ))

    audit.registrar(
        db, accion="editar_factura", tabla="facturas_compra", registro_id=f.id,
        usuario_id=usuario_id, tienda_id=f.tienda_id, datos_antes=antes,
        datos_despues={"valor_total": float(f.valor_total), "valor_pagado": float(f.valor_pagado),
                       "numero_factura": f.numero_factura, "proveedor": f.proveedor,
                       "forma_pago_real": f.forma_pago_real, "delta_caja": delta_caja,
                       "items": len(f.items)},
    )
    db.commit()
    db.refresh(f)
    return _serializar(f)


def registrar_pago(db: Session, factura_id: int, monto: float, forma_pago: str | None,
                   imagen_soporte_url: str | None, usuario_id: int) -> dict:
    """Registra un pago (total o parcial) a una factura de proveedor. Suma al valor_pagado
    (sin sobrepasar el total), guarda la forma y la foto del soporte de pago."""
    f = db.query(FacturaCompra).filter_by(id=factura_id).first()
    if not f:
        raise HTTPException(404, "Factura no encontrada")
    if monto <= 0:
        raise HTTPException(400, "El monto del pago debe ser mayor a 0")
    nuevo = float(f.valor_pagado or 0) + float(monto)
    f.valor_pagado = min(nuevo, float(f.valor_total))   # no permitir sobrepago
    if forma_pago:
        f.forma_pago_real = forma_pago
    if imagen_soporte_url:
        f.imagen_soporte_url = imagen_soporte_url

    # Solo el pago en EFECTIVO sale del cajón → egreso de caja (descuenta de consignaciones).
    # Bancos/crédito/cheque se manejan por el banco: quedan solo como registro de la factura.
    if (forma_pago or "").lower() in ("efectivo", "contado"):
        turno_activo = db.query(CajaTurno).filter(
            CajaTurno.tienda_id == f.tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.abierto,
        ).first()
        if turno_activo:
            concepto = f"Pago proveedor: {f.proveedor}"
            if f.numero_factura:
                concepto += f" — Fact. {f.numero_factura}"
            db.add(MovimientoCaja(
                caja_turno_id=turno_activo.id,
                tipo="egreso",
                concepto=concepto,
                valor=float(monto),
                usuario_id=usuario_id,
                factura_id=f.id,
            ))

    audit.registrar(
        db, accion="pago_proveedor", tabla="facturas_compra", registro_id=f.id,
        usuario_id=usuario_id, tienda_id=f.tienda_id,
        datos_despues={"monto": monto, "valor_pagado": f.valor_pagado, "forma": forma_pago},
    )
    db.commit()
    db.refresh(f)
    return _serializar(f)


def get_dashboard_pagos(db: Session, tienda_id: int | None = None,
                        desde=None, hasta=None) -> dict:
    """Consolidado de pagos a proveedores: totales, ranking por proveedor, por mes y por sede,
    + la lista de facturas (filtrable en el front por proveedor/estado/producto)."""
    q = db.query(FacturaCompra)
    if tienda_id is not None:
        q = q.filter(FacturaCompra.tienda_id == tienda_id)
    if desde is not None:
        q = q.filter(FacturaCompra.fecha_recibido >= desde)
    if hasta is not None:
        q = q.filter(FacturaCompra.fecha_recibido <= hasta)
    facturas = q.order_by(FacturaCompra.fecha_recibido.desc()).all()

    por_prov: dict = {}
    por_mes: dict = {}
    por_sede: dict = {}
    tot_fact = tot_pag = 0.0
    for f in facturas:
        vt = float(f.valor_total or 0)
        vp = float(f.valor_pagado or 0)
        tot_fact += vt
        tot_pag += vp
        p = por_prov.setdefault(f.proveedor, {"proveedor": f.proveedor, "facturado": 0.0, "pagado": 0.0, "n": 0})
        p["facturado"] += vt; p["pagado"] += vp; p["n"] += 1
        mes = (f.fecha_recibido or f.fecha_registro).strftime("%Y-%m")
        m = por_mes.setdefault(mes, {"mes": mes, "facturado": 0.0, "pagado": 0.0})
        m["facturado"] += vt; m["pagado"] += vp
        snombre = f.tienda.nombre if f.tienda else f"Sede {f.tienda_id}"
        s = por_sede.setdefault(f.tienda_id, {"tienda": snombre, "facturado": 0.0, "pagado": 0.0})
        s["facturado"] += vt; s["pagado"] += vp

    def _round_grupo(g, *campos):
        for x in g:
            for c in campos:
                x[c] = round(x[c], 2)
            if "facturado" in x and "pagado" in x:
                x["pendiente"] = round(x["facturado"] - x["pagado"], 2)
        return g

    ranking = sorted(_round_grupo(list(por_prov.values()), "facturado", "pagado"),
                     key=lambda x: x["facturado"], reverse=True)
    return {
        "totales": {
            "facturado": round(tot_fact, 2),
            "pagado": round(tot_pag, 2),
            "pendiente": round(tot_fact - tot_pag, 2),
            "n_facturas": len(facturas),
        },
        "por_proveedor": ranking,
        "por_mes": _round_grupo(sorted(por_mes.values(), key=lambda x: x["mes"]), "facturado", "pagado"),
        "por_sede": _round_grupo(list(por_sede.values()), "facturado", "pagado"),
        "facturas": [_serializar(f) for f in facturas],
    }
