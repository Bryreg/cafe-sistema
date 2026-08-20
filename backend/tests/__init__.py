"""Paquete de tests.

Existe por una razon concreta, no por costumbre: cuatro archivos importan
helpers con `from tests.base_cuadre import ...` / `from tests.test_piso_venta
import ...`. Sin este `__init__.py`, `tests/` es solo un namespace package, y
Python le da prioridad a CUALQUIER paquete regular llamado `tests` que aparezca
en sys.path -- y hay wheels de terceros que instalan uno en site-packages. Con
el archivo, el paquete de este repo gana porque `backend/` va primero.
"""
