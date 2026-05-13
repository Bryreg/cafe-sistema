from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os, logging
from app.database import engine, SessionLocal
from app.models.models import Base
from app.routers import (auth, caja, inventario, pasteleria, consignaciones,
                          dashboard, ventas, conteos, mermas, solicitudes,
                          informes, audit, alertas, notificaciones, limpieza,
                          facturas, compras, comunicados)
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        "ALTER TABLE movimientos_caja ADD COLUMN imagen_url VARCHAR(300)",
        "ALTER TABLE entregas_turno ADD COLUMN tipo VARCHAR(20) DEFAULT 'entrega' NOT NULL",
        "ALTER TABLE pasteleria_diaria ADD COLUMN numero_lote VARCHAR(100)",
        "ALTER TABLE pasteleria_diaria ADD COLUMN fecha_vencimiento DATETIME",
        # Facturas de compra
        "ALTER TABLE facturas_compra ADD COLUMN numero_lote VARCHAR(100)",
        "ALTER TABLE facturas_compra ADD COLUMN fecha_recibido DATETIME",
        # Conteos de compras
        "ALTER TABLE conteos_compras ADD COLUMN nota VARCHAR(300)",
        "ALTER TABLE conteos_compras ADD COLUMN fecha_ajuste DATETIME",
        "ALTER TABLE conteos_compras ADD COLUMN usuario_ajuste_id INTEGER",
        # Integridad relacional: consignaciones ligadas a un turno específico
        "ALTER TABLE consignaciones ADD COLUMN caja_turno_id INTEGER REFERENCES caja_turnos(id)",
    ]:
        try:
            _conn.execute(_text(_sql))
            _conn.commit()
        except Exception:
            _conn.rollback()  # necesario en PostgreSQL: libera el estado de error antes del siguiente statement
            pass  # columna ya existe

Base.metadata.create_all(bind=engine)

