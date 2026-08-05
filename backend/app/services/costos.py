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
import math
from datetime import date, timedelta
from statistics import median

from fastapi import HTTPException
from sqlalchemy import func, not_, or_
from sqlalchemy.orm import Session

from app.core.tz import dia_col, hoy_col, rango_col_utc
from app.models.models import (CajaTurno, Configuracion, Consignacion,
                               CostoCategoria, EntregaTurno,
                               EstadoConsignacionEnum, EstadoTurnoEnum,
                               FacturaCompra, MovimientoCaja, Obligacion, Pago,
                               Ticket, Tienda, TipoMovCajaEnum)
from app.services import audit
# La lista de conceptos reservados que services/facturas.py escribe para los pagos
# a proveedor vive en rentabilidad.py y se REUSA, no se copia: si allá cambia, acá
# tiene que cambiar en el mismo commit o el anti-doble-conteo se abre un agujero.
from app.services.rentabilidad import _CONCEPTOS_COMPRA

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
        # Con valor = el pago es el espejo de un egreso de caja adoptado (Fase 3).
        "movimiento_caja_id": p.movimiento_caja_id,
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


# ── Adopción de egresos históricos (Fase 3) ─────────────────────────────────
#
# Los gastos fijos que YA se registraron como egreso suelto de caja ("Arriendo
# local", texto libre) se pueden ADOPTAR: nace una Obligacion devengada y un Pago
# espejo con `movimiento_caja_id`. El MovimientoCaja NO SE TOCA NI SE BORRA — el
# cuadre del turno tiene que seguir dando exactamente lo mismo.
#
# La plata cambia de bolsa, no de tamaño: el P&L excluye los movimientos adoptados
# de la query de gastos y suma las obligaciones devengadas. Las dos mitades son
# inseparables; con una sola, el total de gastos se movería.


def _es_egreso_de_compra(db: Session, movimiento_id: int) -> bool:
    """¿El concepto matchea un patrón reservado de pago a proveedor? Se evalúa con
    el MISMO `LIKE` en SQL que usa el P&L, no con una reimplementación en Python:
    dos motores de match distintos se desincronizan en el primer caso raro."""
    return db.query(MovimientoCaja.id).filter(
        MovimientoCaja.id == movimiento_id,
        or_(*[MovimientoCaja.concepto.like(p) for p in _CONCEPTOS_COMPRA]),
    ).first() is not None


def _query_egresos_adoptables(db: Session):
    """Egresos de caja que PODRÍAN adoptarse: los mismos que el P&L cuenta hoy como
    gasto de texto libre. Excluye lo ligado a compras por las dos vías (factura_id
    estructural + concepto reservado histórico)."""
    return (
        db.query(MovimientoCaja, CajaTurno.tienda_id)
        .join(CajaTurno, MovimientoCaja.caja_turno_id == CajaTurno.id)
        .filter(
            MovimientoCaja.tipo == TipoMovCajaEnum.egreso,
            MovimientoCaja.factura_id.is_(None),
            not_(or_(*[MovimientoCaja.concepto.like(p) for p in _CONCEPTOS_COMPRA])),
        )
    )


def _subquery_adoptados(db: Session):
    """movimiento_caja_id de los pagos VIVOS. Se usa como SUBCONSULTA y nunca como
    lista de ids: en una caja con años de movimientos, un `IN (...)` explícito
    revienta el tope de variables de SQLite."""
    return (db.query(Pago.movimiento_caja_id)
              .filter(Pago.movimiento_caja_id.isnot(None), Pago.anulado.is_(False))
              .distinct().subquery())


