# Cafe-Sistema — Arquitectura Definitiva del Sistema Operativo

> Documento de arquitectura. Producido tras una auditoría multi-agente del código real
> (42 modelos, routers, servicios, frontend) contrastada contra la visión de producto.
> Este documento RECONCILIA las propuestas en un solo diseño coherente — no cuatro diseños
> en paralelo. Las decisiones marcadas con **[DECISIÓN]** son del founder y gatean el resto.

---

## 0. Veredicto en una línea

La visión es correcta y **~80% de la columna vertebral ya existe** cableada por `turno_id`.
No hace falta reescribir. Hace falta: **un agregado nuevo por encima del turno (`DiaOperativo`)**,
**una máquina de estados en el turno**, **6 tablas de eventos que faltan**, y **atribución en dos capas**.
Todo lo demás es reuso.

---

## 1. Correcciones a la auditoría (verificadas contra el código)

Dos afirmaciones de los agentes eran falsas o exageradas. Las corrijo aquí porque cambian la prioridad:

### 1.1 El "race condition del turno" NO es un no-op — está defendido
- La crítica afirmó que no existe constraint y que dos dispositivos pueden abrir dos turnos.
- **FALSO.** En `backend/app/main.py:76` existe:
  ```sql
  CREATE UNIQUE INDEX IF NOT EXISTS uq_one_turno_abierto
    ON caja_turnos (tienda_id) WHERE estado = 'abierto'
  ```
- Este índice parcial enforce **un turno abierto por sede** a nivel de base de datos, atómicamente.
  El `except IntegrityError` en `caja.py` SÍ se dispara. El agente leyó solo `models.py` (donde no hay
  `Index()` en la clase) y no vio el DDL inline en `main.py`. La defensa existe.
- **Consecuencia:** mantener "un turno abierto por sede" (lo que ya tenemos) es la decisión correcta
  de concurrencia (ver **[DECISIÓN D4]**). NO migrar a "uno por tipo simultáneo".

### 1.2 Producción ya corre en PostgreSQL
- El default en `config.py:16` es SQLite, pero `DATABASE_URL` se lee del entorno y en Render
  apunta a PostgreSQL. **En prod ya estás en Postgres.**
- El "techo de SQLite" aplica solo a desarrollo local. La migración a Postgres no es una emergencia;
  es alinear el entorno de dev con prod. El índice parcial y los row-locks ya funcionan en prod.

**Neto:** la "emergencia #1" de la crítica no existe. Eso libera la secuencia para enfocarse en el
diseño, no en apagar un incendio que ya está apagado.

---

## 2. La tensión crítica, resuelta

**El POS-first y el flujo con gates NO se contradicen. Se reconcilian con un concepto:**

> **El gate se paga UNA vez, por APERTURA DE TURNO — no por sesión, no por venta.**

- La primera barista abre el turno con el flujo completo, UNA vez:
  `Sede (device) → PIN → Tipo de turno → Baristas → Cuadre llegada → Conteo apertura → POS`.
- Cuando `tiene_conteo_apertura = true`, el turno queda **OPERATIVO**. Desde ahí el dispositivo
  arranca directo en POS el resto del turno. No re-gatea en reload, crash, ni en hora pico.
- "Vender aunque llegue el proveedor en tráfico alto" se preserva: el conteo se hizo a las 6am
  en la apertura, no a las 2pm en el rush. A esa hora el turno ya está operativo y el POS es instantáneo.

**Por qué el conteo de apertura DEBE volver como gate (cuestionando la remoción que hicimos):**
Sin conteo de apertura no hay línea base → el `cantidad_sistema` del conteo de cierre es ficción →
la merma es incalculable → las diferencias de inventario no se pueden atribuir → toda la promesa de
"decisiones basadas en datos" se cae. El error original no fue gatear; fue gatear la unidad equivocada
(la sesión). Gateando el *turno*, el rush no paga nada.

**Intermedio y cierre heredan la línea base del día y NO repiten el conteo de apertura.**
Eso es la continuidad hecha concreta.

