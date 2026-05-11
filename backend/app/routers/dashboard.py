from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date
from app.database import get_db
from app.core.deps import ensure_tienda_access, require_admin
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


@router.get("/{tienda_id}")
def get_dashboard(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_dashboard(db, tienda_id)


class ChecklistUpdate(BaseModel):
    campo: str
    valor: bool


@router.patch("/{tienda_id}/checklist")
def update_checklist(tienda_id: int, body: ChecklistUpdate, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    result = svc.actualizar_checklist_manual(db, tienda_id, body.campo, body.valor)
    if result is None:
        raise HTTPException(status_code=400, detail=f"Campo '{body.campo}' no es editable manualmente")
    return {"ok": True}