def listar_egresos_sin_adoptar(db: Session, *, desde: date | None = None,
                               hasta: date | None = None,
                               tienda_id: int | None = None,
                               limite: int = 200) -> dict:
    """Bandeja de "egresos sin categorizar": lo que el P&L todavía muestra como texto
    libre. Solo lectura — adoptar es una acción aparte y explícita."""
    d_utc, h_utc = rango_col_utc(desde or (hoy_col() - timedelta(days=90)), hasta)
    adoptados = _subquery_adoptados(db)
    q = _query_egresos_adoptables(db).filter(
        MovimientoCaja.fecha >= d_utc,
        MovimientoCaja.fecha <= h_utc,
        MovimientoCaja.id.notin_(db.query(adoptados.c.movimiento_caja_id)),
    )
    if tienda_id is not None:
        q = q.filter(CajaTurno.tienda_id == tienda_id)
    filas = q.order_by(MovimientoCaja.fecha.desc(), MovimientoCaja.id.desc()).limit(
        max(1, min(int(limite or 200), 500))).all()

    tiendas = {t.id: t.nombre for t in db.query(Tienda).all()}
    egresos = [{
        "id": mov.id,
        "concepto": mov.concepto,
        "valor": round(float(mov.valor or 0), 2),
        # El día de NEGOCIO en que se tecleó. Es el devengo por defecto y también lo
        # que la UI muestra para que el admin decida si hay que corregirlo.
        "fecha": dia_col(mov.fecha) if mov.fecha else None,
        "tienda_id": tid,
        "tienda_nombre": tiendas.get(tid),
        "barista_nombre": mov.barista_nombre,
    } for mov, tid in filas]
    return {
        "egresos": egresos,
        "totales": {"monto": round(sum(e["valor"] for e in egresos), 2), "n": len(egresos)},
    }


