# Sistema Café — Guía de inicio

## Requisitos
- Python 3.11+
- Node.js 18+

> SQLite por defecto (no requiere PostgreSQL). Para prod, editar `.env` con `DATABASE_URL=postgresql://...`

## Inicio rápido (Windows)

Doble clic en `iniciar.bat` en la raíz del proyecto. Abre el backend, frontend y el navegador automáticamente.

---

## Inicio manual

### 1. Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python seed.py          # crea tablas y datos iniciales (solo primera vez)
python -m uvicorn app.main:app --port 8000
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev -- --port 5174
```

Abre: http://localhost:5174

---

## Flujo del barista (orden obligatorio)

1. **Hub** → Abrir turno
2. **Conteos** → Conteo de apertura (activa módulo de Ventas)
3. **Ventas** → Registrar ventas del día (activa conteo de cierre)
4. **Conteos** → Conteo de cierre (habilita cerrar turno)
5. **Hub** → Cerrar turno

**Cuadre de llegada (opcional, sin cerrar turno):** Cuando llega un barista a mitad de turno, va a Hub → "Cuadre de llegada" y registra efectivo físico, ventas Siigo y Bold.

> El sistema bloquea cada paso hasta que el anterior esté completado.

---

## Módulos disponibles

| Módulo | Roles | Descripción |
|--------|-------|-------------|
| Dashboard | admin | Resumen del día, alertas, cuadres de llegada |
| Hub | barista | Pantalla principal: estado del turno, acciones disponibles |
| Entrega | barista | Cuadre de llegada a mitad de turno (sin cerrar) |
| Ventas | barista | Registro de ventas con desglose efect/tarjeta |
| Conteos | barista | Conteo físico apertura y cierre |
| Inventario | admin, barista | Stock en tiempo real, movimientos |
| Mermas | barista | Registro de mermas (descuenta stock) |
| Pastelería | barista | Control de frescura |
| Consignaciones | admin, barista | Registro con foto |
| Pedido | barista | Solicitud de insumos al admin (con sugerencias de cantidad) |
| Sencilla | barista | Solicitar cambio al admin |
| Bandeja | **solo admin** | Aprobar pedidos de insumos y sencillas |
| Informes | **solo admin** | Reportes por período |

---

## Usuarios de prueba (login por PIN)
| Usuario | PIN | Rol |
|---------|-----|-----|
| Administrador | 1234 | admin |
| Juan Barista | 1234 | barista |
| María Barista | 1234 | barista |
