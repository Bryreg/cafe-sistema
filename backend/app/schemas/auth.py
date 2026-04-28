from pydantic import BaseModel
from typing import Optional

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginPinRequest(BaseModel):
    user_id: int
    pin: str

class UsuarioPublic(BaseModel):
    id: int
    nombre: str
    rol: str
    tienda_id: int | None
    class Config: from_attributes = True

class RegisterRequest(BaseModel):
    nombre: str
    email: str
    password: str
    rol: str = "barista"
    tienda_id: Optional[int] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str
    nombre: str
    tienda_id: Optional[int]
    user_id: int
