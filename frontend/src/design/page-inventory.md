# Inventario de páginas — Sistema Café

> 18 páginas totales. Generado desde el código real en `frontend/src/pages/`.

---

## /login

| Campo | Valor |
|-------|-------|
| **Archivo** | `Login.tsx` |
| **Rol** | Ambos (admin / barista) |
| **Propósito** | Selección de usuario + ingreso de PIN numérico |

**Elementos UI:**
- Grid 2 columnas de tarjetas de usuario (avatar con iniciales, nombre, rol badge)
- Campo PIN oculto (4 puntos visuales)
- Teclado numpad 3×4 (dígitos 1–9, 0, borrar)
- Botón "Ingresar" — se habilita cuando hay 4 dígitos
- Banner de error en rojo si PIN incorrecto

**Datos que muestra:**
- Lista de usuarios: `id`, `nombre`, `rol` — desde `GET /auth/usuarios`

**Acciones:**
- `POST /auth/login` con `{ usuario_id, pin }` → devuelve JWT
- Redirige a `/hub` (barista) o `/dashboard` (admin)

---

## /hub

| Campo | Valor |
|-------|-------|
| **Archivo** | `Hub.tsx` |
| **Rol** | Barista |
| **Propósito** | Centro de operaciones del turno: estado, alertas y navegación |

**Elementos UI:**
- Header sticky: logo café + nombre usuario + logout
- Sección pastelería activa: lista de lotes con badge "Fresco / Por vencer / Vencido"
- Sección stock crítico: tarjetas de productos sin stock o bajo mínimo
- Sección flujo del turno: 5 pasos secuenciales (Apertura → Conteo apertura → Ventas → Conteo cierre → Cierre), con checkmark si completado
- Grid 4×2 de acciones rápidas: Inventario, Mermas, Pastelería, Consignaciones, Pedido, Sencilla, Conteos, Entrega
- Banner "Sin turno abierto" si no hay turno activo
- Indicador KPI: cuadres de llegada del turno (si los hay)

**Datos que muestra:**
- `GET /caja/activo/{tienda_id}` → turno: `id`, `total_ventas`, `total_efectivo`, `total_tarjeta`, `tiene_conteo_apertura`, `tiene_ventas`, `tiene_conteo_cierre`, `base_real`, `efectivo_esperado_actual`
- `GET /inventario/alertas/{tienda_id}` → productos con `alerta: true` o `stock_actual: 0`
- `GET /pasteleria/tienda/{tienda_id}` → lotes activos con `fecha_frescura`

**Acciones:**
- Navega a todas las demás páginas de barista

---

## /apertura

| Campo | Valor |
|-------|-------|
| **Archivo** | `Apertura.tsx` |
| **Rol** | Barista |
| **Propósito** | Apertura de caja — cuenta el efectivo base del turno |

**Elementos UI:**
- Label "Paso 1 de 5" en amber
- Contador de denominaciones con 2 secciones colapsables (Billetes $2K–$100K, Monedas $50–$1K)
- Cada fila: badge denominación + botón − + input cantidad + botón + + subtotal COP
- Footer sticky: total en caja (grande) + fondo esperado + diferencia con badge color
- Campo justificación (aparece solo si hay diferencia)
- Botón "Abrir caja" (deshabilitado si total = 0 o hay diferencia sin justificar)

**Datos que muestra:**
- Turno activo desde `TurnoContext` (si ya existe)

**Acciones:**
- `POST /caja/abrir` con `{ tienda_id, base_real, denominaciones_json, diferencia_base, justificacion_base }`

---

## /conteo-apertura

| Campo | Valor |
|-------|-------|
| **Archivo** | `ConteoApertura.tsx` |
| **Rol** | Barista |
| **Propósito** | Conteo físico del inventario al inicio del turno |

**Elementos UI:**
- Label "Paso 2 de 5"
- Botón "Todo coincide con sistema" (rellena todos con stock actual)
- Lista de productos agrupados: ícono estado (gris/verde/rojo) + nombre + stock sistema + input cantidad
- Fila en `bg-red-50` si hay diferencia; muestra "Diferencia: +/-X unidad"
- Banner con total de diferencias encontradas
- Botón "Confirmar conteo de apertura"

**Datos que muestra:**
- `GET /inventario/tienda/{tienda_id}` → `producto_id`, `producto_nombre`, `unidad_medida`, `stock_actual`, `categoria`

**Acciones:**
- `POST /conteos/` con `{ tienda_id, tipo: 'apertura', items: [{producto_id, cantidad_real}] }`

---

## /ventas

