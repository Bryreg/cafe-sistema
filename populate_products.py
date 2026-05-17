"""
Popula la base de datos de producción con los productos reales del café.
Elimina los productos de seed falsos (si no tienen movimientos) y crea los reales.
"""
import requests, sys

API = "https://cafe-sistema-oert.onrender.com/api/v1"

# ─── Autenticar ─────────────────────────────────────────────────────────────
r = requests.post(f"{API}/auth/login", json={"email": "admin@cafe.com", "password": "admin123"})
if r.status_code != 200:
    print("Error autenticando:", r.text); sys.exit(1)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("✓ Autenticado como admin")

# ─── Obtener productos actuales ──────────────────────────────────────────────
productos_actuales = requests.get(f"{API}/inventario/productos", headers=headers).json()
nombres_existentes = {p["nombre"].strip().lower() for p in productos_actuales}
ids_por_nombre = {p["nombre"].strip().lower(): p["id"] for p in productos_actuales}
print(f"Productos actuales en BD: {len(productos_actuales)}")

# ─── Productos SEED a eliminar (nombres falsos del seed inicial) ─────────────
SEED_FALSOS = [
    "Café Espresso", "Leche Oat", "Muffin Arándanos", "Brownie", "Tarta Limón",
    "Café Molido", "Jarabe Vainilla", "Vasos 8oz",
]

for nombre in SEED_FALSOS:
    key = nombre.strip().lower()
    if key in ids_por_nombre:
        pid = ids_por_nombre[key]
        resp = requests.delete(f"{API}/inventario/productos/{pid}", headers=headers)
        if resp.status_code == 200:
            print(f"  🗑  Eliminado: {nombre}")
            nombres_existentes.discard(key)
        else:
            print(f"  ⚠  No se pudo eliminar '{nombre}': {resp.json().get('detail','')}")

