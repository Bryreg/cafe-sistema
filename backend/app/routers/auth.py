from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from app.database import get_db
from app.schemas.auth import LoginRequest, LoginPinRequest, RegisterRequest, TokenResponse, UsuarioPublic
from app.models.models import Usuario
from app.core.security import verify_password, hash_password, create_access_token
from app.core.deps import require_admin, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/usuarios", response_model=List[UsuarioPublic])
def listar_usuarios(db: Session = Depends(get_db)):
    """Lista pública de usuarios activos para pantalla de login por PIN."""
    return db.query(Usuario).filter(Usuario.activo == True).all()


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == data.email, Usuario.activo == True).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    user.ultimo_acceso = datetime.utcnow()
    db.commit()
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token, rol=user.rol.value,
        nombre=user.nombre, tienda_id=user.tienda_id, user_id=user.id
    )


@router.post("/login-pin", response_model=TokenResponse)
def login_pin(data: LoginPinRequest, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.id == data.user_id, Usuario.activo == True).first()
    if not user or not user.pin_hash:
        raise HTTPException(status_code=401, detail="PIN no configurado")
    if not verify_password(data.pin, user.pin_hash):
        raise HTTPException(status_code=401, detail="PIN incorrecto")
    user.ultimo_acceso = datetime.utcnow()
    db.commit()
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token, rol=user.rol.value,
        nombre=user.nombre, tienda_id=user.tienda_id, user_id=user.id
    )


@router.get("/me")
def me(user: Usuario = Depends(get_current_user)):
    """Etapa 9: Verifica sesión activa y retorna datos del usuario."""
    return {
        "id": user.id, "nombre": user.nombre, "email": user.email,
        "rol": user.rol.value, "tienda_id": user.tienda_id,
        "ultimo_acceso": user.ultimo_acceso,
    }


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    if db.query(Usuario).filter(Usuario.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email ya registrado")
    user = Usuario(
        nombre=data.nombre, email=data.email,
        password_hash=hash_password(data.password),
        rol=data.rol, tienda_id=data.tienda_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "nombre": user.nombre, "email": user.email}
