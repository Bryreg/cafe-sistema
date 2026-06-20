# Cafe-Sistema — Flujos, Pestañas, Pantallas y Analíticas

> Documento de PRODUCTO (no de ingeniería). Para revisar cómo se ve y cómo se usa el sistema.
> Pantalla por pantalla, con mockups. Acompaña a `ARQUITECTURA.md` (que tiene el detalle técnico).
> Decisiones ya cerradas: responsabilidad colectiva · gate duro al abrir turno · un turno por sede.

---

## ÍNDICE

1. Las dos identidades (dispositivo vs persona)
2. La estructura del día
3. FLUJO A — Activar el dispositivo (una vez en la vida del equipo)
4. FLUJO B — Abrir un turno (el gate, se paga una vez)
5. FLUJO C — Vender (operación normal, sin fricción)
6. FLUJO D — Cambio de turno (entrega / intermedio)
7. FLUJO E — Cierre del día
8. Las pestañas y la navegación
9. El banner operativo (centro de operación)
10. Mapa de pantallas (cuadros) del barista
11. El Hub Administrativo (analíticas) — pestaña por pestaña
12. Continuidad entre turnos (qué se hereda)

---

## 1. Las dos identidades

El sistema nunca confunde QUÉ equipo es con QUIÉN lo usa.

| | DISPOSITIVO (kiosko) | PERSONA (barista) |
|---|---|---|
| Representa | La SEDE (qué tienda es esta pantalla) | QUIÉN es responsable |
| Cómo se prueba | PIN del sistema → token de 10 años | Selección de baristas al abrir turno |
| Cuándo | Una vez, al instalar el equipo | Cada vez que se abre un turno |
| Nunca | Atribuye una venta a una persona | Define qué tienda es |

Como elegiste **responsabilidad colectiva**, las ventas NO piden PIN. El dispositivo (confiado para su
sede) vende directo. La responsabilidad es del TURNO completo (todas las baristas seleccionadas).

---

## 2. La estructura del día

```
DÍA OPERATIVO (martes, Sede Vida)
│
├── TURNO Apertura     06:00 → 14:00   [Ana, Luis]
│     ├── Cuadre de llegada
│     ├── Conteo de apertura   ← línea base del día
│     ├── Ventas, mermas, rutinas, novedades...
│     └── Entrega
│
├── TURNO Intermedio   14:00 → 18:00   [María]
│     ├── Cuadre de llegada (recibe la entrega anterior)
│     ├── (NO repite conteo de apertura — hereda la línea base)
│     └── Ventas, mermas, rutinas, novedades...
│
└── TURNO Cierre       18:00 → 22:00   [Sofía, Pedro]
      ├── Cuadre de llegada
      ├── Ventas...
      ├── Conteo de cierre
      └── Cierre del día (efectivo entregado, inventario final)
```

**Todo lo del día está conectado.** El intermedio ve lo que hizo la apertura. El cierre ve todo el día.
Nada se reinicia. Nada queda suelto.

---

## 3. FLUJO A — Activar el dispositivo (una vez)

Solo se hace cuando se instala una tablet/PC nueva en la sede.

```
┌─────────────────────────────────────────┐
│                                         │
│              📶  Activar dispositivo     │
│       Ingresa el PIN del sistema         │
│                                         │
│   SEDE (ID)                             │
│   ┌─────────────────────────────────┐   │
│   │ 2                               │   │
│   └─────────────────────────────────┘   │
│                                         │
│   PIN DE SISTEMA                        │
│   ┌─────────────────────────────────┐   │
│   │ ••••••                          │   │
│   └─────────────────────────────────┘   │
│                                         │
│   ┌─────────────────────────────────┐   │
│   │       🔒  Activar dispositivo    │   │
│   └─────────────────────────────────┘   │
│                                         │
│   El admin configura el PIN    Admin → │
└─────────────────────────────────────────┘
```

Tras activar: el equipo queda ligado a esa sede para siempre (token 10 años). De ahí en adelante,
al abrir el link va directo al **resolver** que decide qué mostrar (ver Flujo B/C).

---

## 4. FLUJO B — Abrir un turno (el gate, se paga UNA vez)

Cuando NO hay turno operativo, el dispositivo entra al flujo gateado. Es la única vez que se "paga" el gate.

