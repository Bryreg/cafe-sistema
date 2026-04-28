# Sistema Café — Documentación técnica completa

> Última actualización: 2026-04-17
> Stack: FastAPI + SQLite (SQLAlchemy) · React + Vite + TailwindCSS
> Puertos: backend `8000` · frontend `5174`

---

## 1. Estructura de directorios

```
cafe-sistema/
├── iniciar.bat                      # Inicio rápido Windows: mata procesos viejos, lanza backend+frontend+browser
├── INICIO.md                        # Guía de inicio
├── SISTEMA.md                       # Este archivo
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, routers, static files, migraciones auto
│   │   ├── config.py                # Settings (DATABASE_URL, SECRET_KEY, etc.)
│   │   ├── database.py              # SQLAlchemy engine, SessionLocal, Base, get_db()
│   │   ├── models/
│   │   │   └── models.py            # TODOS los modelos SQLAlchemy + enums
│   │   ├── schemas/
│   │   │   ├── auth.py              # LoginRequest, LoginPinRequest, TokenResponse, UsuarioPublic
│   │   │   ├── caja.py              # AbrirCajaRequest, CerrarCajaRequest, TurnoOut, EntregaTurnoOut
│   │   │   ├── ventas.py            # RegistrarVentaRequest, VentaDiariaOut
│   │   │   ├── conteos.py           # RegistrarConteoRequest, ConteoFisicoOut
│   │   │   ├── mermas.py            # RegistrarMermaRequest, MermaOut
│   │   │   ├── solicitudes.py       # Pedido y Sencilla requests/outs
│   │   │   ├── inventario.py        # MovimientoInvRequest
│   │   │   ├── pasteleria.py
│   │   │   └── consignaciones.py
│   │   ├── routers/
│   │   │   ├── auth.py              # /auth/usuarios, /auth/login, /auth/login-pin, /auth/register
│   │   │   ├── caja.py              # /caja/abrir, /caja/{id}/cerrar, /caja/{id}/movimiento,
│   │   │   │                        # /caja/activo/{tienda_id}, /caja/{id}/entrega,
│   │   │   │                        # /caja/entregas/tienda/{tienda_id}, /caja/{id}/entregas
│   │   │   ├── ventas.py            # /ventas/, /ventas/turno/{turno_id}
│   │   │   ├── conteos.py           # /conteos/, /conteos/turno/{turno_id}
│   │   │   ├── mermas.py            # /mermas/, /mermas/tienda/{tienda_id}
│   │   │   ├── solicitudes.py       # /solicitudes/pedido, /sencilla, /bandeja/{tienda_id}
│   │   │   ├── inventario.py        # /inventario/tienda/{id}, /inventario/movimiento, etc.
│   │   │   ├── pasteleria.py
│   │   │   ├── consignaciones.py
│   │   │   └── dashboard.py         # /dashboard/{tienda_id}
│   │   ├── services/
│   │   │   ├── caja.py              # lógica de turno, registrar_entrega(), _tick_checklist()
│   │   │   ├── ventas.py            # registrar_venta(), auto-actualiza CajaTurno
│   │   │   ├── conteos.py           # registrar_conteo(), activa flags del turno
│   │   │   ├── mermas.py            # registrar_merma(), crea MovimientoInventario automático
│   │   │   ├── solicitudes.py       # crear/aprobar/rechazar pedidos y sencillas, bandeja
│   │   │   ├── inventario.py        # get_inventario_tienda(), registrar_movimiento(), get_alertas()
│   │   │   ├── pasteleria.py
│   │   │   ├── consignaciones.py
│   │   │   └── dashboard.py         # agrega KPIs, alertas, checklist
│   │   └── core/
│   │       ├── security.py          # bcrypt hash, JWT create/decode
│   │       └── deps.py              # get_current_user(), require_admin()
│   ├── seed.py                      # Crea tiendas, usuarios (con PIN), productos, inventario
│   ├── requirements.txt
│   └── .env.example                 # DATABASE_URL, SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES
└── frontend/
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx                  # Rutas separadas por rol (admin vs barista)
    │   ├── index.css
    │   ├── api/
    │   │   └── client.ts            # axios con baseURL=/api/v1, interceptor JWT
    │   ├── contexts/
    │   │   ├── AuthContext.tsx      # token, rol, nombre, tienda_id, user_id en localStorage
    │   │   └── TurnoContext.tsx     # turno activo global, refresh(), campos calculados
    │   ├── components/
    │   │   ├── Layout.tsx           # Header + nav diferenciada por rol
    │   │   ├── ProtectedRoute.tsx   # Redirige si no hay sesión o rol incorrecto
    │   │   ├── MoneyInput.tsx       # Input de dinero formateado COP
    │   │   ├── DifferenceBadge.tsx  # Badge verde/rojo para diferencias de caja
    │   │   └── ImageUploader.tsx    # Subida de foto: cámara o archivo, con preview
    │   └── pages/
    │       ├── Login.tsx            # Cards de usuario + teclado PIN (4 dígitos, login automático)
    │       ├── Dashboard.tsx        # Solo admin: KPIs tienda, alertas, checklist, cuadres de llegada
    │       ├── Hub.tsx              # Barista: pantalla principal, flujo turno, alerta cuadre de llegada
    │       ├── Entrega.tsx          # Barista: cuadre de llegada mid-turno (efectivo + Siigo + Bold + foto)
    │       ├── VentasDia.tsx        # Barista: registro ventas con desglose efect/tarjeta/NC/vales
    │       ├── ConteoFisico.tsx     # Barista: conteo apertura y cierre contra stock sistema
    │       ├── Inventario.tsx       # Ambos: ver stock, registrar entrada/salida/ajuste
    │       ├── Mermas.tsx           # Barista: registrar merma (descuenta stock automático)
    │       ├── Pasteleria.tsx       # Barista: registrar productos con fecha de frescura
    │       ├── Consignaciones.tsx   # Ambos: registrar/confirmar consignaciones con foto
    │       ├── SolicitudPedido.tsx  # Barista: armar pedido (sección críticos con cantidad sugerida)
    │       ├── SolicitudSencilla.tsx # Barista: solicitar sencilla (cambio) al admin
    │       ├── Bandeja.tsx          # Solo admin: aprobar/rechazar pedidos y sencillas
    │       └── Informes.tsx         # Solo admin: reportes por período
    ├── vite.config.ts               # proxy /api → localhost:8000, /uploads → localhost:8000
    └── package.json
```