| Campo | Valor |
|-------|-------|
| **Archivo** | `VentasDia.tsx` |
| **Rol** | Barista |
| **Propósito** | Registrar ventas del turno (acumulativas, múltiples registros por turno) |

**Elementos UI:**
- Label "Paso 3 de 5"
- Grid 3 KPIs: Total turno / Efectivo / Tarjeta (aparece si ya hay ventas)
- Input grande "Total ventas brutas" (4xl font, autoFocus)
- Input "Datáfono Bold" en azul (siempre visible)
- Panel verde en tiempo real: "Efectivo Siigo = Total − NC − Vales − Tarjeta"
- Acordeón opcional: "Vales y notas crédito"
- Botón "Registrar ventas" con feedback de éxito
- Historial de registros del turno al final

**Datos que muestra:**
- Turno desde `TurnoContext`
- `GET /ventas/turno/{turno_id}` → historial de registros

**Acciones:**
- `POST /ventas/` con `{ tienda_id, venta_total, nota_credito, vales, tarjetas, nota }`

---

## /conteo-cierre

| Campo | Valor |
|-------|-------|
| **Archivo** | `ConteoCierre.tsx` |
| **Rol** | Barista |
| **Propósito** | Conteo físico del inventario al final del turno (igual a apertura) |

**Elementos UI:**
- Label "Paso 4 de 5"
- Botón "Todo coincide"
- Lista idéntica a ConteoApertura (sin columna categoría)
- Botón "Confirmar y continuar al cierre" (bg-gray-900)

**Datos que muestra:**
- `GET /inventario/tienda/{tienda_id}`

**Acciones:**
- `POST /conteos/` con `{ tienda_id, tipo: 'cierre', items: [...] }` → redirige a `/cierre`

---

## /cierre

| Campo | Valor |
|-------|-------|
| **Archivo** | `Cierre.tsx` |
| **Rol** | Barista |
| **Propósito** | Cuadre de caja al cerrar el turno (dark theme) |

**Elementos UI:**
- Pantalla completa `bg-gray-900` (dark theme)
- Label "Paso 5 de 5"
- Panel resumen de ventas del sistema (Total / Efectivo / Tarjeta)
- Contador de denominaciones dark: Billetes y Monedas colapsables (igual a Apertura pero fondo oscuro)
- Panel KPI en tiempo real: total en caja vs esperado por sistema
- Campo Datáfono Bold con input azul grande
- Panel dual de cuadre: Efectivo (verde) + Tarjeta Bold (azul) con `CheckCircle2` o `XCircle`
- Campo justificación obligatorio si hay diferencia
- Botón "Cerrar turno"

**Datos que muestra:**
- Turno desde `TurnoContext`: `efectivo_esperado_actual`, `total_ventas`, `total_efectivo`, `total_tarjeta`, `ingresos_movimientos`, `egresos_movimientos`

**Acciones:**
- `POST /caja/{turno_id}/cerrar` con `{ efectivo_final_real, datafono_real, justificacion_cierre }`

---

## /entrega

| Campo | Valor |
|-------|-------|
| **Archivo** | `Entrega.tsx` |
| **Rol** | Barista |
| **Propósito** | Cuadre de llegada mid-turno (dark theme) — registro de entrega parcial |

**Elementos UI:**
- Dark theme completo `bg-gray-900`
- Grid 3 KPIs: Base apertura / Ventas ef. / Tarjeta
- SectionCard 1: "Cuadre efectivo" — input MoneyInput + panel diferencia verde/rojo
- SectionCard 2: "Siigo y Bold" — 2 inputs (ventas Siigo debe coincidir + Bold tarjeta) + paneles diferencia
- SectionCard 3: "Evidencia fotográfica" — ImageUploader (obligatoria recomendada)
- Botón "Confirmar cuadre de llegada" (solo si Siigo cuadra exacto)
- Aviso si Siigo no cuadra

**Datos que muestra:**
- Turno desde `TurnoContext`

**Acciones:**
- `POST /caja/{turno_id}/entrega` (multipart/form-data): `efectivo_real`, `ventas_efectivo_siigo`, `ventas_tarjeta_bold`, `imagen?`

---

## /inventario

| Campo | Valor |
|-------|-------|
| **Archivo** | `Inventario.tsx` |
| **Rol** | Ambos (barista y admin) |
| **Propósito** | Ver stock y registrar movimientos (entrada / salida / ajuste) |

