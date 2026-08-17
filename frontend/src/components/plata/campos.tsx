import { ReactNode, KeyboardEvent } from 'react'

// ─── Los ladrillos de las filas de carga ─────────────────────────────────────
//
// Existen porque el pedido dice «fácil de digitar» y eso no es una opinión de
// estilo: son cuatro reglas concretas que TODOS los formularios de este módulo
// tienen que cumplir igual, y que copiadas a mano en seis banners se separan.
//
//   1. INPUTS GRANDES. min-h 44px es el mínimo táctil real en la tablet; abajo
//      de eso el dedo del dueño abre el campo de al lado.
//   2. TECLADO NUMÉRICO donde va plata (`inputMode="numeric"`). Sin esto el
//      celular abre el teclado de letras para teclear un monto.
//   3. ENTER GUARDA. El dueño viene de una hoja de cálculo: si Enter no guarda,
//      teclea 20 movimientos buscando el botón con el dedo cada vez.
//   4. EL FOCO VUELVE AL PRIMER CAMPO después de guardar (lo hace cada
//      formulario con su propia ref: acá vive solo la parte compartida).
//
// Los colores son los de MEDIUM CAFÉ tal como los usan los componentes vecinos:
// borde `warm-200`, foco `forest`, error `danger`, aviso `gold`.

/** Rótulo + campo. El rótulo va arriba y no adentro (un placeholder que hace de
 *  etiqueta desaparece justo cuando el dueño está tecleando y duda). */
export function Campo({ label, hint, children, ancho = '' }: {
  label: string
  hint?: ReactNode
  children: ReactNode
  /** Clases de grilla: 'col-span-2' para los campos que necesitan la fila entera. */
  ancho?: string
}) {
  return (
    <label className={`block min-w-0 ${ancho}`}>
      <span className="block text-[10px] font-bold uppercase tracking-wide text-warm-500 mb-1">
        {label}
      </span>
      {children}
      {hint && <span className="block text-[11px] text-warm-400 leading-snug mt-1">{hint}</span>}
    </label>
  )
}

/** Clases de un input de texto/fecha/select. Una sola definición para que dos
 *  banners no terminen con dos alturas distintas en la misma pantalla. */
export const CLS_INPUT =
  'w-full min-h-[44px] border-2 border-warm-200 rounded-xl px-3 py-2 text-sm bg-white ' +
  'focus:outline-none focus:border-forest'

/** Igual, pero para PLATA: fuente mono y tabular para que los ceros se cuenten. */
export const CLS_INPUT_PLATA =
  'w-full min-h-[44px] border-2 border-warm-200 rounded-xl px-3 py-2 text-base font-bold ' +
  'font-mono tabular-nums bg-white focus:outline-none focus:border-forest'

export const CLS_BOTON_GUARDAR =
  'min-h-[44px] px-4 rounded-xl bg-forest hover:bg-forest-700 disabled:opacity-40 ' +
  'text-white text-sm font-bold shrink-0'

export const CLS_BOTON_SUAVE =
  'min-h-[44px] px-4 rounded-xl border border-warm-200 bg-white text-sm font-bold text-warm-500 shrink-0'

/**
 * Enter guarda; Escape cancela.
 *
 * `listo` se pregunta ACÁ y no se delega al botón deshabilitado: un Enter sobre
 * un formulario a medio llenar no puede disparar un POST que el backend va a
 * rechazar. Y se ignora dentro de un <textarea>, donde Enter es un salto de
 * línea de verdad.
 */
export function teclas(
  { listo, guardar, cancelar }: { listo: boolean; guardar: () => void; cancelar?: () => void },
) {
  return (e: KeyboardEvent<HTMLDivElement | HTMLFormElement>) => {
    const t = e.target as HTMLElement
    // El handler vive en el div que envuelve TODO el formulario, botones
    // incluidos. Sin esta salida, con el foco en «Cancelar» el Enter hacía
    // preventDefault —matando la activación por teclado del botón— y guardaba:
    // el atajo terminaba haciendo lo contrario de lo que el botón enfocado dice.
    if (t.tagName === 'BUTTON' || t.tagName === 'A') return
    // `e.repeat` = la tecla quedó apretada. Sin esto, mantener Enter dispara un
    // guardado por cada repetición del teclado.
    if (e.key === 'Enter' && t.tagName !== 'TEXTAREA' && !e.repeat) {
      e.preventDefault()
      if (listo) guardar()
    } else if (e.key === 'Escape' && cancelar) {
      e.preventDefault()
      cancelar()
    }
  }
}

/** El error de un formulario, con el texto del backend TAL CUAL (los `detail`
 *  de este backend están escritos para que el dueño sepa qué corregir). */
export function ErrorCampo({ msg }: { msg: string }) {
  if (!msg) return null
  return (
    <p className="text-sm text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-3 py-2">
      {msg}
    </p>
  )
}

/**
 * La cabecera de un banner: título corto, número grande, UNA línea que lo
 * explique y la acción si la tiene.
 *
 * Es el principio 3 del pedido hecho componente. Si un banner necesita un
 * párrafo para entenderse está mal armado: la explicación larga va adentro de
 * un <details> «¿cómo se calcula?», que se abre solo si lo piden.
 */
export function Banner({ titulo, sub, accion, tono = 'blanco', children, id }: {
  titulo: ReactNode
  sub?: ReactNode
  accion?: ReactNode
  tono?: 'blanco' | 'rojo' | 'ambar'
  children?: ReactNode
  id?: string
}) {
  const marco = tono === 'rojo' ? 'border-danger-200 bg-danger-50'
    : tono === 'ambar' ? 'border-gold-200 bg-gold-50'
    : 'border-warm-200 bg-white'
  const linea = tono === 'rojo' ? 'border-danger-200/60'
    : tono === 'ambar' ? 'border-gold-200/60'
    : 'border-warm-100'
  const texto = tono === 'rojo' ? 'text-danger-700'
    : tono === 'ambar' ? 'text-gold-700'
    : 'text-warm-700'
  return (
    <section id={id} className={`rounded-2xl border overflow-hidden ${marco}`}>
      <div className={`flex items-center gap-2 px-4 py-3 border-b ${linea}`}>
        <div className="min-w-0 flex-1">
          <h2 className={`text-sm font-bold ${texto}`}>{titulo}</h2>
          {sub && <p className={`text-[11px] leading-snug ${tono === 'blanco' ? 'text-warm-500' : `${texto}/90`}`}>{sub}</p>}
        </div>
        {accion && <div className="shrink-0">{accion}</div>}
      </div>
      {children}
    </section>
  )
}

/**
 * «¿Cómo se calcula?» — el párrafo que NO va en la cabecera.
 *
 * Cerrado por defecto: el dueño abre la pantalla para decidir, no para leer.
 * Pero el texto no se tira, porque cada uno de estos párrafos es la respuesta a
 * una pregunta que ya hizo (por qué el saldo no bajó, de dónde sale la venta
 * esperada, qué hace adoptar un egreso).
 */
export function ComoSeCalcula({ children, titulo = '¿Cómo se calcula esto?' }: {
  children: ReactNode
  titulo?: string
}) {
  return (
    <details className="border-t border-warm-100 group">
      <summary className="cursor-pointer select-none list-none px-4 py-2.5 text-[11px] font-bold text-warm-500 hover:bg-warm-50">
        <span className="group-open:hidden">▸ </span>
        <span className="hidden group-open:inline">▾ </span>
        {titulo}
      </summary>
      <div className="px-4 pb-3 text-[11px] text-warm-500 leading-relaxed space-y-2">
        {children}
      </div>
    </details>
  )
}