---

## 2. Base de datos — modelos completos

### Enums

| Enum | Valores |
|------|---------|
| `RolEnum` | `admin`, `barista` |
| `EstadoTurnoEnum` | `abierto`, `cerrado` |
| `TipoMovCajaEnum` | `ingreso`, `egreso` |
| `CategoriaProductoEnum` | `pasteleria`, `bebida`, `insumo` |
| `TipoMovInvEnum` | `entrada`, `salida`, `ajuste` |
| `EstadoConsignacionEnum` | `pendiente`, `realizada` |
| `TipoConteoEnum` | `apertura`, `cierre` |
| `EstadoSolicitudEnum` | `pendiente`, `aprobada`, `rechazada` |

### Tabla: `tiendas`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| nombre | String(100) | |
| direccion | String(200) | nullable |
| activa | Boolean | default True |

### Tabla: `usuarios`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| nombre | String(100) | |
| email | String(150) | unique |
| password_hash | String(255) | bcrypt |
| pin_hash | String(255) | nullable, bcrypt 4 dígitos |
| rol | Enum(RolEnum) | admin \| barista |
| tienda_id | FK → tiendas | nullable |
| activo | Boolean | default True |

> bcrypt requiere versión 4.x (incompatible con bcrypt 5.x): `pip install "bcrypt==4.0.1"`

