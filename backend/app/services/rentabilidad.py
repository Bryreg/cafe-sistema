"""Rentabilidad (P&L de caja) del negocio.

Cruza las tres fuentes de dinero del sistema, cada una en su base:
  - VENTAS:  Σ Ticket.total (excluye anulados/reversados) — ingreso real.
  - COMPRAS: Σ FacturaCompra.valor_total por fecha de recibido — mercancía que
    ENTRÓ en el período (base de recepción, no de consumo: un mes donde se
    stockea fuerte se ve peor de lo que fue; se documenta en `nota`).
  - GASTOS:  Σ MovimientoCaja tipo=egreso EXCLUYENDO los ligados a facturas de
    proveedor (concepto 'Pago proveedor:%' / 'Ajuste factura%'), que ya están
    contados dentro de COMPRAS — sin esta exclusión se contarían dos veces.

margen_bruto = ventas - compras;  margen_neto = margen_bruto - gastos.
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, not_, or_

from app.core.tz import dia_col, hoy_col, rango_col_utc
from app.models.models import (
    CajaTurno, FacturaCompra, FacturaCompraItem, MovimientoCaja, Producto,
    ProductoInsumo, ProductoDesechable, Ticket, TicketItem, Tienda, TipoMovCajaEnum,
)

# Patrones de concepto que crea services/facturas.py para pagos a proveedor.
# Si esos strings cambian allá, hay que actualizarlos acá (no hay FK).
_CONCEPTOS_COMPRA = ("Pago proveedor:%", "Reverso Pago proveedor:%", "Ajuste factura%")

ESTADOS_ANULADOS = ("anulado", "reversado")


def _mes(dt) -> str:
    return dia_col(dt).strftime("%Y-%m")


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
        )
    )
    if tienda_id is not None:
        q_gastos = q_gastos.filter(CajaTurno.tienda_id == tienda_id)
    gastos_rows = q_gastos.all()

    # ── Agregaciones ──────────────────────────────────────────────────────────
    tot_ventas = round(sum(float(r[1] or 0) for r in ventas_rows), 2)
    tot_compras = round(sum(float(r[1] or 0) for r in compras_rows), 2)
    tot_gastos = round(sum(float(r[1] or 0) for r in gastos_rows), 2)

    por_mes: dict[str, dict] = defaultdict(lambda: {"ventas": 0.0, "compras": 0.0, "gastos": 0.0})
    por_sede: dict[int, dict] = defaultdict(lambda: {"ventas": 0.0, "compras": 0.0, "gastos": 0.0})
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
        },
        "por_mes": [
            {"mes": mes, **_cerrar(vals)}
            for mes, vals in sorted(por_mes.items())
        ],
        "por_sede": [
            {"tienda_id": tid, "tienda": tiendas.get(tid, f"Sede {tid}"), **_cerrar(vals)}
            for tid, vals in sorted(por_sede.items())
        ],
        "gastos_detalle": sorted(
            [{"concepto": c, "total": round(v["total"], 2), "n": v["n"]}
             for c, v in gastos_por_concepto.items()],
            key=lambda x: -x["total"],
        )[:20],
        "nota": (
            "Compras = facturas de proveedor RECIBIDAS en el período (no el consumo real): "
            "un mes donde se stockea fuerte se ve con menos margen del real. "
            "Gastos = egresos de caja manuales; los pagos a proveedor por caja se excluyen "
            "porque ya están dentro de Compras."
        ),
    }


# ─── Margen por producto ──────────────────────────────────────────────────────

def _costos_insumos(db) -> tuple[dict, dict]:
    """Costo por unidad de inventario de cada producto. Prioridad:
      1) Producto.precio_costo (costo OFICIAL fijado a mano) — si existe, MANDA.
      2) promedio ponderado de FacturaCompraItem (lo llena el escaneo / backfill).
    Devuelve (costo por producto, último costo de factura conocido)."""
    rows = (
        db.query(FacturaCompraItem.producto_id, FacturaCompraItem.cantidad,
                 FacturaCompraItem.precio_unitario, FacturaCompra.fecha_recibido)
        .join(FacturaCompra, FacturaCompra.id == FacturaCompraItem.factura_id)
        .filter(FacturaCompraItem.precio_unitario.isnot(None),
                FacturaCompraItem.precio_unitario > 0,
                FacturaCompraItem.cantidad > 0)
        .all()
    )
    acum: dict[int, dict] = defaultdict(lambda: {"plata": 0.0, "cant": 0.0, "ultimo": None, "ultima_fecha": None})
    for pid, cant, precio, fecha in rows:
        a = acum[pid]
        a["plata"] += float(cant) * float(precio)
        a["cant"] += float(cant)
        if a["ultima_fecha"] is None or (fecha and fecha > a["ultima_fecha"]):
            a["ultima_fecha"], a["ultimo"] = fecha, float(precio)
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
    costo_prom, _costo_ult = _costos_insumos(db)
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
    from app.services.factura_ocr import facturas_pendientes_de_costos
    return {
        "productos": out,
        "facturas_pendientes_de_costos": facturas_pendientes_de_costos(db),
        "nota": (
            "Costo = insumos de la receta × costo promedio de compra (de las facturas "
            "leídas). Si a un producto le faltan costos de insumos, el margen que se "
            "muestra es PARCIAL (mayor al real) hasta que se lean más facturas."
        ),
    }