def adoptar_egreso(db: Session, movimiento_id: int, categoria_id: int, usuario_id: int,
                   fecha_devengo: date | None = None, concepto: str | None = None,
                   beneficiario: str | None = None, nota: str | None = None,
                   barista_id: int | None = None,
                   barista_nombre: str | None = None) -> dict:
    """Convierte un egreso suelto de caja en obligación devengada + pago espejo.

    NO cambia ningún total: el MovimientoCaja queda intacto (el turno cuadra igual)
    y el P&L lo deja de contar como gasto de texto libre justo cuando empieza a
    contar la obligación. Lo único que cambia es dónde aparece la plata.

    `fecha_devengo` es un OVERRIDE EXPLÍCITO y nunca silencioso. Por defecto vale
    `dia_col(mov.fecha)`, pero `mov.fecha` es cuándo se TECLEÓ el egreso, no cuándo
    salió la plata: `MovimientoCajaRequest` (schemas/caja.py) no acepta fecha y el
    modelo la fija con `default=datetime.utcnow`, así que registrar un pago de un
    día pasado es imposible por cualquier camino. Si el arriendo de julio se tecleó
    en agosto, corregir esta fecha MUEVE EL COSTO DE MES en el P&L — por eso la UI
    lo muestra editable y avisa, en vez de decidirlo sola.

    `fecha_pago` del espejo, en cambio, siempre es `dia_col(mov.fecha)`: la plata
    salió de ESA caja ese día, y eso no se corrige desde acá.
    """
    mov = db.query(MovimientoCaja).filter(MovimientoCaja.id == movimiento_id).first()
    if not mov:
        raise HTTPException(404, "Movimiento de caja no encontrado")

    tipo = getattr(mov.tipo, "value", mov.tipo)
    if tipo != "egreso":
        raise HTTPException(400, "Solo se adoptan egresos — un ingreso no es un costo")

    # Guarda 1: vínculo ESTRUCTURAL con una compra. La deuda ya vive en
    # FacturaCompra y adoptarla crearía una obligación espejo de esa misma plata.
    if mov.factura_id is not None:
        raise HTTPException(
            400, "Este egreso es el pago de una factura de proveedor — ya está contado "
                 "en Compras. Manejalo desde Pagos a Proveedores.")

    # Guarda 2: filas ANTERIORES a la columna factura_id, donde el único vínculo con
    # la compra es el concepto reservado que escribe services/facturas.py.
    if _es_egreso_de_compra(db, mov.id):
        raise HTTPException(
            400, "El concepto de este egreso es de pago a proveedor — ya está contado "
                 "en Compras y adoptarlo lo contaría dos veces.")

    # Guarda 3: se adopta UNA sola vez. El servicio responde 409 en vez de dejar que
    # reviente el índice único parcial de la DB (que es la garantía final, no esta).
    ya = db.query(Pago).filter(Pago.movimiento_caja_id == mov.id).order_by(
        Pago.anulado, Pago.id).first()
    if ya is not None:
        if ya.anulado:
            raise HTTPException(
                409, "Este egreso ya se adoptó una vez y su pago fue anulado — la "
                     "adopción no se puede rehacer. Editá la obligación existente.")
        raise HTTPException(409, "Este egreso ya fue adoptado")

    cat = _validar_categoria(db, categoria_id)
    # La sede sale del turno del movimiento: así el P&L por sede no se mueve un peso.
    turno = db.query(CajaTurno).filter(CajaTurno.id == mov.caja_turno_id).first()
    tienda_id = turno.tienda_id if turno else None

    dia_mov = dia_col(mov.fecha) if mov.fecha else hoy_col()
    obligacion = Obligacion(
        tienda_id=tienda_id,
        categoria_id=cat.id,
        concepto=_validar_concepto(concepto or mov.concepto),
        beneficiario=(beneficiario or "").strip() or None,
        monto=_validar_monto(mov.valor),
        fecha_devengo=fecha_devengo or dia_mov,
        # Ya está pagada: no hay nada que agendar, así que no lleva vencimiento.
        fecha_vencimiento=None,
        nota=nota,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(obligacion)
    db.flush()

    pago = Pago(
        obligacion_id=obligacion.id,
        factura_id=None,
        tienda_id=tienda_id,
        monto=float(obligacion.monto),
        fecha_pago=dia_mov,
        # Un egreso de caja es plata que salió del cajón, siempre.
        metodo="efectivo",
        movimiento_caja_id=mov.id,   # la llave anti-doble-conteo
        nota="Adopción del egreso de caja",
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(pago)
    db.flush()

    audit.registrar(
        db, accion="adoptar_egreso_caja", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_antes={"movimiento_caja_id": mov.id, "concepto": mov.concepto,
                     "valor": float(mov.valor or 0), "dia_movimiento": dia_mov},
        datos_despues={"categoria": cat.clave, "monto": float(obligacion.monto),
                       "fecha_devengo": obligacion.fecha_devengo,
                       "devengo_corregido": bool(fecha_devengo and fecha_devengo != dia_mov),
                       "pago_id": pago.id},
    )
    db.commit()
    db.refresh(obligacion)
    db.refresh(pago)
    return _serializar(obligacion, [pago])


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


# ── Flujo de caja proyectado (Fase 4) ───────────────────────────────────────
#
# El único número que ningún otro reporte del sistema puede producir: EL DÍA EN
# QUE SE ACABA LA PLATA. Ventas, P&L y agenda miran para atrás o miran una sola
# dimensión; esto cruza lo que hay con lo que entra y lo que sale.
#
#   saldo_proyectado(D) = caja_hoy + Σ entradas(d) − Σ salidas(d),  d en (hoy, D]
#
# Las tres reglas anti-doble-conteo que sostienen la fórmula:
#
#   1. las consignaciones NO son entrada — mueven plata del cajón al banco: no se
#      suman como entrada Y se restan del efectivo del turno, porque si no la
#      misma plata quedaría contada en la registradora y otra vez en el banco;
#   2. los MovimientoCaja egreso YA registrados NO se restan como salida futura
#      — son pasado y ya están descontados dentro del efectivo de la registradora;
#   3. la deuda con proveedores se lee de la agenda (unión de dos consultas) y
#      nunca de una copia: FacturaCompra sigue siendo su única verdad.

HORIZONTE_DEFAULT = 30
HORIZONTE_MAX = 180
SEMANAS_HISTORIA = 8          # 56 días = exactamente 8 muestras de cada día de semana
DIAS_SALDO_BANCO_VIGENTE = 7  # más viejo que esto y la respuesta se marca desactualizada
SALDO_BANCO_MAX = 1e12
CLAVE_SALDO_BANCO = "saldo_banco"
CLAVE_SALDO_BANCO_FECHA = "saldo_banco_fecha"


def _efectivo_en_registradora(db: Session, tienda_id: int) -> tuple:
    """(efectivo que hay AHORA en el cajón de la sede, de dónde salió el dato).

    Con turno abierto es la fórmula del cuadre —base_real + total_efectivo +
    ingresos − egresos, services/caja.py:1016-1024— MENOS lo ya consignado, que
    es plata que salió del cajón y hoy está en el banco. Se replica acá porque
    allá vive inline dentro de `registrar_cuadre_llegada` y no hay función que
    extraer sin tocar caja.py: si esa fórmula cambia, esta línea cambia en el
    mismo commit.

    Sin turno abierto manda el `efectivo_final_real` del ÚLTIMO TURNO CERRADO: el
    conteo físico del cierre. `cerrar_caja` NO crea ningún EntregaTurno —guarda el
    conteo en la columna del turno (services/caja.py:518)— y el único cierre que
    deja EntregaTurno es el del kiosko, y solo si hay imagen. Leer "el último
    EntregaTurno de cualquier tipo" devolvía entonces el cuadre de LLEGADA: la
    base de la mañana. De noche, con la sede cerrada —justo cuando el dueño mira—
    una sede que abrió con 100.000 y cerró con 1.000.000 volvía a 100.000 e
    inventaba un punto de quiebre con alerta roja en el Dashboard.

    El EntregaTurno queda solo como respaldo, para el turno que cerró sin conteo
    (efectivo_final_real NULL) y para los cierres viejos anteriores a la columna.
    Ahí no se descuentan consignaciones: el número es un CONTEO FÍSICO y lo que ya
    se depositó no estaba en el cajón cuando se contó. Restarlo otra vez subestima
    la caja, que es el error que fabrica quiebres falsos.
    """
    turno = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if turno is not None:
        ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
            MovimientoCaja.caja_turno_id == turno.id,
            MovimientoCaja.tipo == "ingreso",
        ).scalar() or 0.0
        egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
            MovimientoCaja.caja_turno_id == turno.id,
            MovimientoCaja.tipo == "egreso",
        ).scalar() or 0.0
        # Deliberado, y la razón es el doble conteo: `Consignacion` no genera
        # MovimientoCaja, así que la plata ya depositada seguiría contando en la
        # registradora Y otra vez dentro del `saldo_banco` que declara el dueño.
        # Solo las REALIZADAS, mismo criterio que abrir_caja (caja.py:257-260).
        consignado = db.query(func.sum(Consignacion.valor)).filter(
            Consignacion.caja_turno_id == turno.id,
            Consignacion.estado == EstadoConsignacionEnum.realizada,
        ).scalar() or 0.0
        esperado = (float(turno.base_real or 0) + float(turno.total_efectivo or 0)
                    + float(ingresos) - float(egresos) - float(consignado))
        return round(esperado, 2), "turno_abierto"

    # `fecha_cierre.isnot(None)` no es cosmético: SQLite y Postgres ordenan los
    # NULL al revés en un ORDER BY DESC, así que un turno cerrado sin fecha
    # (legacy) se colaría como "el último" en un motor y no en el otro.
    cerrado = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado,
        CajaTurno.fecha_cierre.isnot(None),
    ).order_by(CajaTurno.fecha_cierre.desc(), CajaTurno.id.desc()).first()
    if cerrado is not None and cerrado.efectivo_final_real is not None:
        return round(float(cerrado.efectivo_final_real), 2), "ultimo_cierre"

    ultima = db.query(EntregaTurno).filter(
        EntregaTurno.tienda_id == tienda_id,
    ).order_by(EntregaTurno.fecha_hora.desc(), EntregaTurno.id.desc()).first()
    if ultima is not None:
        return round(float(ultima.efectivo_real or 0), 2), "ultimo_cuadre"
    return 0.0, "sin_datos"


