# -*- coding: utf-8 -*-
"""Genera menu_venta.json (menú de venta del POS) desde PRODUCTOS_POR_GRUPOS.
Categorías: bebida | pasteleria | porciones. Alinea nombres de pastelería a los del
inventario para que el cargador de menú los una (no duplique)."""
import openpyxl, unicodedata, re, json
def norm(s): return re.sub(r'\s+', ' ', unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()).strip().upper()

wb = openpyxl.load_workbook('C:/Users/bmgpe/Downloads/PRODUCTOS_POR_GRUPOS (2).xlsx', data_only=True)
ws = wb['PRODUCTOS']
SECTION_CAT = {
 'SIN CAFE': 'bebida', 'CAFE': 'bebida', 'MALTEADAS': 'bebida', 'BEBIDAS FRIAS': 'bebida',
 'MOKA': 'bebida', 'CAPU': 'bebida', 'LIBRA': 'bebida', 'MATCHA': 'bebida',
 'PANADERIA Y PASTELERIA': 'pasteleria', 'PORCIONES': 'porciones',
}
SKIP = {'CODIGO', 'PRODUCTO', 'PRECIO', 'CATALOGO DE PRODUCTOS'}
def nice(name):
    small = {'de', 'con', 'y', 'en', 'x', 'la', 'el', 'al', 'oz'}
    return ' '.join(w if (w in small and i > 0) else w.capitalize() for i, w in enumerate(name.lower().split()))
# Alineación con nombres del inventario (para que el cargador de menú los una)
OVERRIDE = {
 'CROISANT': 'Croissant Queso', 'CROISANT CHOCOLATE': 'Croissant de Chocolate',
 'OMELET HUEVO': 'Omelette', 'OMELET JAMON Y QUESO': 'Omelette de Jamón y Queso',
 'PORCION LECHE CONDENSADA': 'Porción Leche Condensada',
}
blocks = [(0, 1, 2), (4, 5, 6), (8, 9, 10)]
cur = {b: None for b in range(3)}
items = []
seen = set()
for row in ws.iter_rows(values_only=True):
    for bi, (c, p, pr) in enumerate(blocks):
        code = row[c] if c < len(row) else None
        prod = row[p] if p < len(row) else None
        price = row[pr] if pr < len(row) else None
        if code is None and prod is None and price is None: continue
        if isinstance(price, (int, float)) and prod and str(prod).strip():
            cat = SECTION_CAT.get(norm(cur[bi]) if cur[bi] else '', 'bebida')
            nm = OVERRIDE.get(norm(prod), nice(str(prod).strip()))
            k = norm(nm)
            if k in seen: continue
            seen.add(k)
            items.append({'nombre': nm, 'categoria': cat, 'precio': int(price)})
        else:
            val = code if (code and str(code).strip()) else (prod if (prod and str(prod).strip()) else None)
            if val and norm(val) not in SKIP and not isinstance(price, (int, float)):
                cur[bi] = str(val).strip()

json.dump(items, open('menu_venta.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
from collections import Counter
print('menu_venta.json ->', len(items), 'items', dict(Counter(i['categoria'] for i in items)))
