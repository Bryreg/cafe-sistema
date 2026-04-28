# Design Brief — Rediseño UI Sistema Café

## 1. Descripción del negocio y usuarios

**Negocio:** Sistema operativo para cafeterías de la marca "Medium Café" en Colombia. Gestiona el ciclo completo del turno de cada barista: apertura de caja, conteos de inventario, registro de ventas, mermas, pedidos y cierre con cuadre de efectivo y datáfono Bold.

**Usuarios:**

| Usuario | Dispositivo | Contexto de uso |
|---------|-------------|-----------------|
| **Barista** | Celular (iPhone/Android) en mano | De pie, posiblemente con guantes, ambiente con poca luz (cafetería 5am–7am), bajo estrés operativo, en medio del servicio |
| **Administrador** | Tablet o desktop | Oficina o escritorio, visión general de múltiples tiendas, revisión al final del día o en tiempo real |

---

## 2. Flujo crítico del barista (5 pasos secuenciales)

```
1. APERTURA DE CAJA (/apertura)
   └─ Cuenta denominaciones → define base en efectivo

2. CONTEO DE APERTURA (/conteo-apertura)
   └─ Verifica stock físico vs sistema

3. REGISTRO DE VENTAS (/ventas)
   └─ Múltiples registros durante el turno: total Siigo + Bold + NC + vales

4. CONTEO DE CIERRE (/conteo-cierre)
   └─ Verifica stock físico al final del turno

5. CIERRE DE CAJA (/cierre)
   └─ Cuenta físico + lee datáfono Bold → cuadre dual (efectivo + tarjeta)
```

El sistema bloquea el paso siguiente si el anterior no está completo.
**La secuencia es la parte más crítica del producto.**

---

## 3. Flujo del admin

```
Dashboard (/dashboard)
├─ KPIs del día: ventas totales, descuadre %, turno abierto
├─ Checklist operativo: 6 items (4 automáticos + 2 manuales)
├─ Cuadres de llegada en tiempo real
└─ Alertas inteligentes

Bandeja (/bandeja)
├─ Pedidos de insumos pendientes → Aprobar / Rechazar
└─ Solicitudes de sencilla → Ajustar denominaciones → Aprobar / Rechazar

Informes (/informes)
├─ Ventas por período (filtro fechas)
├─ Mermas por producto
├─ Inventario consumido
├─ Cuadres de llegada
├─ Turnos cerrados
└─ Exportación CSV de cualquier reporte
```

---

## 4. Restricciones de diseño

### 4.1 Barista — mobile first, operativo extremo
- **Pantalla pequeña:** diseño para 375–430px de ancho. No hay desktop para barista.
- **Uso con una mano:** botones de acción principal mínimo 56px de altura (py-4). Zona de pulgares en la parte inferior.
- **Posibles guantes:** elementos táctiles con suficiente separación (gap-3 mínimo entre targets). Sin swipe ocultos.
- **Poca luz:** contraste alto. El Cierre y la Entrega ya usan dark theme (`bg-gray-900`) — esto es correcto.
- **Sin errores en cuadre:** los campos de diferencia deben ser imposibles de ignorar. Usar rojo intenso y bloquear el submit si hay diferencia sin justificar.
- **Velocidad:** el barista puede tener 5 clientes esperando. Mínimo de taps para completar el flujo.

### 4.2 Admin — tablet / desktop
- Puede usar pantallas más anchas (max-w-5xl).
- Nav horizontal con 5 tabs es adecuado.
- Tablas de datos son aceptables (no en barista).
- El Dashboard debe ser un "single screen" sin scroll excesivo.

### 4.3 Contexto colombiano
- Monedas: COP. Formato `$1.234.567` (miles con punto, sin decimales para montos enteros).
- Denominaciones: $50, $100, $200, $500, $1.000 (monedas) | $2.000, $5.000, $10.000, $20.000, $50.000, $100.000 (billetes).
- Nombres de usuarios colombianos (Juan Sebastián, Valentina, Camila, etc.).
- Horarios: apertura 5:30–6:00am, cierre 8:00–10:00pm.

---

## 5. Pantallas prioritarias para rediseño (orden de impacto operativo)

| Prioridad | Pantalla | Razón |
|-----------|----------|-------|
| 🔴 1 | `/cierre` | El cuadre de caja es el punto más crítico — errores cuestan dinero |
| 🔴 2 | `/apertura` | Primera acción del día — define la base del turno |
| 🔴 3 | `/hub` | Centro de navegación — el barista lo ve 50+ veces por turno |
| 🟠 4 | `/ventas` | Se usa 3–5 veces por turno — input principal del negocio |
| 🟠 5 | `/conteo-apertura` | Lista larga — necesita UX de escaneo rápido |
| 🟠 6 | `/entrega` | Cuadre mid-turno — alta tensión operativa |
| 🟡 7 | `/dashboard` | Admin lo revisa 2–3 veces al día |
| 🟡 8 | `/bandeja` | Aprobaciones rápidas — necesita claridad en estados |
| 🟢 9–18 | Resto | Mermas, pastelería, pedido, sencilla, consignaciones, informes |

---

## 6. Identidad visual actual

**No existe un sistema de diseño formal.** El sistema usa Tailwind CSS puro con los defaults del framework.

**Color dominante:** `amber-600` (#d97706) — usado como CTA principal, acentos, steps del flujo.

**Paleta en uso:**
- Acción principal: `amber-600` → hover `amber-700`
- Éxito: `green-500 / green-600`
- Peligro: `red-500 / red-600`
- Info / tarjeta: `blue-600`
- Dark UI (cierre/entrega): `gray-900` base, `amber-400` accent

**Sin logo formal** en la interfaz — solo ícono `Coffee` de Lucide + texto "Sistema Café".

**Sin tipografía de marca** — sistema usa la fuente del sistema operativo (system-ui).

---

## 7. Oportunidades de mejora identificadas

1. **Hub del barista:** el grid 4×2 de acciones no tiene jerarquía visual. El flujo principal (5 pasos) y las acciones secundarias deberían tener pesos visuales distintos.
2. **Apertura/Cierre:** las denominaciones son funcionales pero densas. En la oscuridad y con guantes, los targets de +/- son pequeños (32×32px).
3. **Conteos:** la lista plana sin agrupación por categoría hace difícil encontrar un producto rápido. ConteoApertura tiene categorías en los datos pero no las usa para agrupar.
4. **Dashboard:** la barra de progreso del checklist es la única visualización — los 6 items individuales son invisibles.
5. **Login:** el numpad funciona pero el feedback de PIN (puntos) es minúsculo en pantallas pequeñas.
6. **Alertas:** existe un engine de alertas inteligentes en el backend (`GET /alertas/{tienda_id}`) que no tiene UI en el frontend aún.
7. **Notificaciones:** existe sistema de notificaciones en backend (`GET /notificaciones/`) sin badge/centro de notificaciones en el frontend.

---

## 8. Consideraciones técnicas para el rediseño

- El sistema es **mobile-first SPA** en React + TypeScript + TailwindCSS
- El rediseño debe mantenerse en Tailwind (sin cambiar a CSS custom ni otro framework)
- El dark theme de Cierre/Entrega es intencional y debe preservarse
- No hay assets gráficos (imágenes, íconos de marca) — solo Lucide Icons
- Las pantallas del barista usan `max-w-lg mx-auto` (512px centrado)
- Las pantallas del admin usan `max-w-5xl mx-auto` (1024px centrado)