### Tabla: `caja_turnos`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| usuario_apertura_id | FK → usuarios | |
| usuario_cierre_id | FK → usuarios | nullable |
| fecha_apertura | DateTime | default utcnow |
| fecha_cierre | DateTime | nullable |
| base_sistema | Float | efectivo_final_real del turno anterior |
| base_real | Float | conteo físico al abrir |
| diferencia_apertura | Float | base_real - base_sistema |
| justificacion_apertura | Text | nullable, obligatoria si diferencia ≠ 0 |
| total_ventas | Float | **calculado automáticamente** desde VentaDiaria |
| total_efectivo | Float | **calculado automáticamente** desde VentaDiaria |
| total_tarjeta | Float | **calculado automáticamente** desde VentaDiaria |
| efectivo_final_real | Float | nullable, ingresado al cerrar |
| datafono_real | Float | nullable, total Bold al cerrar (obligatorio si total_tarjeta > 0) |
| diferencia_cierre | Float | nullable, calculada al cerrar |
| diferencia_tarjeta | Float | nullable, datafono_real - total_tarjeta |
| justificacion_cierre | Text | nullable, obligatoria si diferencia ≠ 0 |
| estado | Enum(EstadoTurnoEnum) | abierto \| cerrado |
| **tiene_conteo_apertura** | Boolean | default False — activa módulo de Ventas |
| **tiene_ventas** | Boolean | default False — activa conteo de cierre |
| **tiene_conteo_cierre** | Boolean | default False — activa cierre del turno |

> ⚠️ Los flags `tiene_*` son **solo-escritura del backend**. El frontend los lee para UI pero nunca los envía.

### Tabla: `entregas_turno` (cuadre de llegada)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| turno_id | FK → caja_turnos | |
| tienda_id | FK → tiendas | |
| usuario_id | FK → usuarios | barista que realiza el cuadre |
| fecha_hora | DateTime | default utcnow |
| efectivo_esperado | Float | base_real + total_efectivo + ingresos - egresos al momento |
| efectivo_real | Float | conteo físico del barista entrante |
| ventas_efectivo_siigo | Float | debe coincidir exactamente con total_efectivo del turno |
| ventas_tarjeta_bold | Float | total del datáfono Bold |
| diferencia_efectivo | Float | efectivo_real - efectivo_esperado |
| diferencia_tarjeta | Float | ventas_tarjeta_bold - total_tarjeta |
| imagen_url | String(300) | nullable, foto de evidencia |

### Tabla: `movimientos_caja`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| caja_turno_id | FK → caja_turnos | |
| tipo | Enum(TipoMovCajaEnum) | ingreso \| egreso |
| concepto | String(200) | |
| valor | Float | |
| fecha | DateTime | |
| usuario_id | FK → usuarios | |

### Tabla: `ventas_diarias`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| turno_id | FK → caja_turnos | |
| venta_total | Float | total bruto |
| nota_credito | Float | default 0 |
| vales | Float | default 0 |
| tarjetas | Float | default 0 |
| efectivo_calculado | Float | venta_total - nota_credito - vales - tarjetas |
| fecha_registro | DateTime | |
| usuario_id | FK → usuarios | |
| nota | String(300) | nullable |

> Al insertar, `service.ventas.registrar_venta()` acumula en `CajaTurno.total_ventas`, `total_efectivo`, `total_tarjeta` y activa `tiene_ventas = True` (solo si venta_total > 0).

### Tabla: `conteos_fisicos`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| turno_id | FK → caja_turnos | |
| tipo | Enum(TipoConteoEnum) | apertura \| cierre |
| fecha_registro | DateTime | |
| usuario_id | FK → usuarios | |

### Tabla: `conteos_fisicos_items`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| conteo_id | FK → conteos_fisicos | cascade delete |
| producto_id | FK → productos | |
| cantidad_sistema | Float | stock_actual al momento del conteo |
| cantidad_real | Float | ingresado por el barista |
| diferencia | Float | cantidad_real - cantidad_sistema |

> Al registrar tipo=`apertura`: activa `turno.tiene_conteo_apertura = True` y marca `checklist.inventario_check = True`.
> Al registrar tipo=`cierre`: activa `turno.tiene_conteo_cierre = True`.

### Tabla: `productos`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| nombre | String(150) | |
| categoria | Enum(CategoriaProductoEnum) | pasteleria \| bebida \| insumo |
| unidad_medida | String(30) | litro, kg, unidad, oz, porción |
| controla_stock | Boolean | default True |