def _leer_saldo_banco(db: Session) -> tuple:
    """(saldo declarado, fecha de la declaración) desde `configuracion`.

    Tolera basura guardada: la fila es TEXTO y un 'inf' o una fecha inválida de
    otra versión no puede tumbar la pantalla entera del dueño. Ante cualquier
    duda devuelve 0 / None, que además deja la respuesta marcada desactualizada.
    """
    filas = {c.clave: c.valor for c in db.query(Configuracion).filter(
        Configuracion.clave.in_((CLAVE_SALDO_BANCO, CLAVE_SALDO_BANCO_FECHA))).all()}
    try:
        saldo = float(filas.get(CLAVE_SALDO_BANCO) or 0)
    except (TypeError, ValueError):
        saldo = 0.0
    if not math.isfinite(saldo) or saldo < 0 or saldo > SALDO_BANCO_MAX:
        saldo = 0.0
    fecha = None
    crudo = (filas.get(CLAVE_SALDO_BANCO_FECHA) or "").strip()
    if crudo:
        try:
            fecha = date.fromisoformat(crudo)
        except ValueError:
            fecha = None
    return round(saldo, 2), fecha


def _caja_hoy(db: Session, hoy: date, tienda_id: int | None) -> dict:
    """Con cuánta plata arranca la proyección. Dos sumandos, porque el sistema
    solo conoce uno:

    - el efectivo de cada registradora, que SÍ se deriva de los datos;
    - el saldo del banco, que es un INPUT DEL DUEÑO. El sistema registra
      Consignacion (depósitos) pero jamás un saldo bancario: no hay de dónde
      derivarlo. Si la declaración tiene más de una semana, la respuesta lo dice
      en vez de mentir.

    DECISIÓN (opción a de la revisión): con `tienda_id` el saldo del banco NO
    entra al total. La cuenta es de la EMPRESA — una sede no "tiene" el banco— y
    no hay dato para repartirla entre sedes. Sumarla completa mientras `get_agenda`
    excluye las obligaciones corporativas (tienda_id NULL) dejaba la serie de la
    sede SISTEMÁTICAMENTE OPTIMISTA: toda la plata del negocio contra solo una
    parte de sus salidas, o sea un quiebre real convertido en verde tranquilizador
    con solo mover el filtro.

    Se descartó la opción (b) —meter las corporativas en la agenda de cada sede—
    porque no hay forma de repartirlas: sumar las dos sedes contaría el arriendo
    dos veces y el total dejaría de cuadrar con la agenda global (la misma razón
    por la que `get_agenda` y `listar_obligaciones` ya las excluyen). Lo que la
    vista por sede ignora se declara aparte, en `advertencias.excluye_corporativas`.

    El saldo declarado se sigue devolviendo aunque no entre al total: es un dato
    real que el dueño tiene que poder ver. `saldo_banco_incluido` dice si suma.
    """
    q = db.query(Tienda).filter(Tienda.activa == True)  # noqa: E712
    if tienda_id is not None:
        q = q.filter(Tienda.id == tienda_id)

    detalle = []
    efectivo = 0.0
    for t in q.order_by(Tienda.id).all():
        monto, origen = _efectivo_en_registradora(db, t.id)
        efectivo += monto
        detalle.append({"tienda_id": t.id, "tienda_nombre": t.nombre,
                        "efectivo": monto, "origen": origen})

    saldo_banco, fecha_banco = _leer_saldo_banco(db)
    desactualizado = (fecha_banco is None
                      or (hoy - fecha_banco).days > DIAS_SALDO_BANCO_VIGENTE)
    incluye_banco = tienda_id is None
    return {
        "efectivo_registradora": round(efectivo, 2),
        "por_tienda": detalle,
        "saldo_banco": saldo_banco,
        "saldo_banco_fecha": fecha_banco,
        "saldo_banco_desactualizado": desactualizado,
        "saldo_banco_incluido": incluye_banco,
        "total": round(efectivo + (saldo_banco if incluye_banco else 0.0), 2),
    }


