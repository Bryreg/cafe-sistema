from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os, logging
from sqlalchemy import event
from app.database import engine, SessionLocal
from app.models.models import Base
from app.routers import (auth, caja, inventario, pasteleria, consignaciones,
                          dashboard, ventas, conteos, mermas, solicitudes,
                          informes, audit, alertas, notificaciones, limpieza,
                          facturas, compras, comunicados, pedidos, mantenimientos,
                          auditorias, pos, rutinas, novedades, temperaturas, recepciones,
                          inventario_mensual, dashboard_ejecutivo)
from app.routers import config_ticket
from app.routers import rentabilidad
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── SQLite: enforce foreign keys (dev/prod parity) ───────────────────────────
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in str(engine.url):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Migraciones inline ANTES de create_all
from sqlalchemy import text as _text
with engine.connect() as _conn:
    # Migrate entregas_turno: add tienda_id column if missing (never drop the table)
    try:
        _conn.execute(_text("ALTER TABLE entregas_turno ADD COLUMN tienda_id INTEGER"))
        _conn.commit()
    except Exception as e:
        _conn.rollback()
        logger.warning("Migration skipped (already applied or error): %s", e)
    for _sql in [
        "ALTER TABLE solicitudes_sencilla ADD COLUMN detalle TEXT",
        "ALTER TABLE caja_turnos ADD COLUMN tiene_conteo_apertura BOOLEAN DEFAULT FALSE",
        "ALTER TABLE caja_turnos ADD COLUMN tiene_ventas BOOLEAN DEFAULT FALSE",
        "ALTER TABLE caja_turnos ADD COLUMN tiene_conteo_cierre BOOLEAN DEFAULT FALSE",
        "ALTER TABLE caja_turnos ADD COLUMN datafono_real FLOAT",
        "ALTER TABLE caja_turnos ADD COLUMN diferencia_tarjeta FLOAT",
        "ALTER TABLE pasteleria_diaria ADD COLUMN activo BOOLEAN DEFAULT TRUE",
        # Etapa 6: timestamps operativos en turnos
        "ALTER TABLE caja_turnos ADD COLUMN ts_conteo_apertura TIMESTAMP",
        "ALTER TABLE caja_turnos ADD COLUMN ts_primera_venta TIMESTAMP",
        "ALTER TABLE caja_turnos ADD COLUMN ts_conteo_cierre TIMESTAMP",
        # Etapa 9: último acceso de usuario
        "ALTER TABLE usuarios ADD COLUMN ultimo_acceso TIMESTAMP",
        # pin_hash sigue mapeado en el modelo Usuario → toda query SELECT-ea esta columna.
        # Si falta en una DB preexistente, CUALQUIER consulta a usuarios (login incluido) da 500.
        "ALTER TABLE usuarios ADD COLUMN pin_hash VARCHAR(255)",
        # Mermas: tipo, traslado y seguimiento
        "ALTER TABLE mermas ADD COLUMN tipo VARCHAR(20) DEFAULT 'consumo'",
        "ALTER TABLE mermas ADD COLUMN tienda_destino_id INTEGER",
        "ALTER TABLE mermas ADD COLUMN recibido BOOLEAN DEFAULT FALSE",
        "ALTER TABLE mermas ADD COLUMN fecha_recibido TIMESTAMP",
        "ALTER TABLE movimientos_caja ADD COLUMN imagen_url VARCHAR(300)",
        "ALTER TABLE entregas_turno ADD COLUMN tipo VARCHAR(20) DEFAULT 'entrega' NOT NULL",
        "ALTER TABLE pasteleria_diaria ADD COLUMN numero_lote VARCHAR(100)",
        "ALTER TABLE pasteleria_diaria ADD COLUMN fecha_vencimiento TIMESTAMP",
        # Facturas de compra
        "ALTER TABLE facturas_compra ADD COLUMN numero_lote VARCHAR(100)",
        "ALTER TABLE facturas_compra ADD COLUMN fecha_recibido TIMESTAMP",
        # Conteos de compras
        "ALTER TABLE conteos_compras ADD COLUMN nota VARCHAR(300)",
        "ALTER TABLE conteos_compras ADD COLUMN fecha_ajuste TIMESTAMP",
        "ALTER TABLE conteos_compras ADD COLUMN usuario_ajuste_id INTEGER",
        # Integridad relacional: consignaciones ligadas a un turno específico
        "ALTER TABLE consignaciones ADD COLUMN caja_turno_id INTEGER REFERENCES caja_turnos(id)",
        # Panel de pedidos: proveedor fijo y tiempo de entrega por producto
        "ALTER TABLE productos ADD COLUMN proveedor VARCHAR(100)",
        "ALTER TABLE productos ADD COLUMN lead_time_dias INTEGER DEFAULT 2",
        "ALTER TABLE caja_turnos ADD COLUMN consignaciones_deducidas FLOAT DEFAULT 0",
        # Turno: tipo de turno (apertura/intermedio/cierre)
        "ALTER TABLE caja_turnos ADD COLUMN tipo_turno VARCHAR(20)",
        # Gate de operación: cuadre de llegada hecho (habilita el POS junto con el conteo de apertura)
        # IMPORTANTE: DEFAULT FALSE (no 0) — Postgres rechaza '0' como default de BOOLEAN.
        "ALTER TABLE caja_turnos ADD COLUMN tiene_cuadre_llegada BOOLEAN DEFAULT FALSE",
        # Fase 1: enlace al día operativo. SIN REFERENCES porque dias_operativos la crea
        # create_all() DESPUÉS de este loop; en Postgres un REFERENCES a tabla inexistente
        # abortaría el ALTER y la columna no se crearía. El FK real lo define el modelo.
        "ALTER TABLE caja_turnos ADD COLUMN dia_operativo_id INTEGER",
        "ALTER TABLE caja_turnos ADD COLUMN turno_anterior_id INTEGER",
        "ALTER TABLE caja_turnos ADD COLUMN secuencia_dia INTEGER",
        # POS nativo: precio de venta por producto (tickets/ticket_items los crea create_all)
        "ALTER TABLE productos ADD COLUMN precio_venta NUMERIC(12,2) DEFAULT 0",
        # Saneo: alinear precio_venta a NOT NULL (el modelo lo declara así). SQLite ignora ALTER COLUMN.
        "UPDATE productos SET precio_venta = 0 WHERE precio_venta IS NULL",
        "ALTER TABLE productos ALTER COLUMN precio_venta SET NOT NULL",
        # POS: descuento por ticket (suma) y por linea de producto
        "ALTER TABLE tickets ADD COLUMN descuento NUMERIC(12,2) DEFAULT 0",
        "ALTER TABLE ticket_items ADD COLUMN descuento NUMERIC(12,2) DEFAULT 0",
        # Barista activa persistente: barista REAL que opera (≠ usuario_id del dispositivo/kiosko).
        # barista_id es una columna PLANA (sin FK) para no introducir un segundo ForeignKey a
        # usuarios y disparar AmbiguousForeignKeysError en el mapper. barista_nombre es el snapshot
        # de display (sin join). El usuario_id existente se mantiene como "dispositivo".
        "ALTER TABLE mermas ADD COLUMN barista_id INTEGER",
        "ALTER TABLE mermas ADD COLUMN barista_nombre VARCHAR(100)",
        "ALTER TABLE conteos_fisicos ADD COLUMN barista_id INTEGER",
        "ALTER TABLE conteos_fisicos ADD COLUMN barista_nombre VARCHAR(100)",
        "ALTER TABLE facturas_compra ADD COLUMN barista_id INTEGER",
        "ALTER TABLE facturas_compra ADD COLUMN barista_nombre VARCHAR(100)",
        "ALTER TABLE consignaciones ADD COLUMN barista_id INTEGER",
        "ALTER TABLE consignaciones ADD COLUMN barista_nombre VARCHAR(100)",
        "ALTER TABLE entregas_turno ADD COLUMN barista_id INTEGER",
        "ALTER TABLE entregas_turno ADD COLUMN barista_nombre VARCHAR(100)",
        "ALTER TABLE movimientos_caja ADD COLUMN barista_id INTEGER",
        "ALTER TABLE movimientos_caja ADD COLUMN barista_nombre VARCHAR(100)",
        "ALTER TABLE rutina_eventos ADD COLUMN barista_id INTEGER",
        "ALTER TABLE rutina_eventos ADD COLUMN barista_nombre VARCHAR(100)",
        # Inventario mensual: atribución de barista (el modelo las declara e inserta).
        "ALTER TABLE inventarios_mensuales ADD COLUMN barista_id INTEGER",
        "ALTER TABLE inventarios_mensuales ADD COLUMN barista_nombre VARCHAR(100)",
        # Movimientos de inventario: atribución de barista en kiosko compartido (plano, sin FK).
        "ALTER TABLE movimientos_inventario ADD COLUMN barista_id INTEGER",
        "ALTER TABLE movimientos_inventario ADD COLUMN barista_nombre VARCHAR(100)",
        # Limpieza semanal: barista REAL que marcó (antes solo el usuario del kiosko).
        "ALTER TABLE limpieza_semanal ADD COLUMN barista_id INTEGER",
        "ALTER TABLE limpieza_semanal ADD COLUMN barista_nombre VARCHAR(100)",
        # Pagos a proveedores: valor pagado, forma de pago real y foto del soporte de pago.
        "ALTER TABLE facturas_compra ADD COLUMN valor_pagado NUMERIC(12,2) DEFAULT 0",
        "ALTER TABLE facturas_compra ADD COLUMN forma_pago_real VARCHAR(40)",
        "ALTER TABLE facturas_compra ADD COLUMN imagen_soporte_url VARCHAR(300)",
        # Trazabilidad de lotes: proveedor/lote/fabricación/factura/agotado.
        "ALTER TABLE lotes_inventario ADD COLUMN numero_lote VARCHAR(100)",
        "ALTER TABLE lotes_inventario ADD COLUMN proveedor VARCHAR(150)",
        "ALTER TABLE lotes_inventario ADD COLUMN fecha_fabricacion TIMESTAMP",
        "ALTER TABLE lotes_inventario ADD COLUMN factura_id INTEGER",
        "ALTER TABLE lotes_inventario ADD COLUMN fecha_agotado TIMESTAMP",
        # Atribución de VENTAS por barista en kiosko compartido (plano, sin FK).
        "ALTER TABLE tickets ADD COLUMN barista_id INTEGER",
        "ALTER TABLE tickets ADD COLUMN barista_nombre VARCHAR(100)",
        # Módulo 6: umbrales de stock configurables (ideal hacia el que reponer, crítico para alerta roja)
        "ALTER TABLE inventario ADD COLUMN stock_ideal FLOAT DEFAULT 0",
        "ALTER TABLE inventario ADD COLUMN stock_critico FLOAT DEFAULT 0",
        # Salida parcial de barista sin cerrar el turno
        "ALTER TABLE turno_baristas ADD COLUMN salida_at TIMESTAMP",
        # Concurrency: only one open shift per store at any time
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_turno_abierto ON caja_turnos (tienda_id) WHERE estado = 'abierto'",
        # Concurrency: only one conteo of each type (apertura/cierre) per shift
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_conteo_turno_tipo ON conteos_fisicos (turno_id, tipo)",
        # Perf: ventas del día por tienda (lo consulta crear_ticket en cada venta para la
        # regla ventas_dia, y los informes/dashboard). Filtrar por rango de fecha usa este índice.
        "CREATE INDEX IF NOT EXISTS ix_tickets_tienda_fecha ON tickets (tienda_id, fecha)",
        "ALTER TABLE productos ADD COLUMN incluir_en_conteo BOOLEAN DEFAULT TRUE",
        # Config ticket: dimensiones de impresión
        "ALTER TABLE config_tickets ADD COLUMN ancho_papel_mm INTEGER DEFAULT 80",
        "ALTER TABLE config_tickets ADD COLUMN escala_fuente VARCHAR(10) DEFAULT 'normal'",
        "ALTER TABLE config_tickets ADD COLUMN margen_mm INTEGER DEFAULT 2",
        # Categoría nueva "porciones" en el enum nativo de Postgres (en SQLite el ALTER TYPE
        # falla y se ignora; el enum allí es varchar). PG 12+ permite ADD VALUE en transacción.
        "ALTER TYPE categoriaproductoenum ADD VALUE IF NOT EXISTS 'porciones'",
        # Inventario a granel: unidades selladas + nivel de la abierta (dibujo bolsa/botella).
        "ALTER TABLE productos ADD COLUMN fraccionable BOOLEAN DEFAULT FALSE",
        "ALTER TABLE productos ADD COLUMN envase VARCHAR(10)",
        # Desglose del efectivo esperado congelado al momento de cada cuadre (transparencia para
        # la barista y trazabilidad histórica en el hub admin). esperado = base + ventas_efectivo
        # + ingresos - egresos, todos capturados en el instante del cuadre (no recalculados).
        "ALTER TABLE entregas_turno ADD COLUMN base_snapshot NUMERIC(12,2)",
        "ALTER TABLE entregas_turno ADD COLUMN ventas_efectivo_snapshot NUMERIC(12,2)",
        "ALTER TABLE entregas_turno ADD COLUMN ingresos_snapshot NUMERIC(12,2)",
        "ALTER TABLE entregas_turno ADD COLUMN egresos_snapshot NUMERIC(12,2)",
        # Caja fuerte: reserva fija guardada aparte de la registradora. Se registra para
        # control pero NO entra en efectivo_esperado. La base es solo el efectivo operativo.
        "ALTER TABLE caja_turnos ADD COLUMN caja_fuerte NUMERIC(12,2) DEFAULT 0",
        # Cuadre con venta de ayer separada: la barista cuenta SOLO la registradora; el
        # monto separado (base del día anterior) queda documentado sin contar en base_snapshot.
        "ALTER TABLE entregas_turno ADD COLUMN base_separada BOOLEAN DEFAULT FALSE",
        # Insumos a granel en gramos: contenido de la unidad sellada (gr por bolsa) para
        # contar bolsas cerradas × contenido + gramos pesados de la abierta (gramera).
        "ALTER TABLE productos ADD COLUMN contenido_por_unidad FLOAT",
        # Orden fijo del conteo/inventario (planilla de la encargada de pedidos).
        "ALTER TABLE productos ADD COLUMN orden_conteo INTEGER",
        # Grupo de conteo: NULL = conteo diario normal; 'desechables' = solo se cuenta
        # cuando el admin lo solicita (formato de desechables).
        "ALTER TABLE productos ADD COLUMN grupo_conteo VARCHAR(20)",
        # Producto sustituto/reserva para consumo por receta (ej. leche entera → deslactosada).
        "ALTER TABLE productos ADD COLUMN sustituto_id INTEGER",
        # Gr/ml por empaque comercial: Recibir convierte "N botellas" → gramos.
        "ALTER TABLE productos ADD COLUMN contenido_por_empaque FLOAT",
        # Sobrante de apertura a bancar con el turno (solo turnos post-fix; viejos NULL).
        "ALTER TABLE caja_turnos ADD COLUMN sobrante_consignable FLOAT",
        # Conteo de desechables: nuevo tipo en el enum nativo de Postgres.
        "ALTER TYPE tipoconteoenum ADD VALUE IF NOT EXISTS 'desechables'",
        "ALTER TYPE tipoconteoenum ADD VALUE IF NOT EXISTS 'existencia'",
        # El unique (turno_id, tipo) solo aplica a apertura/cierre: los desechables pueden
        # contarse más de una vez en el mismo turno si el admin lo vuelve a pedir. En prod
        # el unique vive como CONSTRAINT de tabla (create_all original) — hay que dropear
        # el constraint (no solo el índice) antes de crear el índice parcial.
        "ALTER TABLE conteos_fisicos DROP CONSTRAINT IF EXISTS uq_conteo_turno_tipo",
        "DROP INDEX IF EXISTS uq_conteo_turno_tipo",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_conteo_turno_tipo ON conteos_fisicos (turno_id, tipo) WHERE tipo IN ('apertura', 'cierre')",
        # Mermas de consumo: quién consumió (dueños/reuniones), aparte de quién registró.
        "ALTER TABLE mermas ADD COLUMN quien VARCHAR(100)",
        # Pedido: unidad elegida por la barista (gr/unidad/lt/paquete), aparte de la del producto.
        "ALTER TABLE solicitudes_pedido_items ADD COLUMN unidad_solicitada VARCHAR(20)",
        # Huella del atajo "Todo coincide con sistema": distingue conteo fisico real de un eco.
        "ALTER TABLE conteos_fisicos ADD COLUMN es_atajo BOOLEAN DEFAULT FALSE",
        # Vínculo estructural egreso↔factura de proveedor (antes solo texto del concepto,
        # que se rompía al renombrar proveedor/número). Lo usa rentabilidad y eliminar_factura.
        "ALTER TABLE movimientos_caja ADD COLUMN factura_id INTEGER",
        # Costo oficial por unidad fijado a mano (verificador de facturas). Manda sobre
        # el promedio de facturas en rentabilidad.
        "ALTER TABLE productos ADD COLUMN precio_costo FLOAT",
    ]:
        try:
            _conn.execute(_text(_sql))
            _conn.commit()
        except Exception as e:
            _conn.rollback()  # necesario en PostgreSQL: libera el estado de error antes del siguiente statement
            logger.warning("Migration skipped (already applied or error): %s", e)  # columna ya existe