# ─── Lista de productos reales ───────────────────────────────────────────────
# (categoria, nombre, unidad_medida)
PRODUCTOS_REALES = [
    # ── PASTELERÍA ────────────────────────────────────────────────────────────
    ("pasteleria", "Almojábanas",           "und"),
    ("pasteleria", "Croissant Queso",       "und"),
    ("pasteleria", "Croissant Chocolate",   "und"),
    ("pasteleria", "Croissant Mantequilla", "und"),
    ("pasteleria", "Muffin Mora",           "und"),
    ("pasteleria", "Muffin Vainilla",       "und"),
    ("pasteleria", "Muffin Queso",          "und"),
    ("pasteleria", "Muffin Naranja",        "und"),
    ("pasteleria", "Alfajor",               "und"),
    ("pasteleria", "Torta Chocolate",       "und"),
    ("pasteleria", "Torta Zanahoria",       "und"),
    ("pasteleria", "Torta Naranja",         "und"),
    ("pasteleria", "Torta Red Velvet",      "und"),
    ("pasteleria", "Brownies",              "und"),
    ("pasteleria", "Cake Zanahoria",        "und"),
    ("pasteleria", "Cake Banano",           "und"),
    ("pasteleria", "Wafles Pandebono",      "und"),
    ("pasteleria", "Pastel Pollo",          "und"),
    ("pasteleria", "Pastel Carne",          "und"),
    ("pasteleria", "Pastel Queso",          "und"),
    ("pasteleria", "Masa Pandebono",        "und"),
    ("pasteleria", "Omelette",              "und"),
    ("pasteleria", "Omelette Queso",        "und"),
    ("pasteleria", "Pan Pollo",             "und"),
    ("pasteleria", "Pan Esponjado",         "und"),
    ("pasteleria", "Dedo de Queso",         "und"),

    # ── BEBIDA ────────────────────────────────────────────────────────────────
    ("bebida", "Café Alta Tostión x2500g",   "g"),
    ("bebida", "Café Libra Medium 500g",     "und"),
    ("bebida", "Café Descafeinado",          "g"),
    ("bebida", "Leche Entera",               "und"),
    ("bebida", "Leche Deslactosada",         "und"),
    ("bebida", "Leche Condensada",           "g"),
    ("bebida", "Leche en Polvo",             "g"),
    ("bebida", "Sour Cream",                 "und"),
    ("bebida", "Crema Chantilly",            "und"),
    ("bebida", "Helado Vainilla",            "g"),
    ("bebida", "Helado Chocolate",           "g"),
    ("bebida", "Salsa Caramelo",             "g"),
    ("bebida", "Salsa Chocolate",            "g"),
    ("bebida", "Salsa Frutos Rojos",         "g"),
    ("bebida", "Salsa Maracuyá",             "g"),
    ("bebida", "Agua Normal Botella",        "und"),
    ("bebida", "Agua con Gas Botella",       "und"),
    ("bebida", "Pulpa Mango",                "und"),
    ("bebida", "Pulpa Lulo",                 "und"),
    ("bebida", "Pulpa Mora",                 "und"),
    ("bebida", "Pulpa Limón",                "und"),
    ("bebida", "Saborizante Vainilla",       "und"),
    ("bebida", "Saborizante Canela",         "und"),
    ("bebida", "Saborizante Macadamia",      "und"),
    ("bebida", "Saborizante Frutos Amarillos","und"),
    ("bebida", "Saborizante Kiwi Fresa",     "und"),
    ("bebida", "Chai Latte",                 "g"),
    ("bebida", "Azúcar",                     "g"),
    ("bebida", "Azúcar Blanca Tubos",        "und"),
    ("bebida", "Canela Molida",              "g"),
    ("bebida", "Cocoa",                      "g"),
    ("bebida", "Galleta Oreo",               "g"),
    ("bebida", "Milo",                       "g"),
    ("bebida", "Panela",                     "g"),
    ("bebida", "Aromática Toronjil",         "und"),
    ("bebida", "Aromática Limoncillo",       "und"),
    ("bebida", "Aromática Cidrón",           "und"),
    ("bebida", "Aromática Manzanilla",       "und"),
    ("bebida", "Aromática Hierbabuena",      "und"),
    ("bebida", "Licor Amaretto",             "und"),
    ("bebida", "Licor Baileys",              "und"),
    ("bebida", "Licor Black & White",        "und"),

    # ── INSUMO ────────────────────────────────────────────────────────────────
    ("insumo", "Vaso Cartón 9oz",             "und"),
    ("insumo", "Vaso Cartón 12oz",            "und"),
    ("insumo", "Vaso Cartón 16oz",            "und"),
    ("insumo", "Vaso Cartón 4oz",             "und"),
    ("insumo", "Vaso Plástico 7oz",           "und"),
    ("insumo", "Tapa Viajera 12oz",           "und"),
    ("insumo", "Tapa Pitillera 16oz",         "und"),
    ("insumo", "Plato Blanco",                "und"),
    ("insumo", "Caja Hamburguesa",            "und"),
    ("insumo", "Bolsa Domicilio",             "und"),
    ("insumo", "Bolsa Antigrasa",             "und"),
    ("insumo", "Bolsa Kraft",                 "und"),
    ("insumo", "Bolsa Basura",                "und"),
    ("insumo", "Pitillo Papel",               "und"),
    ("insumo", "Cuchara Postre Desechable",   "und"),
    ("insumo", "Mezclador Ecológico",         "und"),
    ("insumo", "Servilletas",                 "und"),
    ("insumo", "Endulzante",                  "und"),
    ("insumo", "Gel Antibacterial",           "und"),
    ("insumo", "Guantes Transparentes x100",  "und"),
    ("insumo", "Guantes Monocolor",           "und"),
    ("insumo", "Rollo Impresora",             "und"),
    ("insumo", "Paño Wypall",                 "und"),
    ("insumo", "Esponjilla",                  "und"),
    ("insumo", "Malla Suave",                 "und"),
    ("insumo", "Papel Aluminio",              "g"),
    ("insumo", "Papel Vinilpel",              "g"),
    ("insumo", "Detergente en Polvo",         "g"),
    ("insumo", "Limpiapisos",                 "g"),
    ("insumo", "Jabón Loza",                  "g"),
    ("insumo", "Limpiavidrios",               "g"),
    ("insumo", "Blanqueador",                 "g"),
    ("insumo", "Jabón de Manos",              "g"),
    ("insumo", "Citronela",                   "und"),
    ("insumo", "Trapeador",                   "und"),
    ("insumo", "Escoba",                      "und"),
]

# ─── Crear productos que no existen ─────────────────────────────────────────
creados = 0
omitidos = 0
errores = 0

for cat, nombre, unidad in PRODUCTOS_REALES:
    key = nombre.strip().lower()
    if key in nombres_existentes:
        omitidos += 1
        continue
    body = {"nombre": nombre, "categoria": cat, "unidad_medida": unidad, "controla_stock": True}
    resp = requests.post(f"{API}/inventario/productos", json=body, headers=headers)
    if resp.status_code == 200:
        print(f"  ✓  [{cat:10s}] {nombre} ({unidad})")
        nombres_existentes.add(key)
        creados += 1
    else:
        print(f"  ✗  Error al crear '{nombre}': {resp.text}")
        errores += 1

print(f"\n{'─'*50}")
print(f"  Creados:  {creados}")
print(f"  Omitidos: {omitidos}  (ya existían)")
print(f"  Errores:  {errores}")
print(f"{'─'*50}")
