# UI — Sistema de diseño base

Fundación de diseño minimalista (estilo Apple) para el rediseño del POS.
**Un solo token source**: tokens Tailwind semánticos + estos componentes.
Regla: en componentes nuevos, **nunca** `oklch()` inline — consumí tokens y estos componentes.

Import:

```ts
import { Card, StatTile, SectionLabel, Pill, Badge, MoneyInput, Stepper, Sheet, Toast } from '@/components/ui'
```

---

## Tokens nuevos (tailwind.config.js)

Agregados de forma additiva; `forest` / `warm` / `bark` quedan intactos.

| Token       | Uso                              | DEFAULT              | Escala disponible                  |
| ----------- | -------------------------------- | -------------------- | ---------------------------------- |
| `clay`      | Naranja CTA / acción primaria    | `oklch(60% 0.16 50)` | 50, 100, 200, 400, 500, 600        |
| `danger`    | Rojo error / stock crítico       | `#c64a3a`            | 50, 100, 200, 400, 500, 600, 700   |
| `success`   | Verde ok / confirmación          | `oklch(48% 0.16 145)`| 50, 100, 200, 400, 500, 600, 700   |
| `gold`      | Dorado destaque / consignaciones | `oklch(72% 0.14 65)` | 50, 100, 200, 400, 500, 600, 700   |

Convención de escala: `50` = fondo claro, `500` = base, `600/700` = texto fuerte.
Ej. card de error → `bg-danger-50 border-danger-200 text-danger-700`.

Números (dinero): usá `font-mono tabular-nums` para alinear cifras.

---

## Componentes

### `Card`
Contenedor blanco base: `bg-white rounded-2xl border border-warm-200`.

| Prop      | Tipo                                | Default | Notas                                            |
| --------- | ----------------------------------- | ------- | ------------------------------------------------ |
| `padding` | `'none' \| 'sm' \| 'md' \| 'lg'`    | `'md'`  | `none` para listas con `divide-y` propias        |
| `...rest` | `HTMLAttributes<HTMLDivElement>`    | —       | `className`, `onClick`, etc.                      |

### `StatTile`
Tile de KPI. Valor en `font-mono tabular-nums`.

| Prop       | Tipo                                                       | Default     |
| ---------- | ---------------------------------------------------------- | ----------- |
| `label`    | `string`                                                   | (requerido) |
| `value`    | `ReactNode`                                                | (requerido) |
| `sublabel` | `ReactNode`                                                | —           |
| `tint`     | `'neutral' \| 'success' \| 'danger' \| 'clay' \| 'gold'`   | `'neutral'` |

### `SectionLabel`
Label uppercase: `text-[11px] font-bold uppercase tracking-wide text-warm-500`.

| Prop      | Tipo        | Default     |
| --------- | ----------- | ----------- |
| `children`| `ReactNode` | (requerido) |
| `...rest` | `HTMLAttributes<HTMLParagraphElement>` | — |

### `Pill`
Etiqueta redondeada (`rounded-full`) de estado / chip de monto.

| Prop      | Tipo                                                    | Default  |
| --------- | ------------------------------------------------------- | -------- |
| `tone`    | `'success' \| 'danger' \| 'warm' \| 'clay' \| 'gold'`   | `'warm'` |
| `children`| `ReactNode`                                             | (requerido) |

`Tone` se exporta desde el barrel (compartido con Badge). Para cifras agregá `className="font-mono tabular-nums"`.

### `Badge`
Etiqueta cuadrada con borde (`rounded-md border`, uppercase). Para tags de categoría.

| Prop      | Tipo        | Default  |
| --------- | ----------- | -------- |
| `tone`    | `Tone`      | `'warm'` |
| `children`| `ReactNode` | (requerido) |

### `MoneyInput`
Input numérico con prefijo `$` (formato es-CO). Tokens, sin modo oscuro.

| Prop         | Tipo                       | Default | Notas                          |
| ------------ | -------------------------- | ------- | ------------------------------ |
| `value`      | `string`                   | (requerido) | controlado                 |
| `onChange`   | `(v: string) => void`      | (requerido) |                            |
| `label`      | `string`                   | —       | uppercase si se pasa           |
| `placeholder`| `string`                   | `'0'`   |                                |
| `hint`       | `string`                   | —       |                                |
| `size`       | `'sm' \| 'lg'`             | `'lg'`  | `lg` = 3xl (totales)           |
| `autoFocus`  | `boolean`                  | `false` |                                |
| `inputRef`   | `Ref<HTMLInputElement>`    | —       |                                |

> **Colisión documentada**: ya existe un `components/MoneyInput.tsx` legacy con API distinta
> (`{ label, dark, size }`, soporta tema oscuro). Este nuevo vive en `components/ui/` y **no rompe**
> imports existentes (apuntan a `../components/MoneyInput`). El legacy se migra después.

### `Stepper`
Control −/cantidad/+ del carrito. `+` verde (success), `−` neutro.

| Prop     | Tipo         | Default | Notas                                  |
| -------- | ------------ | ------- | -------------------------------------- |
| `value`  | `number`     | (requerido) | mostrado en mono tabular           |
| `onDec`  | `() => void` | (requerido) |                                    |
| `onInc`  | `() => void` | (requerido) |                                    |
| `min`    | `number`     | `0`     | deshabilita `−` al alcanzarlo          |
| `max`    | `number`     | —       | deshabilita `+` al alcanzarlo          |

### `Sheet`
Modal responsive: bottom-sheet en mobile, dialog centrado en desktop.
Maneja backdrop, Escape y safe-area.

| Prop          | Tipo         | Default | Notas                                          |
| ------------- | ------------ | ------- | ---------------------------------------------- |
| `open`        | `boolean`    | (requerido) | si false no renderiza                      |
| `onClose`     | `() => void` | (requerido) | backdrop / X / Escape                      |
| `title`       | `ReactNode`  | —       | sin título → sin header                        |
| `dismissable` | `boolean`    | `true`  | `false` bloquea cierre (ej. durante un cobro)  |
| `showHandle`  | `boolean`    | `true`  | drag-handle (solo mobile)                      |

El contenido va como `children` (ya tiene padding lateral `px-5`).

### `Toast`
Aviso transitorio inline (banner) con ícono por tono.

| Prop        | Tipo                              | Default  | Notas                                  |
| ----------- | --------------------------------- | -------- | -------------------------------------- |
| `tone`      | `'success' \| 'danger' \| 'warm'` | `'warm'` |                                        |
| `children`  | `ReactNode`                       | (requerido) |                                     |
| `duration`  | `number` (ms)                     | —        | auto-cierre; requiere `onDismiss`      |
| `onDismiss` | `() => void`                      | —        | llamado al expirar `duration`          |

El padre controla el unmount; `Toast` solo dispara `onDismiss` al expirar.