```
PASO 1 — ¿Quién abre?          PASO 2 — Tipo de turno
┌───────────────────────┐      ┌───────────────────────────┐
│  Ingresá tu PIN        │      │  ¿Qué turno vas a iniciar? │
│   ● ● ● ●               │      │                           │
│   1  2  3              │      │  ☀️  Apertura              │
│   4  5  6              │ ───► │     Primer turno del día   │
│   7  8  9              │      │  🌇  Intermedio            │
│      0  ⌫               │      │     Relevo de turno        │
└───────────────────────┘      │  🌙  Cierre                │
                                │     Último turno del día   │
   Reglas validadas por el      └───────────────────────────┘
   sistema: no cierre sin
   apertura, no doble apertura.            │
                                           ▼
PASO 3 — Baristas del turno    PASO 4 — Cuadre de llegada
┌───────────────────────┐      ┌───────────────────────────┐
│ 👥 ¿Quiénes están?     │      │  💵 Cuadre de llegada      │
│                       │      │  Lo que debe haber: $X    │
│ ☑ Ana                 │ ───► │  Efectivo contado: ____   │
│ ☑ Luis                │      │  Diferencia: $0           │
│ ☐ María               │      │  📷 Evidencia (opcional)  │
│                       │      │                           │
│   [ Continuar ]       │      │   [ Confirmar llegada ]   │
└───────────────────────┘      └───────────────────────────┘
                                           │
                                           ▼
PASO 5 — Conteo de apertura    →  ✅ TURNO OPERATIVO → POS
┌───────────────────────────┐
│  📦 Conteo de apertura     │   Solo en turno APERTURA.
│  (línea base del día)      │   Intermedio/cierre SALTAN este
│                           │   paso (heredan la línea base).
│  Café .......... ____      │
│  Leche ......... ____      │   ⚠ GATE DURO: sin este conteo,
│  Azúcar ........ ____      │   el POS NO se habilita. Pero una
│  Chocolate ..... ____      │   vez hecho, el turno entero vende
│  Salsas ........ ____      │   sin volver a pedirlo.
│  Desechables ... ____      │
│   [ Confirmar conteo ]     │
└───────────────────────────┘
```

**Importante:** este flujo se hace UNA vez por turno, normalmente a las 6am en calma. El proveedor que
llega a las 2pm en hora pico ya encuentra el turno operativo → se vende sin fricción.

---

## 5. FLUJO C — Vender (operación normal)

Con el turno operativo, abrir el link va DIRECTO al POS. Sin PIN, sin pasos, instantáneo.

```
┌──────────────────────────────────────────────────────────────┐
│ ☰  ● Vida · Intermedio · 14:32 · 3 baristas        [Turno] ←pestañas
├──────────────────────────────────────────────┬───────────────┤
│  CATEGORÍAS    PRODUCTOS                      │  🛒 CARRITO    │
│  ┌─────────┐   ┌──────┐ ┌──────┐ ┌──────┐    │               │
│  │ Bebidas │   │ Café │ │Latte │ │Capp. │    │ Latte    x2   │
│  ├─────────┤   │ $4.0 │ │ $6.0 │ │ $6.5 │    │ Croissant x1  │
│  │Pastelería│  └──────┘ └──────┘ └──────┘    │               │
│  ├─────────┤   ┌──────┐ ┌──────┐ ┌──────┐    │ ───────────   │
│  │ Comida  │   │Croiss│ │Muffin│ │ Pan  │    │ Total $18.5   │
│  └─────────┘   │ $5.5 │ │ $4.5 │ │ $3.0 │    │               │
│                └──────┘ └──────┘ └──────┘    │ [💵][💳][Pagar]│
└──────────────────────────────────────────────┴───────────────┘
   ☰ = banner operativo (acciones rápidas, ver sección 9)
```

- **Stock negativo permitido:** si un producto está en 0, se vende igual (queda negativo). Al recibir
  mercancía (Flujo del banner → "Recibir mercancía"), el stock se normaliza solo.
- **Sin atribución individual:** la venta queda al turno completo. No se pregunta quién la hizo.

---

## 6. FLUJO D — Cambio de turno (entrega / intermedio)

La barista que sale entrega; la que entra recibe. La info NO se reinicia.

```
SALE (Ana, Luis)                      ENTRA (María)
┌───────────────────────────┐         ┌───────────────────────────┐
│ ☰ → "Cambio de turno"      │         │  Abrir turno → Intermedio  │
│                           │         │                           │
│  💵 Entrega                │         │  👥 Baristas: ☑ María      │
│  Efectivo esperado: $X     │  ────►  │                           │
│  Efectivo real:     ____   │         │  💵 Cuadre de llegada      │
│  📷 Evidencia              │         │  (esperado PRE-CARGADO de  │
│  Estado operativo: ok      │         │   la entrega de Ana/Luis)  │
│   [ Confirmar entrega ]    │         │                           │
└───────────────────────────┘         │  ✓ Conteo apertura SALTADO │
                                       │    (hereda línea base)     │
                                       │   → OPERATIVO → POS        │
                                       └───────────────────────────┘
```