### [DECISIÓN D2 — RESUELTA] Gate duro, sin override

El founder eligió: **sin turno abierto y contado, no se vende. Punto.** No hay excepción, no hay override.
Esto SIMPLIFICA el diseño — se elimina toda la maquinaria de excepción:
- NO hay estado `operando_con_override`. La máquina de estados es lineal:
  `iniciado → caja_validada → conteo_apertura_ok → operando → conteo_cierre_ok → entregado → cerrado`.
- NO hay `Novedad(tipo=gate_override)`. Las novedades quedan solo para incidentes/notas reales.
- `es_operativo` es un booleano duro: `tiene_cuadre_llegada && tiene_conteo_apertura`. Sin él, el
  backend RECHAZA toda venta. Cero huecos de auditoría.

**Consecuencia aceptada:** la primera venta del día exige completar el flujo de apertura (cuadre + conteo)
sí o sí. El caso "proveedor en hora pico" sigue cubierto porque a esa hora el turno YA está abierto.
El único costo es la apertura misma — por eso el flujo de apertura debe ser RÁPIDO (ver nota de build).

> **Nota de build (calidad):** con gate duro, abrir el turno y hacer el conteo de apertura tiene que ser
> ágil — pocos taps, insumos críticos pre-cargados, sin campos innecesarios. Un gate duro sobre un flujo
> lento se siente como un bloqueo; sobre un flujo rápido, se siente como disciplina. El diseño del conteo
> de apertura es, por lo tanto, crítico para que esta decisión funcione en la práctica.

---

## 3. La columna vertebral: `DiaOperativo`

Hoy `CajaTurno` es el tope de la cadena → no hay entidad que diga "este es el martes de Sede Vida,
y estos 3 turnos le pertenecen". La continuidad se reconstruye con queries por rango de fechas — frágil.

`DiaOperativo` es el **dueño del día**. Una fila por `(tienda_id, fecha_operativa)`. Cada turno apunta
hacia arriba a él. Los rollups del día, el flag de apertura/cierre del día, y "¿cerró bien ayer?" viven acá.

```python
class DiaOperativo(Base):
    __tablename__ = "dias_operativos"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    fecha_operativa = Column(Date, nullable=False, index=True)   # día-negocio, NO utcnow
    estado = Column(SAEnum(EstadoDiaEnum), default="abierto")    # abierto | cerrado | incompleto
    abierto_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    cerrado_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True)
    fecha_apertura = Column(DateTime, default=datetime.utcnow)
    fecha_cierre   = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("tienda_id", "fecha_operativa", name="uq_dia_tienda_fecha"),)
```

`CajaTurno` recibe: `dia_operativo_id` (FK), `turno_anterior_id` (FK self, cadena de turnos),
`estado_flujo` (máquina de estados), `secuencia_dia`.

**Por qué `Date` y no `DateTime`:** un día de café cruza la medianoche (cierre a las 00:30). El día
*operativo* es una decisión de negocio fijada en la apertura, NO el reloj de pared. Este campo mata
toda la clase de bugs "ventas después de medianoche contadas en el día equivocado".

**Continuidad = caminar un FK, no adivinar:** intermedio/cierre leen `dia.turnos` ordenados por
`fecha_apertura` para heredar conteo de apertura, cuadres previos, mermas, ventas acumuladas.
La visión "la info NO se reinicia entre turnos" queda **garantizada estructuralmente**.

### Decisión de rollups: tablas separadas, job después del cierre
Los rollups (`rollup_dia_sede`, `rollup_dia_producto`, `rollup_dia_barista`) NO van como columnas en
`DiaOperativo` ni se calculan dentro de la transacción de cierre (eso bloquearía el "cerrar turno").
Van en tablas separadas, materializadas por un job **después del commit** del cierre del día.
Días cerrados son inmutables → su rollup nunca se recalcula. El dashboard lee agregados; solo "hoy"
se calcula en vivo. **[DECISIÓN D5]**

---