def _venta_esperada_por_dia_semana(db: Session, hoy: date,
                                   tienda_id: int | None) -> dict:
    """{día de la semana (0=lunes): venta esperada} — MEDIANA, no promedio.

    Un solo día atípico (un evento, una venta corporativa) movería el promedio y
    con él TODAS las proyecciones de ese día de semana. La mediana lo ignora, que
    es exactamente lo que se quiere de una proyección de caja: ser aburrida.

    Ventana: [hoy-56, hoy-1]. Cualquier ventana de 56 días tiene exactamente 8
    muestras de cada día de la semana. HOY queda fuera a propósito: es un día a
    medio vender y hundiría la mediana de su propio día de semana.

    Solo se promedian días CON ventas: un lunes cerrado no entra como 0 (no es
    "vendimos nada", es "no abrimos"), así que no contamina la mediana.

    Sin rezago de cobro: en el POS toda venta se cobra el mismo día — no hay
    cuentas por cobrar que diferir.
    """
    d_utc, h_utc = rango_col_utc(hoy - timedelta(days=SEMANAS_HISTORIA * 7),
                                 hoy - timedelta(days=1))
    q = db.query(Ticket.fecha, Ticket.total).filter(
        Ticket.fecha >= d_utc,
        Ticket.fecha <= h_utc,
        Ticket.estado.notin_(("anulado", "reversado")),
    )
    if tienda_id is not None:
        q = q.filter(Ticket.tienda_id == tienda_id)

    por_dia: dict = {}
    for fecha, total in q.all():
        if fecha is None:
            continue
        # dia_col es Python puro: agrupar por día COLOMBIA en SQL exigiría
        # funciones de fecha distintas en SQLite y en Postgres.
        d = dia_col(fecha)
        por_dia[d] = por_dia.get(d, 0.0) + float(total or 0)

    muestras: dict = {}
    for d, total in por_dia.items():
        muestras.setdefault(d.weekday(), []).append(total)
    return {dow: round(median(vals), 2) for dow, vals in muestras.items()}