El `efectivo esperado` del intermedio sale de la entrega anterior, no de una base nueva. Eso es
"sin reinicio" en términos de plata.

---

## 7. FLUJO E — Cierre del día

```
☰ → "Cerrar turno"  (pide PIN — acción sensible)
        │
        ▼
┌───────────────────────────┐    ┌───────────────────────────┐
│  📦 Conteo de cierre        │    │  🔒 Cierre final           │
│  (vs línea base del día)    │    │  Efectivo final:    ____   │
│                           │ ─► │  Datáfono Bold:     ____   │
│  Café .... sist:10 real:__ │    │  Diferencia: $0           │
│  Leche ... sist:5  real:__ │    │  Inventario final ✓        │
│   [ Confirmar conteo ]     │    │   [ Cerrar día ]          │
└───────────────────────────┘    └───────────────────────────┘
                                           │
                                           ▼
                          DÍA CERRADO → se materializan los
                          rollups del día (alimentan el Hub)
```

Al cerrar el último turno, el día queda cerrado e inmutable, y se calculan sus resúmenes (rollups)
que alimentan las analíticas. Por eso el Hub carga rápido: lee resúmenes, no recalcula todo.

---

## 8. Las pestañas y la navegación

### Lado BARISTA (en el kiosko)
Solo DOS pestañas. Todo lo demás vive en el banner operativo (sección 9).

```
┌──────────────────────────────────────────────┐
│                                    [POS][Turno]│  ← 2 pestañas
└──────────────────────────────────────────────┘
   POS    = vender (pantalla principal, el corazón)
   Turno  = estado del turno + acciones de turno (cuadres, conteos, entrega, cierre)
```

### Lado ADMIN (en PC)
El Hub Administrativo es OTRO mundo — no es una copia del POS. Es el centro de decisiones.

```
┌────────────────────────────────────────────────────────────────┐
│ ☕ Admin   Ventas │ Clientes │ Operación │ Inventario │ Compras │ Marketing │
└────────────────────────────────────────────────────────────────┘
```
(Detalle de cada pestaña en la sección 11.)

---

## 9. El banner operativo (centro de operación)

Botón permanente arriba a la izquierda (☰). Está SIEMPRE, incluso vendiendo. Al abrirlo, panel lateral
que NO te saca del POS (todo abre como ventana encima).

```
☰  abre  ►
┌─────────────────────────────────────────┐
│ ESTADO DEL TURNO                        │
│ Sede Vida · Día martes 19/06            │
│ Turno: Intermedio · abierto 14:03       │
│ Baristas: [Ana] [Luis] [María]          │
│ Caja: base $50 · efectivo $230 · dif $0 │
│ Conteo apertura ✓ · Cuadre llegada ✓    │
├─────────────────────────────────────────┤
│ ACCIONES RÁPIDAS                        │
│ ▸ Registrar merma                       │
│ ▸ Registrar limpieza / surtido          │
│ ▸ Registrar temperatura                 │
│ ▸ Registrar novedad                     │
│ ▸ Recibir mercancía                     │
│ ▸ Solicitar sencilla                    │
│ ▸ Solicitar pedido                      │
│ ▸ Inventario rápido                     │
│ ▸ Ver pendientes / rutinas (3)          │
│ ▸ Ver alertas                           │
├─────────────────────────────────────────┤
│ CONTINUIDAD                             │
│ ▸ Cambio de turno (entrega)             │
│ ▸ Cerrar turno          🔒              │
└─────────────────────────────────────────┘
```

Cada acción abre un cuadro (modal) sobre el POS. La barista nunca "abandona la operación".

---

## 10. Mapa de pantallas (cuadros) del barista

