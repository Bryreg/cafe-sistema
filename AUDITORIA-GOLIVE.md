# Auditoría final pre-go-live — cafe-sistema

## ✅ Correcciones aplicadas (2026-06-30)

**Verificado:** frontend `tsc` + `vite build` OK; backend booteado contra SQLite con smoke test (login, kiosk-pin leer/cambiar, kiosk-init, movimiento con atribución de barista, merma con/ sin motivo, set-password, umbrales con minimo=0).

**Críticos (2/2):**
- **C2** + rework de auth: PIN de barista eliminado (obsoleto con el modelo POS); `pin_hash` con migración; **clave de admin editable** desde el hub (`set-password`); **PIN de kiosko movido a DB** (`configuracion`, sembrado con el env), editable desde Usuarios con efecto inmediato; **sede como lista** al activar kiosko.
- **C1**: guard de `registrar_entrega` usa el día (`_hay_conteo_apertura_en_dia`) → intermedio/cierre cierran y entran-con-cuadre. (también **H7** y **M14**)

**High (10/10):** H1 logout→/admin-login · H2 parseo de error inventario (síntoma "Error") · H3 mermas dashboard · H4 traslado crea lote · H5 pastelería /activos · H6 ConteoFisico cargas separadas · H8 atribución barista en movimiento de inventario (columnas + migración + `get_barista_actor`) · H9 limpieza de `barista_activa_*` · H10 migración `inventarios_mensuales`.

**Medium (14/15):** M1 TabConteos error · M2 realizado_por null · M3 umbrales con 0 · M4 ticker null · M5 push no-configurado · M6 PagosProveedores error · M8 rutinas entre turnos · M9 conciliación en proceso · M10 ajuste honesto · M11 mixto epsilon · M12 ConfigTicket sin default a tienda 1 · M13 confirmación "todo coincide".
- **M15** (race de `cerrar_caja`): NO tocado a propósito — ventana de concurrencia estrecha en código de caja, alto riesgo sin poder testear la carrera. Documentado.

**Low (~10):** L2 consignaciones por pendiente · L3 ProtectedRoute · L8 cambio null · L9 motivo no vacío · L10 auditoría merma con id · L11 N+1 sugerencia · L13/L22 spinners infinitos · L20 TurnoContext dep · L26 nullable factura.
- **Documentados como intencionales / WONTFIX / feature:** L1 (historial pedido — feature) · L4 (/tiendas público por diseño) · L5 (catch silencioso TabPedidos) · L6, L14 (relaciones latentes) · L7 (PASS) · L12/L21 (campana multi-sede — decisión de producto) · L15 (N+1 acotado) · L16 (moot por H5) · L17 (SW click) · L18, L19, L23, L24, L25, L27/L28.

> **Deploy del PIN de kiosko:** al arrancar, el backend siembra `configuracion.kiosk_pin` con el valor del env `KIOSK_PIN` (sigue siendo `2026`). De ahí en más se gestiona desde **Usuarios**; el env queda como respaldo.

---

**Fecha:** 2026-06-30
**Alcance:** 22 flujos (barista + admin), trazados de punta a punta (frontend → API → router → service → modelo) y verificados de forma adversarial contra el código real.
**Resultado:** 55 defectos confirmados — 2 críticos, 10 high, 15 medium, 28 low.

> Nota de integridad: la auditoría transversal de **relaciones SQLAlchemy salió limpia** (no hay `back_populates` huérfano → el backend arranca sano). La clase de bug que tumbó producción antes ya no está presente.
> **Flujo 100% limpio:** Usuarios / Nota crédito / Cuadre de turnos.

Las rutas con `file:line` son aproximadas al estado del código en la fecha de auditoría.

---

## 🔴 CRÍTICOS (2) — bloquean go-live

