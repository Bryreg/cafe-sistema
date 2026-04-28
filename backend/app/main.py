from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os, logging
from app.database import engine
from app.models.models import Base
from app.routers import (auth, caja, inventario, pasteleria, consignaciones,
                          dashboard, ventas, conteos, mermas, solicitudes,
                          informes, audit, alertas, notificaciones, limpieza, recetas)
from app.config import settings

logging.basicConfig(level=logging.INFO)

# Migraciones inline ANTES de create_all
from sqlalchemy import text as _text
with engine.connect() as _conn:
    # Drop entregas_turno si tiene schema viejo (sin tienda_id) — create_all la recreará
    try:
        _conn.execute(_text("SELECT tienda_id FROM entregas_turno LIMIT 1"))
    except Exception:
        # columna no existe → schema viejo o tabla no existe → dropar para que create_all la cree fresca
        try:
            _conn.execute(_text("DROP TABLE IF EXISTS entregas_turno"))
            _conn.commit()
        except Exception:
            pass
    for _sql in [
        "ALTER TABLE solicitudes_sencilla ADD COLUMN detalle TEXT",
        "ALTER TABLE caja_turnos ADD COLUMN tiene_conteo_apertura BOOLEAN DEFAULT 0",
        "ALTER TABLE caja_turnos ADD COLUMN tiene_ventas BOOLEAN DEFAULT 0",
        "ALTER TABLE caja_turnos ADD COLUMN tiene_conteo_cierre BOOLEAN DEFAULT 0",
        "ALTER TABLE caja_turnos ADD COLUMN datafono_real FLOAT",
        "ALTER TABLE caja_turnos ADD COLUMN diferencia_tarjeta FLOAT",
        "ALTER TABLE pasteleria_diaria ADD COLUMN activo BOOLEAN DEFAULT 1",
        # Etapa 6: timestamps operativos en turnos
        "ALTER TABLE caja_turnos ADD COLUMN ts_conteo_apertura DATETIME",
        "ALTER TABLE caja_turnos ADD COLUMN ts_primera_venta DATETIME",
        "ALTER TABLE caja_turnos ADD COLUMN ts_conteo_cierre DATETIME",
        # Etapa 9: último acceso de usuario
        "ALTER TABLE usuarios ADD COLUMN ultimo_acceso DATETIME",
        # Mermas: tipo, traslado y seguimiento
        "ALTER TABLE mermas ADD COLUMN tipo VARCHAR(20) DEFAULT 'consumo'",
        "ALTER TABLE mermas ADD COLUMN tienda_destino_id INTEGER",
        "ALTER TABLE mermas ADD COLUMN recibido BOOLEAN DEFAULT 0",
        "ALTER TABLE mermas ADD COLUMN fecha_recibido DATETIME",
    ]:
        try:
            _conn.execute(_text(_sql))
            _conn.commit()
        except Exception:
            pass  # columna ya existe

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sistema Café", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth.router, prefix="/api/v1")
app.include_router(caja.router, prefix="/api/v1")
app.include_router(inventario.router, prefix="/api/v1")
app.include_router(pasteleria.router, prefix="/api/v1")
app.include_router(consignaciones.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(ventas.router, prefix="/api/v1")
app.include_router(conteos.router, prefix="/api/v1")
app.include_router(mermas.router, prefix="/api/v1")
app.include_router(solicitudes.router, prefix="/api/v1")
app.include_router(informes.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(alertas.router, prefix="/api/v1")
app.include_router(notificaciones.router, prefix="/api/v1")
app.include_router(limpieza.router, prefix="/api/v1")
app.include_router(recetas.router, prefix="/api/v1")

@app.get("/")
def root():
    return {"status": "ok", "app": "Sistema Café v1.0"}
