from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date
from app.database import get_db
from app.core.deps import ensure_tienda_access, require_admin, get_current_user
from app.models.models import Usuario
from app.services import dashboard as svc
from app.services import kpis as kpis_svc

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/comparativo")
def get_comparativo(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Etapa 10: Comparativo multi-tienda del día actual."""
    return kpis_svc.get_comparativo(db)


@router.get("/{tienda_id}/kpis")
def get_kpis(
    tienda_id: int,
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Etapa 5: KPIs operativos del período."""
    ensure_tienda_access(user, tienda_id)
    return kpis_svc.get_kpis(db, tienda_id, fecha_desde, fecha_hasta)


@router.get("/{tienda_id}/admin-resumen")
def get_admin_resumen(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Resumen financiero + operativo del mes para el admin: ventas, consignaciones,
    insumos (inicio/cierre/actual), entradas por proveedor y egresos de caja."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_admin_resumen(db, tienda_id)


@router.get("/{tienda_id}/debug-siigo")
def debug_siigo(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),  # diagnostic endpoint — keep protected, remove when no longer needed
):
    """Temporal: diagnóstico de por qué ventas_dia puede ser 0."""
    from datetime import datetime
    from sqlalchemy import func, text
    from app.models.models import SiigoVentaItem
    hoy = datetime.utcnow().date()
    count = db.query(SiigoVentaItem).filter(SiigoVentaItem.tienda_id == tienda_id).count()
    count_hoy = db.query(SiigoVentaItem).filter(
        SiigoVentaItem.tienda_id == tienda_id,
        SiigoVentaItem.fecha == hoy,
    ).count()
    suma_hoy = db.query(func.sum(SiigoVentaItem.total_con_descuento)).filter(
        SiigoVentaItem.tienda_id == tienda_id,
        SiigoVentaItem.fecha == hoy,
    ).scalar()
    # Raw SQL para descartar problemas de ORM
    raw = db.execute(text(
        "SELECT COUNT(*), SUM(total_con_descuento), MIN(fecha), MAX(fecha) "
        "FROM siigo_venta_items WHERE tienda_id = :tid AND fecha = CURRENT_DATE"
    ), {"tid": tienda_id}).fetchone()
    sample = db.execute(text(
        "SELECT fecha, total_con_descuento FROM siigo_venta_items WHERE tienda_id = :tid ORDER BY id DESC LIMIT 5"
    ), {"tid": tienda_id}).fetchall()
    return {
        "utc_hoy": str(hoy),
        "total_items_tienda": count,
        "items_hoy_orm": count_hoy,
        "suma_hoy_orm": suma_hoy,
        "raw_current_date_count": raw[0],
        "raw_current_date_sum": raw[1],
        "raw_min_fecha": str(raw[2]) if raw[2] else None,
        "raw_max_fecha": str(raw[3]) if raw[3] else None,
        "sample_rows": [{"fecha": str(r[0]), "total": r[1]} for r in sample],
    }


@router.get("/{tienda_id}")
def get_dashboard(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_dashboard(db, tienda_id)


class ChecklistUpdate(BaseModel):
    campo: str
    valor: bool


@router.patch("/{tienda_id}/checklist")
def update_checklist(tienda_id: int, body: ChecklistUpdate, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    result = svc.actualizar_checklist_manual(db, tienda_id, body.campo, body.valor)
    if result is None:
        raise HTTPException(status_code=400, detail=f"Campo '{body.campo}' no es editable manualmente")
    return {"ok": True}
