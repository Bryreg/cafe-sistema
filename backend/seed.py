"""Seed de datos iniciales"""
import sys, os
sys.path.append(os.path.dirname(__file__))
from app.database import SessionLocal, engine, Base
from app.models import models  # noqa: importa todos los modelos para metadata
from app.models.models import Tienda, Usuario, Producto, Inventario, CategoriaProductoEnum
from app.core.security import hash_password

Base.metadata.create_all(bind=engine)

def seed():
    db = SessionLocal()
    try:
        if db.query(Tienda).count() > 0:
            print("Ya existe data, omitiendo seed.")
            return

        # Tiendas
        t1 = Tienda(nombre="Vida", direccion="Sede Vida")
        t2 = Tienda(nombre="Palmetto", direccion="Sede Palmetto Plaza")
        db.add_all([t1, t2])
        db.flush()

        # Usuarios
        admin = Usuario(nombre="Administrador", email="admin@cafe.com",
                        password_hash=hash_password("admin123"), pin_hash=hash_password("1234"),
                        rol="admin", tienda_id=t1.id)
        baristas = [
            Usuario(nombre="Elina",      email="elina@cafe.com",     password_hash=hash_password("barista123"), pin_hash=hash_password("1111"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Catherin",   email="catherin@cafe.com",  password_hash=hash_password("barista123"), pin_hash=hash_password("2222"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Alejandra",  email="alejandra@cafe.com", password_hash=hash_password("barista123"), pin_hash=hash_password("3333"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Ana Maria",  email="anamaria@cafe.com",  password_hash=hash_password("barista123"), pin_hash=hash_password("4444"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Esther",     email="esther@cafe.com",    password_hash=hash_password("barista123"), pin_hash=hash_password("5555"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Luisa",      email="luisa@cafe.com",     password_hash=hash_password("barista123"), pin_hash=hash_password("6666"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Nicole",     email="nicole@cafe.com",    password_hash=hash_password("barista123"), pin_hash=hash_password("7777"), rol="barista", tienda_id=t1.id),
            Usuario(nombre="Laura",      email="laura@cafe.com",     password_hash=hash_password("barista123"), pin_hash=hash_password("8888"), rol="barista", tienda_id=t1.id),
        ]
        db.add(admin)
        db.add_all(baristas)
        db.flush()

        # Productos
        productos = [
            Producto(nombre="Café Espresso", categoria=CategoriaProductoEnum.bebida, unidad_medida="oz"),
            Producto(nombre="Leche Entera", categoria=CategoriaProductoEnum.insumo, unidad_medida="litro"),
            Producto(nombre="Leche Oat", categoria=CategoriaProductoEnum.insumo, unidad_medida="litro"),
            Producto(nombre="Azúcar", categoria=CategoriaProductoEnum.insumo, unidad_medida="kg"),
            Producto(nombre="Croissant", categoria=CategoriaProductoEnum.pasteleria, unidad_medida="unidad"),
            Producto(nombre="Muffin Arándanos", categoria=CategoriaProductoEnum.pasteleria, unidad_medida="unidad"),
            Producto(nombre="Brownie", categoria=CategoriaProductoEnum.pasteleria, unidad_medida="unidad"),
            Producto(nombre="Tarta Limón", categoria=CategoriaProductoEnum.pasteleria, unidad_medida="porción"),
            Producto(nombre="Café Molido", categoria=CategoriaProductoEnum.insumo, unidad_medida="kg"),
            Producto(nombre="Jarabe Vainilla", categoria=CategoriaProductoEnum.insumo, unidad_medida="litro"),
            Producto(nombre="Cocoa", categoria=CategoriaProductoEnum.insumo, unidad_medida="kg"),
            Producto(nombre="Vasos 8oz", categoria=CategoriaProductoEnum.insumo, unidad_medida="unidad"),
            Producto(nombre="Vasos 12oz", categoria=CategoriaProductoEnum.insumo, unidad_medida="unidad"),
        ]
        db.add_all(productos)
        db.flush()

        # Inventario para t1 y t2
        stocks = [15, 10, 5, 3, 12, 8, 6, 4, 2, 3, 1, 100, 80]
        minimos = [5, 3, 2, 1, 5, 3, 3, 2, 1, 1, 0.5, 20, 20]
        for p, s, m in zip(productos, stocks, minimos):
            db.add(Inventario(producto_id=p.id, tienda_id=t1.id, stock_actual=s, stock_minimo=m))
            db.add(Inventario(producto_id=p.id, tienda_id=t2.id, stock_actual=s * 0.5, stock_minimo=m))

        db.commit()
        print("Seed completado exitosamente")
        print("   Administrador  PIN: 1234")
        print("   Elina          PIN: 1111")
        print("   Catherin       PIN: 2222")
        print("   Alejandra      PIN: 3333")
        print("   Ana Maria      PIN: 4444")
        print("   Esther         PIN: 5555")
        print("   Luisa          PIN: 6666")
        print("   Nicole         PIN: 7777")
        print("   Laura          PIN: 8888")
    except Exception as e:
        db.rollback()
        print(f"Error en seed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