## 4. Responsabilidad compartida: resuelta por query, no por schema

La visión dice que cada registro se asocia a TODAS las baristas del turno. La lectura ingenua es
"agregar una lista de baristas a cada tabla". Eso está MAL — denormaliza el mismo hecho en 10 tablas.

**El modelo correcto ya está puesto:**
- `TurnoBarista (turno_id, usuario_id, nombre_snapshot)` es la única fuente de verdad de
  "quién es responsable de este turno". Ya existe.
- Cada registro operativo **ya lleva `turno_id`** (ventas, conteos, entregas) o **debe recibirlo**
  (mermas, solicitudes, movimientos_inventario, pasteleria, facturas).
- Por lo tanto: **baristas responsables de CUALQUIER registro = `TurnoBarista` donde `turno_id =
  registro.turno_id`**. Un join. Siempre consistente. Imposible de desincronizar.

### [DECISIÓN D1 — RESUELTA] Responsabilidad 100% colectiva, sin atribución individual por venta

El founder eligió: **el turno es la única unidad de responsabilidad.** No hay actor individual por venta.
Esto es coherente con la filosofía del proyecto ("importa es el turno") y **simplifica el POS**:

- **Cero fricción en el POS:** no hay chip de actor, no hay PIN por venta, no hay cache de PIN.
  El dispositivo (confiado para su sede) vende directo. El rush es instantáneo de punta a punta.
- **Atribución = el roster del turno.** Cada registro lleva `turno_id`; el set responsable es
  `TurnoBarista` de ese turno. `Ticket.usuario_id` deja de ser una afirmación de identidad individual
  (queda como el usuario kiosk / dispositivo); la responsabilidad real es el roster completo.
- **Consecuencia aceptada (sin sorpresas después):** NO existe ranking individual de baristas.
  Las métricas se atribuyen a nivel TURNO. "Qué barista vende más" no es respondible; sí lo es
  "qué turno / qué combinación de baristas rinde mejor". El `rollup_dia_barista` se reemplaza por
  atribución turno-share (cada barista del turno recibe la métrica del turno, marcada como compartida).

> Esto está alineado con la visión original kiosk-fast: el POS es device-trusted y frictionless.
> Es la decisión que MENOS fricción operativa genera. El precio es perder la competencia individual
> entre baristas — que para un equipo de responsabilidad compartida es, probablemente, deseable.

### FKs `turno_id` que faltan (aditivo, nullable para backfill)
`mermas`, `solicitudes_pedido`, `solicitudes_sencilla`, `movimientos_inventario`, `pasteleria_diaria`,
`facturas_compra`. Filas viejas = `NULL` = "legacy", los reportes hacen fallback a fecha+tienda.
NO retro-asignar turnos adivinando — eso fabrica trazabilidad falsa.

---

## 5. Los 6 módulos que faltan

Todos cuelgan de `dia_id` + `turno_id` + `usuario_id`. Reuso sobre reconstrucción.

| Módulo | Tablas nuevas | Mecánica clave |
|---|---|---|
| **Recepción de mercancía** | `recepciones`, `recepcion_items` | Al confirmar: crea `LoteInventario` + `MovimientoInventario(entrada)` + `Inventario.stock_actual += cantidad`. **Aquí sana el stock negativo**: si estaba en −4 y recibís 20, queda en 16. Suma ordinaria sobre entero con signo. |
| **Motor de rutinas** | `rutina_plantillas` (la regla), `rutina_eventos` (el hecho) | Recurrentes = EVENTOS, no checkboxes. Cumplimiento = `COUNT(eventos)` vs `esperadas_por_turno`. SIN scheduler en v1 — el cumplimiento es comparación derivada al leer. |
| **Control de temperaturas** | `equipos`, `lecturas_temperatura` | `en_rango` computado al guardar vs umbrales del equipo. Fuera de rango → `Notificacion(critico)`. Falta de lectura la detecta el motor de rutinas. |
| **Novedades** | `novedades` | Bitácora humana por turno (≠ AuditLog que son mutaciones de sistema). `requiere_seguimiento && !resuelta` se arrastra al siguiente turno → reemplaza el "le aviso por WhatsApp". |
| **Producción** | `produccion_eventos` | Activa las tablas `Receta`/`RecetaIngrediente` (hoy código muerto): producir consume ingredientes (salida) y genera producto (entrada) → food-cost %. |
| **Event log operativo** | `audit_events` | Stream estructurado y consultable (≠ `AuditLog` forense). Cada escritura emite uno. Alimenta el banner, las alertas en tiempo real y los dashboards. |

