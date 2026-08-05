"""Costos del negocio: obligaciones (qué se debe) y pagos (qué salió, y cuándo).

Por qué existe este servicio y no se reusa MovimientoCaja: `registrar_movimiento`
(services/caja.py) exige un turno ABIERTO con el cuadre de llegada hecho, y el
movimiento no tiene fecha propia — hereda la del turno. Así, el arriendo que se
paga un sábado por transferencia desde el celular hoy no se puede registrar en
ningún lado. Además el arriendo/nómina corporativa no pertenece a una sede, y todo
MovimientoCaja está atado a un turno y por lo tanto a una sede.

Regla central: el estado de una obligación NO se almacena, se DERIVA de la suma de
sus pagos vivos. Lo único persistido es `anulada`. Es una asimetría deliberada con
FacturaCompra.valor_pagado — esa columna es justamente la que se puede
desincronizar de los movimientos que la originaron.
"""
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.tz import dia_col, hoy_col
from app.models.models import (CostoCategoria, FacturaCompra, Obligacion, Pago,
                               Tienda)
from app.services import audit

METODOS_PAGO = {"efectivo", "transferencia", "tarjeta", "cheque", "otro"}
RECURRENCIAS = {"mensual", "quincenal", "semanal"}
ESTADOS = {"pendiente", "parcial", "pagada", "anulada"}


# ── Catálogo ────────────────────────────────────────────────────────────────

def listar_categorias(db: Session, incluir_inactivas: bool = False) -> list:
    q = db.query(CostoCategoria)
    if not incluir_inactivas:
        q = q.filter(CostoCategoria.activa == True)  # noqa: E712
    cats = q.order_by(CostoCategoria.orden, CostoCategoria.nombre).all()
    return [{"id": c.id, "clave": c.clave, "nombre": c.nombre,
             "grupo": c.grupo, "orden": c.orden} for c in cats]


# ── Estado derivado ─────────────────────────────────────────────────────────

def _pagos_vivos(db: Session, obligacion_ids: list) -> dict:
    """{obligacion_id: [Pago vivo, ...]} en UNA query — no una por obligación."""
    if not obligacion_ids:
        return {}
    filas = db.query(Pago).filter(
        Pago.obligacion_id.in_(obligacion_ids),
        Pago.anulado == False,  # noqa: E712
    ).order_by(Pago.fecha_pago, Pago.id).all()
    agrupado: dict = {}
    for p in filas:
        agrupado.setdefault(p.obligacion_id, []).append(p)
    return agrupado


def estado_derivado(obligacion: Obligacion, pagado: float) -> str:
    """pendiente (Σ == 0) | parcial (0 < Σ < monto) | pagada (Σ >= monto).
    `anulada` es el único estado ALMACENADO y manda sobre todos los demás."""
    if obligacion.anulada:
        return "anulada"
    monto = float(obligacion.monto or 0)
    if pagado <= 0:
        return "pendiente"
    if pagado + 0.005 < monto:   # tolerancia de centavo: Numeric(12,2)
        return "parcial"
    return "pagada"


def _serializar(obligacion: Obligacion, pagos: list) -> dict:
    pagado = round(sum(float(p.monto or 0) for p in pagos), 2)
    monto = float(obligacion.monto or 0)
    cat = obligacion.categoria
    return {
        "id": obligacion.id,
        "tienda_id": obligacion.tienda_id,
        "tienda_nombre": obligacion.tienda.nombre if obligacion.tienda else None,
        "categoria_id": obligacion.categoria_id,
        "categoria_clave": cat.clave if cat else "",
        "categoria_nombre": cat.nombre if cat else "",
        "categoria_grupo": cat.grupo if cat else "",
        "concepto": obligacion.concepto,
        "beneficiario": obligacion.beneficiario,
        "monto": round(monto, 2),
        "pagado": pagado,
        # Nunca negativo: un pago de más deja la obligación en 'pagada' con saldo 0,
        # no con un saldo negativo que ensuciaría los totales de la lista.
        "saldo": round(max(monto - pagado, 0), 2),
        "estado": estado_derivado(obligacion, pagado),
        "fecha_devengo": obligacion.fecha_devengo,
        "fecha_vencimiento": obligacion.fecha_vencimiento,
        "recurrencia": obligacion.recurrencia,
        "nota": obligacion.nota,
        "imagen_url": obligacion.imagen_url,
        "anulada": bool(obligacion.anulada),
        "fecha_registro": obligacion.fecha_registro,
        "barista_nombre": obligacion.barista_nombre,
        "pagos": [_serializar_pago(p) for p in pagos],
    }


