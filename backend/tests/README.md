# Pruebas Backend

La suite principal esta en `test_caja_flow.py` y cubre:

- flujo critico de caja
- permisos por tienda y admin
- validaciones de ventas
- entrega y cierre
- movimientos de caja
- conteos
- inventario

## Ejecutar

Desde `C:\Users\bmgpe\Desktop\cafe-sistema\backend`:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

## Nota del entorno actual

Si el comando falla con referencia a `Python312\python.exe`, el `venv` esta roto porque apunta a un Python base que ya no existe.

Para repararlo:

1. Instala o restaura Python 3.12 en Windows.
2. Recrea el entorno virtual en `backend\venv`.
3. Reinstala dependencias con `requirements.txt`.
4. Vuelve a ejecutar la suite.
