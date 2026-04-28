# Prompt para Claude Design — Nueva interfaz Medium Café

---

## EL NEGOCIO

**Medium Café** es una cadena de cafeterías colombiana con 2 sedes en Cali.
Personal: 1 administrador que supervisa todo + baristas por sede.
Operación diaria: turno único o doble, ventas mixtas (efectivo + Bold + vales).
El sistema reemplaza un Excel manual con un flujo digital completo de turno.

---

## LOS DOS USUARIOS — son completamente diferentes

### BARISTA
- Usa el sistema en su **celular**, de pie, con las manos ocupadas
- Lo usa a las **5-6am** con sueño, antes de abrir
- El error en el cuadre de caja le genera problemas con el admin
- Necesita: **pantallas de un solo propósito, botones grandes, números claros**
- Su flujo es secuencial y guiado: 5 pasos en orden, no puede saltarse ninguno
- Tiempo promedio por pantalla: 2-4 minutos máximo

### ADMINISTRADOR
- Usa el sistema en **tablet o desktop**, sentado
- Lo usa durante el día para supervisar desde lejos
- Necesita ver el estado de **las 2 tiendas al mismo tiempo**
- Necesita: **densidad de información alta, tablas, gráficos, filtros**
- Su flujo es no-lineal: salta entre dashboard, bandeja, informes

---

## LAS 5 PANTALLAS MÁS CRÍTICAS A DISEÑAR

### 1. LOGIN — Selección de usuario + numpad PIN

**Contexto:** El barista llega a las 5am. No puede equivocarse el PIN.

**Elementos:**
- Lista de usuarios del punto de venta (máximo 6-8 personas)
- Numpad táctil de 4 dígitos (grande, imposible de errar con el dedo)
- Feedback visual inmediato al ingresar cada dígito (●●●●)
- Sin campo de texto, sin teclado del sistema

**Tono visual:** oscuro, calmado, contraste alto para ambiente de poca luz

---

### 2. HUB DEL BARISTA — Centro de operaciones (/hub)

**Contexto:** Pantalla principal después del login. El barista ve aquí qué necesita atención ahora mismo.

**Secciones en orden de urgencia (de arriba a abajo):**

**A) PASTELERÍA ACTIVA** — solo si hay lotes registrados
- Cards horizontales con: nombre, cantidad, badge de frescura (colores por tiempo)
  - 🔴 VENCIDO — rojo
  - 🟠 Vence en <2h — naranja
  - 🟢 Fresco — verde
- Badge naranja "Xd" si lleva >3 días en stock (alerta rotación)
- Botón "Terminado" por lote

**B) STOCK CRÍTICO** — solo si hay productos bajo mínimo
- "AGOTADOS" en rojo: productos con stock = 0
- "POR AGOTARSE" en ámbar: stock entre 0 y mínimo
- Botón "Pedir →" destacado

**C) PROGRESO DEL TURNO**
- Barra de progreso visual con 5 pasos:
  Apertura → Conteo → Ventas → Conteo cierre → Cierre
- Cada paso: ✓ verde (hecho) / ● ámbar (actual) / ○ gris (pendiente)
- Totales del turno: Ventas / Efectivo / Tarjeta (3 números grandes)
- **Botón "Siguiente paso"** — prominente, color ámbar, imposible ignorar

**D) ACCIONES RÁPIDAS** — Grid 4x2 de tiles cuadrados
- Ventas | Inventario | Mermas | Pastelería
- Consignación | Pedido | Sencilla | Conteos
- Tile Inventario: badge rojo si hay productos agotados

**Regla de diseño:** El barista debe saber en <3 segundos qué hacer ahora mismo.

---

### 3. APERTURA DE CAJA (/apertura)

**Contexto:** Primer paso del turno. El barista cuenta el efectivo físico.

**Elemento central — CONTADOR DE DENOMINACIONES:**
Dos columnas: Billetes y Monedas

| Denominación | Cantidad | Subtotal |
|---|---|---|
| $100.000 | [campo] | $0 |
| $50.000 | [campo] | $0 |
| $20.000 | [campo] | $0 |
| $10.000 | [campo] | $0 |
| $5.000 | [campo] | $0 |
| $2.000 | [campo] | $0 |
| $1.000 | [campo] | $0 |
| $500 | [campo] | $0 |
| $200 | [campo] | $0 |
| $100 | [campo] | $0 |
| $50 | [campo] | $0 |

**Total contado:** suma automática, grande, destacada

**Comparación:**
- Base esperada (del turno anterior): $XX.XXX
- Total contado: $XX.XXX
- Diferencia: $0 ✓ (verde si 0, rojo si hay diferencia)

**Si hay diferencia:** campo de justificación OBLIGATORIO antes de continuar.
Diseñar de forma que sea imposible ignorar — no puede avanzar sin completarlo.

**Botón "Abrir turno"** — bloqueado visualmente si hay diferencia sin justificar.

---

### 4. CIERRE DE CAJA (/cierre)

**Contexto:** Último paso del turno. El barista hace el cuadre final.

**Mismo contador de denominaciones** que en apertura.

