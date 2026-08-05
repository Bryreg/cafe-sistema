from pydantic import BaseModel
from typing import Optional

class LoginRequest(BaseModel):
    email: str
    password: str

class UsuarioPublic(BaseModel):
    id: int
    nombre: str
    rol: str
    tienda_id: int | None
    class Config: from_attributes = True

class RegisterRequest(BaseModel):
    nombre: str
    email: Optional[str] = None      # requerido solo para admin (login); barista lo genera el backend
    password: Optional[str] = None   # idem
    rol: str = "barista"
    tienda_id: Optional[int] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str
    nombre: str
    tienda_id: Optional[int]
    user_id: int
    kiosk: bool = False

class UsuarioAdmin(BaseModel):
    id: int
    nombre: str
    email: str
    rol: str
    tienda_id: Optional[int]
    tienda_nombre: Optional[str]
    activo: bool
    ultimo_acceso: Optional[str]
    class Config: from_attributes = True

class ActualizarUsuario(BaseModel):
    nombre: Optional[str] = None
    rol: Optional[str] = None
    tienda_id: Optional[int] = None
    activo: Optional[bool] = None

class SetPasswordRequest(BaseModel):
    password: str

class KioskPinRequest(BaseModel):
    pin: str

class MetaVentasRequest(BaseModel):
    meta: float
