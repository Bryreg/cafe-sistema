from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError
from app.database import get_db
from app.core.security import decode_token
from app.models.models import CajaTurno, Usuario

bearer = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
) -> Usuario:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        user_id: int = int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = db.query(Usuario).filter(Usuario.id == user_id, Usuario.activo == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    # Si el token contiene tienda_id (sede seleccionada al iniciar turno), usarla
    tienda_override = payload.get("tienda_id")
    if tienda_override is not None:
        # Expulsar del session antes de mutar para evitar persistencia accidental en DB
        db.expunge(user)
        user.tienda_id = int(tienda_override)
    return user

def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.rol != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere rol admin")
    return current_user


def ensure_tienda_access(current_user: Usuario, tienda_id: int) -> int:
    if current_user.rol == "admin":
        return tienda_id
    if current_user.tienda_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario sin tienda asignada")
    if current_user.tienda_id != tienda_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta tienda")
    return tienda_id


def ensure_turno_access(db: Session, current_user: Usuario, turno_id: int) -> CajaTurno:
    turno = db.query(CajaTurno).filter(CajaTurno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turno no encontrado")
    ensure_tienda_access(current_user, turno.tienda_id)
    return turno