### C1 · La 2da/3ra barista no puede cerrar turno
- **Dónde:** `frontend/src/pages/Cierre.tsx:129` · backend `backend/app/routers/caja.py:302`
- **Impacto:** El cierre por ruta no-kiosko (Hub / GestionTurno → `/cierre`) hace `POST /caja/{id}/entrega`, que tiene un guard `tiene_conteo_apertura`. Los turnos `intermedio`/`cierre` nunca hacen conteo de apertura (heredan el del día), así que el flag queda `False` → **HTTP 400 "Debes completar el conteo de apertura"**. La foto se pierde y el turno queda abierto. El path kiosko (`SalidaEfectivo` → `/salida` → `cerrar_turno_rapido`) sí funciona porque no llama a `/entrega`.
- **Fix sugerido:** Rutear `Cierre.tsx` por `POST /caja/{id}/salida` (multipart) igual que `SalidaEfectivo.tsx`, para que foto + cierre + justificación sean atómicos. Alternativa backend: relajar el guard en `registrar_entrega` para que use `_hay_conteo_apertura_en_dia(db, turno)`.

### C2 · Login por PIN de barista y pantalla Usuarios dan 500 (falta migración `pin_hash`)
- **Dónde:** `backend/app/main.py` (lista de migraciones) · `backend/app/models/models.py:124` · `backend/app/routers/auth.py:106,166,198`
- **Impacto:** `models.py` declara `pin_hash`, pero no existe `ALTER TABLE usuarios ADD COLUMN pin_hash`. `create_all` no agrega columnas a tablas existentes. Si la tabla `usuarios` es anterior a `pin_hash`, la columna falta → `POST /auth/login-pin`, `POST /auth/usuarios/{id}/set-pin` y `GET /auth/admin/usuarios` revientan con 500. (El reset que hicimos fue `DELETE` de filas, no recreó la tabla, así que la estructura no cambió.)
- **Fix sugerido:** Agregar a la lista de migraciones en `main.py`: `"ALTER TABLE usuarios ADD COLUMN pin_hash VARCHAR(255)"`. Idempotente bajo el try/except existente. Seguro corra o no exista ya.

---

## 🟠 HIGH (10)

### H1 · Logout admin cae en la pantalla de kiosko
- **Dónde:** `frontend/src/components/Layout.tsx:136`
- **Impacto:** `handleLogout` hace `navigate('/login')`, ruta inexistente → el wildcard `*` redirige a `/` → `Landing` devuelve `KioskSetup` porque `!user`. El admin queda en la pantalla de PIN de kiosko sin formulario de login ni error.
- **Fix:** Cambiar a `navigate('/admin-login')`.

### H2 · Panel de inventario admin muestra "Error" crudo / array 422 (síntoma reportado)
- **Dónde:** `frontend/src/pages/Inventario.tsx:117` (`InventarioAdmin.registrar`)
- **Impacto:** `setError(e.response?.data?.detail || 'Error')`. En un 422 el `detail` es un array de objetos (truthy) → React intenta renderizarlo (`[object Object]`/crash); en 500 sin body muestra el literal `"Error"`. El handler de barista (líneas 533-538) sí parsea bien. **Causa más probable del síntoma "ajuste muestra Error".**
- **Fix:** Replicar el parseo del handler de barista (`Array.isArray(raw) ? raw[0]?.msg : raw`). Aplicar también a `guardarEdicion`/`crearProducto`/`guardarMinimo`.

### H3 · DashboardEjecutivo: panel de mermas siempre en 0
- **Dónde:** `frontend/src/pages/DashboardEjecutivo.tsx:292` · backend `backend/app/services/informes.py:123`
- **Impacto:** Lee `r.data.items`, pero el backend devuelve `{filas, totales}`. `.slice` sobre el objeto lanza TypeError, tragado por `.catch(() => null)` → mermas queda `[]`. Además, en la vista "Todas" (sedeId=null) no manda `tienda_id` (que es `Query(...)` requerido) → 422. Da un falso "sin pérdidas".
- **Fix:** Leer `r.data.filas` y mapear `total_cantidad`→`cantidad`; manejar el caso sin sede (guardar la llamada o hacer `tienda_id` opcional en backend).

### H4 · `recibir_traslado` suma stock pero no crea lote
- **Dónde:** `backend/app/services/mermas.py:107-126`
- **Impacto:** Al confirmar un traslado recibido, incrementa `Inventario.stock_actual` pero no crea `LoteInventario`. El FIFO en destino no encuentra lotes → mermas posteriores sub-drenan en silencio; trazabilidad y vencimientos divergen del stock real con el tiempo.
- **Fix:** Tras incrementar/crear el `Inventario` destino, llamar `inventario.agregar_lote(...)` (idealmente arrastrando vencimiento/lote/proveedor del original).