def _serializar_pago(p: Pago) -> dict:
    return {
        "id": p.id,
        "obligacion_id": p.obligacion_id,
        "factura_id": p.factura_id,
        "tienda_id": p.tienda_id,
        "monto": round(float(p.monto or 0), 2),
        "fecha_pago": p.fecha_pago,
        "metodo": p.metodo,
        "imagen_soporte_url": p.imagen_soporte_url,
        "nota": p.nota,
        "anulado": bool(p.anulado),
        "fecha_registro": p.fecha_registro,
    }


# ── Validaciones compartidas ────────────────────────────────────────────────

def _validar_categoria(db: Session, categoria_id: int) -> CostoCategoria:
    cat = db.query(CostoCategoria).filter(CostoCategoria.id == categoria_id).first()
    if not cat:
        raise HTTPException(400, "Categoría de costo inexistente")
    if not cat.activa:
        raise HTTPException(400, f"La categoría «{cat.nombre}» está desactivada — elegí otra")
    return cat


def _validar_tienda(db: Session, tienda_id):
    """tienda_id None es VÁLIDO y significativo: gasto corporativo (sin sede)."""
    if tienda_id is None:
        return
    if not db.query(Tienda).filter(Tienda.id == tienda_id).first():
        raise HTTPException(400, "Sede inexistente")


def _validar_monto(monto) -> float:
    try:
        valor = float(monto)
    except (TypeError, ValueError):
        raise HTTPException(400, "El monto debe ser un número")
    if valor <= 0:
        raise HTTPException(400, "El monto debe ser mayor a 0")
    return round(valor, 2)


def _validar_concepto(concepto: str) -> str:
    limpio = (concepto or "").strip()
    if not limpio:
        raise HTTPException(400, "El concepto es obligatorio")
    return limpio


def _validar_recurrencia(recurrencia):
    if recurrencia is None or recurrencia == "":
        return None
    if recurrencia not in RECURRENCIAS:
        raise HTTPException(400, "Recurrencia inválida: mensual | quincenal | semanal")
    return recurrencia


# ── Obligaciones ────────────────────────────────────────────────────────────

