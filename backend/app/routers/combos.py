import json

from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.database import get_db
from app.models.models import Usuario
from app.services import combos as svc


class ComboProductoIn(BaseModel):
    producto_id: int
    cantidad: float = 1


class ComboOpcionIn(BaseModel):
    nombre: str
    productos: list[ComboProductoIn]


class ComboGrupoIn(BaseModel):
    nombre: str
    opciones: list[ComboOpcionIn]


class ComboIn(BaseModel):
    """Definición completa de un combo. `grupos` con UNA opción son fijos: el
    POS los auto-selecciona y el combo se vende de un toque."""
    nombre: str
    precio: float
    orden: int = 0
    grupos: list[ComboGrupoIn]


class ComboCrearIn(ComboIn):
    # Sin sede el combo no se vende en ninguna parte, y la pantalla lo muestra
    # igual: es el error que nadie descubre. Se pide desde el alta.
    tienda_ids: list[int] = Field(min_length=1)

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


@router.post("")
def crear(data: ComboCrearIn, db: Session = Depends(get_db),
          user: Usuario = Depends(require_admin)):
    """Crea un combo con su composición y sus sedes.

    Hasta ahora los combos SOLO se podían crear corriendo `cargar_combos.py`
    contra la base, o sea entrando al servidor: no había forma de dar de alta un
    combo desde la app. El armado es la misma función que usa el script
    (`services/combos.sincronizar_combo`), no una segunda copia."""
    return svc.crear(db, data.model_dump(), data.tienda_ids, user.id)


@router.put("/{combo_id}")
def editar(combo_id: int, data: ComboIn, db: Session = Depends(get_db),
           user: Usuario = Depends(require_admin)):
    """Reemplaza nombre, precio, orden y composición de un combo.

    Las SEDES no viajan acá: quitar una sede es una decisión distinta a cambiar
    la composición y tiene su propio endpoint. Renombrar también renombra el
    producto sombra, que es el nombre que el ticket muestra."""
    return svc.editar(db, combo_id, data.model_dump(), user.id)


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