Base.metadata.create_all(bind=engine)

# ─── PIN de kiosko: sembrar fila en `configuracion` si no existe ───────────
# Migra el PIN del env var KIOSK_PIN a la DB para que el admin lo edite desde el hub.
# Idempotente: solo inserta si la clave no está. Fallback "2026" si el env var está vacío.
def _seed_kiosk_pin():
    from app.models.models import Configuracion
    db = SessionLocal()
    try:
        existe = db.query(Configuracion).filter(Configuracion.clave == "kiosk_pin").first()
        if not existe:
            db.add(Configuracion(clave="kiosk_pin", valor=settings.KIOSK_PIN or "2026"))
            db.commit()
            logger.info("Configuracion.kiosk_pin sembrada en DB")
    except Exception as e:
        db.rollback()
        logger.warning("No se pudo sembrar kiosk_pin: %s", e)
    finally:
        db.close()

_seed_kiosk_pin()

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


def _seed_tareas_limpieza():
    """Crea el catálogo de 13 tareas de limpieza para cada tienda que aún no lo tenga."""
    from app.models.models import Tienda, TareaLimpieza
    DEFAULTS = [
        {"key": "pisos_puntos_ciegos", "label": "Aseo general pisos y puntos ciegos"},
        {"key": "computador_caja",     "label": "Limpieza del computador, cajón monedero, impresora, teléfono, datafono"},
        {"key": "congelador_helado",   "label": "Lavar congelador de helado"},
        {"key": "nevera_pasteleria",   "label": "Lavar nevera de pastelería"},
        {"key": "nevera_leche",        "label": "Lavar nevera de leche"},
        {"key": "trampa_grasas",       "label": "Lavar trampa de grasas"},
        {"key": "gabinetes_cajones",   "label": "Asear y organizar gabinetes, puertas, cajones y materias primas por fecha"},
        {"key": "maquinas",            "label": "Aseo de máquinas (licuadoras, hornos y molinos)"},
        {"key": "recipientes",         "label": "Limpieza de recipientes (Milo, Oreo, granizado, café descafeinado, azúcar)"},
        {"key": "loza",                "label": "Limpieza y desmanchado de loza (tazas, platos y copas)"},
        {"key": "utensilios",          "label": "Desinfección de utensilios (jarras, espresso, cucharas, jigger, cuchillos)"},
        {"key": "avisos_pop",          "label": "Limpieza de avisos y material POP"},
        {"key": "sillas_mesas_barra",  "label": "Sillas, mesas y barra (aseo general patas y por debajo)"},
    ]
    db = SessionLocal()
    try:
        for tienda in db.query(Tienda).all():
            if db.query(TareaLimpieza).filter_by(tienda_id=tienda.id).count() == 0:
                for i, t in enumerate(DEFAULTS):
                    db.add(TareaLimpieza(tienda_id=tienda.id, key=t["key"], label=t["label"], orden=i))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Seed tareas_limpieza error: %s", e)
    finally:
        db.close()

