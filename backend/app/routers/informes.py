from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, require_admin
from app.models.models import Usuario
from app.services import informes as svc
from datetime import date
import csv
import io

router = APIRouter(prefix="/informes", tags=["informes"])


@router.get("/ventas")
def ventas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.reporte_ventas(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/mermas")
def mermas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.reporte_mermas(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/inventario-consumido")
def inventario_consumido(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.reporte_inventario_consumido(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/entregas")
def entregas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.reporte_entregas(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/turnos")
def turnos(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.reporte_turnos(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/kpi-mermas")
def kpi_mermas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.kpi_mermas(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/rotacion")
def rotacion(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.reporte_rotacion(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/baristas")
def baristas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.reporte_baristas(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/export")
def export_csv(
    tipo: str = Query(..., description="ventas | mermas | inventario | turnos | entregas"),
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Etapa 8: Exportar reporte en formato CSV."""
    ensure_tienda_access(user, tienda_id)
    fn_map = {
        "ventas": svc.reporte_ventas,
        "mermas": svc.reporte_mermas,
        "inventario": svc.reporte_inventario_consumido,
        "turnos": svc.reporte_turnos,
        "entregas": svc.reporte_entregas,
    }
    if tipo not in fn_map:
        raise HTTPException(status_code=400, detail=f"tipo inválido. Opciones: {list(fn_map)}")

    data = fn_map[tipo](db, tienda_id, fecha_desde, fecha_hasta)
    filas = data.get("filas", [])

    output = io.StringIO()
    if filas:
        # Aplanar listas/dicts anidados a string
        flat_filas = [
            {k: (str(v) if isinstance(v, (list, dict)) else v) for k, v in f.items()}
            for f in filas
        ]
        writer = csv.DictWriter(output, fieldnames=flat_filas[0].keys())
        writer.writeheader()
        writer.writerows(flat_filas)

    output.seek(0)
    filename = f"{tipo}_{fecha_desde}_{fecha_hasta}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