### H5 · Pastelería: el lote cerrado reaparece al recargar
- **Dónde:** `frontend/src/pages/Pasteleria.tsx:163` · backend `backend/app/services/pasteleria.py:74-79`
- **Impacto:** `cerrar_lote` marca `activo=False` bien, pero `loadRegistros()` llama a `/pasteleria/tienda/{id}` (→ `get_por_fecha`, sin filtro `activo`). El lote cerrado desaparece y reaparece en la misma fecha; la barista no puede limpiar lotes terminados.
- **Fix:** Llamar a `/pasteleria/tienda/{id}/activos` (`get_activos`, que filtra `activo==True`).

### H6 · ConteoFisico: un solo try/catch anula el turno si falla solo el inventario
- **Dónde:** `frontend/src/pages/ConteoFisico.tsx:38-47`
- **Impacto:** `Promise.all` envuelve la llamada de turno y la de inventario en un único try; el catch hace `setTurno(null)` sin importar cuál falló → "No hay turno abierto" con el turno abierto. Además, ítems no tocados envían `item.stock_actual` como conteo real (afirma "todo coincide" sin contar).
- **Fix:** Separar los awaits; setear turno e inventario por separado; exponer error de inventario distinto.

### H7 · La ruta no-kiosko de cierre es alcanzable (reachability de C1)
- **Dónde:** `frontend/src/components/ConteoInventario.tsx:42` · `Hub.tsx:145-146` · `GestionTurno.tsx:255`
- **Impacto:** Solo se rutea a `/salida-efectivo` (path que funciona) si hay `?kiosk=1`. Hub y GestionTurno navegan sin ese flag → usuarios reales caen en el `Cierre.tsx` roto (C1). Confirma que el path roto es alcanzable en producción.
- **Fix:** Mismo que C1 — unificar el flujo de cierre en una sola pantalla/contrato que funcione.

### H8 · Movimientos de inventario en kiosko se atribuyen al device, no a la barista
- **Dónde:** `backend/app/routers/inventario.py:24` (no usa `get_barista_actor`)
- **Impacto:** Toda entrada/salida/ajuste desde kiosko queda bajo la cuenta del dispositivo, no de la barista. Pérdida de atribución en la operación de inventario más frecuente. (Hay traza parcial vía `audit.registrar` con `usuario_id`.)
- **Fix:** Agregar columnas `barista_id`/`barista_nombre` a `MovimientoInventario` (modelo) + 2 `ALTER TABLE movimientos_inventario` (Postgres-valid) + `Depends(get_barista_actor)` en el handler y propagarlas. (Ver M7, es el mismo defecto.)

### H9 · `logout()`/401 no limpian la key de barista por tienda → atribución cruzada
- **Dónde:** `frontend/src/contexts/AuthContext.tsx:55-64` · `frontend/src/api/client.ts:25-33`
- **Impacto:** Limpian `barista_activa_id` (global) pero no `barista_activa_{tiendaId}`. En el siguiente turno, si la barista anterior está en el roster nuevo, se re-selecciona sola sin aviso → escrituras atribuidas a quien no es, de forma permanente.
- **Fix:** En `logout()` y el interceptor 401, borrar también las keys `barista_activa_*` (iterar `Object.keys(localStorage)`), o no auto-restaurar desde la per-store key en sesión nueva.

### H10 · `inventarios_mensuales`: columnas `barista_id`/`barista_nombre` sin migración
- **Dónde:** `backend/app/models/models.py:1123-1124` · `backend/app/services/inventario_mensual.py:58-59` · `backend/app/main.py`
- **Impacto:** El modelo declara e inserta esas columnas, pero la lista de migraciones (que SÍ las agrega a otras 8 tablas) las omite para `inventarios_mensuales`. Si la tabla precede al cambio del modelo → `POST /inventario-mensual/iniciar` da 500. Misma clase silenciosa que C2.
- **Fix:** Agregar `"ALTER TABLE inventarios_mensuales ADD COLUMN barista_id INTEGER"` y `... barista_nombre VARCHAR(100)` a `main.py`.

