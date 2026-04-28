"""
Actualiza el catálogo de productos con los insumos reales de Medium Café.
- Crea productos que no existan (por nombre exacto)
- Para cada tienda existente, crea un registro de inventario con stock=0 si no existe
- No borra ni modifica datos existentes
- Idempotente: puede correrse varias veces sin problema

Uso:
    cd backend
    python actualizar_productos.py

Opciones:
    python actualizar_productos.py --resetear-tiendas   # También crea VIDA / PALMETTO / JARDÍN PLAZA
"""
import sys, os
sys.path.append(os.path.dirname(__file__))

from app.database import SessionLocal, engine
from app.models import models  # noqa
from app.models.models import (
    Base, Tienda, Producto, Inventario, CategoriaProductoEnum
)

Base.metadata.create_all(bind=engine)

# ─── TIENDAS REALES ────────────────────────────────────────────────────────────
TIENDAS_REALES = [
    ("Vida",     "Sede Vida"),
    ("Palmetto", "Sede Palmetto Plaza"),
]

# ─── CATÁLOGO DE PRODUCTOS ─────────────────────────────────────────────────────
# (nombre, categoría, unidad_medida, controla_stock)
PRODUCTOS = [
    # ── PASTELERÍA ──────────────────────────────────────────────────────────────
    ("Almojábana",                   "pasteleria", "und",     True),
    ("Croissant de Queso",           "pasteleria", "und",     True),
    ("Croissant de Chocolate",       "pasteleria", "und",     True),
    ("Masa de Pandebono x25g",       "pasteleria", "und",     True),
    ("Torta de Chocolate",           "pasteleria", "porción", True),
    ("Torta de Zanahoria",           "pasteleria", "porción", True),
    ("Torta de Naranja",             "pasteleria", "porción", True),
    ("Torta Red Velvet",             "pasteleria", "porción", True),
    ("Pastel de Pollo",              "pasteleria", "und",     True),
    ("Palito de Queso",              "pasteleria", "und",     True),
    ("Omelette",                     "pasteleria", "und",     True),
    ("Omelette de Jamón y Queso",    "pasteleria", "und",     True),

    # ── BEBIDAS / INSUMOS CAFÉ ──────────────────────────────────────────────────
    ("Agua Medium Botella",          "bebida",     "und",     True),
    ("Agua Medium con Gas Botella",  "bebida",     "und",     True),
    ("Café Alta Tostión x2500g",     "bebida",     "und",     True),
    ("Café Libra Medium Exportación","bebida",     "und",     True),
    ("Café Descafeinado New Colony", "bebida",     "g",       True),
    ("Leche Entera / Deslactosada",  "bebida",     "und",     True),
    ("Leche Condensada",             "bebida",     "g",       True),
    ("Leche en Polvo",               "bebida",     "g",       True),
    ("Crema Chantilly",              "bebida",     "und",     True),
    ("Cocoa",                        "bebida",     "g",       True),
    ("Chai Latte",                   "bebida",     "g",       True),
    ("Té Matcha",                    "bebida",     "g",       True),
    ("Milo",                         "bebida",     "g",       True),
    ("Galleta Oreo",                 "bebida",     "g",       True),
    ("Helado Gogos Chocolate",       "bebida",     "g",       True),
    ("Helado Gogos Vainilla",        "bebida",     "g",       True),
    ("Salsa Sundae Caramelo",        "bebida",     "g",       True),
    ("Salsa Sundae Chocolate",       "bebida",     "g",       True),
    ("Salsa Sundae Frutos Rojos",    "bebida",     "g",       True),
    ("Salsa Maracuyá",               "bebida",     "g",       True),
    ("Sour Cream",                   "bebida",     "g",       True),
    ("Mezcla Granizado",             "bebida",     "g",       True),
    ("Espressos Fríos",              "bebida",     "g",       True),
    ("Pulpa de Lulo",                "bebida",     "und",     True),
    ("Pulpa de Mango",               "bebida",     "und",     True),
    ("Pulpa de Mora",                "bebida",     "und",     True),
    ("Pulpa de Limón",               "bebida",     "und",     True),
    ("Aromática",                    "bebida",     "und",     True),
    ("Azúcar a Granel x2500g",       "bebida",     "und",     True),
    ("Azúcar Blanca Tubos",          "bebida",     "g",       True),
    ("Endulzante Diet / Stevia",     "bebida",     "g",       True),
    ("Panela",                       "bebida",     "g",       True),
    ("Canela Molida",                "bebida",     "g",       True),
    ("Saborizante Vainilla",         "bebida",     "und",     True),
    ("Saborizante Canela Cinnamon",  "bebida",     "und",     True),
    ("Saborizante Macadamia",        "bebida",     "und",     True),
    ("Saborizante Frutos Amarillos", "bebida",     "und",     True),
    ("Saborizante Kiwi Fresa",       "bebida",     "und",     True),
    ("Licor Amaretto x750ml",        "bebida",     "und",     True),
    ("Licor Baileys x700ml",         "bebida",     "und",     True),
    ("Licor Baileys x1000ml",        "bebida",     "und",     True),
    ("Licor Whisky B&W x700ml",      "bebida",     "und",     True),
    ("Licor Whisky B&W x1000ml",     "bebida",     "und",     True),

    # ── DESECHABLES ────────────────────────────────────────────────────────────
    ("Vaso Cartón 4oz",              "insumo",     "und",     True),
    ("Vaso Cartón 9oz",              "insumo",     "und",     True),
    ("Vaso Cartón 12oz",             "insumo",     "und",     True),
    ("Vaso Cartón 16oz",             "insumo",     "und",     True),
    ("Vaso Plástico 7oz",            "insumo",     "und",     True),
    ("Tapa Viajera 12oz",            "insumo",     "und",     True),
    ("Tapa Pitillera 16oz",          "insumo",     "und",     True),
    ("Pitillos",                     "insumo",     "und",     True),
    ("Mezclador Eco Bambú",          "insumo",     "und",     True),
    ("Cuchara Desechable",           "insumo",     "und",     True),
    ("Servilletas",                  "insumo",     "und",     True),
    ("Bolsa Medium Kraft",           "insumo",     "und",     True),
    ("Bolsa #4 Papel",               "insumo",     "und",     True),
    ("Bolsa Domicilio",              "insumo",     "und",     True),
    ("Caja Hamburguesa",             "insumo",     "und",     True),
    ("Plato Cartón Medium",          "insumo",     "und",     True),

    # ── VAJILLA ────────────────────────────────────────────────────────────────
    ("Taza Americano",               "insumo",     "und",     False),
    ("Taza Latte",                   "insumo",     "und",     False),
    ("Taza Espresso",                "insumo",     "und",     False),
    ("Copa Cappuccino",              "insumo",     "und",     False),
    ("Copa Helado",                  "insumo",     "und",     False),
    ("Copa Malteada",                "insumo",     "und",     False),
    ("Plato Americano",              "insumo",     "und",     False),
    ("Plato Espresso",               "insumo",     "und",     False),
    ("Plato Brownie",                "insumo",     "und",     False),
    ("Cuchara Larga",                "insumo",     "und",     False),
    ("Cuchara Postrera",             "insumo",     "und",     False),
    ("Cuchara Coctelera",            "insumo",     "und",     False),
    ("Cuchara para Helado",          "insumo",     "und",     False),
    ("Cuchillo para Helado",         "insumo",     "und",     False),
    ("Cuchillo para Tortas Sierra",  "insumo",     "und",     False),
    ("Tenedor Omelette",             "insumo",     "und",     False),
    ("Cuchillo Omelette",            "insumo",     "und",     False),
    ("Jarra Acero Espresso",         "insumo",     "und",     False),
    ("Filtro Ciego Máq. Espresso",   "insumo",     "und",     False),

    # ── LIMPIEZA ───────────────────────────────────────────────────────────────
    ("Paño Wypall",                  "insumo",     "und",     True),
    ("Esponjilla Bombril",           "insumo",     "und",     True),
    ("Guante Monocolor (par)",       "insumo",     "und",     True),
    ("Guante Biofit Transp. x100",   "insumo",     "paq",     True),
    ("Bolsa Basura",                 "insumo",     "und",     True),
    ("Papel Extensible / Vinilpel",  "insumo",     "und",     True),
    ("Alcohol Glicerinado",          "insumo",     "und",     True),
    ("Blanqueador",                  "insumo",     "und",     True),
    ("Citronela",                    "insumo",     "und",     True),
    ("Detergente en Polvo",          "insumo",     "und",     True),
    ("Escoba",                       "insumo",     "und",     False),
    ("Jabón de Manos",               "insumo",     "und",     True),
    ("Jabón de Loza",                "insumo",     "und",     True),
    ("Limpiapisos",                  "insumo",     "und",     True),
    ("Limpiavidrios",                "insumo",     "und",     True),
    ("Malla Suave",                  "insumo",     "und",     True),
    ("Recogedor",                    "insumo",     "und",     False),
    ("Trapeador",                    "insumo",     "und",     False),
    ("Rollo Impresora",              "insumo",     "und",     True),
]