**Elementos UI:**
- Contador de críticos y bajos en la parte superior
- Lista de productos: dot de color (rojo=0, amber=bajo, verde=ok) + nombre + categoría/mínimo + stock actual
- Botones + y − en cada fila para abrir modal
- Modal bottom-sheet: 3 tabs Entrada/Salida/Ajuste + input cantidad + motivo + botón confirmar
- Botón refresh

**Datos que muestra:**
- `GET /inventario/tienda/{tienda_id}` → `id`, `producto_id`, `producto_nombre`, `categoria`, `unidad_medida`, `stock_actual`, `stock_minimo`, `alerta`

**Acciones:**
- `POST /inventario/movimiento` con `{ producto_id, tienda_id, tipo, cantidad, motivo }`

---

## /mermas

| Campo | Valor |
|-------|-------|
| **Archivo** | `Mermas.tsx` |
| **Rol** | Barista |
| **Propósito** | Registrar pérdidas / productos descartados |

**Elementos UI:**
- Grid 2×N de tarjetas producto (seleccionable, borde rojo cuando seleccionado)
- Card formulario tras selección: nombre + stock disponible + input cantidad + input motivo
- Botón "Confirmar merma" en rojo
- Lista reciente: producto + cantidad negativa + motivo + fecha

**Datos que muestra:**
- `GET /inventario/tienda/{tienda_id}`
- `GET /mermas/tienda/{tienda_id}`

**Acciones:**
- `POST /mermas/` con `{ tienda_id, producto_id, cantidad, motivo }`

---

## /pasteleria

| Campo | Valor |
|-------|-------|
| **Archivo** | `Pasteleria.tsx` |
| **Rol** | Barista |
| **Propósito** | Registrar lotes de productos de panadería con fecha de frescura |

**Elementos UI:**
- Banner amber si hay vencidos o por vencer (con conteo)
- Card formulario: select producto (categoría pastelería) + input cantidad + datetime-local frescura
- Botón "Registrar"
- Lista de registros del día: nombre + cantidad + hora límite + badge "Fresco/Por vencer/Vencido" con colores

**Datos que muestra:**
- `GET /inventario/productos` → filtrado por `categoria === 'pasteleria'`
- `GET /pasteleria/tienda/{tienda_id}` → lotes del día

**Acciones:**
- `POST /pasteleria/` con `{ tienda_id, producto_id, cantidad, fecha_frescura }`

---

## /consignaciones

| Campo | Valor |
|-------|-------|
| **Archivo** | `Consignaciones.tsx` |
| **Rol** | Barista |
| **Propósito** | Registrar consignaciones bancarias con comprobante fotográfico |

**Elementos UI:**
- Input valor (grande, con `$` prefijo)
- Uploader de imagen (botón → preview con botón eliminar)
- Botón "Registrar consignación"
- Historial: imagen thumbnail + valor + fecha + badge estado (pendiente/realizada)

**Datos que muestra:**
- `GET /consignaciones/tienda/{tienda_id}`

**Acciones:**
- `POST /consignaciones/` (multipart/form-data): `tienda_id`, `valor`, `imagen?`

---

## /pedido

| Campo | Valor |
|-------|-------|
| **Archivo** | `SolicitudPedido.tsx` |
| **Rol** | Barista |
| **Propósito** | Solicitar reabastecimiento de insumos al administrador |

**Elementos UI:**
- Panel rojo si hay productos críticos: lista con stock actual vs mínimo + cantidad sugerida + botón "Agregar todos"
- Lista de productos seleccionados: nombre + controles − cantidad + + botón quitar
- Textarea de nota al admin
- Botón "Enviar solicitud"
- Lista completa de productos para agregar manualmente

**Datos que muestra:**
- `GET /inventario/productos`
- `GET /inventario/alertas/{tienda_id}`

**Acciones:**
- `POST /solicitudes/pedido` con `{ tienda_id, nota, items: [{producto_id, cantidad_solicitada}] }`

---

## /sencilla

| Campo | Valor |
|-------|-------|
| **Archivo** | `SolicitudSencilla.tsx` |
| **Rol** | Barista |
| **Propósito** | Solicitar cambio de sencilla (denominaciones) al administrador |

**Elementos UI:**
- Contador de denominaciones (igual estructura que Apertura/Cierre): billetes y monedas colapsables
- Input por denominación: monto en COP → calcula cantidad de billetes/monedas automáticamente
- Errores en rojo si monto no es múltiplo de la denominación
- Panel total a cambiar (amber, 2xl font)
- Input motivo / nota
- Botones Limpiar + Enviar solicitud
- Historial con desglose de denominaciones aprobado

**Datos que muestra:**
- `GET /solicitudes/sencilla/tienda/{tienda_id}`