| Pantalla | Qué muestra | Qué captura |
|---|---|---|
| **POS** | Categorías, productos, carrito | La venta (efectivo/tarjeta/mixto) |
| **Gestión de turno** | Estado del turno, baristas, ventas del día, acciones | — |
| **Cuadre de llegada** | Efectivo esperado vs contado | Efectivo real, diferencia, foto, justificación |
| **Conteo de apertura** | Lista de insumos críticos | Cantidad física de cada insumo (línea base) |
| **Conteo de cierre** | Insumos: sistema vs real | Cantidad física al cierre, diferencias |
| **Entrega** | Efectivo esperado del día | Efectivo entregado, evidencia, estado |
| **Cierre** | Resumen del turno + datáfono | Efectivo final, Bold, diferencia |
| **Merma** (modal) | Producto + tipo (consumo/daño/traslado) | Cantidad, motivo, foto |
| **Recibir mercancía** (modal) | Sugerencias (stock bajo/negativo) | Cantidades recibidas, lote, factura |
| **Temperatura** (modal) | Equipos de frío + umbrales | Lectura; avisa si está fuera de rango |
| **Novedad** (modal) | — | Incidente/nota, nivel, seguimiento sí/no |
| **Rutinas pendientes** | Qué falta hacer este turno | Marca cada rutina como evento (con hora/usuario) |
| **Solicitar sencilla / pedido** | Productos bajo mínimo | Lo que se necesita |

---

## 11. El Hub Administrativo — analíticas pestaña por pestaña

Cada pestaña responde preguntas de negocio concretas. Cada cuadro = una pregunta.

### 📊 VENTAS
```
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ Venta hoy            │ Ticket promedio      │ Método de pago       │
│ $1.240.000           │ $8.500               │ 🥧 Efectivo 60%      │
│ ▲ 12% vs ayer        │ ▲ 3%                 │    Tarjeta 35% Mixto 5│
├──────────────────────┴──────────────────────┴──────────────────────┤
│ Venta por hora (HORA PICO)                                          │
│  ▁▂▃▅█▇▅▃▂▁▂▃▅▇█▆▄▂▁   ← pico 8-9am y 17-18h                       │
├─────────────────────────────────────────────────────────────────────┤
│ Top productos          │ Top categorías                            │
│ 1. Latte    320 und    │ Bebidas    68%                            │
│ 2. Croissant 180 und   │ Pastelería 25%                            │
│ 3. Capp.    150 und    │ Comida      7%                            │
└─────────────────────────────────────────────────────────────────────┘
```
Preguntas: venta diaria/semanal/mensual · ticket promedio · método predominante · hora pico · qué se vende más.

### 👥 CLIENTES  *(requiere capturar cliente en el POS — ver gaps)*
```
Frecuencia · consumo por cliente · recurrencia.
⚠ HOY NO HAY DATOS: falta capturar cliente en la venta. Pestaña en espera
  hasta decidir si se pide identificación del cliente al pagar.
```

### ⚙️ OPERACIÓN
```
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ Cumplimiento turnos  │ Cumplimiento rutinas │ Diferencias de caja  │
│ 95% abiertos a tiempo│ 🟩🟩🟨🟥 por rutina   │ 3 turnos con dif >$5k│
├──────────────────────┴──────────────────────┴──────────────────────┤
│ Mermas del período: $85.000  ·  Novedades sin resolver: 2          │
│ Lecturas de temperatura fuera de rango: 1 (Nevera vitrina, 11:00)  │
│ 🔔 Aprobaciones pendientes: 2  [merma $40k] [reversión venta #1042]│
└─────────────────────────────────────────────────────────────────────┘
```
Preguntas: ¿se cumplen turnos y rutinas? · mermas · diferencias recurrentes de caja · desviaciones.

**Autoridad de aprobación = el ADMIN.** Toda solicitud que pasa de un umbral (merma de valor alto,
diferencia de cuadre, reversión de venta, sencilla/pedido) le llega como **notificación** y queda
pendiente acá hasta que la aprueba o rechaza. Ninguna barista auto-aprueba.

### 📦 INVENTARIO
```
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ Consumo real         │ Rotación             │ Cobertura (días)     │
│ Café 12kg/sem        │ Leche 4.2x/sem       │ Azúcar: 3 días ⚠      │
├──────────────────────┴──────────────────────┴──────────────────────┤
│ Productos críticos (bajo mínimo o negativos)                       │
│ • Vasos 12oz   -8   ⚠ negativo                                     │
│ • Azúcar       2kg  (mín 5kg)                                       │
└─────────────────────────────────────────────────────────────────────┘
```
Preguntas: consumo real · rotación · cobertura · productos críticos.

### 🛒 COMPRAS
```
┌─────────────────────────────────────────────────────────────────────┐
│ Necesidades futuras (pronóstico)                                    │
│ Producto   Consumo/día   Lead time   Punto reorden   Sugerencia     │
│ Café       1.7kg         2 días       8kg            Pedir 15kg ▸    │
│ Leche      6L            1 día        10L            Pedir 40L  ▸    │
├─────────────────────────────────────────────────────────────────────┤
│ Confiabilidad de proveedores (pedido vs factura vs recibido)        │
│ Lácteos SA: 98% completo · Café del Valle: 85% (faltantes frec.)   │
└─────────────────────────────────────────────────────────────────────┘
```
Preguntas: qué hay que comprar y cuándo · qué proveedor cumple.