# ─── Seed automático (solo si la base está vacía) ──────────────────────────
def _seed_if_empty():
    from app.models.models import Tienda, Usuario, Producto, Inventario, CategoriaProductoEnum
    from app.core.security import hash_password
    db = SessionLocal()
    try:
        if db.query(Tienda).count() > 0:
            return  # Ya hay datos
        logger.info("Base de datos vacía — ejecutando seed inicial...")

        t1 = Tienda(nombre="Vida",     direccion="Sede Vida")
        t2 = Tienda(nombre="Palmetto", direccion="Sede Palmetto Plaza")
        db.add_all([t1, t2]); db.flush()

        admin = Usuario(nombre="Administrador", email="admin@cafe.com",
                        password_hash=hash_password("admin123"),
                        pin_hash=hash_password("1234"), rol="admin", tienda_id=t1.id)
        baristas = [
            Usuario(nombre="Elina",     email="elina@cafe.com",     password_hash=hash_password("barista123"), pin_hash=hash_password("1111"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Catherin",  email="catherin@cafe.com",  password_hash=hash_password("barista123"), pin_hash=hash_password("2222"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Alejandra", email="alejandra@cafe.com", password_hash=hash_password("barista123"), pin_hash=hash_password("3333"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Ana Maria", email="anamaria@cafe.com",  password_hash=hash_password("barista123"), pin_hash=hash_password("4444"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Esther",    email="esther@cafe.com",    password_hash=hash_password("barista123"), pin_hash=hash_password("5555"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Luisa",     email="luisa@cafe.com",     password_hash=hash_password("barista123"), pin_hash=hash_password("6666"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Nicole",    email="nicole@cafe.com",    password_hash=hash_password("barista123"), pin_hash=hash_password("7777"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Laura",     email="laura@cafe.com",     password_hash=hash_password("barista123"), pin_hash=hash_password("8888"), rol="barista", tienda_id=t1.id),
        ]
        db.add(admin); db.add_all(baristas); db.flush()

        productos = [
            Producto(nombre="Café Espresso",    categoria=CategoriaProductoEnum.bebida,    unidad_medida="oz"),
            Producto(nombre="Leche Entera",     categoria=CategoriaProductoEnum.insumo,    unidad_medida="litro"),
            Producto(nombre="Leche Oat",        categoria=CategoriaProductoEnum.insumo,    unidad_medida="litro"),
            Producto(nombre="Azúcar",           categoria=CategoriaProductoEnum.insumo,    unidad_medida="kg"),
            Producto(nombre="Croissant",        categoria=CategoriaProductoEnum.pasteleria, unidad_medida="unidad"),
            Producto(nombre="Muffin Arándanos", categoria=CategoriaProductoEnum.pasteleria, unidad_medida="unidad"),
            Producto(nombre="Brownie",          categoria=CategoriaProductoEnum.pasteleria, unidad_medida="unidad"),
            Producto(nombre="Tarta Limón",      categoria=CategoriaProductoEnum.pasteleria, unidad_medida="porción"),
            Producto(nombre="Café Molido",      categoria=CategoriaProductoEnum.insumo,    unidad_medida="kg"),
            Producto(nombre="Jarabe Vainilla",  categoria=CategoriaProductoEnum.insumo,    unidad_medida="litro"),
            Producto(nombre="Cocoa",            categoria=CategoriaProductoEnum.insumo,    unidad_medida="kg"),
            Producto(nombre="Vasos 8oz",        categoria=CategoriaProductoEnum.insumo,    unidad_medida="unidad"),
            Producto(nombre="Vasos 12oz",       categoria=CategoriaProductoEnum.insumo,    unidad_medida="unidad"),
        ]
        db.add_all(productos); db.flush()

        stocks  = [15, 10, 5, 3, 12, 8, 6, 4, 2, 3, 1, 100, 80]
        minimos = [5,  3,  2, 1, 5,  3, 3, 2, 1, 1, 0.5, 20, 20]
        for p, s, m in zip(productos, stocks, minimos):
            db.add(Inventario(producto_id=p.id, tienda_id=t1.id, stock_actual=s,       stock_minimo=m))
            db.add(Inventario(producto_id=p.id, tienda_id=t2.id, stock_actual=s * 0.5, stock_minimo=m))

        db.commit()
        logger.info("Seed completado: 2 tiendas, 9 usuarios, 13 productos.")
    except Exception as exc:
        db.rollback()
        logger.error("Error en seed inicial: %s", exc)
    finally:
        db.close()

_seed_if_empty()


# ─── Migración de productos reales (idempotente) ───────────────────────────
def _migrate_productos_reales():
    """
    Añade los productos reales del café si no existen todavía.
    Elimina productos del seed falso (si no tienen movimientos).
    Idempotente — se puede ejecutar muchas veces sin problema.
    """
    from app.models.models import Tienda, Producto, Inventario, MovimientoInventario, LoteInventario, CategoriaProductoEnum
    db = SessionLocal()
    try:
        # Necesitamos tiendas para crear filas de inventario
        tiendas = db.query(Tienda).all()
        if not tiendas:
            return  # No hay tiendas → la base está vacía o en un estado inesperado

        # Nombres del seed inicial que deben eliminarse (si no tienen movimientos)
        SEED_FALSOS = [
            # Claramente falsos
            "Café Espresso", "Leche Oat", "Muffin Arándanos", "Brownie",
            "Tarta Limón", "Café Molido", "Jarabe Vainilla", "Vasos 8oz",
            # Con categoría/unidad incorrectas — se recrean desde la lista real
            "Leche Entera", "Azúcar", "Cocoa", "Croissant", "Vasos 12oz",
        ]
        from app.models.models import (PasteleriaDiaria, Merma, ConteoFisicoItem)
        _TABLAS_DEPENDIENTES = [
            PasteleriaDiaria, Merma, ConteoFisicoItem, LoteInventario, Inventario,
        ]
        for nombre_falso in SEED_FALSOS:
            p = db.query(Producto).filter_by(nombre=nombre_falso).first()
            if not p:
                continue
            tiene_mov = db.query(MovimientoInventario).filter_by(producto_id=p.id).first()
            if tiene_mov:
                continue  # No tocar si ya tiene historia real
            try:
                sp = db.begin_nested()
                for tabla in _TABLAS_DEPENDIENTES:
                    db.query(tabla).filter_by(producto_id=p.id).delete()
                db.delete(p)
                sp.commit()
                logger.info("Producto seed eliminado: %s", nombre_falso)
            except Exception as e:
                sp.rollback()
                logger.warning("No se pudo eliminar '%s' (dependencias): %s", nombre_falso, e)

        # Lista completa de productos reales
        PRODUCTOS_REALES = [
            # (categoria_enum, nombre, unidad_medida)
            # ── PASTELERÍA
            (CategoriaProductoEnum.pasteleria, "Almojábanas",             "und"),
            (CategoriaProductoEnum.pasteleria, "Croissant Queso",         "und"),
            (CategoriaProductoEnum.pasteleria, "Croissant Chocolate",     "und"),
            (CategoriaProductoEnum.pasteleria, "Croissant Mantequilla",   "und"),
            (CategoriaProductoEnum.pasteleria, "Muffin Mora",             "und"),
            (CategoriaProductoEnum.pasteleria, "Muffin Vainilla",         "und"),
            (CategoriaProductoEnum.pasteleria, "Muffin Queso",            "und"),
            (CategoriaProductoEnum.pasteleria, "Muffin Naranja",          "und"),
            (CategoriaProductoEnum.pasteleria, "Alfajor",                 "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Chocolate",         "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Zanahoria",         "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Naranja",           "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Red Velvet",        "und"),
            (CategoriaProductoEnum.pasteleria, "Brownies",                "und"),
            (CategoriaProductoEnum.pasteleria, "Cake Zanahoria",          "und"),
            (CategoriaProductoEnum.pasteleria, "Cake Banano",             "und"),
            (CategoriaProductoEnum.pasteleria, "Wafles Pandebono",        "und"),
            (CategoriaProductoEnum.pasteleria, "Pastel Pollo",            "und"),
            (CategoriaProductoEnum.pasteleria, "Pastel Carne",            "und"),
            (CategoriaProductoEnum.pasteleria, "Pastel Queso",            "und"),
            (CategoriaProductoEnum.pasteleria, "Masa Pandebono",          "und"),
            (CategoriaProductoEnum.pasteleria, "Omelette",                "und"),
            (CategoriaProductoEnum.pasteleria, "Omelette Queso",          "und"),
            (CategoriaProductoEnum.pasteleria, "Pan Pollo",               "und"),
            (CategoriaProductoEnum.pasteleria, "Pan Esponjado",           "und"),
            (CategoriaProductoEnum.pasteleria, "Dedo de Queso",           "und"),
            # ── BEBIDA
            (CategoriaProductoEnum.bebida, "Café Alta Tostión x2500g",    "g"),
            (CategoriaProductoEnum.bebida, "Café Libra Medium 500g",      "und"),
            (CategoriaProductoEnum.bebida, "Café Descafeinado",           "g"),
            (CategoriaProductoEnum.bebida, "Leche Entera",                "und"),
            (CategoriaProductoEnum.bebida, "Leche Deslactosada",          "und"),
            (CategoriaProductoEnum.bebida, "Leche Condensada",            "g"),
            (CategoriaProductoEnum.bebida, "Leche en Polvo",              "g"),
            (CategoriaProductoEnum.bebida, "Sour Cream",                  "und"),
            (CategoriaProductoEnum.bebida, "Crema Chantilly",             "und"),
            (CategoriaProductoEnum.bebida, "Helado Vainilla",             "g"),
            (CategoriaProductoEnum.bebida, "Helado Chocolate",            "g"),
            (CategoriaProductoEnum.bebida, "Salsa Caramelo",              "g"),
            (CategoriaProductoEnum.bebida, "Salsa Chocolate",             "g"),
            (CategoriaProductoEnum.bebida, "Salsa Frutos Rojos",          "g"),
            (CategoriaProductoEnum.bebida, "Salsa Maracuyá",              "g"),
            (CategoriaProductoEnum.bebida, "Agua Normal Botella",         "und"),
            (CategoriaProductoEnum.bebida, "Agua con Gas Botella",        "und"),
            (CategoriaProductoEnum.bebida, "Pulpa Mango",                 "und"),
            (CategoriaProductoEnum.bebida, "Pulpa Lulo",                  "und"),
            (CategoriaProductoEnum.bebida, "Pulpa Mora",                  "und"),
            (CategoriaProductoEnum.bebida, "Pulpa Limón",                 "und"),
            (CategoriaProductoEnum.bebida, "Saborizante Vainilla",        "und"),
            (CategoriaProductoEnum.bebida, "Saborizante Canela",          "und"),
            (CategoriaProductoEnum.bebida, "Saborizante Macadamia",       "und"),
            (CategoriaProductoEnum.bebida, "Saborizante Frutos Amarillos","und"),
            (CategoriaProductoEnum.bebida, "Saborizante Kiwi Fresa",      "und"),
            (CategoriaProductoEnum.bebida, "Chai Latte",                  "g"),
            (CategoriaProductoEnum.bebida, "Azúcar",                      "g"),
            (CategoriaProductoEnum.bebida, "Azúcar Blanca Tubos",         "und"),
            (CategoriaProductoEnum.bebida, "Canela Molida",               "g"),
            (CategoriaProductoEnum.bebida, "Cocoa",                       "g"),
            (CategoriaProductoEnum.bebida, "Galleta Oreo",                "g"),
            (CategoriaProductoEnum.bebida, "Milo",                        "g"),
            (CategoriaProductoEnum.bebida, "Panela",                      "g"),
            (CategoriaProductoEnum.bebida, "Aromática Toronjil",          "und"),
            (CategoriaProductoEnum.bebida, "Aromática Limoncillo",        "und"),
            (CategoriaProductoEnum.bebida, "Aromática Cidrón",            "und"),
            (CategoriaProductoEnum.bebida, "Aromática Manzanilla",        "und"),
            (CategoriaProductoEnum.bebida, "Aromática Hierbabuena",       "und"),
            (CategoriaProductoEnum.bebida, "Licor Amaretto",              "und"),
            (CategoriaProductoEnum.bebida, "Licor Baileys",               "und"),
            (CategoriaProductoEnum.bebida, "Licor Black & White",         "und"),
            # ── INSUMO
            (CategoriaProductoEnum.insumo, "Vaso Cartón 9oz",             "und"),
            (CategoriaProductoEnum.insumo, "Vaso Cartón 12oz",            "und"),
            (CategoriaProductoEnum.insumo, "Vaso Cartón 16oz",            "und"),
            (CategoriaProductoEnum.insumo, "Vaso Cartón 4oz",             "und"),
            (CategoriaProductoEnum.insumo, "Vaso Plástico 7oz",           "und"),
            (CategoriaProductoEnum.insumo, "Tapa Viajera 12oz",           "und"),
            (CategoriaProductoEnum.insumo, "Tapa Pitillera 16oz",         "und"),
            (CategoriaProductoEnum.insumo, "Plato Blanco",                "und"),
            (CategoriaProductoEnum.insumo, "Caja Hamburguesa",            "und"),
            (CategoriaProductoEnum.insumo, "Bolsa Domicilio",             "und"),
            (CategoriaProductoEnum.insumo, "Bolsa Antigrasa",             "und"),
            (CategoriaProductoEnum.insumo, "Bolsa Kraft",                 "und"),
            (CategoriaProductoEnum.insumo, "Bolsa Basura",                "und"),
            (CategoriaProductoEnum.insumo, "Pitillo Papel",               "und"),
            (CategoriaProductoEnum.insumo, "Cuchara Postre Desechable",   "und"),
            (CategoriaProductoEnum.insumo, "Mezclador Ecológico",         "und"),
            (CategoriaProductoEnum.insumo, "Servilletas",                 "und"),
            (CategoriaProductoEnum.insumo, "Endulzante",                  "und"),
            (CategoriaProductoEnum.insumo, "Gel Antibacterial",           "und"),
            (CategoriaProductoEnum.insumo, "Guantes Transparentes x100",  "und"),
            (CategoriaProductoEnum.insumo, "Guantes Monocolor",           "und"),
            (CategoriaProductoEnum.insumo, "Rollo Impresora",             "und"),
            (CategoriaProductoEnum.insumo, "Paño Wypall",                 "und"),
            (CategoriaProductoEnum.insumo, "Esponjilla",                  "und"),
            (CategoriaProductoEnum.insumo, "Malla Suave",                 "und"),
            (CategoriaProductoEnum.insumo, "Papel Aluminio",              "g"),
            (CategoriaProductoEnum.insumo, "Papel Vinilpel",              "g"),
            (CategoriaProductoEnum.insumo, "Detergente en Polvo",         "g"),
            (CategoriaProductoEnum.insumo, "Limpiapisos",                 "g"),
            (CategoriaProductoEnum.insumo, "Jabón Loza",                  "g"),
            (CategoriaProductoEnum.insumo, "Limpiavidrios",               "g"),
            (CategoriaProductoEnum.insumo, "Blanqueador",                 "g"),
            (CategoriaProductoEnum.insumo, "Jabón de Manos",              "g"),
            (CategoriaProductoEnum.insumo, "Citronela",                   "und"),
            (CategoriaProductoEnum.insumo, "Trapeador",                   "und"),
            (CategoriaProductoEnum.insumo, "Escoba",                      "und"),
        ]

        # Obtener nombres ya existentes (después de las eliminaciones)
        nombres_existentes = {p.nombre.strip().lower()
                              for p in db.query(Producto).all()}
        creados = 0
        for cat, nombre, unidad in PRODUCTOS_REALES:
            if nombre.strip().lower() in nombres_existentes:
                continue
            p = Producto(nombre=nombre, categoria=cat,
                         unidad_medida=unidad, controla_stock=True)
            db.add(p)
            db.flush()
            for t in tiendas:
                db.add(Inventario(producto_id=p.id, tienda_id=t.id,
                                  stock_actual=0.0, stock_minimo=0.0))
            nombres_existentes.add(nombre.strip().lower())
            creados += 1

        db.commit()
        if creados:
            logger.info("Migración productos reales: %d productos añadidos.", creados)
    except Exception as exc:
        db.rollback()
        logger.error("Error en migración de productos reales: %s", exc)
    finally:
        db.close()


_migrate_productos_reales()

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
app.include_router(facturas.router, prefix="/api/v1")
app.include_router(compras.router, prefix="/api/v1")
app.include_router(comunicados.router, prefix="/api/v1")

# ─── Servir frontend React (solo en producción) ────────────────────────────────
_frontend_dist = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "dist")
)
_spa_mode = os.path.isdir(_frontend_dist)

if _spa_mode:
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="assets")

@app.get("/")
def root():
    if _spa_mode:
        return FileResponse(os.path.join(_frontend_dist, "index.html"))
    return {"status": "ok", "app": "Sistema Café v1.0"}

if _spa_mode:
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """SPA fallback: cualquier ruta que no sea /api/* devuelve index.html."""
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        index = os.path.join(_frontend_dist, "index.html")
        return FileResponse(index)