---

## 🟡 MEDIUM (15)

| # | Título | Ubicación | Impacto | Fix |
|---|--------|-----------|---------|-----|
| M1 | TabConteos traga errores de fetch | `PedidosAdmin.tsx:399-404` | Catch vacío (`/* silencioso */`); fallo del fetch = lista vacía indistinguible de "sin pendientes". | Setear el error state existente en el catch y renderizarlo. |
| M2 | `realizado_por` no se puede borrar | `services/auditorias.py:174` | `upd.get("realizado_por") or item.realizado_por` — `or` ignora el `null` → el nombre viejo persiste. | Chequeo por presencia: `if "realizado_por" in upd: item.realizado_por = upd[...] or None`. |
| M3 | Validación de umbrales corta con `stock_minimo=0` | `routers/inventario.py:118-121` | `if inv.stock_critico and inv.stock_minimo and ...` — el 0 es falsy → permite `critico > minimo` incoherente. | Usar `is not None` en vez de truthiness. |
| M4 | Ticker muestra `"null: mensaje"` | `components/TickerNoticias.tsx:60` | Si `titulo` es null, el template literal coacciona a `"null"`. Visible en el POS. | Invertir el guard: `c.titulo ? \`${c.titulo}: ${c.mensaje}\` : c.mensaje`. |
| M5 | Push test "0 dispositivos" con VAPID sin configurar | `services/push.py:98-99` | Si falta `VAPID_PRIVATE_KEY`, devuelve 0 con HTTP 200 — idéntico a "sin suscriptores". Canal roto parece vacío benigno. | Devolver flag `push_habilitado` y avisar en el front. |
| M6 | PagosProveedores traga errores de pago | `PagosProveedores.tsx:81-93` | `catch { /* noop */ }`, sin error state. Pago fallido = cero feedback (dinero). | Agregar error state y mostrarlo; solo cerrar/recargar en éxito. |
| M7 | Ajuste de inventario ignora `X-Barista-Id` | `routers/inventario.py:21-24` | Atribución al device en kiosko (mismo defecto que H8, visto desde el endpoint). | Igual que H8: columnas + migración + `get_barista_actor`. |
| M8 | Rutinas en "alert" entre turnos | `services/rutinas.py:149-162` | Sin turno activo, el fallback toma el último evento sin cota temporal → minutos inflados y todo en `alert`. | Cuando `turno` es None, devolver estado neutro o acotar a ventana reciente. |
| M9 | Conciliación con KPIs en cero para conteos abiertos | `pages/ConciliacionInventario.tsx` · `services/inventario_mensual.py:132-170` | `get_conciliacion` no filtra por `estado`; diferencias solo se calculan en `cerrar()` → conteo `en_proceso` muestra todo $0 (se lee como "sin discrepancias"). | Devolver None/flag si `estado != 'cerrado'`, o banner en el front. |
| M10 | Ajuste de barista es set-absoluto pero la UI dice "cantidad" | `pages/Inventario.tsx:579-594` · `services/inventario.py:105-114` | `ajuste` hace `stock_actual = cantidad` (reemplaza). El input solo dice "Cantidad" → sobrescritura silenciosa; un 0 vacía el stock. | Relabelizar a "Stock final (reemplaza el actual)", mostrar stock actual y confirmar si baja. |
| M11 | Pago mixto: igualdad estricta de floats traba "Cobrar" | `components/CheckoutModal.tsx:91` | `ef + tar === totalEstimado` con floats crudos → un redondeo IEEE-754 deshabilita el botón sin explicación. | Tolerancia: `Math.abs(ef + tar - total) < 0.01`. Idem en los `diff === 0`. |
| M12 | `tienda_id` cae a 1 para admin sin sede → corrupción cruzada | `pages/ConfigTicket.tsx:30` | `user?.tienda_id ?? 1`: un admin con `tienda_id` null lee/sobrescribe la config de ticket de la tienda 1 sin aviso. | No defaultear; mostrar estado de error y no hacer GET/PUT hasta elegir tienda. Endurecer `ensure_tienda_access`. |
| M13 | "Todo coincide" permite cerrar sin contar | `components/ConteoInventario.tsx:54-59,86` | El botón llena todo con el stock del sistema y habilita Confirmar; el cierre reconcilia a esos valores → drift nunca detectado. | Decisión de producto: diálogo de confirmación o exigir N filas editadas. |
| M14 | Foto de cierre se pierde si falla `/entrega` | `pages/Cierre.tsx:128` | La imagen va solo en el FormData de `/entrega`; si da 400 (C1), la prueba de cierre nunca se guarda. | Mismo fix que C1 (rutear por `/salida`, que persiste la foto atómicamente). |
| M15 | `cerrar_caja` recalcula diferencia → 400 por race | `services/caja.py:221-244` | Un movimiento concurrente entre carga y submit cambia la diferencia server-side → 400 "se requiere justificación" que la UI no mostró. | Devolver la diferencia recalculada para reprompt, o `refresh()` antes de submit. |