def _salidas_por_dia(db: Session, hoy: date, dias: int,
                     tienda_id: int | None) -> dict:
    """{día: plata que hay que pagar ese día} — REUSA `get_agenda`, no la duplica.

    Así la proyección hereda gratis toda la semántica ya probada de la agenda:
    la precedencia COALESCE(programada, vencimiento, recibido+plazo), el saldo en
    vez del total, las obligaciones anuladas y los pagos anulados que devuelven
    saldo. Una segunda implementación de esas reglas se desincronizaría.

    Todo lo que ya se debe se acumula ENTERO en hoy+1: es plata que se debe AHORA.
    Repartirla en el horizonte o dejarla fuera haría desaparecer la mora de la
    proyección justo cuando más importa.

    Lo que vence HOY entra en ese mismo bloque. La serie arranca en hoy+1, así
    que sin esto un pago de hoy no caería en ningún día y se perdería en silencio.

    Los MovimientoCaja egreso NO se restan acá: son pasado y ya están descontados
    dentro del efectivo de la registradora (`_efectivo_en_registradora`).
    """
    agenda = get_agenda(db, desde=None, hasta=hoy + timedelta(days=dias),
                        tienda_id=tienda_id)
    manana = hoy + timedelta(days=1)
    por_dia: dict = {}
    for item in agenda["items"]:
        fecha = item["fecha"]
        if fecha <= hoy:
            fecha = manana
        por_dia[fecha] = round(por_dia.get(fecha, 0.0) + item["monto"], 2)
    return por_dia


def _corporativas_fuera(db: Session, hoy: date, dias: int) -> float:
    """Plata que la vista de UNA sede no muestra: el saldo de las obligaciones
    CORPORATIVAS (tienda_id NULL — arriendo, nómina) que vencen en el horizonte.

    Reusa `get_agenda` global y filtra en Python, igual que `_salidas_por_dia`: la
    semántica de fechas y saldos se hereda en vez de reimplementarse. Las facturas
    nunca son corporativas (FacturaCompra.tienda_id es NOT NULL), así que este
    total sale entero de obligaciones.
    """
    agenda = get_agenda(db, desde=None, hasta=hoy + timedelta(days=dias),
                        tienda_id=None)
    return round(sum(i["monto"] for i in agenda["items"] if i["tienda_id"] is None), 2)