_seed_tareas_limpieza()


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

        # Nombres que deben eliminarse si no tienen movimientos reales
        SEED_FALSOS = [
            # Claramente falsos (seed inicial)
            "Café Espresso", "Leche Oat", "Muffin Arándanos", "Brownie",
            "Tarta Limón", "Café Molido", "Jarabe Vainilla", "Vasos 8oz",
            # Con categoría/unidad incorrectas — se recrean desde la lista real
            "Leche Entera", "Azúcar", "Cocoa", "Croissant", "Vasos 12oz",
            # Obsoletos — nombres viejos o productos que ya no se manejan
            "Palito de Queso", "Dedo de Queso", "Pan Esponjado",
            "Omelette Queso", "Pastel Pollo",
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
            (CategoriaProductoEnum.pasteleria, "Croissant Chocolate",     "und"),
            (CategoriaProductoEnum.pasteleria, "Croissant Mantequilla",   "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Chocolate",         "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Zanahoria",         "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Naranja",           "und"),
            (CategoriaProductoEnum.pasteleria, "Torta Red Velvet",        "und"),
            (CategoriaProductoEnum.pasteleria, "Pastel de Pollo",         "und"),
            (CategoriaProductoEnum.pasteleria, "Masa Pandebono",          "und"),
            (CategoriaProductoEnum.pasteleria, "Omelette",                "und"),
            (CategoriaProductoEnum.pasteleria, "Omelette Jamón y Queso", "und"),
            (CategoriaProductoEnum.pasteleria, "Esponjado de Queso",      "und"),
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


# ─── Migración de proveedores y lead times (idempotente) ──────────────────────
def _migrate_proveedores():
    """
    Asigna proveedor fijo y lead_time_dias a los productos conocidos.
    Para el resto fija el lead_time según categoría.
    Idempotente — siempre sobreescribe los fijos, respeta customizaciones del resto.
    """
    from app.models.models import Producto, CategoriaProductoEnum
    db = SessionLocal()
    try:
        # Renombrar/fusionar productos a sus nombres correctos (idempotente)
        from app.models.models import Inventario as _Inv
        RENOMBRES = {
            "Omelette Queso":  "Omelette Jamón y Queso",
            "Pastel Pollo":    "Pastel de Pollo",
            "Pan Esponjado":   "Esponjado de Queso",
            "Dedo de Queso":   "Esponjado de Queso",   # mismo producto
            "Palito de Queso": "Esponjado de Queso",   # mismo producto
        }
        for nombre_viejo, nombre_nuevo in RENOMBRES.items():
            p_viejo = db.query(Producto).filter_by(nombre=nombre_viejo).first()
            if not p_viejo:
                continue
            p_nuevo = db.query(Producto).filter_by(nombre=nombre_nuevo).first()
            if not p_nuevo:
                # Caso normal: solo existe el nombre viejo → renombrar
                p_viejo.nombre = nombre_nuevo
                logger.info("Producto renombrado: %s → %s", nombre_viejo, nombre_nuevo)
            else:
                # Ambos existen (duplicado por orden de migración) → fusionar stock y ocultar el viejo
                for inv_v in db.query(_Inv).filter_by(producto_id=p_viejo.id).all():
                    inv_n = db.query(_Inv).filter_by(
                        producto_id=p_nuevo.id, tienda_id=inv_v.tienda_id
                    ).first()
                    if inv_n and inv_v.stock_actual:
                        inv_n.stock_actual += inv_v.stock_actual
                    inv_v.stock_actual = 0.0
                p_viejo.controla_stock = False
                # También fuera del conteo: la lista de conteo filtra por incluir_en_conteo,
                # no por controla_stock — sin esto el duplicado viejo aparece repetido al contar.
                p_viejo.incluir_en_conteo = False
                logger.info("Duplicado fusionado: '%s' → '%s' (viejo oculto)", nombre_viejo, nombre_nuevo)
        db.flush()

        # Productos que ya no se manejan → ocultar de todo el sistema
        DESACTIVAR = {
            "Panela",
            "Pastel Carne", "Pastel Queso", "Pan Pollo", "Wafles Pandebono",
            "Cake Zanahoria", "Cake Banano", "Brownies", "Alfajor",
            "Muffin Mora", "Muffin Vainilla", "Muffin Queso", "Muffin Naranja",
            "Croissant Queso",
            # nombres viejos — por si sobreviven con movimientos y no pudieron borrarse
            "Palito de Queso", "Dedo de Queso", "Pan Esponjado",
            "Omelette Queso", "Pastel Pollo",
        }
        for p in db.query(Producto).filter(Producto.nombre.in_(DESACTIVAR)).all():
            if p.controla_stock or p.incluir_en_conteo:
                p.controla_stock = False
                p.incluir_en_conteo = False  # fuera del conteo también (la lista filtra por este flag)
                logger.info("Producto desactivado: %s", p.nombre)
        db.flush()

        FIJOS = {
            # La Paola — entrega al día siguiente
            "Omelette":               ("La Paola", 1),
            "Omelette Jamón y Queso": ("La Paola", 1),
            "Pastel de Pollo":        ("La Paola", 1),
            "Esponjado de Queso":     ("La Paola", 1),
            # Delitas — entrega al día siguiente si se pide antes del mediodía
            "Croissant Chocolate":    ("Delitas", 1),
            "Croissant Mantequilla":  ("Delitas", 1),
            # Wilenses
            "Almojábanas":            ("Wilenses", 1),
            # María María — tortas y repostería
            "Torta Chocolate":        ("María María", 1),
            "Torta Zanahoria":        ("María María", 1),
            "Torta Naranja":          ("María María", 1),
            "Torta Red Velvet":       ("María María", 1),
            # Maxipulpas
            "Pulpa Mango":            ("Maxipulpas", 2),
            "Pulpa Lulo":             ("Maxipulpas", 2),
            "Pulpa Mora":             ("Maxipulpas", 2),
            "Pulpa Limón":            ("Maxipulpas", 2),
        }
        # Productos con entrega lenta (helados, saborizantes, licores, desechables)
        LENTOS = {
            "Helado Vainilla", "Helado Chocolate",
            "Saborizante Vainilla", "Saborizante Canela", "Saborizante Macadamia",
            "Saborizante Frutos Amarillos", "Saborizante Kiwi Fresa",
            "Licor Amaretto", "Licor Baileys", "Licor Black & White",
        }
        for p in db.query(Producto).all():
            if p.nombre in FIJOS:
                p.proveedor, p.lead_time_dias = FIJOS[p.nombre]
            elif p.proveedor:
                pass  # ya tiene proveedor asignado manualmente → no tocar
            elif p.nombre in LENTOS:
                p.lead_time_dias = 5
            elif p.categoria == CategoriaProductoEnum.pasteleria:
                p.lead_time_dias = 1
            elif p.categoria == CategoriaProductoEnum.insumo:
                p.lead_time_dias = 5
            else:  # bebida
                p.lead_time_dias = 2
        db.commit()
        logger.info("Migración proveedores/lead_time completada.")
    except Exception as exc:
        db.rollback()
        logger.error("Error en migración proveedores: %s", exc)
    finally:
        db.close()


_migrate_proveedores()


def _seed_rutinas():
    """Crea plantillas de rutina por defecto (globales) si no existen. Idempotente por clave."""
    from app.models.models import RutinaPlantilla, CategoriaRutinaEnum, FrecuenciaRutinaEnum
    db = SessionLocal()
    try:
        defaults = [
            ("limpieza_general",  "Limpieza general",               CategoriaRutinaEnum.limpieza,     FrecuenciaRutinaEnum.por_turno, 1, False, False),
            ("revision_banos",    "Revisión de baños",              CategoriaRutinaEnum.banos,        FrecuenciaRutinaEnum.por_turno, 2, False, False),
            ("surtido_vitrina",   "Surtido de vitrina",             CategoriaRutinaEnum.vitrina,      FrecuenciaRutinaEnum.por_turno, 1, False, False),
            ("control_temp_nevera", "Control de temperatura (nevera)", CategoriaRutinaEnum.temperatura, FrecuenciaRutinaEnum.por_turno, 1, False, True),
            # Panel de turno — rutinas de 1 clic
            ("limpieza",  "Limpieza General",  CategoriaRutinaEnum.limpieza, FrecuenciaRutinaEnum.por_turno, 1, False, False),
            ("surtido",   "Surtido",           CategoriaRutinaEnum.surtido,  FrecuenciaRutinaEnum.por_turno, 1, False, False),
            ("vitrina",   "Revisión Vitrina",  CategoriaRutinaEnum.vitrina,  FrecuenciaRutinaEnum.por_turno, 1, False, False),
            ("novedad",   "Novedad",           CategoriaRutinaEnum.otro,     FrecuenciaRutinaEnum.por_turno, 0, False, False),
            ("merma_op",  "Merma rápida",      CategoriaRutinaEnum.otro,     FrecuenciaRutinaEnum.por_turno, 0, False, False),
        ]
        creadas = 0
        for clave, nombre, cat, frec, esp, eimg, eval_ in defaults:
            existe = db.query(RutinaPlantilla).filter(
                RutinaPlantilla.clave == clave, RutinaPlantilla.tienda_id.is_(None)
            ).first()
            if not existe:
                db.add(RutinaPlantilla(
                    clave=clave, nombre=nombre, categoria=cat, frecuencia=frec,
                    esperadas_por_periodo=esp, requiere_evidencia=eimg, requiere_valor=eval_,
                    tienda_id=None, activa=True,
                ))
                creadas += 1
        db.commit()
        if creadas:
            logger.info("_seed_rutinas: %s plantillas de rutina creadas.", creadas)
    except Exception as e:
        db.rollback()
        logger.warning("_seed_rutinas: %s", e)
    finally:
        db.close()


_seed_rutinas()


def _seed_equipos():
    """Equipos de frío por defecto por sede, si no existen. Idempotente por (tienda, nombre)."""
    from app.models.models import Tienda, EquipoFrio, TipoEquipoEnum
    db = SessionLocal()
    try:
        defaults = [
            ("Nevera barra", TipoEquipoEnum.refrigerador, 0.0, 8.0),
            ("Congelador", TipoEquipoEnum.congelador, -18.0, -8.0),
            ("Vitrina pastelería", TipoEquipoEnum.nevera_vitrina, 2.0, 8.0),
        ]
        for tienda in db.query(Tienda).filter(Tienda.activa == True).all():
            for nombre, tipo, tmin, tmax in defaults:
                existe = db.query(EquipoFrio).filter(
                    EquipoFrio.tienda_id == tienda.id, EquipoFrio.nombre == nombre
                ).first()
                if not existe:
                    db.add(EquipoFrio(tienda_id=tienda.id, nombre=nombre, tipo=tipo,
                                      temp_min=tmin, temp_max=tmax, activo=True))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("_seed_equipos: %s", e)
    finally:
        db.close()


_seed_equipos()


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
app.include_router(pedidos.router, prefix="/api/v1")
app.include_router(mantenimientos.router, prefix="/api/v1")
app.include_router(auditorias.router, prefix="/api/v1")
app.include_router(pos.router, prefix="/api/v1")
app.include_router(rutinas.router, prefix="/api/v1")
app.include_router(novedades.router, prefix="/api/v1")
app.include_router(temperaturas.router, prefix="/api/v1")
app.include_router(recepciones.router, prefix="/api/v1")
app.include_router(inventario_mensual.router, prefix="/api/v1")
app.include_router(dashboard_ejecutivo.router, prefix="/api/v1")
app.include_router(config_ticket.router,     prefix="/api/v1")
app.include_router(rentabilidad.router,      prefix="/api/v1")

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