### Tabla: `inventario`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| producto_id | FK → productos | |
| tienda_id | FK → tiendas | |
| stock_actual | Float | se actualiza en tiempo real |
| stock_minimo | Float | umbral de alerta |

### Tabla: `movimientos_inventario`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| producto_id | FK → productos | |
| tienda_id | FK → tiendas | |
| tipo | Enum(TipoMovInvEnum) | entrada \| salida \| ajuste |
| cantidad | Float | |
| fecha | DateTime | |
| usuario_id | FK → usuarios | |
| motivo | String(200) | nullable |

### Tabla: `mermas`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| producto_id | FK → productos | |
| cantidad | Float | |
| motivo | String(300) | |
| fecha_registro | DateTime | |
| usuario_id | FK → usuarios | |

> Al crear una merma, `service.mermas` crea automáticamente un `MovimientoInventario` tipo `salida` y descuenta `Inventario.stock_actual`.

### Tabla: `pasteleria_diaria`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| producto_id | FK → productos | (solo categoría=pasteleria) |
| cantidad | Float | |
| fecha_frescura | DateTime | hasta cuándo es fresco |
| fecha_registro | DateTime | |
| usuario_id | FK → usuarios | |

> Al registrar, marca `checklist.pasteleria_check = True`.

### Tabla: `consignaciones`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| fecha | DateTime | |
| valor | Float | |
| imagen_url | String(300) | nullable, ruta relativa a /uploads/ |
| usuario_id | FK → usuarios | |
| estado | Enum(EstadoConsignacionEnum) | pendiente \| realizada |

### Tabla: `solicitudes_pedido`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| fecha_solicitud | DateTime | |
| estado | Enum(EstadoSolicitudEnum) | pendiente \| aprobada \| rechazada |
| nota | String(500) | nullable |
| usuario_id | FK → usuarios | barista que solicita |
| usuario_aprobacion_id | FK → usuarios | nullable, admin que aprueba/rechaza |
| fecha_aprobacion | DateTime | nullable |

### Tabla: `solicitudes_pedido_items`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| solicitud_id | FK → solicitudes_pedido | cascade delete |
| producto_id | FK → productos | |
| cantidad_solicitada | Float | |

### Tabla: `solicitudes_sencilla`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| fecha_solicitud | DateTime | |
| estado | Enum(EstadoSolicitudEnum) | pendiente \| aprobada \| rechazada |
| monto_solicitado | Float | |
| motivo | String(300) | |
| usuario_id | FK → usuarios | barista que solicita |
| usuario_aprobacion_id | FK → usuarios | nullable |
| fecha_aprobacion | DateTime | nullable |

### Tabla: `checklist_diario`
| Campo | Tipo | Notas |
|-------|------|-------|
| id | Integer PK | |
| tienda_id | FK → tiendas | |
| fecha | DateTime | fecha del día |
| apertura_realizada | Boolean | ← `service.caja.abrir_caja()` |
| inventario_check | Boolean | ← `service.conteos.registrar(tipo=apertura)` |
| pasteleria_check | Boolean | ← `service.pasteleria.registrar()` |
| siigo_check | Boolean | manual (futuro: Siigo sync) |
| limpieza_check | Boolean | manual desde frontend |
| cierre_realizado | Boolean | ← `service.caja.cerrar_caja()` |

> `_tick_checklist(db, tienda_id, campo=True)` es idempotente y atómica con la acción que la dispara.

---

## 3. Flujo obligatorio del turno

El barista debe completar estos pasos **en orden**. El backend bloquea con `HTTP 400` si se intenta saltar un paso:

