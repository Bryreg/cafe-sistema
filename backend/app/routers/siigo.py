from fastapi import APIRouter, Query, HTTPException
from app.services import siigo as siigo_svc
from app.config import settings

router = APIRouter(prefix="/siigo", tags=["siigo"])


def _check_configured():
    if not settings.SIIGO_USERNAME or not settings.SIIGO_ACCESS_KEY:
        raise HTTPException(400, "Siigo no configurado: falta SIIGO_USERNAME o SIIGO_ACCESS_KEY")


@router.get("/ventas-por-producto")
async def ventas_por_producto(
    fecha_desde: str = Query(..., description="YYYY-MM-DD"),
    fecha_hasta: str = Query(..., description="YYYY-MM-DD"),
):
    _check_configured()
    try:
        invoices = await siigo_svc.get_invoices(fecha_desde, fecha_hasta)
    except Exception as e:
        raise HTTPException(502, f"Error consultando Siigo: {e}")

    agg = siigo_svc.aggregate_by_product(invoices)
    total = agg["total_ventas"]

    productos_lista = sorted(
        [
            {
                "nombre":     p["nombre"],
                "codigo":     p["codigo"],
                "cantidad":   round(p["cantidad"], 2),
                "total":      round(p["total"], 0),
                "porcentaje": round(p["total"] / total * 100, 1) if total > 0 else 0,
            }
            for p in agg["productos"].values()
            if p["total"] > 0
        ],
        key=lambda x: -x["total"],
    )

    return {
        "fecha_desde":    fecha_desde,
        "fecha_hasta":    fecha_hasta,
        "total_facturas": len(invoices),
        "total_ventas":   round(total, 0),
        "productos":      productos_lista,
    }