---

## 6. El banner operativo (permanente, arriba a la izquierda)

Botón flotante montado en el shell de la app, **sobre** el router outlet → sobrevive toda pantalla,
incluido POS. Lee `TurnoContext`. **Reemplaza el `BaristaBottomNav` actual.**

Colapsado: `● SEDE · Turno {tipo} · {HH:MM operando} · {n baristas}` con punto de estado.
Expandido (panel lateral que NO navega fuera del POS):
- Estado del turno (sede, día, baristas activas, caja en vivo, gates ✓)
- Accesos rápidos (cada uno abre un modal SOBRE el POS): merma, limpieza/surtido, novedad,
  solicitar sencilla, solicitar pedido, inventario rápido, ver pendientes, ver alertas
- Continuidad: cambio de turno (entrega), cerrar turno (con PIN)

Cada acción rápida es un modal sobre el POS → la barista nunca "abandona la operación".

---

## 7. El backend es la fuente de verdad del gate

`GET /caja/activo` devuelve el **veredicto del gate**: `es_operativo = tiene_cuadre_llegada &&
tiene_conteo_apertura`. El frontend lee UN booleano y rutea. Pero además:
**`POST /pos` y `/ventas` RECHAZAN la venta si `!es_operativo`.** El gate del frontend es UX;
el del backend es verdad. Un front manipulado no puede vender fuera de un turno contado.

---

## 8. Las 5 decisiones del founder

| # | Decisión | Opciones | Resolución |
|---|---|---|---|
| **D1** ✅ | Atribución por venta | (a) chip sin PIN / (b) PIN cacheado / (c) solo colectiva | **(c) RESUELTA** — responsabilidad 100% colectiva, sin ranking individual. POS frictionless. |
| **D2** ✅ | Dónde vive el gate + ¿override? | gate duro sin override / gate con override | **RESUELTA: gate DURO sin override.** Máquina de estados lineal, sin huecos. |
| **D3** ✅ | SQLite vs Postgres en dev | seguir SQLite / alinear con Postgres | **Tomada: alinear dev con Postgres**, no bloqueante — prod ya está en Postgres |
| **D4** ✅ | ¿Turnos solapados? | un turno por sede / uno por tipo | **Tomada: un turno abierto por sede** (el índice actual ya lo enforce) |
| **D5** ✅ | Rollups | columnas en DiaOperativo / tablas separadas | **Tomada: tablas separadas, job post-cierre** |

---

## 9. Roadmap por fases

Principio: **parar el sangrado → poner los cimientos → construir el OS → optimizar.**
Cada fase es entregable independiente.

- **Fase 0 — Reconciliar el build con la visión** *(días)*
  Restaurar el flujo gateado (Sede+PIN → Turno → Baristas → Cuadre → Conteo → POS), hacer `GestionTurno`
  alcanzable, convertir el gate de conteo de apertura en bloqueo real *al abrir el turno* (no por venta).
  Mantener venta con stock negativo una vez abierto. Mover el rechazo del gate al backend.

- **Fase 1 — Spine `DiaOperativo` + continuidad + atribución en dos capas** *(1-2 sem)*
  La pieza estructural. Temperaturas, recepción, producción y rollups cuelgan de `dia_id`.

- **Fase 2 — Event log + Motor de Rutinas** *(1-2 sem)*
  Tabla de eventos tipados, rutinas como eventos, primeras automatizaciones push
  (stock crítico, rutina vencida, diferencia recurrente).

