"""Siigo Nube API client — authentication + invoice fetching."""

import time
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date as date_type
from app.config import settings

SIIGO_AUTH_URL = "https://api.siigo.com/auth"
SIIGO_BASE = "https://api.siigo.com"

# In-memory token cache (process lifetime)
_cache: dict = {"token": None, "expires_at": 0.0}


async def _get_token() -> str:
    now = time.time()
    if _cache["token"] and _cache["expires_at"] > now + 60:
        return _cache["token"]

    username = (settings.SIIGO_USERNAME or "").strip()
    access_key = (settings.SIIGO_ACCESS_KEY or "").strip()

    import logging
    logging.getLogger(__name__).info(
        "Siigo auth attempt: user=%s key_len=%d", username, len(access_key)
    )

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            SIIGO_AUTH_URL,
            json={"username": username, "access_key": access_key},
            headers={"Content-Type": "application/json", "Partner-Id": settings.SIIGO_PARTNER_ID},
        )
        if not r.is_success:
            raise ValueError(f"Siigo auth {r.status_code}: {r.text[:300]}")
        data = r.json()

    token = data.get("access_token") or data.get("token") or data.get("accessToken")
    if not token:
        raise ValueError(f"Token not found in Siigo response: {list(data.keys())}")

    _cache["token"] = token
    _cache["expires_at"] = now + 86_000  # renew ~7 min before 24h expiry
    return token


async def _invalidate_token() -> None:
    """Clear the in-memory token cache so the next call re-authenticates."""
    _cache["token"] = None
    _cache["expires_at"] = 0.0


async def get_invoices(fecha_desde: str, fecha_hasta: str) -> list[dict]:
    """Fetch all sales invoices in [fecha_desde, fecha_hasta] (YYYY-MM-DD).

    If Siigo returns 401 (token invalidated server-side), clears the local
    cache and retries once with a fresh token before raising.
    """
    date_start = f"{fecha_desde}T00:00:00Z"
    date_end   = f"{fecha_hasta}T23:59:59Z"

    for attempt in range(2):
        token = await _get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Partner-Id": settings.SIIGO_PARTNER_ID,
        }

        all_invoices: list[dict] = []
        page = 1
        failed = False

        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                r = await client.get(
                    f"{SIIGO_BASE}/v1/invoices",
                    headers=headers,
                    params={
                        "date_start": date_start,
                        "date_end":   date_end,
                        "page":       page,
                        "page_size":  100,
                    },
                )

                if r.status_code == 401 and attempt == 0:
                    # Token invalidated server-side — clear cache and retry once
                    await _invalidate_token()
                    failed = True
                    break

                if not r.is_success:
                    raise ValueError(f"Siigo invoices {r.status_code}: {r.text[:300]}")

                data = r.json()
                results = data.get("results", [])
                all_invoices.extend(results)

                pagination = data.get("pagination", {})
                total = pagination.get("total_results", len(results))
                if not results or len(all_invoices) >= total:
                    break
                page += 1

        if not failed:
            return all_invoices

    raise ValueError("Siigo invoices: token inválido después de reautenticar. Verificá las credenciales.")


def _parse_item(item: dict, factura_id: str) -> dict:
    """Parse a single Siigo invoice line item into a normalized dict."""
    codigo = item.get("code", "") or ""
    descripcion = item.get("description", "") or ""
    cantidad = float(item.get("quantity", 0) or 0)
    precio = float(item.get("price", 0) or 0)
    raw_disc = item.get("discount", 0) or 0
    if isinstance(raw_disc, dict):
        desc_pct = float(raw_disc.get("percentage", 0) or 0)
    else:
        desc_pct = float(raw_disc)
    total_sin = round(cantidad * precio, 2)
    desc_monto = round(total_sin * desc_pct / 100, 2) if desc_pct else None
    total_con = round(total_sin * (1 - desc_pct / 100), 2)
    return {
        "codigo_producto": codigo,
        "descripcion": descripcion,
        "cantidad": cantidad,
        "precio_unitario": precio,
        "total_sin_descuento": total_sin,
        "descuento_porcentaje": desc_pct if desc_pct else None,
        "descuento_monto": desc_monto,
        "total_con_descuento": total_con,
        "siigo_factura_id": factura_id,
    }


