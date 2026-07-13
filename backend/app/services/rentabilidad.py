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
from datetime import date

from sqlalchemy import func, not_, or_

from app.core.tz import dia_col, rango_col_utc
from app.models.models import (
    CajaTurno, FacturaCompra, MovimientoCaja, Ticket, Tienda, TipoMovCajaEnum,
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
