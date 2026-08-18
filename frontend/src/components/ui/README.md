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

---

## Carga · vacío · error — la convención de la casa

Un dato del backend NO se representa con `T | null`. Se representa con
`Dato<T>` (`src/api/dato.ts`), que tiene cuatro ramas:

```ts
type Dato<T> =
  | { estado: 'cargando' }
  | { estado: 'falla';   mensaje: string }
  | { estado: 'sinBase'; porque: string }
  | { estado: 'listo';   valor: T }       // ← `valor` SOLO existe acá
```

### Por qué

`T | null` hace que tres cosas distintas compartan un valor: *todavía no llegó*,
*llegó vacío* y *no volvió*. Y como el código no las puede separar, cada `?? 0` y
cada `?? []` río abajo convierte «no se pudo preguntar» en «la respuesta es
cero». No fue un descuido de nadie: fue el único camino que el tipo dejaba
abierto. `computeOutliers([])` devolvía `[]`, así que **«ningún producto está
mal» y «no miré ningún producto» eran el mismo valor**, y el banner pintaba el
verde «todos coherentes con su categoría» sobre una medición que nunca corrió.

Que `valor` viva solo en la rama `listo` es todo el diseño: `d.valor` no compila
sin estrechar primero, y sin `.valor` no hay nada a la izquierda de un `?? 0`. El
candado es el compilador, no la disciplina de quien edite dentro de seis meses.

El precedente en este repo es `DiaLibro` (`components/plata/banco.ts`), que ya
usaba el truco para que un día sin cadena no pueda dibujar un saldo. `Dato<T>` es
lo mismo un nivel más arriba: allá es la fila del libro, acá es el sobre entero.

### `sinBase` — el estado que no emite la red

Lo emiten las **derivaciones de dominio**, no el fetch. El caso que lo hizo
necesario: `computeOutliers` necesita 4 productos costeados en una misma
categoría para comparar. Con cien productos repartidos de a dos, no compara nada
y devuelve `[]` — indistinguible del verde. `sinBase` lleva el `porque` en
castellano y el banner lo muestra tal cual.

### Las piezas

| Pieza | Dónde | Para qué |
| --- | --- | --- |
| `Dato<T>` | `api/dato.ts` | el tipo y sus constructores `dato*` |
| `ambos(a, b)` | `api/dato.ts` | dos datos que solo sirven juntos; la falla gana sobre el cargando |
| `useDato(pedir, nombre, fallback, deps)` | `api/useDato.ts` | devuelve `Fuente<T>` = dato + nombre + última lectura buena + `recargar()` |
| `SegunDato` | `ui/SegunDato.tsx` | obliga a escribir las tres ramas; `switch` sin `default` |
| `NoSeSabe` | `ui/SegunDato.tsx` | el hueco honesto, con Reintentar. `bloque` para reemplazar una sección entera |
| `FranjaDeConfianza` | `ui/FranjaDeConfianza.tsx` | «¿le puedo creer a esta pantalla?» en un renglón; invisible si no hay nada roto |

### Las reglas

1. Nunca `?? 0` ni `|| 0` sobre algo derivado de un `Dato`. Si no está `listo`, va
   `—` (o `…` si está `cargando`), nunca una cifra.
2. Nunca `?? []` para después sacar una conclusión de `.length === 0`.
3. Nunca un verde, un «ninguno» o un «al día» fuera de la rama `listo`.
4. Una sección que hoy **desaparece** cuando su dato falta tiene que dibujar un
   `<NoSeSabe bloque>`. Un «Vencido — pagalo ya» que se evapora se lee como «no
   debés nada»: el hueco ocupa lugar a propósito.
5. **Ningún formulario adentro de un gate por estado.** Si el catálogo no cargó, el
   formulario queda montado con su aviso arriba del select y deja teclear lo que
   no dependa de él. Esconderlo le rompe el trabajo de las 7am al dueño.
6. `cargando` no es `falla`: en carga va un placeholder mudo, no un mensaje de error.

### Lo que todavía usa el molde viejo

`Dashboard.tsx` y otros ~49 archivos. Los dos peores están en Dashboard y son
*peores* que los de Plata, porque no colapsan a `null` sino que fabrican un objeto
plausible adentro del `catch`: `.catch(() => ({ id: s.id, abierto: false }))`
afirma que una sede está **cerrada** cuando no se pudo preguntar.
