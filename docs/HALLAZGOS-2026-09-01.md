# Hallazgos y cambios — 1 de septiembre de 2026

Cierre de agosto, apertura de septiembre y auditoría completa de recetas.
Sedes: **Vida = tienda 1**, **Palmetto = tienda 2**.

---

## 1. El conteo de cierre de agosto quedó como inventario real

**Qué se hizo.** Se fijó el stock de los 123 productos contados en cada sede
exactamente en lo que contaron las baristas, sin sumar ni restar nada de lo que
traía el sistema. 71 ajustes en Vida y 68 en Palmetto (los demás ya coincidían).
Verificado: **246 de 246 productos quedaron iguales a lo contado, cero
descuadres.** Entre el cierre del conteo (31-ago 7:36 pm Vida, 7:41 pm Palmetto)
y la aplicación no hubo ningún movimiento, así que no se borró nada.

**Por qué a mano y no con el botón de la app.** El botón «aplicar conteo» suma la
diferencia al stock actual (`stock_actual + diferencia`) en vez de fijar el valor
contado. Con eso quedaban en negativo varias líneas y la operación se bloqueaba:
Salsa Frutos Rojos en Vida habría quedado en −30, Helado Vainilla en Palmetto en
−400, Croissant Mantequilla en −6.

**Mecanismo usado.** `POST /inventario/movimiento` con `tipo: "ajuste"` — es el
único que tiene semántica absoluta (`stock_actual = cantidad`), sincroniza los
lotes FIFO y deja movimiento auditable. Motivo:
`Inventario mensual 08/2026: se fija el stock en lo contado`.

---

## 2. BUG: aprobar una verificación de conteo se come los movimientos del medio

**El defecto.** `resolver_verificacion` (backend/app/services/conteos.py) escribe
`cantidad_verificada` como stock absoluto **en el instante de aprobar**, no en el
instante del conteo. Todo lo que se movió entre el conteo y la aprobación se
borra en silencio.

**Ocurrió dos veces el 1-sep:**

| Sede | Producto | Contado | Se movió después | Quedó mal | Corregido a |
|---|---|---|---|---|---|
| Vida | Mezcla granizado | 5.800 (6:26 am) | +7.500 (preparación 8:12 am) | 5.800 | **13.300** |
| Vida | Leche en polvo | 1.664 | −900 (misma preparación) | 1.664 | **764** |
| Vida | Leche condensada | 4.949 | −1.800 (misma preparación) | 4.949 | **3.149** |
| Vida | Croissant mantequilla | 3 | −2 (venta 8:57 am) | 0 | **1** |
| Palmetto | Almojabanas | 12 (8:37 am) | −1 (venta 8:55 am) | 12 | **11** |

**Señal para detectarlo.** Cuando la barista responde la verificación repitiendo
el número del conteo de apertura al gramo exacto, a pesar de que hubo consumo en
el medio, no es un reconteo: es una re-digitación. Vida repitió 1.664 y 4.949
después de una preparación que se llevó 900 y 1.800 gramos.

**Regla que se adoptó.** El conteo físico es verdad **en el momento en que se
tomó**; los movimientos posteriores se ruedan encima:
`stock = contado(o verificado) + movimientos posteriores al conteo`.
Con esa regla los 54 productos de la apertura de Vida cuadran exactamente.

**Arreglo pendiente en código:** que la aprobación de una verificación ruede sola
los movimientos posteriores, igual que ya hace el conteo mensual.

---

## 3. Cocoa: se vendía en gramos y descontaba 1 gramo por taza