**Resumen en tiempo real** (se actualiza al escribir):
```
Efectivo esperado:    $95.000
Efectivo contado:     $96.000
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Diferencia:           +$1.000  ← rojo si hay diferencia
```

```
Ventas Bold esperadas:  $35.000
Datafono ingresado:     $35.000
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Diferencia tarjeta:     $0  ← verde si 0
```

**Si hay CUALQUIER diferencia:** campo de justificación aparece inmediatamente.
Diseño de alerta: fondo rojo claro, borde rojo, texto explicativo.

---

### 5. DASHBOARD ADMIN (/dashboard)

**Contexto:** El admin abre la app y necesita saber el estado de todo en 5 segundos.

**Selector de tienda** visible y persistente (tiene 2 sedes).

**Fila 1 — KPIs del día** (4 cards):
- 💰 Ventas del día: $XXX.XXX
- ⚠️ Diferencia de caja: $X.XXX (verde si 0, rojo si hay)
- 📦 Stock crítico: X productos
- 🏦 Consignaciones pendientes: X

**Fila 2 — Estado de caja** (badge grande):
- SIN TURNO (gris)
- TURNO ABIERTO — CUADRADO (verde)
- TURNO ABIERTO — CON DIFERENCIA (rojo)

**Fila 3 — Checklist del día** (6 ítems con porcentaje):
- ✓ Apertura de caja (automático)
- ✓ Conteo de inventario (automático)
- ✓ Registro de pastelería (automático)
- ✓ Cierre de turno (automático)
- ○ Carga en Siigo (toggle manual del admin)
- ○ Limpieza del día (toggle manual del admin)
Porcentaje de cumplimiento visible: "4/6 — 67%"

**Fila 4 — Alertas inteligentes** (solo si hay):
- 🔴 Turno largo: abierto >16h sin cierre
- 🟡 Sin cuadre de llegada en >8h
- 🟡 Caída de ventas >30% vs semana anterior
- 🔴 Barista con diferencias repetidas

**Fila 5 — Cuadres de llegada del día**
- Tabla compacta: hora | barista | efectivo | tarjeta | diferencia | foto

---

## SISTEMA DE DISEÑO SOLICITADO

### Paleta de colores

Construir sobre estos colores semánticos para operación de cafetería:

| Rol | Color sugerido | Uso |
|---|---|---|
| Primario | Verde oscuro / teal | Acciones principales, éxito, completado |
| Crítico | Rojo | Diferencias, agotado, vencido, alerta |
| Advertencia | Ámbar / naranja | Por agotarse, próximo vencimiento, pendiente |
| Neutro oscuro | Gris pizarra | Textos, estados pendientes |
| Superficie | Blanco / gris muy claro | Fondo de cards |
| Fondo | Gris muy claro / warm white | Fondo de página |

**Paleta de identidad sugerida para Medium Café:**
Inspiración en el café colombiano — tonos cálidos terrosos (café, crema, tostado)
combinados con verde oscuro (vegetación del Valle del Cauca).
No usar azul corporativo genérico.

### Tipografía
- Headlines y números grandes: peso bold, 24-32px
- Texto de interfaz: 14-16px regular
- Labels y badges: 11-12px medium
- Fuente sugerida: Inter o Plus Jakarta Sans (Google Fonts, gratuita)

### Componentes clave a diseñar

1. **Numpad PIN** — 3x4 grid, botones 72px+, feedback táctil visual
2. **Contador de denominaciones** — tabla con suma automática, campos numéricos grandes
3. **Barra de progreso de turno** — 5 pasos con estado visual claro
4. **Badge de frescura** — pasteles rojos/naranjas/verdes, texto legible
5. **Card de stock crítico** — urgencia visual inmediata
6. **Diferencia de cuadre** — número grande, color semántico, imposible ignorar
7. **Checklist con toggle** — switch interactivo, feedback de estado
8. **Grid de acciones 4x2** — tiles táctiles, badge de alerta opcional
9. **KPI card** — número grande, label muted, indicador de tendencia

### Principios de diseño

- **Jerarquía de urgencia:** lo más urgente siempre arriba
- **Un propósito por pantalla:** el barista nunca debe preguntarse qué hacer
- **Números siempre en COP:** formato $X.XXX.XXX sin decimales
- **Colores semánticos consistentes:** rojo = problema, verde = ok, ámbar = atención
- **Táctil primero:** mínimo 44px de área de toque en elementos interactivos
- **Sin modales innecesarios:** todo en la pantalla, sin capas
- **Estados de error explícitos:** el barista no puede cometer errores silenciosos

---

## ALCANCE DEL DISEÑO

Diseñar en este orden de prioridad:

1. Sistema de diseño base (tokens, componentes, paleta)
2. Login
3. Hub del barista
4. Apertura de caja
5. Cierre de caja
6. Dashboard admin

Pantallas adicionales si hay tiempo:
- Conteo de apertura / cierre
- Registro de ventas
- Bandeja admin

---

## FORMATO DE ENTREGA ESPERADO

- Componentes en React con Tailwind CSS
- Responsive: mobile-first para barista, adaptado a tablet/desktop para admin
- Modo oscuro opcional (el login en particular)
- Archivos separados por pantalla
- Un archivo `design-system.tsx` con todos los tokens y componentes base