```
[Sin turno]
    │
    ▼ POST /api/v1/caja/abrir
    │   body: { tienda_id, base_real, justificacion_apertura? }
    │   efecto: crea CajaTurno, marca checklist.apertura_realizada=True
    │
[Turno abierto — tiene_conteo_apertura=False]
    │   Bloqueado: ventas, conteo cierre, cerrar
    │
    ▼ POST /api/v1/conteos/
    │   body: { tienda_id, tipo: "apertura", items: [{producto_id, cantidad_real}] }
    │   efecto: activa tiene_conteo_apertura=True, checklist.inventario_check=True
    │
[tiene_conteo_apertura=True]
    │   Desbloqueado: ventas, cuadre de llegada
    │   Bloqueado: conteo cierre, cerrar
    │
    ▼ POST /api/v1/ventas/
    │   body: { tienda_id, venta_total, nota_credito?, vales?, tarjetas?, nota? }
    │   REGLA: venta_total debe ser > 0
    │   efecto: acumula en CajaTurno.total_ventas/total_efectivo/total_tarjeta
    │           activa tiene_ventas=True
    │
    │   [OPCIONAL — mid-turno, no cierra el turno]
    │   ▼ POST /api/v1/caja/{turno_id}/entrega
    │       multipart/form-data: efectivo_real, ventas_efectivo_siigo, ventas_tarjeta_bold, imagen?
    │       REGLA: ventas_efectivo_siigo debe coincidir exactamente con turno.total_efectivo
    │       efecto: crea EntregaTurno, turno sigue abierto
    │
[tiene_ventas=True]
    │   Desbloqueado: conteo cierre
    │   Bloqueado: cerrar
    │
    ▼ POST /api/v1/conteos/
    │   body: { tienda_id, tipo: "cierre", items: [...] }
    │   efecto: activa tiene_conteo_cierre=True
    │
[tiene_conteo_cierre=True]
    │   Desbloqueado: cerrar turno
    │
    ▼ POST /api/v1/caja/{turno_id}/cerrar
        body: { efectivo_final_real, justificacion_cierre?, datafono_real? }
        cálculo:
          ingresos = SUM(movimientos_caja WHERE tipo=ingreso)
          egresos  = SUM(movimientos_caja WHERE tipo=egreso)
          efectivo_esperado = base_real + total_efectivo + ingresos - egresos
          diferencia_cierre = efectivo_final_real - efectivo_esperado
          diferencia_tarjeta = datafono_real - total_tarjeta
        REGLA: si diferencia ≠ 0 y no hay justificacion → HTTP 400
        REGLA: si total_tarjeta > 0 → datafono_real obligatorio
        efecto: cierra turno, marca checklist.cierre_realizado=True
```

---

## 4. Fórmulas clave

### Fórmula de cierre de caja

```
efectivo_esperado = base_real + total_efectivo + ingresos_movimientos - egresos_movimientos
diferencia_cierre = efectivo_final_real - efectivo_esperado
diferencia_tarjeta = datafono_real - total_tarjeta
```

### Fórmula de cuadre de llegada

```
efectivo_esperado_actual = base_real + total_efectivo + ingresos_mov - egresos_mov
diferencia_efectivo = efectivo_real - efectivo_esperado_actual
diferencia_tarjeta = ventas_tarjeta_bold - total_tarjeta
```

La entrega solo se puede guardar si `ventas_efectivo_siigo == turno.total_efectivo` exactamente.

### Fórmula de efectivo en ventas

```
efectivo_calculado = venta_total - nota_credito - vales - tarjetas
```

### Cantidad sugerida en alertas de inventario

```
cantidad_sugerida = max(1, round(stock_minimo - stock_actual + stock_minimo))
```

---

## 5. API endpoints completos

Todos los endpoints requieren `Authorization: Bearer <token>` excepto `/auth/login`, `/auth/login-pin` y `/auth/usuarios`.

### Auth — `/api/v1/auth`

| Método | Ruta | Body | Respuesta |
|--------|------|------|-----------|
| GET | `/usuarios` | — | Lista de usuarios activos (id, nombre, rol, tienda_id) |
| POST | `/login` | `{email, password}` | `TokenResponse` |
| POST | `/login-pin` | `{user_id, pin}` | `TokenResponse` |
| POST | `/register` | `{nombre, email, password, rol?, tienda_id?}` | `{id, nombre, email}` |

`TokenResponse`: `{access_token, token_type, rol, nombre, tienda_id, user_id}`