`Cocoa` (#1036) era un solo producto: el polvo en gramos Y la bebida del POS a
$10.900. Cada taza vendida descontaba **1 gramo**.

Medido en agosto: 26 tazas vendidas, **132 gramos desaparecidos** → ~5 gr/taza.

**Arreglo aplicado.** Se separó igual que las aromáticas:
- `Cocoa` (#1036) sigue en el POS a $10.900, `controla_stock=False`, con receta
  de **6 gr** de `Cocoa en polvo`.
- `Cocoa en polvo` (#1077) es el insumo que cuentan las baristas: 229 gr en Vida,
  230 gr en Palmetto, mínimo de 200 gr en ambas.

Falta ponerle el costo (el paquete de Makro).

---

## 4. Aromáticas: la bolsita y la bebida eran el mismo producto

Las 5 aromáticas (Cidrón #786, Hierbabuena #789, Limoncillo #792, Manzanilla
#795, Toronjil #798) no tenían receta: vender una descontaba **1 bolsita** cuando
una taza lleva **2**.

Eso explicaba el faltante crónico de agosto en Vida: 24 bolsitas de más contra 37
aromáticas vendidas.

**Arreglo aplicado.** Para cada una:
- La bebida conserva su precio ($5.900), pasa a `controla_stock=False`,
  `incluir_en_conteo=False` y receta de **2 × bolsita**.
- Se creó `Aromatica de X (bolsitas)` (#1072–#1076) como insumo, con el saldo
  intacto, en la misma posición de la planilla (orden 42–46) y mínimo de 10.
- Costo: **$8.500 la caja de 20 = $425 la bolsita** (`precio_costo` en las 5).

**Efecto en el margen.** Una aromática cuesta $850 y se vende a $5.900 → margen
real de $5.050 (86%). Antes el sistema la reportaba con 100% de margen.

---

## 5. Auditoría de las 101 recetas del POS

Método: escalera de conciliación de agosto (`/inventario-mensual/escalera`) en
las dos sedes, cruzada con el recetario completo. La firma de una receta mal
dosificada es **un faltante proporcional a lo vendido que aparece en las DOS
sedes** (la receta es global).

### 5.1 Salsas cortas — CORREGIDO

| Insumo | Receta decía | Real Vida | Real Palmetto | Plata/mes |
|---|---|---|---|---|
| Salsa Caramelo | 30 gr | 34 | 34 | $31.300 |
| Salsa Chocolate | 30 gr | 32 | 35 | $26.700 |
| Salsa Frutos Rojos | 30 gr | 45 | 35 | $22.400 |
| Salsa Maracuyá | 30 gr | 43 | 34 | $13.200 |

Caramelo y Chocolate son las más confiables: 14% y 15% de faltante casi idéntico
en las dos sedes. Frutos Rojos y Maracuyá dan muy distinto entre sedes (49% vs
15%), eso es dosificación a ojo de cada barista, no la receta.

**Aplicado:** las 4 salsas subieron de 30 a **34 gr** en **22 recetas**. Las **7
porciones chicas de 20 gr** (Granizado Baileys y los 5 Mokaccinos saborizados)
quedaron intactas a propósito.

### 5.2 Pendientes de decisión

| Insumo | Receta | Real Vida | Real Palmetto |
|---|---|---|---|
| Leche Condensada | 30 gr | 36 | 43 |
| Helado Vainilla | 200 gr | 204 | 245 |

`Agua Medium Caliente` ($1.900) se vende y no descuenta nada — debería descontar
un agua. `Bebida Agrandada` ($2.000) probablemente está bien así (es recargo).

### 5.3 Dosis inconsistentes entre bebidas parecidas (sin resolver)

- **Salsa Chocolate**: 30 gr en 12 bebidas, 20 gr en los Mokaccinos saborizados
  (Amaretto, Baileys, Canela, Macadamia, Vainilla) y Granizado Amaretto.
- **Salsa Caramelo**: 30 gr en 6, 20 gr solo en Granizado Baileys.
- **Milo**: 30 gr en 4, 20 gr en Granizado Milo.
- **Galleta Oreo**: 30 gr en 2, 20 gr en Granizado Oreo.
- **Saborizantes** (Vainilla, Canela, Macadamia): 20 gr en cappuccinos, 10 gr en
  mokaccinos.

Puede ser intencional (el mokaccino ya lleva chocolate) o carga errónea.

### 5.4 Lo que se revisó y está bien

- Los **13 productos que descuentan 1 unidad de sí mismos** (tortas, croissants,
  pasteles, aguas, esponjado): todos en `und`, todos cuadran con faltante de 0 a
  2 en el mes. Cocoa era el único en gramos.
- Los **sobrantes grandes NO son receta**: café +9.167 gr y saborizante vainilla
  +5.609 gr vienen de que el libro arrancó agosto en negativo (café en Vida
  −7.626, vainilla en Palmetto esperaba −2.100). Es mercancía que entró sin
  registrar.
- **Leche Deslactosada** aparece como «insumo sin consumidor» pero es correcto:
  entra por la cascada a sustituto desde Leche Entera.

---

## 6. Datos sueltos sin resolver

- **Papel Aluminio en Vida**: el sistema tenía 0 y contaron 572. Se dejó en 572
  porque es lo contado, pero el salto es raro.
- **Azúcar Blanca Tubos en Palmetto**: el conteo de apertura dijo 2, la
  verificación confirmó **556**. El 2 era error de conteo, no faltante.
- **Agua Medium botella en Vida**: se vendieron 192 y faltan 21. No es receta —
  es fuga real.
- **Palmetto: 6 diferencias de la apertura sin aplicar** (azúcar a granel +210,
  chai −170, oreo +40, mezcla granizado +30, sour cream −20, cocoa +10). Siguen
  con el número de agosto.

---

## 7. Notas de operación del sistema

- **Dónde ver las mermas por sede, producto y fecha**: `Informes` → pestaña
  `Movimientos` → chip `Mermas`. Filtra por sede (incluye «Ambas»), rango de
  fechas y búsqueda de producto, y exporta a Excel. La pantalla `Mermas` del menú
  es solo de registro: muestra únicamente el día de hoy y la sede del usuario.
  En agosto: 47 mermas en Vida y 124 en Palmetto, casi todas consumo de personal
  y descargas de tarjeta virtual, no daño.
- **Falta**: un resumen de mermas valorizado en Informes (cuánto costó el consumo
  interno por sede y producto). Hoy la lista existe pero no suma plata.
- `/inventario/tienda/{id}` excluye lo que tiene `incluir_en_conteo=False`
  (vasos, tapas, helado); esos salen por `/inventario/desechables/{id}`. Para
  barrer el catálogo completo hay que consultar los dos.