def crear_obligacion(db: Session, data, usuario_id: int,
                     barista_id: int | None = None,
                     barista_nombre: str | None = None) -> dict:
    _validar_categoria(db, data.categoria_id)
    _validar_tienda(db, data.tienda_id)
    obligacion = Obligacion(
        tienda_id=data.tienda_id,
        categoria_id=data.categoria_id,
        concepto=_validar_concepto(data.concepto),
        beneficiario=(data.beneficiario or "").strip() or None,
        monto=_validar_monto(data.monto),
        fecha_devengo=data.fecha_devengo,
        fecha_vencimiento=data.fecha_vencimiento,
        recurrencia=_validar_recurrencia(data.recurrencia),
        nota=data.nota,
        imagen_url=data.imagen_url,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(obligacion)
    db.flush()
    audit.registrar(
        db, accion="crear_obligacion", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=obligacion.tienda_id,
        datos_despues={"concepto": obligacion.concepto, "monto": float(obligacion.monto),
                       "fecha_devengo": obligacion.fecha_devengo},
    )
    db.commit()
    db.refresh(obligacion)
    return _serializar(obligacion, [])


def editar_obligacion(db: Session, obligacion_id: int, data, usuario_id: int) -> dict:
    obligacion = db.query(Obligacion).filter(Obligacion.id == obligacion_id).first()
    if not obligacion:
        raise HTTPException(404, "Obligación no encontrada")
    if obligacion.anulada:
        raise HTTPException(400, "La obligación está anulada — no se puede editar")

    # exclude_unset: distingue "no lo mandaron" de "lo mandaron en null". Sin esto,
    # tienda_id=None (corporativo) sería indistinguible de omitir el campo.
    campos = data.model_dump(exclude_unset=True)
    if "categoria_id" in campos and campos["categoria_id"] is not None:
        _validar_categoria(db, campos["categoria_id"])
        obligacion.categoria_id = campos["categoria_id"]
    if "tienda_id" in campos:
        _validar_tienda(db, campos["tienda_id"])
        obligacion.tienda_id = campos["tienda_id"]
    if "concepto" in campos and campos["concepto"] is not None:
        obligacion.concepto = _validar_concepto(campos["concepto"])
    if "monto" in campos and campos["monto"] is not None:
        obligacion.monto = _validar_monto(campos["monto"])
    if "fecha_devengo" in campos and campos["fecha_devengo"] is not None:
        obligacion.fecha_devengo = campos["fecha_devengo"]
    if "fecha_vencimiento" in campos:
        obligacion.fecha_vencimiento = campos["fecha_vencimiento"]
    if "recurrencia" in campos:
        obligacion.recurrencia = _validar_recurrencia(campos["recurrencia"])
    if "beneficiario" in campos:
        obligacion.beneficiario = (campos["beneficiario"] or "").strip() or None
    if "nota" in campos:
        obligacion.nota = campos["nota"]
    if "imagen_url" in campos:
        obligacion.imagen_url = campos["imagen_url"]

    audit.registrar(
        db, accion="editar_obligacion", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=obligacion.tienda_id,
        datos_despues=campos,
    )
    db.commit()
    db.refresh(obligacion)
    return _serializar(obligacion, _pagos_vivos(db, [obligacion.id]).get(obligacion.id, []))


def anular_obligacion(db: Session, obligacion_id: int, usuario_id: int,
                      motivo: str | None = None) -> dict:
    """Baja LÓGICA. Nunca un DELETE: dejaría los pagos huérfanos y sin traza."""
    obligacion = db.query(Obligacion).filter(Obligacion.id == obligacion_id).first()
    if not obligacion:
        raise HTTPException(404, "Obligación no encontrada")
    if obligacion.anulada:
        return _serializar(obligacion, [])
    obligacion.anulada = True
    if motivo:
        obligacion.nota = f"{obligacion.nota + ' — ' if obligacion.nota else ''}Anulada: {motivo}"
    audit.registrar(
        db, accion="anular_obligacion", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=obligacion.tienda_id,
        datos_antes={"concepto": obligacion.concepto, "monto": float(obligacion.monto or 0)},
        datos_despues={"motivo": motivo},
    )
    db.commit()
    db.refresh(obligacion)
    return _serializar(obligacion, [])


def listar_obligaciones(db: Session, *, tienda_id: int | None = None,
                        solo_corporativas: bool = False,
                        categoria: str | None = None,
                        estado: str | None = None,
                        desde: date | None = None, hasta: date | None = None,
                        campo_fecha: str = "devengo") -> dict:
    """Listado + totales. Reglas de los filtros:

    - sin `tienda_id` y sin `solo_corporativas` → TODO, corporativas incluidas (son
      el gasto más grande: esconderlas del "todas" sería mentir en el total);
    - con `tienda_id` → SOLO esa sede (las corporativas quedan distinguidas aparte);
    - `solo_corporativas` → SOLO las que no tienen sede.

    Por defecto las anuladas no aparecen ni suman; se piden explícitamente con
    estado='anulada'.
    """
    if estado is not None and estado not in ESTADOS:
        raise HTTPException(400, "Estado inválido: pendiente | parcial | pagada | anulada")
    if campo_fecha not in ("devengo", "vencimiento"):
        raise HTTPException(400, "campo_fecha inválido: devengo | vencimiento")

    q = db.query(Obligacion)
    if solo_corporativas:
        q = q.filter(Obligacion.tienda_id.is_(None))
    elif tienda_id is not None:
        q = q.filter(Obligacion.tienda_id == tienda_id)
    if categoria:
        q = q.join(CostoCategoria, Obligacion.categoria_id == CostoCategoria.id)
        q = q.filter(CostoCategoria.clave == categoria)
    columna = (Obligacion.fecha_devengo if campo_fecha == "devengo"
               else Obligacion.fecha_vencimiento)
    if desde is not None:
        q = q.filter(columna >= desde)
    if hasta is not None:
        q = q.filter(columna <= hasta)
    # anulada == True solo se muestra si se pide ese estado explícitamente.
    q = q.filter(Obligacion.anulada == (estado == "anulada"))

    filas = q.order_by(Obligacion.fecha_devengo.desc(), Obligacion.id.desc()).all()
    pagos_por_obligacion = _pagos_vivos(db, [o.id for o in filas])

    obligaciones = []
    total_monto = total_pagado = 0.0
    for o in filas:
        item = _serializar(o, pagos_por_obligacion.get(o.id, []))
        # El estado se DERIVA, así que el filtro por estado se aplica acá y no en SQL.
        if estado is not None and item["estado"] != estado:
            continue
        obligaciones.append(item)
        total_monto += item["monto"]
        total_pagado += item["pagado"]

    return {
        "obligaciones": obligaciones,
        "totales": {
            "monto": round(total_monto, 2),
            "pagado": round(total_pagado, 2),
            "saldo": round(max(total_monto - total_pagado, 0), 2),
            "n": len(obligaciones),
        },
    }


# ── Agenda unificada (Fase 2) ───────────────────────────────────────────────
#
# La única lista de "qué hay que pagar esta semana", mezclando el proveedor de
# leche con el arriendo. Es la UNIÓN DE DOS CONSULTAS, jamás una tabla copiada:
# FacturaCompra sigue siendo la ÚNICA verdad de la deuda con proveedores y NO se
# crean obligaciones espejo. Copiar esa deuda acá daría dos verdades sobre la
# misma plata — exactamente lo que este diseño evita.

def _fecha_proyectada(f: FacturaCompra) -> tuple:
    """(día Colombia en que toca pagar la factura, de dónde salió esa fecha).

    Precedencia = COALESCE(fecha_programada, fecha_vencimiento,
    fecha_recibido + plazo_dias): lo que el dueño DECIDIÓ manda sobre lo que el
    proveedor exige, y lo exigido manda sobre lo derivado del plazo.

    Sin ninguna de las tres devuelve (None, ''): la factura NO se agenda. No se
    inventa un vencimiento — no hay tabla maestra de proveedores de donde sacar un
    plazo (FacturaCompra.proveedor es un String suelto), así que las históricas
    entran a la agenda recién cuando alguien les carga el plazo a mano.
    """
    if f.fecha_programada is not None:
        return dia_col(f.fecha_programada), "programada"
    if f.fecha_vencimiento is not None:
        return dia_col(f.fecha_vencimiento), "vencimiento"
    if f.plazo_dias is not None and f.fecha_recibido is not None:
        return dia_col(f.fecha_recibido) + timedelta(days=int(f.plazo_dias)), "plazo"
    return None, ""


def get_agenda(db: Session, desde: date | None = None, hasta: date | None = None,
               tienda_id: int | None = None) -> dict:
    """Facturas con saldo + obligaciones con saldo, ordenadas por fecha de pago.

    El monto de cada ítem es el SALDO, nunca el total: la agenda responde "cuánta
    plata falta", no "cuánto se facturó".

    Filtro de sede, con la misma regla que `listar_obligaciones`: sin `tienda_id`
    entra TODO —las obligaciones corporativas (tienda_id NULL) incluidas, una sola
    vez—; con `tienda_id` entra SOLO esa sede. Repartir las corporativas entre las
    sedes las duplicaría y el total de la agenda dejaría de cuadrar.
    """
    hoy = hoy_col()
    items: list = []

    # 1) Facturas de proveedor. El rango se filtra en Python y no en SQL porque la
    #    fecha proyectada puede ser derivada (fecha_recibido + plazo_dias) y esa
    #    suma no es portable entre SQLite y Postgres.
    q = db.query(FacturaCompra).filter(
        FacturaCompra.valor_total - func.coalesce(FacturaCompra.valor_pagado, 0) > 0)
    if tienda_id is not None:
        q = q.filter(FacturaCompra.tienda_id == tienda_id)
    for f in q.all():
        fecha, origen = _fecha_proyectada(f)
        if fecha is None:
            continue
        if (desde is not None and fecha < desde) or (hasta is not None and fecha > hasta):
            continue
        items.append({
            "tipo": "factura",
            "id": f.id,
            "concepto": f.proveedor,
            "beneficiario": f.proveedor,
            "referencia": f.numero_factura,
            "tienda_id": f.tienda_id,
            "tienda_nombre": f.tienda.nombre if f.tienda else None,
            "monto": round(float(f.valor_total) - float(f.valor_pagado or 0), 2),
            "fecha": fecha,
            "origen_fecha": origen,
            "vencida": fecha < hoy,
            "categoria": None,   # las facturas no pasan por el catálogo de costos
        })

    # 2) Obligaciones (arriendo, nómina, servicios). Sin fecha_vencimiento no se
    #    agendan: no hay para cuándo pagarlas.
    qo = db.query(Obligacion).filter(
        Obligacion.anulada == False,  # noqa: E712
        Obligacion.fecha_vencimiento.isnot(None),
    )
    if tienda_id is not None:
        qo = qo.filter(Obligacion.tienda_id == tienda_id)
    if desde is not None:
        qo = qo.filter(Obligacion.fecha_vencimiento >= desde)
    if hasta is not None:
        qo = qo.filter(Obligacion.fecha_vencimiento <= hasta)
    filas = qo.all()
    pagos_por_obligacion = _pagos_vivos(db, [o.id for o in filas])
    for o in filas:
        pagado = sum(float(p.monto or 0) for p in pagos_por_obligacion.get(o.id, []))
        saldo = round(float(o.monto or 0) - pagado, 2)
        if saldo <= 0:   # ya pagada: no es algo que pagar
            continue
        fecha = o.fecha_vencimiento
        items.append({
            "tipo": "obligacion",
            "id": o.id,
            "concepto": o.concepto,
            "beneficiario": o.beneficiario,
            "referencia": None,
            "tienda_id": o.tienda_id,
            "tienda_nombre": o.tienda.nombre if o.tienda else None,
            "monto": saldo,
            "fecha": fecha,
            "origen_fecha": "vencimiento",
            "vencida": fecha < hoy,
            "categoria": o.categoria.clave if o.categoria else None,
        })

    # tipo+id como desempate: dos cosas que vencen el mismo día tienen que salir
    # siempre en el mismo orden (si no, la lista "salta" entre cargas).
    items.sort(key=lambda i: (i["fecha"], i["tipo"], i["id"]))
    total = round(sum(i["monto"] for i in items), 2)
    vencido = round(sum(i["monto"] for i in items if i["vencida"]), 2)
    return {
        "items": items,
        "totales": {"monto": total, "vencido": vencido, "n": len(items)},
    }


# ── Pagos ───────────────────────────────────────────────────────────────────

def registrar_pago(db: Session, data, usuario_id: int,
                   barista_id: int | None = None,
                   barista_nombre: str | None = None) -> dict:
    """El pago es lo que hace útil todo el módulo: fecha_pago es EL DÍA QUE SALIÓ
    LA PLATA, un dato que hoy no existe en ninguna tabla del sistema."""
    tiene_obligacion = data.obligacion_id is not None
    tiene_factura = data.factura_id is not None
    if tiene_obligacion and tiene_factura:
        raise HTTPException(400, "El pago apunta a una obligación O a una factura, no a las dos")
    if not tiene_obligacion and not tiene_factura:
        raise HTTPException(400, "El pago debe apuntar a una obligación o a una factura")
    if data.metodo not in METODOS_PAGO:
        raise HTTPException(400, "Método inválido: efectivo | transferencia | tarjeta | cheque | otro")
    monto = _validar_monto(data.monto)

    tienda_id = None
    if tiene_obligacion:
        obligacion = db.query(Obligacion).filter(Obligacion.id == data.obligacion_id).first()
        if not obligacion:
            raise HTTPException(404, "Obligación no encontrada")
        if obligacion.anulada:
            raise HTTPException(400, "La obligación está anulada — no admite pagos")
        tienda_id = obligacion.tienda_id   # snapshot copiado del padre

    pago = Pago(
        obligacion_id=data.obligacion_id,
        factura_id=data.factura_id,
        tienda_id=tienda_id,
        monto=monto,
        fecha_pago=data.fecha_pago,
        metodo=data.metodo,
        imagen_soporte_url=data.imagen_soporte_url,
        nota=data.nota,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(pago)
    db.flush()
    audit.registrar(
        db, accion="registrar_pago_costo", tabla="pagos",
        registro_id=pago.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"obligacion_id": pago.obligacion_id, "factura_id": pago.factura_id,
                       "monto": monto, "fecha_pago": pago.fecha_pago, "metodo": pago.metodo},
    )
    db.commit()
    db.refresh(pago)
    return _serializar_pago(pago)


def anular_pago(db: Session, pago_id: int, usuario_id: int, motivo: str | None = None) -> dict:
    """Baja lógica del pago. Al dejar de contar, la obligación vuelve sola al
    estado que corresponda (de 'pagada' a 'parcial', por ejemplo): el estado se
    deriva, así que no hay ningún contador que corregir a mano."""
    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    if not pago.anulado:
        pago.anulado = True
        if motivo:
            pago.nota = f"{pago.nota + ' — ' if pago.nota else ''}Anulado: {motivo}"
        audit.registrar(
            db, accion="anular_pago_costo", tabla="pagos",
            registro_id=pago.id, usuario_id=usuario_id, tienda_id=pago.tienda_id,
            datos_antes={"monto": float(pago.monto or 0), "fecha_pago": pago.fecha_pago},
            datos_despues={"motivo": motivo},
        )
        db.commit()
        db.refresh(pago)
    return _serializar_pago(pago)


def listar_pagos(db: Session, *, obligacion_id: int | None = None,
                 factura_id: int | None = None,
                 desde: date | None = None, hasta: date | None = None,
                 incluir_anulados: bool = False) -> list:
    """Pagos por fecha_pago — la vista de "qué plata salió" en un rango."""
    q = db.query(Pago)
    if obligacion_id is not None:
        q = q.filter(Pago.obligacion_id == obligacion_id)
    if factura_id is not None:
        q = q.filter(Pago.factura_id == factura_id)
    if desde is not None:
        q = q.filter(Pago.fecha_pago >= desde)
    if hasta is not None:
        q = q.filter(Pago.fecha_pago <= hasta)
    if not incluir_anulados:
        q = q.filter(Pago.anulado == False)  # noqa: E712
    return [_serializar_pago(p) for p in q.order_by(Pago.fecha_pago.desc(), Pago.id.desc()).all()]