### Caja — `/api/v1/caja`

| Método | Ruta | Body | Notas |
|--------|------|------|-------|
| POST | `/abrir` | `{tienda_id, base_real, justificacion_apertura?}` | Error si ya hay turno abierto. Error si diferencia≠0 y no hay justificación |
| POST | `/{turno_id}/cerrar` | `{efectivo_final_real, justificacion_cierre?, datafono_real?}` | Error si no tiene_conteo_cierre. Error si diferencia≠0 y no hay justificación. datafono_real obligatorio si total_tarjeta > 0 |
| POST | `/{turno_id}/movimiento` | `{tipo, concepto, valor}` | tipo: ingreso\|egreso |
| POST | `/{turno_id}/entrega` | multipart/form-data: `efectivo_real`, `ventas_efectivo_siigo`, `ventas_tarjeta_bold`, `imagen?` | Cuadre de llegada. Requiere tiene_conteo_apertura. ventas_efectivo_siigo debe == turno.total_efectivo |
| GET | `/activo/{tienda_id}` | — | Retorna TurnoOut (con campos calculados) o 404 |
| GET | `/historial/{tienda_id}` | — | Últimos 30 turnos |
| GET | `/entregas/tienda/{tienda_id}` | — | Últimas 20 entregas de la tienda |
| GET | `/{turno_id}/entregas` | — | Entregas del turno específico |

`TurnoOut` incluye campos base de `caja_turnos` más campos calculados en `get_turno_activo()`:
- `ingresos_movimientos`, `egresos_movimientos` — suma de movimientos del turno
- `efectivo_esperado_actual` — `base_real + total_efectivo + ingresos - egresos`
- `ultima_entrega_fecha`, `ultima_entrega_diferencia_efectivo` — datos del último cuadre de llegada

> ⚠️ Orden de rutas importa: `/entregas/tienda/{tienda_id}` debe estar declarado ANTES de `/{turno_id}/entregas` para evitar conflictos de matching.

### Ventas — `/api/v1/ventas`

| Método | Ruta | Body | Notas |
|--------|------|------|-------|
| POST | `/` | `{tienda_id, venta_total, nota_credito?, vales?, tarjetas?, nota?}` | Requiere turno abierto y tiene_conteo_apertura=True. venta_total debe ser > 0 |
| GET | `/turno/{turno_id}` | — | Lista de VentaDiaria del turno |

### Conteos — `/api/v1/conteos`

| Método | Ruta | Body | Notas |
|--------|------|------|-------|
| POST | `/` | `{tienda_id, tipo, items: [{producto_id, cantidad_real}]}` | tipo=cierre requiere tiene_ventas=True |
| GET | `/turno/{turno_id}` | — | Lista de ConteoFisico con items |

### Inventario — `/api/v1/inventario`

| Método | Ruta | Notas |
|--------|------|-------|
| GET | `/tienda/{tienda_id}` | Retorna stock con campo `en_alerta` (stock_actual ≤ stock_minimo) |
| POST | `/movimiento` | `{producto_id, tienda_id, tipo, cantidad, motivo?}` |
| GET | `/alertas/{tienda_id}` | Solo productos en alerta, incluye `producto_id`, `unidad`, `cantidad_sugerida` |
| GET | `/productos` | Todos los productos (sin filtro de tienda) |

### Mermas — `/api/v1/mermas`

| Método | Ruta | Body | Notas |
|--------|------|------|-------|
| POST | `/` | `{tienda_id, producto_id, cantidad, motivo}` | Crea MovimientoInventario tipo=salida automáticamente |
| GET | `/tienda/{tienda_id}` | — | Últimas 50 mermas |

### Solicitudes — `/api/v1/solicitudes`