### 📣 MARKETING
```
Horas pico (para promos) · productos estrella · oportunidades comerciales
(combos de productos que se venden juntos, días flojos para activar).
```

### 🏪 COMPARATIVO DE SEDES (vista transversal)
```
Sede       Venta    Ticket prom   Cumplim.   Mermas   Dif. caja
Vida       $1.2M    $8.500        95%        $85k     $12k
Palmetto   $0.9M    $7.200        88%        $120k    $31k  ⚠
→ "¿Qué sede opera mejor?" respondido en una fila.
```

### ↩️ REVERTIR VENTA → Nota Crédito  *(acción del ADMIN)*

Desde el panel admin se puede revertir una venta ya registrada. Contablemente es una **Nota Crédito**.
El paso clave es decidir, producto por producto, **si se usó o no** — porque eso define qué pasa con el inventario.

```
Ventas → buscar ticket #1042 → "Revertir venta"
┌─────────────────────────────────────────────────────────┐
│  Revertir venta #1042 · $18.500                         │
│  Motivo:  ________________________________               │
│                                                         │
│  ¿Se usó el producto?                                   │
│   Latte      x2    [ ● Sí, se usó ] [ ○ No, vuelve ]    │
│   Croissant  x1    [ ○ Sí, se usó ] [ ● No, vuelve ]    │
│                                                         │
│   ● Sí, se usó  → queda DESCONTADO del inventario       │
│   ● No, vuelve  → RE-INGRESA al stock (vuelve al conteo)│
│                                                         │
│   [ Confirmar Nota Crédito ]                            │
└─────────────────────────────────────────────────────────┘
```

**Qué pasa al confirmar (todo conectado):**
- El ticket queda marcado como `reversado` y se crea la **Nota Crédito** (contable).
- **Producto "Sí, se usó"** → se consumió de verdad. El inventario NO se toca; solo se devuelve la plata.
- **Producto "No, vuelve"** → re-ingresa al inventario (entrada) → vuelve al conteo.
- La venta neta del día baja (alimenta `nota_credito`). Si fue en efectivo, la devolución es egreso de caja
  y se refleja en el cuadre.
- Queda **auditado**: qué admin, cuándo, por qué, y qué productos volvieron al stock.

> Ejemplo: el Latte ya estaba hecho (se usó la leche y el café) → se queda descontado. El Croissant no se
> tocó → vuelve al inventario. La Nota Crédito devuelve los $18.500 igual; el inventario solo recupera lo no usado.

---

## 12. Continuidad entre turnos (qué hereda cada turno)

Cuando entra el intermedio o el cierre, NO ve pantallas en blanco. Hereda del día:

| Dato heredado | De dónde | Dónde lo ve |
|---|---|---|
| Conteo de apertura (línea base) | Conteo de la apertura | Su conteo de cierre lo usa como "sistema" |
| Cuadres previos | Entregas anteriores | Su cuadre de llegada pre-cargado |
| Ventas acumuladas | Tickets del día | Banner + Hub |
| Mermas del día | Mermas registradas | "Ver pendientes" |
| Novedades sin resolver | Novedades del turno anterior | Aviso forzado al abrir |
| Movimientos de inventario | Del día | Inventario rápido |
| Estado de caja | Turno actual | Línea de caja del banner |

**Novedad sin resolver del turno anterior = aviso obligatorio al abrir.** Reemplaza el "le aviso por
WhatsApp a la del otro turno". Queda registrado quién la creó y quién la resolvió.

---

## Resumen para revisar

- **Barista:** 2 pestañas (POS + Turno) + banner operativo con todo lo demás. Vender es instantáneo.
- **Gate:** se paga una vez al abrir el turno (cuadre + conteo). Duro, sin excepción.
- **Admin:** 6 pestañas de analítica, cada cuadro responde una pregunta de negocio.
- **Aprobaciones:** las autoriza el admin; le llegan como notificación. Ninguna barista auto-aprueba.
- **Reversión de venta (Nota Crédito):** acción del admin. Por producto se decide si se usó (queda
  descontado) o no (vuelve al conteo). Conecta contabilidad con inventario.
- **Todo conectado:** el día es dueño de los turnos; nada se reinicia; todo es trazable al turno.
- **Pendiente de decidir:** pestaña Clientes (¿se captura cliente en el POS?).
