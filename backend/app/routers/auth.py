from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta
from collections import defaultdict
from time import time
import secrets
from app.database import get_db
from app.schemas.auth import LoginRequest, LoginPinRequest, RegisterRequest, TokenResponse, UsuarioPublic, UsuarioAdmin, ActualizarUsuario, SetPinRequest
from app.models.models import Usuario, Tienda, RolEnum
from app.core.security import verify_password, hash_password, create_access_token
from app.core.deps import require_admin, get_current_user
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

# ─── PIN brute-force protection (in-memory, resets on restart) ────────────────
_pin_attempts: dict[int, list[float]] = defaultdict(list)
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 900  # 15 minutes


def _check_rate_limit(user_id: int) -> None:
    now = time()
    attempts = [t for t in _pin_attempts[user_id] if now - t < WINDOW_SECONDS]
    _pin_attempts[user_id] = attempts
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Intentá en 15 minutos.",
        )
    _pin_attempts[user_id].append(now)


@router.post("/seleccionar-sede", response_model=TokenResponse)
def seleccionar_sede(tienda_id: int, db: Session = Depends(get_db),
                     user: Usuario = Depends(get_current_user)):
    """Emite un nuevo token con la sede seleccionada embebida, para que el backend la use en lugar de la DB."""
    tienda = db.query(Tienda).filter(Tienda.id == tienda_id, Tienda.activa == True).first()
    if not tienda:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    token = create_access_token({"sub": str(user.id), "tienda_id": tienda_id})
    return TokenResponse(
        access_token=token, rol=user.rol.value,
        nombre=user.nombre, tienda_id=tienda_id, user_id=user.id
    )


@router.get("/tiendas")
def listar_tiendas(db: Session = Depends(get_db)):
    """Lista pública de sedes activas para selección al iniciar turno."""
    return [{"id": t.id, "nombre": t.nombre} for t in db.query(Tienda).filter(Tienda.activa == True).all()]


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
    _check_rate_limit(user.id)
    if not verify_password(data.pin, user.pin_hash):
        raise HTTPException(status_code=401, detail="PIN incorrecto")
    # Successful login: clear failed attempts
    _pin_attempts[user.id] = []
    user.ultimo_acceso = datetime.utcnow()
    db.commit()
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token, rol=user.rol.value,
        nombre=user.nombre, tienda_id=user.tienda_id, user_id=user.id
    )


@router.post("/logout")
def logout():
    """Stateless logout — client must discard the token from storage."""
    return {"message": "Logged out"}


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


@router.get("/admin/usuarios", response_model=List[UsuarioAdmin])
def listar_usuarios_admin(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Lista completa de usuarios para el panel admin."""
    usuarios = db.query(Usuario).order_by(Usuario.activo.desc(), Usuario.nombre).all()
    result = []
    for u in usuarios:
        tienda = db.query(Tienda).filter(Tienda.id == u.tienda_id).first() if u.tienda_id else None
        result.append(UsuarioAdmin(
            id=u.id, nombre=u.nombre, email=u.email, rol=u.rol.value,
            tienda_id=u.tienda_id, tienda_nombre=tienda.nombre if tienda else None,
            activo=u.activo,
            ultimo_acceso=u.ultimo_acceso.isoformat() if u.ultimo_acceso else None,
            tiene_pin=bool(u.pin_hash),
        ))
    return result


@router.patch("/usuarios/{user_id}")
def actualizar_usuario(user_id: int, data: ActualizarUsuario, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Actualiza nombre, rol, sede o estado activo de un usuario."""
    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if data.nombre is not None:
        user.nombre = data.nombre
    if data.rol is not None:
        user.rol = data.rol
    if data.tienda_id is not None:
        user.tienda_id = data.tienda_id
    if data.activo is not None:
        user.activo = data.activo
    db.commit()
    db.refresh(user)
    return {"id": user.id, "nombre": user.nombre, "activo": user.activo}


@router.post("/usuarios/{user_id}/set-pin")
def set_pin(user_id: int, data: SetPinRequest, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Establece o resetea el PIN de 4 dígitos de un usuario."""
    if not data.pin.isdigit() or len(data.pin) != 4:
        raise HTTPException(status_code=400, detail="El PIN debe ser exactamente 4 dígitos")
    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.pin_hash = hash_password(data.pin)
    db.commit()
    return {"ok": True}


@router.post("/kiosk-init", response_model=TokenResponse)
def kiosk_init(tienda_id: int, kiosk_pin: str, db: Session = Depends(get_db)):
    """Activa modo kiosco para un dispositivo. Requiere KIOSK_PIN configurado en el servidor."""
    if not settings.KIOSK_PIN or kiosk_pin != settings.KIOSK_PIN:
        raise HTTPException(status_code=401, detail="PIN de kiosco incorrecto")
    tienda = db.query(Tienda).filter(Tienda.id == tienda_id, Tienda.activa == True).first()
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    kiosk_email = f"kiosk@tienda{tienda_id}.device"
    kiosk_user = db.query(Usuario).filter(Usuario.email == kiosk_email).first()
    if not kiosk_user:
        kiosk_user = Usuario(
            nombre="Kiosk", email=kiosk_email,
            password_hash=hash_password(secrets.token_hex(32)),
            rol=RolEnum.barista, tienda_id=tienda_id, activo=True,
        )
        db.add(kiosk_user)
        db.commit()
        db.refresh(kiosk_user)
    token = create_access_token(
        {"sub": str(kiosk_user.id), "tienda_id": tienda_id, "kiosk": True},
        expires_delta=timedelta(days=365 * 10),
    )
    return TokenResponse(
        access_token=token, rol="barista", nombre="Kiosk",
        tienda_id=tienda_id, user_id=kiosk_user.id, kiosk=True,
    )


@router.post("/usuarios")
def crear_usuario(data: RegisterRequest, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Crea un nuevo usuario (barista o admin) desde el panel."""
    email = data.email.strip().lower()
    if db.query(Usuario).filter(Usuario.email == email).first():
        raise HTTPException(status_code=400, detail="Email ya registrado")
    user = Usuario(
        nombre=data.nombre.strip(), email=email,
        password_hash=hash_password(data.password if data.password else "sincontraseña"),
        rol=data.rol, tienda_id=data.tienda_id, activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "nombre": user.nombre, "email": user.email}