| Método | Ruta | Notas |
|--------|------|-------|
| POST | `/pedido` | `{tienda_id, nota?, items: [{producto_id, cantidad_solicitada}]}` |
| GET | `/pedido/tienda/{tienda_id}` | Últimos 30 pedidos |
| PATCH | `/pedido/{id}/aprobar` | Cambia estado a aprobada |
| PATCH | `/pedido/{id}/rechazar` | Cambia estado a rechazada |
| POST | `/sencilla` | `{tienda_id, monto_solicitado, motivo}` |
| GET | `/sencilla/tienda/{tienda_id}` | Últimas 30 sencillas |
| PATCH | `/sencilla/{id}/aprobar` | |
| PATCH | `/sencilla/{id}/rechazar` | |
| GET | `/bandeja/{tienda_id}` | `{pedidos: [...], sencillas: [...], total: N}` (solo pendientes) |

### Pastelería — `/api/v1/pasteleria`

| Método | Ruta | Body |
|--------|------|------|
| POST | `/` | `{tienda_id, producto_id, cantidad, fecha_frescura}` |
| GET | `/tienda/{tienda_id}` | Registros de hoy |

### Consignaciones — `/api/v1/consignaciones`

| Método | Ruta | Notas |
|--------|------|-------|
| POST | `/` | multipart/form-data: `tienda_id`, `valor`, `imagen` (opcional) |
| GET | `/tienda/{tienda_id}` | Historial |
| PATCH | `/{id}/confirmar` | Cambia estado a realizada |

### Dashboard — `/api/v1/dashboard`

| Método | Ruta | Respuesta |
|--------|------|-----------|
| GET | `/{tienda_id}` | `{tienda_nombre, ventas_dia, estado_caja, diferencia_caja, productos_criticos, consignaciones_pendientes, cumplimiento_checklist, alertas: [{tipo, mensaje, nivel}]}` |

---

## 6. Autenticación

- **JWT** con HS256, expiración configurada en `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 480 min = 8h)
- Almacenado en `localStorage`: `token`, `rol`, `nombre`, `tienda_id`, `user_id`
- Interceptor Axios agrega `Authorization: Bearer <token>` automáticamente
- Si el backend retorna 401 → `localStorage.clear()` + redirect a `/login`
- **Login por PIN**: pantalla de cards (GET `/auth/usuarios`), teclado de 4 dígitos, login automático al completar

---

## 7. Separación de roles

### Admin (`rol: "admin"`)
- **Home**: `/dashboard`
- **Nav**: Dashboard · Inventario · Consignaciones · Bandeja · Informes
- **Accesos protegidos**: `/bandeja`, `/informes` (solo admin)

### Barista (`rol: "barista"`)
- **Home**: `/hub`
- **Nav**: Ventas · Conteos · Stock · Mermas · Pastelería · Consignación · Pedido · Sencilla
- **Hub**: pantalla principal con estado del turno y botones de acción (abrir, conteo apertura, conteo cierre, cerrar, cuadre de llegada)

---

## 8. Cuadre de llegada (EntregaTurno)

Permite a un barista entrante registrar el estado de la caja **sin cerrar el turno**. Se activa desde `Hub.tsx`.

**Estados del botón en Hub (prioridad):**
1. `sinEntrega` — sin cuadre previo: amber "Realizar cuadre de llegada"
2. `conDiff` — último cuadre con diferencia: rojo "Último cuadre con diferencia"
3. `hace4h` — último cuadre hace más de 4h: amber "Nuevo cuadre de llegada"
4. default — cuadre reciente y sin diferencia: verde "✓ Cuadre realizado"

**Validación backend:**
- Requiere `tiene_conteo_apertura = True`
- `ventas_efectivo_siigo` debe coincidir exactamente con `turno.total_efectivo`
- Imagen opcional (se recomienda adjuntar)

**Envío desde frontend:**
```typescript
const fd = new FormData()
fd.append('efectivo_real', String(ef))
fd.append('ventas_efectivo_siigo', String(vs))
fd.append('ventas_tarjeta_bold', String(vt))
if (imagen) fd.append('imagen', imagen)
await api.post(`/caja/${turno.id}/entrega`, fd)
// NO establecer Content-Type manualmente — axios lo pone con el boundary correcto
```

---

## 9. Checklist diario — lógica de auto-actualización

El checklist se actualiza como **efecto secundario** dentro de cada service, usando `_tick_checklist(db, tienda_id, campo=True)`. Es idempotente. Se ejecuta dentro de la misma transacción que la acción principal.

| Acción | Campo activado |
|--------|---------------|
| `service.caja.abrir_caja()` | `apertura_realizada = True` |
| `service.conteos.registrar(tipo="apertura")` | `inventario_check = True` |
| `service.pasteleria.registrar()` | `pasteleria_check = True` |
| `service.caja.cerrar_caja()` | `cierre_realizado = True` |
| `siigo_check` | No implementado (manual futuro) |
| `limpieza_check` | No implementado (manual futuro) |

El `cumplimiento_checklist` del dashboard calcula:
```python
campos = [apertura_realizada, inventario_check, pasteleria_check,
          siigo_check, limpieza_check, cierre_realizado]