**Acciones:**
- `POST /solicitudes/sencilla` con `{ tienda_id, monto_solicitado, motivo, detalle: JSON }`

---

## /conteos

| Campo | Valor |
|-------|-------|
| **Archivo** | `ConteoFisico.tsx` |
| **Rol** | Barista |
| **Propósito** | Historial / re-ingreso de conteos del turno (fallback manual) |

**Elementos UI:**
- Selector de tipo (apertura / cierre) — deshabilitado si ya completado o no disponible
- Lista de productos con input cantidad
- Botón confirmar

**Datos que muestra:**
- `GET /caja/activo/{tienda_id}`
- `GET /inventario/tienda/{tienda_id}`

**Acciones:**
- `POST /conteos/` con `{ tienda_id, tipo, items }`

---

## /dashboard

| Campo | Valor |
|-------|-------|
| **Archivo** | `Dashboard.tsx` |
| **Rol** | Admin |
| **Propósito** | Vista operativa del día: KPIs, checklist, cuadres de llegada y alertas |

**Elementos UI:**
- Layout: `Layout.tsx` (header + nav tabs horizontal)
- Grid 2×2 KPIs: Ventas día / Cuadres llegada / Turno abierto / Descuadre%
- Sección checklist del día: barra de progreso + 6 items (4 automáticos + 2 manuales con toggle)
- Tabla cuadres de llegada: usuario + hora + efectivo esperado/real + DifferenceBadge + Bold
- Sección accesos rápidos: Bandeja + Inventario
- Botón comparativo multi-tienda (si hay > 1 tienda)

**Datos que muestra:**
- `GET /dashboard/{tienda_id}` → `total_ventas`, `n_cuadres`, `turno_abierto`, `checklist` (6 campos), `cuadres_llegada[]`, alertas
- `GET /dashboard/{tienda_id}/kpis?fecha_desde&fecha_hasta`
- `GET /dashboard/comparativo`

**Acciones:**
- `PATCH /dashboard/{tienda_id}/checklist` con `{ campo, valor }` para siigo_check / limpieza_check

---

## /bandeja

| Campo | Valor |
|-------|-------|
| **Archivo** | `Bandeja.tsx` |
| **Rol** | Admin |
| **Propósito** | Aprobar o rechazar solicitudes de pedido y sencilla |

**Elementos UI:**
- Badge contador de pendientes total
- Card "Pedidos de insumos": lista de solicitudes con items + nota + botones Aprobar/Rechazar
- Card "Solicitudes de sencilla": monto grande + desglose de denominaciones + botones Rechazar/Cambiar/Aprobar
- Editor inline de denominaciones (al hacer click en "Cambiar")
- Badges estado: pendiente(amber)/aprobada(green)/rechazada(red)

**Datos que muestra:**
- `GET /solicitudes/pedido/tienda/{tienda_id}`
- `GET /solicitudes/sencilla/tienda/{tienda_id}`

**Acciones:**
- `PATCH /solicitudes/pedido/{id}/aprobar` o `/rechazar`
- `PATCH /solicitudes/sencilla/{id}/aprobar` con `{ detalle, monto_solicitado }`
- `PATCH /solicitudes/sencilla/{id}/rechazar`

---

## /informes

| Campo | Valor |
|-------|-------|
| **Archivo** | `Informes.tsx` |
| **Rol** | Admin |
| **Propósito** | Reportes históricos de ventas, mermas, inventario, cuadres y turnos + exportación CSV |

**Elementos UI:**
- Tabs horizontales: Ventas / Mermas / Inv. consumido / Cuadres / Turnos
- Filtros fecha-desde / fecha-hasta + botón Consultar en cada tab
- Tab Ventas: tabla con totales por día (venta, NC, vales, tarjetas, efectivo) + fila totales amber
- Tab Mermas: lista colapsable por producto → detalle por registro
- Tab Inv. consumido: igual a mermas
- Tab Cuadres: KPI cards + lista de cuadres con DifferenceBadge
- Tab Turnos: KPI cards + lista colapsable de turnos con detalles expandibles
- Botón export CSV (implícito — endpoint existe, frontend puede implementar)

**Datos que muestra:**
- `GET /informes/ventas`, `/mermas`, `/inventario-consumido`, `/entregas`, `/turnos`

**Acciones:**
- `GET /informes/export?tipo=ventas|mermas|inventario|turnos|entregas&tienda_id&fecha_desde&fecha_hasta` → descarga CSV

---

*Total: 18 páginas — 15 barista (incluyendo admin embebido) + 3 admin exclusivas (Dashboard, Bandeja, Informes)*