def aggregate_by_product(invoices: list[dict]) -> dict:
    """Group invoice line items by product and compute totals."""
    from collections import defaultdict

    productos: dict = defaultdict(lambda: {
        "nombre": "", "codigo": "", "cantidad": 0.0, "total": 0.0
    })
    total_ventas = 0.0

    for inv in invoices:
        factura_id = str(inv.get("id", "") or "")
        for item in inv.get("items", []):
            parsed = _parse_item(item, factura_id)
            codigo = parsed["codigo_producto"]
            nombre = parsed["descripcion"]
            subtotal = parsed["total_con_descuento"]

            key = codigo or nombre
            productos[key]["nombre"] = nombre
            productos[key]["codigo"] = codigo
            productos[key]["cantidad"] += parsed["cantidad"]
            productos[key]["total"] += subtotal
            total_ventas += subtotal

    return {"productos": dict(productos), "total_ventas": total_ventas}


def _find_turno_id(inv_dt, turnos: list) -> int | None:
    """Return the CajaTurno.id whose apertura–cierre window contains inv_dt, or None."""
    if inv_dt is None:
        return None
    for turno in turnos:
        if turno.fecha_apertura and turno.fecha_cierre:
            if turno.fecha_apertura <= inv_dt <= turno.fecha_cierre:
                return turno.id
    return None


async def sync_ventas(db: Session, tienda_id: int, fecha_desde: str, fecha_hasta: str) -> dict:
    """Fetch invoices from Siigo, persist line items, then auto-populate VentaDiaria."""
    from app.models.models import SiigoVentaItem, CajaTurno
    from datetime import datetime as dt

    invoices = await get_invoices(fecha_desde, fecha_hasta)

    # Load all closed turnos for the date range to attribute each invoice to a barista
    desde_dt = dt.fromisoformat(f"{fecha_desde}T00:00:00")
    hasta_dt = dt.fromisoformat(f"{fecha_hasta}T23:59:59")
    turnos = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.fecha_apertura >= desde_dt,
        CajaTurno.fecha_apertura <= hasta_dt,
        CajaTurno.fecha_cierre.isnot(None),
    ).all()

    rows = []
    for inv in invoices:
        factura_id = str(inv.get("id", "") or "")
        raw_date = inv.get("date") or fecha_desde
        inv_fecha = str(raw_date)[:10]

        # Try to parse a full datetime from the invoice for turno attribution
        inv_dt = None
        if "T" in str(raw_date):
            try:
                # Strip any timezone suffix so comparison against naive CajaTurno datetimes works
                raw_str = str(raw_date).replace("Z", "")
                if "+" in raw_str[10:]:
                    raw_str = raw_str[:10 + raw_str[10:].index("+")]
                elif len(raw_str) > 19 and raw_str[19] == "-":
                    raw_str = raw_str[:19]
                inv_dt = dt.fromisoformat(raw_str)
            except (ValueError, IndexError):
                pass

        turno_id = _find_turno_id(inv_dt, turnos)

        for item in inv.get("items", []):
            parsed = _parse_item(item, factura_id)
            rows.append({**parsed, "tienda_id": tienda_id, "fecha": inv_fecha, "turno_id": turno_id})

    if not rows:
        return {"synced_count": 0, "skipped_count": 0, "date_range": f"{fecha_desde}/{fecha_hasta}", "ventas_pobladas": 0}

    before = db.query(SiigoVentaItem).filter(
        SiigoVentaItem.tienda_id == tienda_id,
        SiigoVentaItem.fecha >= fecha_desde,
        SiigoVentaItem.fecha <= fecha_hasta,
    ).count()

    sql = text("""
        INSERT OR IGNORE INTO siigo_venta_items
        (tienda_id, fecha, codigo_producto, descripcion, cantidad, precio_unitario,
         total_sin_descuento, descuento_porcentaje, descuento_monto, total_con_descuento,
         siigo_factura_id, turno_id)
        VALUES (:tienda_id, :fecha, :codigo_producto, :descripcion, :cantidad, :precio_unitario,
                :total_sin_descuento, :descuento_porcentaje, :descuento_monto, :total_con_descuento,
                :siigo_factura_id, :turno_id)
    """)
    db.execute(sql, rows)

    # Back-fill turno_id on previously-synced rows that were skipped by INSERT OR IGNORE
    rows_with_turno = [r for r in rows if r["turno_id"] is not None]
    if rows_with_turno:
        upd = text("""
            UPDATE siigo_venta_items SET turno_id = :turno_id
            WHERE tienda_id = :tienda_id
              AND siigo_factura_id = :siigo_factura_id
              AND codigo_producto = :codigo_producto
              AND fecha = :fecha
              AND turno_id IS NULL
        """)
        for r in rows_with_turno:
            db.execute(upd, {
                "turno_id": r["turno_id"],
                "tienda_id": r["tienda_id"],
                "siigo_factura_id": r["siigo_factura_id"],
                "codigo_producto": r["codigo_producto"],
                "fecha": r["fecha"],
            })

    db.commit()

    after = db.query(SiigoVentaItem).filter(
        SiigoVentaItem.tienda_id == tienda_id,
        SiigoVentaItem.fecha >= fecha_desde,
        SiigoVentaItem.fecha <= fecha_hasta,
    ).count()

    synced = after - before
    skipped = len(rows) - synced

    ventas_result = auto_poblar_venta_diaria(db, tienda_id, fecha_desde, fecha_hasta)
    return {
        "synced_count": synced,
        "skipped_count": skipped,
        "date_range": f"{fecha_desde}/{fecha_hasta}",
        "ventas_pobladas": ventas_result["ventas_pobladas"],
    }