- **Fase 3 — Banner operativo + Novedades barista-side** *(1-2 sem)*
  El panel permanente. Opcional SSE cuando el dolor de lag en turno compartido sea real.

- **Fase 4 — Dominios operativos: Temperaturas, Recepción, Producción** *(2-3 sem)*
  Net-new, encajan sobre el spine de Fase 1 + eventos de Fase 2.

- **Fase 5 — Hub Administrativo + analítica + forecasting de compras** *(2-3 sem)*
  Rollups materializados que responden cada pregunta de la visión en una lectura indexada.
  Cablea `lead_time_dias` (hoy poblado pero sin usar) para punto de reorden.

- **Fase 6+ — Escala** *(según carga medida, no especulativo)*
  Offline-first, partición de tablas, SSE/WebSocket, integraciones de hardware.

---

## 10. Gaps honestos (la visión los pide, el sistema no los puede dar aún)

- **Clientes (frecuencia, consumo):** no hay entidad `Cliente` ni `Ticket.cliente_id`. Toda la pestaña
  "Clientes" del hub es inconstruible hasta capturar cliente en el POS. No se finge analítica sobre datos
  que no se recogen.
- **DIAN / facturación electrónica:** la integración fiscal completa (resolución de facturación, IVA)
  sigue pendiente. La reversión de venta como **Nota Crédito** SÍ queda definida (ver §11) — cierra la
  parte contable de revertir una venta; la transmisión a DIAN es trabajo posterior.
- **Autoridad de aprobación — RESUELTA:** la autoridad de aprobación es del **ADMINISTRADOR**.
  Toda solicitud que requiera aprobación (merma de valor alto, diferencia de cuadre fuera de umbral,
  reversión de venta, solicitud de sencilla/pedido) **genera una `Notificacion` al admin** y queda
  pendiente hasta que él la apruebe o rechace. Ninguna barista auto-aprueba. El umbral que dispara la
  aprobación se configura por sede.
- **Persistencia del carrito offline:** un blip de red en hora pico pierde el carrito. La persistencia
  del ticket en curso en localStorage debería ser Fase 0, no Fase 6.

---

## 11. Reversión de venta (Nota Crédito)

Acción del **panel ADMIN** (no de la barista). Revierte una venta ya registrada; contablemente es una
**Nota Crédito**. El diseño conecta contabilidad con inventario — el principio del proyecto.

**Datos:**
```python
# Ticket.estado suma el valor "reversado" (además de completado / anulado)

class NotaCredito(Base):
    __tablename__ = "notas_credito"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=False, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="RESTRICT"), nullable=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=True)  # turno donde se reversa
    usuario_admin_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    motivo = Column(Text, nullable=False)
    valor_revertido = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    items = relationship("NotaCreditoItem", back_populates="nota", cascade="all, delete-orphan")

class NotaCreditoItem(Base):
    __tablename__ = "notas_credito_items"
    id = Column(Integer, primary_key=True)
    nota_credito_id = Column(Integer, ForeignKey("notas_credito.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    cantidad = Column(Float, nullable=False)
    producto_usado = Column(Boolean, nullable=False)   # ← la decisión que define el efecto en inventario
```

**La regla que conecta contabilidad con inventario:**
- `producto_usado = True`  → el producto se consumió. **NO se toca el inventario.** Solo se revierte la plata.
- `producto_usado = False` → el producto NO se usó. Se genera `MovimientoInventario(entrada)` que **devuelve
  el stock → "vuelve al conteo"**. El inventario queda como si la venta no hubiera consumido ese ítem.

**Efectos en cadena (todo conectado):**
- El `valor_revertido` alimenta `VentaDiaria.nota_credito` (campo YA existente) → la venta neta del día baja.
- Si la venta original fue en efectivo, la devolución es un **egreso de caja** → se refleja en el efectivo
  esperado del cuadre. No rompe la cuadratura.
- Queda **auditado**: quién (admin), cuándo, por qué, y el detalle producto-por-producto de qué volvió al stock.