cumplimiento = sum(1 for c in campos if c) / len(campos) * 100
```

---

## 10. Configuración

### `.env` (backend)
```
DATABASE_URL=sqlite:///./cafe_sistema.db
SECRET_KEY=supersecretkey_change_in_production_minimum32chars
ACCESS_TOKEN_EXPIRE_MINUTES=480
UPLOAD_DIR=uploads
```

Para PostgreSQL: `DATABASE_URL=postgresql://user:pass@localhost:5432/cafe_sistema`

### `vite.config.ts` (frontend)
```ts
proxy: {
  '/api': 'http://localhost:8000',
  '/uploads': 'http://localhost:8000',
}
```

---

## 11. Seed inicial

Ejecutar: `python seed.py` desde `backend/`

Crea:
- 2 tiendas: **Sede Principal** (t1), **Sede Norte** (t2)
- 3 usuarios (todos con PIN **1234**):

| Usuario | Email | PIN | Rol | Tienda |
|---------|-------|-----|-----|--------|
| Administrador | admin@cafe.com | 1234 | admin | t1 |
| Juan Barista | juan@cafe.com | 1234 | barista | t1 |
| María Barista | maria@cafe.com | 1234 | barista | t2 |

- 13 productos (bebidas, insumos, pastelería)
- Inventario inicial para ambas tiendas

---

## 12. Archivos de imágenes (consignaciones, entregas)

- Se guardan en `backend/uploads/` con nombre `{uuid}.{ext}`
- Servidos estáticamente en `/uploads/{archivo}`
- El frontend accede vía `/uploads/{imagen_url}` (proxy en dev, directo en prod)
- Aplica a consignaciones Y fotos de cuadres de llegada

---

## 13. Migraciones automáticas en `main.py`

El backend aplica migraciones inline al iniciar para evitar errores con esquemas viejos:

1. Detecta si `entregas_turno` tiene esquema viejo (sin `tienda_id`) → lo dropea para que `create_all` lo recree
2. Aplica `ALTER TABLE` para columnas nuevas en tablas existentes (con `IF NOT EXISTS`)
3. Ejecuta `Base.metadata.create_all(bind=engine)` **después** de todas las migraciones

> ⚠️ `create_all` SIEMPRE debe ir después de cualquier DROP/ALTER. Si se invierte el orden, `create_all` crea la tabla y luego el DROP la elimina.

---

## 14. Dependencias críticas

```
bcrypt==4.0.1           # NO usar 5.x — incompatible con passlib
passlib[bcrypt]
python-jose[cryptography]
python-multipart        # necesario para Form() y UploadFile en FastAPI
uvicorn
fastapi
sqlalchemy
```

---

## 15. Pendientes / trabajo futuro

| Módulo | Estado | Notas |
|--------|--------|-------|
| FIFO / Lotes | Modelo creado, no conectado | `LoteInventario` existe pero ningún endpoint lo usa |
| `siigo_check` | Campo existe, sin endpoint | Requiere integración Siigo API |
| `limpieza_check` | Campo existe, sin endpoint | Marcar manualmente desde frontend |
| Multi-tienda en dashboard admin | Parcial | Solo muestra una tienda; falta selector |
| Cambiar PIN desde perfil | No implementado | |
| Notificaciones push | No implementado | |
