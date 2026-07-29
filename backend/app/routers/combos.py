import json

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.database import get_db
from app.models.models import Usuario
from app.services import combos as svc

router = APIRouter(prefix="/combos", tags=["combos"])


def _ids_de_json(raw: str, campo: str) -> list[int]:
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError
        return [int(x) for x in parsed]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"{campo} debe ser una lista JSON de ids")


@router.get("/admin")
def listar(db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Combos con su composición y en qué sedes están habilitados."""
    return svc.listar_admin(db)


@router.put("/{combo_id}/tiendas")
def set_tiendas(combo_id: int, tienda_ids: str = Form(...),
                db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Define en qué sedes se vende el combo. tienda_ids = lista JSON de ids."""
    return svc.set_tiendas(db, combo_id, _ids_de_json(tienda_ids, "tienda_ids"), user.id)


@router.patch("/{combo_id}/activo")
def set_activo(combo_id: int, activo: bool = Form(...),
               db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Prende/apaga el combo en todas las sedes."""
    return svc.set_activo(db, combo_id, activo, user.id)