---

## ⚪ LOW (28)

| # | Título | Ubicación | Impacto / Fix |
|---|--------|-----------|---------------|
| L1 | SolicitudPedido sin historial | `pages/SolicitudPedido.tsx` | La barista no ve sus pedidos enviados ni el estado (riesgo de duplicar). Fix: GET `/solicitudes/pedido/tienda/{id}` + badges como en SolicitudSencilla. |
| L2 | `get_pendiente` lista turnos ya saldados | `services/consignaciones.py:185` | Guard `if esperado > 0` debería ser `if pendiente > 0` → filas fantasma $0 y conteo de turnos inflado. Fix: cambiar el guard. |
| L3 | ProtectedRoute → `/login` (muerto/latente) | `components/ProtectedRoute.tsx:6` | Componente sin uso hoy; si se usa, redirige a kiosko. Fix: `/admin-login` o borrar. |
| L4 | `GET /auth/tiendas` sin auth (público por diseño) | `routers/auth.py:49-52` | Lista de sedes enumerable. Es intencional (selección pre-login). Fix: decisión de producto, no romper el flujo pre-auth. |
| L5 | TabPedidos traga errores | `pages/PedidosAdmin.tsx:318-328` | `.catch(() => {})` → tab en blanco sin distinguir error de vacío. Fix: error state + retry. |
| L6 | `ConfigTicket.tienda` unidireccional (latente) | `models.py:115` | Funciona; agregar `back_populates` a un solo lado crashearía el mapper. Fix: opcional, ambos lados o ninguno. |
| L7 | Relaciones SQLAlchemy: PASS | `models.py` | Sin huérfanos `back_populates`; backend arranca sano. Sin acción. |
| L8 | `cambio` puede ser null vs `TicketData: number` | `components/CheckoutModal.tsx:109-110` | Latente; hoy null-safe. Fix: normalizar `cambio ?? 0` o tipar `number \| null`. |
| L9 | Schema de merma acepta `motivo` vacío | `schemas/mermas.py:10` | Llamada directa con `motivo:''` persiste registro sin razón (UI sí valida). Fix: `Field(min_length=1)`. |
| L10 | `audit.registrar` con `registro_id=None` en merma | `services/mermas.py:83-88` | El AuditLog no referencia el id de la merma (falta `flush`). Fix: `db.flush()` y pasar `merma.id`. |
| L11 | N+1 en `sugerencia_pedido` | `services/pedidos.py:67-75` | Un SELECT por fila por `inv.producto`. Fix: `joinedload(Inventario.producto)`. |
| L12 | NotifBell oculta para admin multi-sede (tienda null) | `components/Layout.tsx:187` | El admin sin sede no ve campana. Fix: decisión de producto (modo all-stores) o aceptar. |
| L13 | CumplimientoAdmin: sin selector de sede + spinner infinito | `pages/CumplimientoAdmin.tsx:32-38` | `if (!tiendaId) return` antes de `setLoading(false)` → "Cargando…" eterno; sin selector multi-sede. Fix: `setLoading(false)` + selector como MantenimientosAdmin. |
| L14 | 3 modelos con FK `tienda_id` sin relación ORM | `models.py:307,325,432` | Latente; `.tienda` daría AttributeError (nadie lo usa hoy). Fix: opcional `relationship("Tienda")`. |
| L15 | N+1 en `get_bitacora` | `services/rutinas.py:211-213` | Un SELECT de Usuario por evento. Fix: bulk fetch con `.in_(ids)`. |
| L16 | `get_por_fecha` omite `dias_en_stock`/`alerta_rotacion` | `services/pasteleria.py:28-39` | Latente (la UI barista no los usa hoy). Fix: queda resuelto si H5 usa `/activos`. |
| L17 | SW `notificationclick` enfoca el primer cliente | `frontend/src/sw.ts:62-70` | Puede sacar a la barista de su tab activo. Fix: preferir el cliente cuya URL ya coincide. |
| L18 | CuadreApertura ("Paso 3 de 5") no afecta `es_operativo` | `pages/CuadreApertura.tsx:34` | Saltable → se pierde el registro EntregaTurno del cuadre. Fix: relabelizar (es opcional) o hacerlo realmente requerido. |
| L19 | `registrar_tarea` acepta `fecha` retroactiva sin validación | `routers/limpieza.py:152-191` | Se pueden marcar tareas de limpieza de semanas pasadas. Fix: ventana permitida o `created_at` separado. |
| L20 | TurnoContext useEffect sin dep `user?.kiosk` | `contexts/TurnoContext.tsx:75-82` | Si cambia kiosk sin cambiar tiendaId, el polling usa el endpoint viejo. Fix: agregar `user?.kiosk` a deps. |
| L21 | NotifBell oculta para admin tienda null (dup de L12) | `components/Layout.tsx:187` | Igual que L12. Fix: decisión de producto. |
| L22 | InventarioMensual: spinner infinito sin `tienda_id` | `pages/InventarioMensual.tsx:32-43` | `if (!user?.tienda_id) return` antes de `setLoading(false)`. Trigger real: sesión kiosko corrupta (no admin). Fix: `setLoading(false)` + mensaje. |
| L23 | Conteo reutiliza endpoint filtrado por `incluir_en_conteo` | `services/inventario.py:31` | Productos excluidos no se reconcilian en cierre (es semántica del flag). Fix: endpoint propio para conteo o documentar. |
| L24 | TickerNoticias nunca marca comunicados leídos | `components/TickerNoticias.tsx:55` | El ticker no auto-descarta (el Hub sí marca leído). Probable WONTFIX. Fix: descarte explícito si se quiere. |
| L25 | `/movimiento` devuelve ORM crudo sin `response_model` | `routers/inventario.py:21` | Latente; ambos fronts ignoran el body. Fix: declarar `response_model` Pydantic. |
| L26 | `FacturaCompra.fecha_recibido` nullable mismatch | `models.py:756` | `nullable=False` en ORM, migración crea nullable (filas viejas con NULL). No crashea (hay fallback). Fix: `nullable=True` o backfill + SET NOT NULL. |
| L27 | `ajustar_stock` 404 si un producto no tiene fila Inventario | `services/compras.py:25-28` | Edge case (la UI solo lista productos con fila). Rollback de todo el conteo. Fix: upsert de la fila Inventario. |
| L28 | `ajustar_stock` raíz = 404 fila faltante (dup de L27) | `services/inventario.py:63-68` | Mismo defecto visto desde `registrar_movimiento`. NO es la causa del "Error" de barista (es admin-only). Fix: mismo que L27. |

---

## Orden de ataque sugerido

1. **C2 + H10** (migraciones faltantes) — 1 línea c/u, idempotentes, eliminan 500 silenciosos.
2. **C1 + H7 + M14** (unificar cierre de turno por `/salida`) — desbloquea el cierre y salva la foto.
3. **H2** (parseo de error en inventario admin) — resuelve el síntoma "Error" reportado.
4. **H1, H9** (logout y atribución de barista) — correctness de sesión.
5. **H4** (traslado→lote), **H3** (dashboard mermas), **H5** (pastelería) — datos correctos.
6. Resto de high → medium → low según prioridad operativa.