CAT_MAP = {
    "pasteleria": CategoriaProductoEnum.pasteleria,
    "bebida":     CategoriaProductoEnum.bebida,
    "insumo":     CategoriaProductoEnum.insumo,
}


def run(crear_tiendas: bool = False):
    db = SessionLocal()
    try:
        # 1. Tiendas reales (opcional)
        if crear_tiendas:
            for nombre, direccion in TIENDAS_REALES:
                existe = db.query(Tienda).filter(Tienda.nombre == nombre).first()
                if not existe:
                    db.add(Tienda(nombre=nombre, direccion=direccion))
                    print(f"  + Tienda: {nombre}")
                else:
                    print(f"  · Tienda ya existe: {nombre}")
            db.flush()

        tiendas = db.query(Tienda).all()
        if not tiendas:
            print("No hay tiendas en la base de datos.")
            print("Corre con --resetear-tiendas para crearlas, o créalas desde el sistema.")
            return

        print(f"\nTiendas activas: {[t.nombre for t in tiendas]}")

        # 2. Productos
        creados = 0
        for nombre, cat_str, unidad, controla in PRODUCTOS:
            existe = db.query(Producto).filter(Producto.nombre == nombre).first()
            if not existe:
                p = Producto(
                    nombre=nombre,
                    categoria=CAT_MAP[cat_str],
                    unidad_medida=unidad,
                    controla_stock=controla,
                )
                db.add(p)
                db.flush()  # para obtener p.id
                creados += 1

                # 3. Crear inventario vacío para cada tienda
                for t in tiendas:
                    db.add(Inventario(
                        producto_id=p.id,
                        tienda_id=t.id,
                        stock_actual=0.0,
                        stock_minimo=0.0,
                    ))
            else:
                # Asegurar registro de inventario en tiendas que aún no lo tengan
                for t in tiendas:
                    inv = db.query(Inventario).filter(
                        Inventario.producto_id == existe.id,
                        Inventario.tienda_id == t.id,
                    ).first()
                    if not inv:
                        db.add(Inventario(
                            producto_id=existe.id,
                            tienda_id=t.id,
                            stock_actual=0.0,
                            stock_minimo=0.0,
                        ))

        db.commit()
        total = db.query(Producto).count()
        print(f"\n✓ Productos nuevos insertados : {creados}")
        print(f"✓ Total productos en catálogo : {total}")
        print(f"✓ Registros de inventario actualizados para {len(tiendas)} tienda(s)")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    crear_tiendas = "--resetear-tiendas" in sys.argv
    run(crear_tiendas=crear_tiendas)