def get_flujo_proyectado(db: Session, dias: int = HORIZONTE_DEFAULT,
                         tienda_id: int | None = None) -> dict:
    """Serie diaria del saldo proyectado y, sobre todo, el PUNTO DE QUIEBRE: el
    primer día en que el saldo cruza a negativo, o None si nunca cruza.

    El punto de quiebre es el único número que el dueño realmente necesita: le
    dice el día en que se queda sin plata ANTES de que pase.

    Con `advertencias` va lo que la serie NO sabe, porque las dos mitades de la
    fórmula no se ganan igual: las ENTRADAS se derivan solas de cada ticket, pero
    las SALIDAS existen únicamente si un humano las tecleó (`recurrencia` todavía
    no genera nada, la compra que no llegó no está, el costo de mercadería aparece
    recién cuando alguien registra la factura). O sea: la PRESENCIA de un punto de
    quiebre significa algo; su AUSENCIA, sola, no significa nada. Estos flags son
    los que le permiten a la pantalla decir "falta información" en vez de vender
    tranquilidad con un verde.
    """
    try:
        dias = int(dias or HORIZONTE_DEFAULT)
    except (TypeError, ValueError):
        dias = HORIZONTE_DEFAULT
    dias = max(1, min(dias, HORIZONTE_MAX))

    hoy = hoy_col()
    caja = _caja_hoy(db, hoy, tienda_id)
    entradas_dow = _venta_esperada_por_dia_semana(db, hoy, tienda_id)
    salidas_dia = _salidas_por_dia(db, hoy, dias, tienda_id)

    serie = []
    saldo = caja["total"]
    quiebre = None
    total_entradas = total_salidas = 0.0
    for n in range(1, dias + 1):
        d = hoy + timedelta(days=n)
        entradas = entradas_dow.get(d.weekday(), 0.0)
        salidas = salidas_dia.get(d, 0.0)
        saldo = round(saldo + entradas - salidas, 2)
        total_entradas += entradas
        total_salidas += salidas
        if quiebre is None and saldo < 0:
            quiebre = d
        serie.append({"fecha": d, "entradas": entradas, "salidas": salidas,
                      "saldo": saldo})

    corporativas_fuera = _corporativas_fuera(db, hoy, dias) if tienda_id else 0.0
    return {
        "hoy": hoy,
        "dias": dias,
        "tienda_id": tienda_id,
        "caja_hoy": caja,
        "serie": serie,
        "punto_de_quiebre": quiebre,
        "dias_hasta_quiebre": (quiebre - hoy).days if quiebre else None,
        "advertencias": {
            # Solo molesta si el banco de verdad entra al total: filtrando por
            # sede no suma, y avisar de un dato que no se usa es ruido.
            "saldo_banco_desactualizado": bool(caja["saldo_banco_incluido"]
                                               and caja["saldo_banco_desactualizado"]),
            # Ni una sola salida en el horizonte: casi siempre significa que nadie
            # cargó las cuentas por pagar, no que no haya nada que pagar.
            "sin_salidas_cargadas": not salidas_dia,
            # Sin muestras no hay venta esperada: la serie asume que no entra nada.
            "sin_historia_ventas": not entradas_dow,
            # La vista de una sede no ve el arriendo ni la nómina corporativa.
            "excluye_corporativas": bool(tienda_id and corporativas_fuera > 0),
            "corporativas_fuera": corporativas_fuera,
        },
        "totales": {
            "entradas": round(total_entradas, 2),
            "salidas": round(total_salidas, 2),
            "saldo_final": saldo,
        },
    }


def guardar_saldo_banco(db: Session, saldo: float, fecha: date,
                        usuario_id: int) -> dict:
    """Persiste la declaración del dueño en `configuracion` (dos claves).

    OJO: este servicio asume que el handler ya rechazó inf/NaN/negativos. Se
    guarda como TEXTO, así que un valor podrido acá envenena toda lectura futura,
    no solo esta escritura — mismo motivo por el que la meta de ventas se valida
    antes de tocar la fila (routers/auth.py).
    """
    valores = {CLAVE_SALDO_BANCO: str(round(float(saldo), 2)),
               CLAVE_SALDO_BANCO_FECHA: fecha.isoformat()}
    filas = {c.clave: c for c in db.query(Configuracion).filter(
        Configuracion.clave.in_(tuple(valores))).all()}
    for clave, valor in valores.items():
        fila = filas.get(clave)
        if fila is not None:
            fila.valor = valor
        else:
            db.add(Configuracion(clave=clave, valor=valor))

    audit.registrar(
        db, accion="declarar_saldo_banco", tabla="configuracion",
        registro_id=None, usuario_id=usuario_id, tienda_id=None,
        datos_despues={"saldo_banco": round(float(saldo), 2),
                       "saldo_banco_fecha": fecha},
    )
    db.commit()
    saldo_guardado, fecha_guardada = _leer_saldo_banco(db)
    return {
        "saldo_banco": saldo_guardado,
        "saldo_banco_fecha": fecha_guardada,
        "saldo_banco_desactualizado": (
            fecha_guardada is None
            or (hoy_col() - fecha_guardada).days > DIAS_SALDO_BANCO_VIGENTE),
    }
