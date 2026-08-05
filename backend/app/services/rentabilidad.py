"""Rentabilidad (P&L de caja) del negocio.

Cruza las tres fuentes de dinero del sistema, cada una en su base:
  - VENTAS:  Σ Ticket.total (excluye anulados/reversados) — ingreso real.
  - COMPRAS: Σ FacturaCompra.valor_total por fecha de recibido — mercancía que
    ENTRÓ en el período (base de recepción, no de consumo: un mes donde se
    stockea fuerte se ve peor de lo que fue; se documenta en `nota`).
  - GASTOS:  dos mitades que se suman. (a) Σ MovimientoCaja tipo=egreso EXCLUYENDO
    los ligados a facturas de proveedor (concepto 'Pago proveedor:%' /
    'Ajuste factura%'), que ya están contados dentro de COMPRAS, y EXCLUYENDO los
    ya adoptados por el módulo Costos; (b) Σ Obligacion.monto por fecha_devengo.
    Adoptar un egreso lo pasa de (a) a (b) sin cambiar el total: sin cualquiera de
    las dos exclusiones, la misma plata se contaría dos veces.

margen_bruto = ventas - compras;  margen_neto = margen_bruto - gastos.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, not_, or_

from app.core.tz import dia_col, hora_col, hoy_col, rango_col_utc
from app.models.models import (
    CajaTurno, Combo, CostoCategoria, FacturaCompra, FacturaCompraItem,
    MovimientoCaja, Obligacion, Pago, Producto,
    ProductoInsumo, ProductoDesechable, Ticket, TicketItem,
    TicketItemComboSeleccion, Tienda, TipoMovCajaEnum,
)

# Patrones de concepto que crea services/facturas.py para pagos a proveedor.
# Si esos strings cambian allá, hay que actualizarlos acá (no hay FK).
_CONCEPTOS_COMPRA = ("Pago proveedor:%", "Reverso Pago proveedor:%", "Ajuste factura%")

ESTADOS_ANULADOS = ("anulado", "reversado")


def _mes(dt) -> str:
    return dia_col(dt).strftime("%Y-%m")


def _costo_unitario_productos(db) -> dict[int, float]:
    """Costo por unidad de VENTA de cada producto (para el COGS teórico).
    Prioridad: precio_costo oficial > receta (Σ insumos × costo) > costo de
    compra (reventa). Los granel-sin-receta quedan afuera (costo por gr vs
    venta por porción no son comparables)."""
    costo_prom, _ = _costos_insumos(db)
    recetas: dict[int, list] = defaultdict(list)
    for pi in db.query(ProductoInsumo).all():
        recetas[pi.producto_id].append(pi)
    out: dict[int, float] = {}
    for p in db.query(Producto).all():
        if p.precio_costo is not None and float(p.precio_costo) > 0:
            out[p.id] = float(p.precio_costo)
            continue
        ings = recetas.get(p.id)
        if ings:
            c, alguno = 0.0, False
            for pi in ings:
                ci = costo_prom.get(pi.insumo_id)
                if ci is not None:
                    c += float(pi.cantidad) * ci
                    alguno = True
            if alguno:
                out[p.id] = c
            continue
        um = (p.unidad_medida or "").lower()
        if um not in ("gr", "g", "gramos", "ml") and p.id in costo_prom:
            out[p.id] = costo_prom[p.id]
    return out


def get_rentabilidad(db, desde: date, hasta: date, tienda_id: int | None = None) -> dict:
    d_utc, h_utc = rango_col_utc(desde, hasta)
    tiendas = {t.id: t.nombre for t in db.query(Tienda).all()}

    # ── Ventas (tickets no anulados) ──────────────────────────────────────────
    q_ventas = db.query(Ticket.fecha, Ticket.total, Ticket.tienda_id).filter(
        Ticket.estado.notin_(ESTADOS_ANULADOS),
        Ticket.fecha >= d_utc,
        Ticket.fecha <= h_utc,
    )
    if tienda_id is not None:
        q_ventas = q_ventas.filter(Ticket.tienda_id == tienda_id)
    ventas_rows = q_ventas.all()

    # ── Compras (facturas de proveedor, por fecha de recibido) ───────────────
    fc_fecha = func.coalesce(FacturaCompra.fecha_recibido, FacturaCompra.fecha_registro)
    q_compras = db.query(fc_fecha, FacturaCompra.valor_total, FacturaCompra.tienda_id).filter(
        fc_fecha >= d_utc, fc_fecha <= h_utc,
    )
    if tienda_id is not None:
        q_compras = q_compras.filter(FacturaCompra.tienda_id == tienda_id)
    compras_rows = q_compras.all()

    # ── Gastos operativos (egresos de caja NO ligados a compras) ─────────────
    # Ligado a compra = tiene factura_id (vínculo estructural) o, para movimientos
    # anteriores a esa columna, el concepto reservado que escribe services/facturas.
    #
    # Y ligado a una obligación = ya fue ADOPTADO (Fase 3): el egreso sigue vivo en
    # caja pero su plata ahora se cuenta abajo, como obligación devengada. Sin esta
    # exclusión el mismo gasto se contaría dos veces. Va como SUBCONSULTA y no como
    # lista de ids: un `IN (...)` explícito revienta el tope de variables de SQLite
    # (mismo patrón deliberado que get_attach_producto).
    adoptados = (
        db.query(Pago.movimiento_caja_id)
        .filter(Pago.movimiento_caja_id.isnot(None), Pago.anulado.is_(False))
        .distinct().subquery()
    )
    q_gastos = (
        db.query(MovimientoCaja.fecha, MovimientoCaja.valor,
                 MovimientoCaja.concepto, CajaTurno.tienda_id)
        .join(CajaTurno, MovimientoCaja.caja_turno_id == CajaTurno.id)
        .filter(
            MovimientoCaja.tipo == TipoMovCajaEnum.egreso,
            MovimientoCaja.fecha >= d_utc,
            MovimientoCaja.fecha <= h_utc,
            MovimientoCaja.factura_id.is_(None),
            not_(or_(*[MovimientoCaja.concepto.like(p) for p in _CONCEPTOS_COMPRA])),
            MovimientoCaja.id.notin_(db.query(adoptados.c.movimiento_caja_id)),
        )
    )
    if tienda_id is not None:
        q_gastos = q_gastos.filter(CajaTurno.tienda_id == tienda_id)
    gastos_rows = q_gastos.all()

    # ── Obligaciones devengadas (módulo Costos) ──────────────────────────────
    # Término NUEVO del gasto, en QUERY SEPARADA a propósito: la de arriba hace
    # `join(CajaTurno)` y filtra sede por `CajaTurno.tienda_id`, y una obligación
    # corporativa (arriendo, nómina) tiene tienda_id NULL y ningún turno — ese join
    # la BORRARÍA. Además `fecha_devengo` es Date, o sea fecha de NEGOCIO ya
    # resuelta: se compara contra desde/hasta y NUNCA contra d_utc/h_utc, que son
    # instantes UTC para columnas de instante.
    q_oblig = (
        db.query(Obligacion.fecha_devengo, Obligacion.monto,
                 Obligacion.tienda_id, CostoCategoria.nombre, CostoCategoria.grupo)
        .join(CostoCategoria, CostoCategoria.id == Obligacion.categoria_id)
        .filter(
            Obligacion.anulada.is_(False),
            Obligacion.fecha_devengo >= desde,
            Obligacion.fecha_devengo <= hasta,
        )
    )
    if tienda_id is not None:
        # Con sede filtrada las corporativas NO se cuelan ni se prorratean: repartirlas
        # las duplicaría y Σ por_sede dejaría de dar el global.
        q_oblig = q_oblig.filter(Obligacion.tienda_id == tienda_id)
    oblig_rows = q_oblig.all()

    # ── COGS teórico: lo VENDIDO × costo de receta (base de consumo, no de
    # recepción). Da el margen bruto real del período sin la distorsión de los
    # días en que se stockea fuerte. Se acompaña de pct_venta_costeada para no
    # leer el número como exacto si hay productos sin costo.
    costo_unit = _costo_unitario_productos(db)
    # Líneas de combo: el producto de la línea es el SOMBRA (Combo.producto_id),
    # sin costo propio — su costo real son los COMPONENTES elegidos
    # (TicketItemComboSeleccion), agregados más abajo.
    sombras_combo = {pid for (pid,) in db.query(Combo.producto_id).all()}
    q_items = (
        db.query(TicketItem.producto_id,
                 func.coalesce(func.sum(TicketItem.cantidad), 0),
                 func.coalesce(func.sum(TicketItem.subtotal), 0.0))
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
        .group_by(TicketItem.producto_id)
    )
    if tienda_id is not None:
        q_items = q_items.filter(Ticket.tienda_id == tienda_id)
    cogs_teorico = 0.0
    venta_costeada = 0.0
    venta_items = 0.0
    for pid, cant, subtotal in q_items.all():
        venta_items += float(subtotal or 0)
        if pid in sombras_combo:
            # La venta del combo cuenta como costeada con su costo agregado
            # (componentes × costo unitario, sumado abajo).
            venta_costeada += float(subtotal or 0)
            continue
        c = costo_unit.get(pid)
        if c is not None:
            cogs_teorico += float(cant or 0) * c
            venta_costeada += float(subtotal or 0)

    # COGS de combos: consumo real de componentes en el rango × costo unitario
    # (la cantidad de la selección es POR combo → total = cantidad × línea).
    q_sel = (
        db.query(TicketItemComboSeleccion.producto_id,
                 func.coalesce(func.sum(TicketItemComboSeleccion.cantidad * TicketItem.cantidad), 0))
        .join(TicketItem, TicketItem.id == TicketItemComboSeleccion.ticket_item_id)
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
        .group_by(TicketItemComboSeleccion.producto_id)
    )
    if tienda_id is not None:
        q_sel = q_sel.filter(Ticket.tienda_id == tienda_id)
    for pid, cant in q_sel.all():
        c = costo_unit.get(pid)
        if c is not None:
            cogs_teorico += float(cant or 0) * c

    # ── Agregaciones ──────────────────────────────────────────────────────────
    tot_ventas = round(sum(float(r[1] or 0) for r in ventas_rows), 2)
    tot_compras = round(sum(float(r[1] or 0) for r in compras_rows), 2)
    # El gasto del período son las DOS mitades: lo que sigue suelto en caja y lo ya
    # adoptado como obligación. Adoptar mueve plata de una a la otra sin cambiar el total.
    tot_gastos = round(sum(float(r[1] or 0) for r in gastos_rows)
                       + sum(float(r[1] or 0) for r in oblig_rows), 2)

    por_mes: dict[str, dict] = defaultdict(lambda: {"ventas": 0.0, "compras": 0.0, "gastos": 0.0})
    # Clave int o None: None = gasto CORPORATIVO (sin sede), no un dato faltante.
    por_sede: dict = defaultdict(lambda: {"ventas": 0.0, "compras": 0.0, "gastos": 0.0})
    for fecha, total, tid in ventas_rows:
        por_mes[_mes(fecha)]["ventas"] += float(total or 0)
        por_sede[tid]["ventas"] += float(total or 0)
    for fecha, total, tid in compras_rows:
        por_mes[_mes(fecha)]["compras"] += float(total or 0)
        por_sede[tid]["compras"] += float(total or 0)
    gastos_por_concepto: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "n": 0})
    for fecha, valor, concepto, tid in gastos_rows:
        por_mes[_mes(fecha)]["gastos"] += float(valor or 0)
        por_sede[tid]["gastos"] += float(valor or 0)
        g = gastos_por_concepto[(concepto or "(sin concepto)").strip()]
        g["total"] += float(valor or 0)
        g["n"] += 1
    # Las obligaciones agrupan por NOMBRE DE CATEGORÍA (no por texto libre): a medida
    # que se adoptan egresos, el bloque de conceptos sueltos se vacía solo.
    # `fecha_devengo` ya es fecha Colombia: se formatea directo, sin pasar por _mes
    # (que convierte de UTC y espera un datetime).
    for devengo, monto, tid, categoria, _grupo in oblig_rows:
        por_mes[devengo.strftime("%Y-%m")]["gastos"] += float(monto or 0)
        por_sede[tid]["gastos"] += float(monto or 0)
        g = gastos_por_concepto[(categoria or "(sin categoría)").strip()]
        g["total"] += float(monto or 0)
        g["n"] += 1

    # ── Cobertura de costos FIJOS (arriendo, nómina, servicios, impuestos) ────
    # Campo ADITIVO: no entra en ninguna fórmula, solo declara si el margen neto
    # de este período está mirando los costos fijos o no. Sin esto la pantalla no
    # puede distinguir "el negocio no tiene costos fijos" de "nadie los cargó", y
    # un semáforo en verde sobre el segundo caso es una mentira tranquilizadora.
    fijos_rows = [r for r in oblig_rows if (r[4] or "") == "fijo"]
    costos_fijos_devengados = round(sum(float(r[1] or 0) for r in fijos_rows), 2)

    def _cerrar(d: dict) -> dict:
        v, c, g = round(d["ventas"], 2), round(d["compras"], 2), round(d["gastos"], 2)
        neto = round(v - c - g, 2)
        return {"ventas": v, "compras": c, "gastos": g,
                "margen_neto": neto,
                "pct_margen_neto": round(neto / v * 100, 1) if v > 0 else None}

    margen_bruto = round(tot_ventas - tot_compras, 2)
    margen_neto = round(margen_bruto - tot_gastos, 2)

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "resumen": {
            "ventas": tot_ventas,
            "compras": tot_compras,
            "gastos": tot_gastos,
            "margen_bruto": margen_bruto,
            "margen_neto": margen_neto,
            "pct_margen_bruto": round(margen_bruto / tot_ventas * 100, 1) if tot_ventas > 0 else None,
            "pct_margen_neto": round(margen_neto / tot_ventas * 100, 1) if tot_ventas > 0 else None,
            "n_tickets": len(ventas_rows),
            "n_facturas": len(compras_rows),
            # Base de CONSUMO (complementa a compras, que es base de recepción):
            "cogs_teorico": round(cogs_teorico, 2),
            "margen_bruto_real": round(tot_ventas - cogs_teorico, 2),
            "pct_margen_bruto_real": round((tot_ventas - cogs_teorico) / tot_ventas * 100, 1) if tot_ventas > 0 else None,
            "brecha_compras": round(tot_compras - cogs_teorico, 2),
            "pct_venta_costeada": round(venta_costeada / venta_items * 100, 1) if venta_items > 0 else None,
            # Cobertura de costos fijos del período (ADITIVO — ya está DENTRO de
            # `gastos` y de `margen_neto`; se expone aparte solo para que la UI
            # sepa si puede emitir un veredicto o tiene que pedir el dato).
            "costos_fijos_devengados": costos_fijos_devengados,
            "n_costos_fijos": len(fijos_rows),
            "tiene_costos_fijos": bool(fijos_rows),
        },
        "por_mes": [
            {"mes": mes, **_cerrar(vals)}
            for mes, vals in sorted(por_mes.items())
        ],
        "por_sede": [
            # tienda_id None es un gasto CORPORATIVO (arriendo, nómina): fila propia
            # "Corporativo", nunca el literal "Sede None". Va primero y ordena aparte
            # porque None no se puede comparar con un int.
            {"tienda_id": tid,
             "tienda": "Corporativo" if tid is None else tiendas.get(tid, f"Sede {tid}"),
             **_cerrar(vals)}
            for tid, vals in sorted(por_sede.items(),
                                    key=lambda kv: (kv[0] is not None, kv[0] or 0))
        ],
        "gastos_detalle": sorted(
            [{"concepto": c, "total": round(v["total"], 2), "n": v["n"]}
             for c, v in gastos_por_concepto.items()],
            key=lambda x: -x["total"],
        )[:20],
        "nota": (
            "Compras = facturas de proveedor RECIBIDAS en el período (no el consumo real): "
            "un mes donde se stockea fuerte se ve con menos margen del real. "
            "Gastos = egresos de caja manuales + obligaciones devengadas (arriendo, nómina, "
            "servicios); los pagos a proveedor por caja se excluyen porque ya están dentro "
            "de Compras, y un egreso adoptado cuenta como obligación, nunca dos veces."
        ),
    }


# ─── Margen por producto ──────────────────────────────────────────────────────

def _costos_insumos(db) -> tuple[dict, dict]:
    """Costo por unidad de inventario de cada producto. Prioridad:
      1) Producto.precio_costo (costo OFICIAL fijado a mano) — si existe, MANDA.
      2) promedio ponderado de FacturaCompraItem (lo llena el escaneo / backfill).
    Devuelve (costo por producto, último costo de factura conocido)."""
    # fecha_recibido puede ser NULL (columna agregada por ALTER) → caer a
    # fecha_registro, igual que get_rentabilidad, para no perder esas filas al
    # buscar el "último precio".
    fc_fecha = func.coalesce(FacturaCompra.fecha_recibido, FacturaCompra.fecha_registro)
    rows = (
        db.query(FacturaCompraItem.producto_id, FacturaCompraItem.cantidad,
                 FacturaCompraItem.precio_unitario, fc_fecha, FacturaCompraItem.id)
        .join(FacturaCompra, FacturaCompra.id == FacturaCompraItem.factura_id)
        .filter(FacturaCompraItem.precio_unitario.isnot(None),
                FacturaCompraItem.precio_unitario > 0,
                FacturaCompraItem.cantidad > 0)
        .all()
    )
    acum: dict[int, dict] = defaultdict(lambda: {"plata": 0.0, "cant": 0.0, "ultimo": None, "ultima_clave": None})
    for pid, cant, precio, fecha, item_id in rows:
        a = acum[pid]
        a["plata"] += float(cant) * float(precio)
        a["cant"] += float(cant)
        # Último precio = factura más reciente; desempate ESTABLE por id de ítem
        # (dos facturas del mismo día no dependen del orden arbitrario del SELECT).
        clave = (fecha or datetime.min, item_id or 0)
        if a["ultima_clave"] is None or clave > a["ultima_clave"]:
            a["ultima_clave"], a["ultimo"] = clave, float(precio)
    costo = {pid: a["plata"] / a["cant"] for pid, a in acum.items() if a["cant"] > 0}
    ultimo = {pid: a["ultimo"] for pid, a in acum.items() if a["ultimo"] is not None}
    # El costo oficial a mano pisa el promedio de facturas (lecturas con ruido).
    for pid, pc in db.query(Producto.id, Producto.precio_costo).filter(
            Producto.precio_costo.isnot(None), Producto.precio_costo > 0).all():
        costo[pid] = float(pc)
    return costo, ultimo


def get_rentabilidad_productos(db) -> dict:
    """Margen por producto de venta: precio_venta vs costo de sus insumos.
    - Producto con receta (ProductoInsumo): costo = Σ cantidad_insumo × costo_insumo.
    - Producto sin receta (reventa): costo = su propio costo de compra.
    Los costos salen de las facturas escaneadas; lo que falte se reporta."""
    costo_prom, costo_ult = _costos_insumos(db)
    productos = db.query(Producto).all()
    por_id = {p.id: p for p in productos}

    recetas: dict[int, list] = defaultdict(list)
    for pi in db.query(ProductoInsumo).all():
        recetas[pi.producto_id].append(pi)

    # Desechables (capa de costo aparte, NO descuenta inventario). Se suman al
    # costo de receta para dar el "costo completo" del producto para llevar.
    desechables: dict[int, list] = defaultdict(list)
    for pd in db.query(ProductoDesechable).all():
        desechables[pd.producto_id].append(pd)

    # Ventas últimos 30 días (Colombia) para ordenar por relevancia real.
    d_utc, h_utc = rango_col_utc(hoy_col() - timedelta(days=29), hoy_col())
    ventas_rows = (
        db.query(TicketItem.producto_id,
                 func.coalesce(func.sum(TicketItem.cantidad), 0),
                 func.coalesce(func.sum(TicketItem.subtotal), 0.0))
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
        .group_by(TicketItem.producto_id)
        .all()
    )
    ventas_30d = {pid: {"unidades": int(u or 0), "plata": float(pl or 0)}
                  for pid, u, pl in ventas_rows}

    out = []
    for p in productos:
        precio_venta = float(p.precio_venta or 0)
        if precio_venta <= 0:
            continue  # no se vende en el POS: es insumo puro
        ingredientes = recetas.get(p.id)
        faltantes: list[str] = []
        if ingredientes:
            tipo = "receta"
            costo = 0.0
            alguno = False
            for pi in ingredientes:
                c = costo_prom.get(pi.insumo_id)
                if c is None:
                    ins = por_id.get(pi.insumo_id)
                    faltantes.append(ins.nombre if ins else f"insumo {pi.insumo_id}")
                else:
                    costo += float(pi.cantidad) * c
                    alguno = True
            if not alguno:
                costo = None
        else:
            tipo = "reventa"
            um = (p.unidad_medida or "").lower()
            if um in ("gr", "g", "gramos", "ml"):
                # Se vende a granel sin receta: el costo guardado es POR GR/ML y
                # el precio de venta es por porción — compararlos daría un margen
                # sin sentido. Necesita receta para costearse.
                costo = None
                faltantes.append("definí la receta (producto a granel)")
            else:
                costo = costo_prom.get(p.id)
                if costo is None:
                    faltantes.append(p.nombre)

        # Costo OFICIAL del producto (Producto.precio_costo, fijado a mano) MANDA sobre
        # la receta y el promedio de facturas. Sirve para productos COMPRADOS hechos que
        # están mal cargados como receta (ej. omelettes con una receta errónea de "1
        # almojábana"): así el margen sale real sin tener que tocar la receta del POS.
        if p.precio_costo is not None and float(p.precio_costo) > 0:
            costo = float(p.precio_costo)
            faltantes = []

        # Desechables: capa de costo aparte (vaso/tapa/servilleta/azúcar…) que NO
        # descuenta inventario. Se suma al costo de receta para el "costo completo"
        # del producto para llevar. Solo aplica a lo que tenga desechables cargados.
        lista_desech = desechables.get(p.id, [])
        costo_desech = 0.0
        desech_faltan: list[str] = []
        for pd in lista_desech:
            c = costo_prom.get(pd.insumo_id)
            if c is None:
                ins = por_id.get(pd.insumo_id)
                desech_faltan.append(ins.nombre if ins else f"insumo {pd.insumo_id}")
            else:
                costo_desech += float(pd.cantidad) * c
        tiene_desech = bool(lista_desech)
        if costo is not None and tiene_desech:
            costo_full = round(costo + costo_desech, 2)
            margen_full = round(precio_venta - costo_full, 2)
        else:
            costo_full = round(costo, 2) if costo is not None else None
            margen_full = round(precio_venta - costo, 2) if costo is not None else None

        v = ventas_30d.get(p.id, {"unidades": 0, "plata": 0.0})
        completo = costo is not None and not faltantes
        margen = round(precio_venta - costo, 2) if costo is not None else None
        out.append({
            "producto_id": p.id,
            "nombre": p.nombre,
            "categoria": getattr(p.categoria, "value", None) or str(p.categoria or ""),
            "tipo": tipo,
            "precio_venta": round(precio_venta, 2),
            "costo": round(costo, 2) if costo is not None else None,
            "costo_completo": completo,
            "insumos_sin_costo": faltantes,
            "margen": margen,
            "pct_margen": round(margen / precio_venta * 100, 1) if margen is not None else None,
            # Costo completo (receta + desechables para llevar). costo_desechables
            # es None si al producto no se le cargó ningún desechable todavía.
            "costo_desechables": round(costo_desech, 2) if tiene_desech else None,
            "costo_con_desechables": costo_full,
            "desechables_sin_costo": desech_faltan,
            "margen_con_desechables": margen_full,
            "pct_margen_con_desechables": round(margen_full / precio_venta * 100, 1) if margen_full is not None else None,
            "unidades_30d": v["unidades"],
            "venta_30d": round(v["plata"], 2),
        })

    out.sort(key=lambda x: -x["venta_30d"])

    # ── Alertas de costo: el ÚLTIMO precio de factura de un insumo supera en
    # >10% al costo con el que hoy se calculan los márgenes (promedio u oficial).
    # Es la señal temprana de "este insumo está subiendo" — palanca central de
    # la estrategia de ganar por costo. Se dimensiona por la venta afectada.
    usa_insumo: dict[int, set] = defaultdict(set)
    for prod_id, ings in recetas.items():
        for pi in ings:
            usa_insumo[pi.insumo_id].add(prod_id)
    alertas_costo = []
    for iid, ultimo in costo_ult.items():
        usado = costo_prom.get(iid)
        if not usado or usado <= 0 or ultimo <= usado * 1.10:
            continue
        afectados = set(usa_insumo.get(iid, set()))
        ins = por_id.get(iid)
        if ins is not None and float(ins.precio_venta or 0) > 0:
            afectados.add(iid)  # el insumo también se vende directo (reventa)
        if not afectados:
            continue
        venta_afectada = sum(ventas_30d.get(pid, {}).get("plata", 0.0) for pid in afectados)
        alertas_costo.append({
            "insumo_id": iid,
            "nombre": ins.nombre if ins else f"insumo {iid}",
            "unidad_medida": ins.unidad_medida if ins else None,
            "costo_usado": round(usado, 2),
            "costo_ultimo": round(ultimo, 2),
            "pct_suba": round((ultimo / usado - 1) * 100, 1),
            "productos_afectados": sorted(
                (por_id[pid].nombre for pid in afectados if pid in por_id))[:6],
            "venta_30d_afectada": round(venta_afectada, 2),
        })
    alertas_costo.sort(key=lambda a: -a["venta_30d_afectada"])

    from app.services.factura_ocr import facturas_pendientes_de_costos
    from app.services.producto_alias import contar_aliases
    return {
        "productos": out,
        "alertas_costo": alertas_costo[:10],
        "facturas_pendientes_de_costos": facturas_pendientes_de_costos(db),
        # Fase 2 del OCR: cuántos aliases proveedor→producto conoce el sistema
        # (visible en "Salud de datos").
        "aliases_conocidos": contar_aliases(db),
        "nota": (
            "Costo = insumos de la receta × costo promedio de compra (de las facturas "
            "leídas). Si a un producto le faltan costos de insumos, el margen que se "
            "muestra es PARCIAL (mayor al real) hasta que se lean más facturas."
        ),
    }


# ─── Pulso: cómo vamos + comportamiento de compra ────────────────────────────

def get_pulso(db) -> dict:
    """El vistazo de 10 segundos + el comportamiento real de compra:
      - mes en curso vs mes anterior EN LA MISMA VENTANA de días (día 1 → hoy),
        para que la comparación a mitad de mes sea justa;
      - ventas diarias del mes (sparkline);
      - attach real y pares por CO-OCURRENCIA de tickets (últimos 30 días);
      - ventas por hora Colombia (daypart) para ubicar pico y valle;
      - top movers: productos subiendo/bajando vs los 30 días anteriores.
    Ventana fija y ambas sedes: es el pulso global del negocio."""
    hoy = hoy_col()
    ini_act = hoy.replace(day=1)
    fin_ant_mes = ini_act - timedelta(days=1)
    ini_ant = fin_ant_mes.replace(day=1)
    fin_ant = ini_ant.replace(day=min(hoy.day, fin_ant_mes.day))

    def _ventana(desde: date, hasta: date) -> tuple[dict, list]:
        d, h = rango_col_utc(desde, hasta)
        rows = (db.query(Ticket.fecha, Ticket.total)
                .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                        Ticket.fecha >= d, Ticket.fecha <= h).all())
        ventas = sum(float(r[1] or 0) for r in rows)
        n = len(rows)
        return ({"ventas": round(ventas, 2), "tickets": n,
                 "ticket_promedio": round(ventas / n, 0) if n else None}, rows)

    actual, rows_act = _ventana(ini_act, hoy)
    anterior, _ = _ventana(ini_ant, fin_ant)

    por_dia: dict = defaultdict(float)
    for f, t in rows_act:
        por_dia[dia_col(f)] += float(t or 0)
    ventas_diarias = [{"dia": d.isoformat(), "ventas": round(v, 2)}
                      for d, v in sorted(por_dia.items())]

    # ── Comportamiento (30 días): attach y pares reales ──────────────────────
    d30, h30 = rango_col_utc(hoy - timedelta(days=29), hoy)
    info_prod = {p.id: (p.nombre, getattr(p.categoria, "value", None) or str(p.categoria or ""))
                 for p in db.query(Producto).all()}
    items = (db.query(TicketItem.ticket_id, TicketItem.producto_id)
             .join(Ticket, Ticket.id == TicketItem.ticket_id)
             .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                     Ticket.fecha >= d30, Ticket.fecha <= h30).all())
    por_ticket: dict = defaultdict(set)
    for tid, pid in items:
        por_ticket[tid].add(pid)
    # Tickets con combo: la línea apunta al SOMBRA (Combo.producto_id), de
    # categoría inerte. Todo combo incluye bebida + acompañamiento/torta, así
    # que para el attach cuenta como bebida CON pastelería.
    sombras_combo = {pid for (pid,) in db.query(Combo.producto_id).all()}
    con_bebida = con_beb_pasteleria = con_beb_addon = 0
    pares: Counter = Counter()
    for pids in por_ticket.values():
        cats = {info_prod.get(p, ("", ""))[1] for p in pids}
        if pids & sombras_combo:
            cats |= {"bebida", "pasteleria"}
        if "bebida" in cats:
            con_bebida += 1
            if "pasteleria" in cats:
                con_beb_pasteleria += 1
            if "porciones" in cats:
                con_beb_addon += 1
        lp = sorted(pids)
        for i in range(len(lp)):
            for j in range(i + 1, len(lp)):
                pares[(lp[i], lp[j])] += 1
    top_pares = []
    for (a, b), c in pares.most_common(40):
        if c < 3:
            break
        na, ca = info_prod.get(a, (f"#{a}", ""))
        nb, cb = info_prod.get(b, (f"#{b}", ""))
        top_pares.append({"a": na, "a_id": a, "a_cat": ca,
                          "b": nb, "b_id": b, "b_cat": cb, "veces": c})
        if len(top_pares) >= 12:
            break
    attach = {
        "tickets_con_bebida": con_bebida,
        "pct_bebida_con_pasteleria": round(con_beb_pasteleria / con_bebida * 100, 1) if con_bebida else None,
        "pct_bebida_con_addon": round(con_beb_addon / con_bebida * 100, 1) if con_bebida else None,
    }

    # ── Daypart: por hora Colombia (30 días) ─────────────────────────────────
    rows30 = (db.query(Ticket.fecha, Ticket.total)
              .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                      Ticket.fecha >= d30, Ticket.fecha <= h30).all())
    horas: dict = defaultdict(lambda: {"tickets": 0, "ventas": 0.0})
    for f, t in rows30:
        e = horas[hora_col(f)]
        e["tickets"] += 1
        e["ventas"] += float(t or 0)
    daypart = [{"hora": h, "tickets": v["tickets"], "ventas": round(v["ventas"], 2)}
               for h, v in sorted(horas.items())]

    # ── Top movers: 30 días vs los 30 anteriores ─────────────────────────────
    def _ventas_prod(desde: date, hasta: date) -> dict:
        d, h = rango_col_utc(desde, hasta)
        rows = (db.query(TicketItem.producto_id,
                         func.coalesce(func.sum(TicketItem.cantidad), 0),
                         func.coalesce(func.sum(TicketItem.subtotal), 0.0))
                .join(Ticket, Ticket.id == TicketItem.ticket_id)
                .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                        Ticket.fecha >= d, Ticket.fecha <= h)
                .group_by(TicketItem.producto_id).all())
        return {pid: (int(u or 0), float(v or 0)) for pid, u, v in rows}

    act30 = _ventas_prod(hoy - timedelta(days=29), hoy)
    ant30 = _ventas_prod(hoy - timedelta(days=59), hoy - timedelta(days=30))
    movers = []
    for pid in set(act30) | set(ant30):
        ua, va = act30.get(pid, (0, 0.0))
        ub, vb = ant30.get(pid, (0, 0.0))
        dv = va - vb
        if abs(dv) < 30000:  # ruido: cambios menores a $30k/mes no son señal
            continue
        movers.append({"producto_id": pid,
                       "nombre": info_prod.get(pid, (f"#{pid}", ""))[0],
                       "unidades": ua, "unidades_prev": ub,
                       "venta": round(va, 2), "venta_prev": round(vb, 2),
                       "delta_venta": round(dv, 2)})
    subiendo = sorted((m for m in movers if m["delta_venta"] > 0),
                      key=lambda m: -m["delta_venta"])[:5]
    bajando = sorted((m for m in movers if m["delta_venta"] < 0),
                     key=lambda m: m["delta_venta"])[:5]

    return {
        "mes_actual": {**actual, "desde": ini_act.isoformat(), "hasta": hoy.isoformat()},
        "mes_anterior": {**anterior, "desde": ini_ant.isoformat(), "hasta": fin_ant.isoformat()},
        "ventas_diarias": ventas_diarias,
        "attach": attach,
        "top_pares": top_pares,
        "daypart": daypart,
        "top_movers": {"subiendo": subiendo, "bajando": bajando},
        "nota": ("Comparación mes en curso vs mes anterior en la MISMA ventana de días. "
                 "Attach, pares, daypart y movers usan los últimos 30 días, ambas sedes."),
    }


def get_attach_producto(db, producto_id: int, dias: int = 30) -> dict:
    """Attach REAL de un producto: en cuántos tickets aparece, con qué se vende
    junto y en qué proporción sale acompañado de bebida.

    Existe porque el `top_pares` del pulso se queda con las 12 combinaciones más
    frecuentes de TODA la carta: un par poco frecuente (croissant + americano)
    queda invisible aunque el sistema sí lo calcule. Para decidir un combo hace
    falta el número exacto de ESE par, no el ranking general.

    `tickets_multiples` (2+ unidades del mismo producto en un ticket) es clave para
    combos que venden de a dos: si mucha gente ya se lleva dos, un combo que las
    empaqueta con descuento canibaliza en vez de sumar.
    """
    dias = max(1, min(int(dias or 30), 365))
    hoy = hoy_col()
    d_utc, h_utc = rango_col_utc(hoy - timedelta(days=dias - 1), hoy)

    prod = db.query(Producto).filter_by(id=producto_id).first()
    if not prod:
        from fastapi import HTTPException
        raise HTTPException(404, "Producto no encontrado")

    # Los tickets que contienen el producto, como SUBCONSULTA (no como lista de IDs):
    # un producto muy vendido en una ventana larga da miles de tickets y una lista
    # enlazada revienta el tope de variables de SQLite.
    sub = (db.query(TicketItem.ticket_id)
           .join(Ticket, Ticket.id == TicketItem.ticket_id)
           .filter(TicketItem.producto_id == producto_id,
                   Ticket.estado.notin_(ESTADOS_ANULADOS),
                   Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
           .distinct().subquery())

    filas = (db.query(TicketItem.ticket_id, TicketItem.producto_id, TicketItem.cantidad)
             .filter(TicketItem.ticket_id.in_(db.query(sub.c.ticket_id))).all())
    por_ticket: dict = defaultdict(lambda: defaultdict(float))
    for tid, pid, cant in filas:
        por_ticket[tid][pid] += float(cant or 0)

    if not por_ticket:
        return {"producto": {"id": prod.id, "nombre": prod.nombre,
                             "categoria": getattr(prod.categoria, "value", None) or str(prod.categoria or "")},
                "dias": dias, "tickets": 0, "unidades": 0, "tickets_multiples": 0,
                "con_bebida": 0, "pct_con_bebida": None, "sin_bebida": 0,
                "por_categoria": {}, "pares": []}

    info = {p.id: (p.nombre, getattr(p.categoria, "value", None) or str(p.categoria or ""))
            for p in db.query(Producto).all()}

    unidades = 0.0
    multiples = 0
    con_bebida = 0
    cats: Counter = Counter()
    pares: Counter = Counter()
    for pids in por_ticket.values():
        propia = pids.get(producto_id, 0)
        unidades += propia
        if propia >= 2:
            multiples += 1
        acompanantes = [p for p in pids if p != producto_id]
        cats_ticket = {info.get(p, ("", ""))[1] for p in acompanantes}
        if "bebida" in cats_ticket:
            con_bebida += 1
        for c in cats_ticket:
            if c:
                cats[c] += 1
        for p in acompanantes:
            pares[p] += 1

    n = len(por_ticket)
    return {
        "producto": {"id": prod.id, "nombre": prod.nombre,
                     "categoria": getattr(prod.categoria, "value", None) or str(prod.categoria or "")},
        "dias": dias,
        "tickets": n,
        "unidades": round(unidades, 2),
        "tickets_multiples": multiples,
        "con_bebida": con_bebida,
        "pct_con_bebida": round(con_bebida / n * 100, 1) if n else None,
        "sin_bebida": n - con_bebida,
        "por_categoria": {c: v for c, v in cats.most_common()},
        "pares": [{"producto_id": p, "nombre": info.get(p, (f"#{p}", ""))[0],
                   "categoria": info.get(p, ("", ""))[1], "veces": v,
                   "pct": round(v / n * 100, 1)}
                  for p, v in pares.most_common()],
    }
