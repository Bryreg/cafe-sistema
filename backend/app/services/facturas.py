from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
from datetime import datetime
from app.models.models import (FacturaCompra, FacturaCompraItem, TipoPagoEnum,
                               CajaTurno, MovimientoCaja, EstadoTurnoEnum,
                               LoteInventario)
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

    # 3) Egresos de caja de esta factura (concepto exacto que escriben crear/pago)
    concepto = f"Pago proveedor: {f.proveedor}"
    if f.numero_factura:
        concepto += f" — Fact. {f.numero_factura}"
    movs = (
        db.query(MovimientoCaja)
        .join(CajaTurno, CajaTurno.id == MovimientoCaja.caja_turno_id)
        .filter(MovimientoCaja.tipo == "egreso",
                MovimientoCaja.concepto == concepto,
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
                    usuario_id=usuario_id,
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

    for item in data.items:
        # Per-item lote takes precedence; fall back to factura-level for legacy clients
        numero_lote_item = item.numero_lote or data.numero_lote
        db.add(FacturaCompraItem(
            factura_id=factura.id,
            producto_id=item.producto_id,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
            numero_lote=numero_lote_item,
            fecha_vencimiento=item.fecha_vencimiento,
        ))
        inv_svc.registrar_movimiento(
            db,
            producto_id=item.producto_id,
            tienda_id=data.tienda_id,
            tipo="entrada",
            cantidad=item.cantidad,
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


def editar_factura(db: Session, factura_id: int, valor_total: float | None,
                   valor_pagado: float | None, numero_factura: str | None,
                   usuario_id: int) -> dict:
    """Corrige montos de una factura (típico: la barista puso un cero de más).
    Solo admin. Ajusta el egreso de caja proporcional si el pago fue en efectivo y
    el turno sigue abierto; bancos/transferencia no tocan caja."""
    f = db.query(FacturaCompra).filter_by(id=factura_id).first()
    if not f:
        raise HTTPException(404, "Factura no encontrada")

    antes = {"valor_total": float(f.valor_total or 0), "valor_pagado": float(f.valor_pagado or 0),
             "numero_factura": f.numero_factura}

    if numero_factura is not None:
        f.numero_factura = numero_factura.strip() or None

    if valor_total is not None:
        if valor_total <= 0:
            raise HTTPException(400, "El valor total debe ser mayor a 0")
        f.valor_total = valor_total

    if valor_pagado is not None:
        if valor_pagado < 0:
            raise HTTPException(400, "El valor pagado no puede ser negativo")
        nuevo_pagado = min(valor_pagado, float(f.valor_total))
    else:
        # Si bajó el total por debajo de lo pagado, recortar el pagado al nuevo total.
        nuevo_pagado = min(float(f.valor_pagado or 0), float(f.valor_total))

    # Si el pago fue en efectivo, el egreso de caja quedó por el monto viejo: ajustar
    # por la diferencia (mismo patrón de matcheo por concepto que eliminar_factura).
    delta_pago = nuevo_pagado - float(f.valor_pagado or 0)
    if abs(delta_pago) > 0.001 and (f.forma_pago_real or "").lower() in ("efectivo", "contado"):
        turno_activo = db.query(CajaTurno).filter(
            CajaTurno.tienda_id == f.tienda_id,
            CajaTurno.estado == EstadoTurnoEnum.abierto,
        ).first()
        if turno_activo:
            concepto = f"Ajuste factura {f.numero_factura or f.id}: corrección de pago"
            db.add(MovimientoCaja(
                caja_turno_id=turno_activo.id,
                tipo="egreso" if delta_pago > 0 else "ingreso",
                concepto=concepto, valor=abs(delta_pago), usuario_id=usuario_id,
            ))

    f.valor_pagado = nuevo_pagado

    audit.registrar(
        db, accion="editar_factura", tabla="facturas_compra", registro_id=f.id,
        usuario_id=usuario_id, tienda_id=f.tienda_id,
        datos_antes=antes,
        datos_despues={"valor_total": float(f.valor_total), "valor_pagado": float(f.valor_pagado),
                       "numero_factura": f.numero_factura},
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
