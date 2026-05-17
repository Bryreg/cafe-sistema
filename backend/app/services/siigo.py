"""Siigo Nube API client — authentication + invoice fetching."""

import time
import httpx
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
            headers={"Content-Type": "application/json", "Partner-Id": "cafe-sistema"},
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


async def get_invoices(fecha_desde: str, fecha_hasta: str) -> list[dict]:
    """Fetch all sales invoices in [fecha_desde, fecha_hasta] (YYYY-MM-DD)."""
    token = await _get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    all_invoices: list[dict] = []
    page = 1

    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            r = await client.get(
                f"{SIIGO_BASE}/v1/invoices",
                headers=headers,
                params={
                    "date_start": fecha_desde,
                    "date_end":   fecha_hasta,
                    "page":       page,
                    "page_size":  100,
                },
            )
            r.raise_for_status()
            data = r.json()

            results = data.get("results", [])
            all_invoices.extend(results)

            pagination = data.get("pagination", {})
            total = pagination.get("total_results", len(results))
            if not results or len(all_invoices) >= total:
                break
            page += 1

    return all_invoices


def aggregate_by_product(invoices: list[dict]) -> dict:
    """Group invoice line items by product and compute totals."""
    from collections import defaultdict

    productos: dict = defaultdict(lambda: {
        "nombre": "", "codigo": "", "cantidad": 0.0, "total": 0.0
    })
    total_ventas = 0.0

    for inv in invoices:
        for item in inv.get("items", []):
            codigo = item.get("code", "") or ""
            nombre = item.get("description", "") or ""
            cantidad = float(item.get("quantity", 0) or 0)
            precio = float(item.get("price", 0) or 0)
            descuento = float(item.get("discount", 0) or 0)
            subtotal = round(cantidad * precio * (1 - descuento / 100), 2)

            key = codigo or nombre
            productos[key]["nombre"] = nombre
            productos[key]["codigo"] = codigo
            productos[key]["cantidad"] += cantidad
            productos[key]["total"] += subtotal
            total_ventas += subtotal

    return {"productos": dict(productos), "total_ventas": total_ventas}
