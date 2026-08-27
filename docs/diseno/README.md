# Propuestas de pantalla — «La vida de cada insumo»

Tres tableros de Claude Design con **tres formas distintas** de presentar la
misma información de inventario: la barra de stock, las entradas y los conteos
físicos de la semana del 21 al 27 de agosto de 2026, con datos reales de Vida y
Palmetto.

| Archivo | La pregunta que responde | A cambio |
|---|---|---|
| `Main.dc.html` | **¿cuánto?** — una barra por insumo a cada lado de lo que el sistema dice, ordenadas por lo que *vale* la diferencia | pierde el tiempo: sólo muestra el estado de hoy |
| `Tendencia.dc.html` | **¿hacia dónde va?** — los siete conteos de cada insumo contra la línea del cero | no dice cuánta plata hay en juego, y cada renglón tiene su propia escala |
| `Parte.dc.html` | **¿qué hago?** — tres párrafos escritos por regla a partir de los mismos números | sólo habla de tres insumos y esconde el resto |

Los tres son **mockups**: el único control que funciona es el selector de sede
(la palanca `sede` del tablero). Todo lo demás es estático.

## De dónde salen los números

- `datos_canvas.json` — extracto completo generado por `datos_canvas.py`
  (en el scratchpad de la sesión) a partir de `series.json`: curvas ya ancladas
  en el primer conteo de la semana y verificadas contra los 260 registros.
- `filas.json` — lo que de verdad consume cada tablero, incrustado en los tres
  `.dc.html`. Los tableros no comparten estado entre sí, así que cada uno lleva
  su propia copia.
- El valor unitario sale de `valor_unitario` de la ficha del insumo, y es lo que
  permite poner la diferencia en pesos.

## Sistema de diseño

Valores exactos del `frontend/tailwind.config.js`, sin paleta nueva: Plus Jakarta
Sans y JetBrains Mono, y los tonos `forest`, `warm`, `bark`, `clay`, `gold` y
`danger` convertidos a hex. Las barras usan **dos tonos de una misma tinta**
(oscuro = falta, claro = sobra) en vez de dos colores: rojo contra verde colapsa
a ΔE 1,6 bajo protanopía y no pasa el validador.

## Volver a armar el lienzo

```bash
node "<base de la skill design>/seed-canvas.mjs" \
  --template "<base de la skill design>/payload.template.html" \
  --out ../../.diseno-vida-insumo/la-vida-de-cada-insumo.html \
  --title "La vida de cada insumo" \
  --artboard Main.dc.html --artboard Tendencia.dc.html --artboard Parte.dc.html \
  --canvas canvas.json
```

El archivo armado pesa 2,5 MB y no se versiona: está en `.gitignore`.
