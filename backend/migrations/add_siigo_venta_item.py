"""Migration: create siigo_venta_items table with unique constraint and indexes."""

import sqlite3
import os


def run():
    db_path = os.environ.get("DB_PATH", "cafe_sistema.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS siigo_venta_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
            fecha DATE NOT NULL,
            codigo_producto VARCHAR NOT NULL,
            descripcion VARCHAR NOT NULL DEFAULT '',
            cantidad REAL NOT NULL DEFAULT 0,
            precio_unitario REAL NOT NULL DEFAULT 0,
            total_sin_descuento REAL NOT NULL DEFAULT 0,
            descuento_porcentaje REAL,
            descuento_monto REAL,
            total_con_descuento REAL NOT NULL DEFAULT 0,
            siigo_factura_id VARCHAR NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(siigo_factura_id, codigo_producto, fecha)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_siigo_tienda_fecha
        ON siigo_venta_items(tienda_id, fecha)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_siigo_codigo
        ON siigo_venta_items(codigo_producto)
    """)

    conn.commit()
    conn.close()
    print("Migration completed: siigo_venta_items table created.")


if __name__ == "__main__":
    run()