def auto_poblar_venta_diaria(db: Session, tienda_id: int, fecha_desde: str, fecha_hasta: str) -> dict:
    """Aggregate synced Siigo items by turno and upsert VentaDiaria automatically."""
    from app.models.models import SiigoVentaItem, CajaTurno, VentaDiaria
    from sqlalchemy import func
    from collections import defaultdict

    # Sum total_con_descuento per turno_id for items that could be attributed
    items = db.query(SiigoVentaItem).filter(
        SiigoVentaItem.tienda_id == tienda_id,
        SiigoVentaItem.fecha >= fecha_desde,
        SiigoVentaItem.fecha <= fecha_hasta,
        SiigoVentaItem.turno_id.isnot(None),
    ).all()

    if not items:
        return {"ventas_pobladas": 0}

    totales: dict[int, float] = defaultdict(float)
    for item in items:
        totales[item.turno_id] += item.total_con_descuento

    turnos = {t.id: t for t in db.query(CajaTurno).filter(CajaTurno.id.in_(totales.keys())).all()}

    count = 0
    for turno_id, total in totales.items():
        turno = turnos.get(turno_id)
        if not turno:
            continue

        # Replace previous auto-sync entry for this turno (re-sync is idempotent)
        db.query(VentaDiaria).filter(
            VentaDiaria.turno_id == turno_id,
            VentaDiaria.nota == "sync:siigo",
        ).delete()

        total_r = round(total, 2)
        venta = VentaDiaria(
            tienda_id=tienda_id,
            turno_id=turno_id,
            venta_total=total_r,
            nota_credito=0.0,
            vales=0.0,
            tarjetas=0.0,
            efectivo_calculado=total_r,
            usuario_id=turno.usuario_apertura_id,
            nota="sync:siigo",
        )
        db.add(venta)
        db.flush()

        # Recalculate turno totals from ALL VentaDiaria (synced + any manual admin entries)
        turno.total_ventas = db.query(func.sum(VentaDiaria.venta_total)).filter(VentaDiaria.turno_id == turno_id).scalar() or 0.0
        turno.total_efectivo = db.query(func.sum(VentaDiaria.efectivo_calculado)).filter(VentaDiaria.turno_id == turno_id).scalar() or 0.0
        turno.total_tarjeta = db.query(func.sum(VentaDiaria.tarjetas)).filter(VentaDiaria.turno_id == turno_id).scalar() or 0.0
        turno.tiene_ventas = True
        count += 1

    db.commit()
    return {"ventas_pobladas": count}


def query_ventas_siigo(db: Session, filtro) -> list:
    """Query locally stored Siigo venta items with cross-filtering support."""
    from app.models.models import SiigoVentaItem

    q = db.query(SiigoVentaItem).filter(
        SiigoVentaItem.tienda_id == filtro.tienda_id,
        SiigoVentaItem.fecha >= filtro.fecha_desde,
        SiigoVentaItem.fecha <= filtro.fecha_hasta,
    )

    if filtro.con_descuento:
        q = q.filter(
            (SiigoVentaItem.descuento_monto > 0) | (SiigoVentaItem.descuento_porcentaje > 0)
        )

    if filtro.producto_search:
        term = f"%{filtro.producto_search}%"
        q = q.filter(
            SiigoVentaItem.descripcion.ilike(term) | SiigoVentaItem.codigo_producto.ilike(term)
        )

    rows = q.order_by(SiigoVentaItem.fecha.desc()).all()
    result = []
    for row in rows:
        d = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        # Convert date/datetime to string for JSON serialization
        if d.get("fecha"):
            d["fecha"] = str(d["fecha"])
        if d.get("created_at"):
            d["created_at"] = str(d["created_at"])
        result.append(d)
    return result
