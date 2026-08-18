import { ReactElement, ReactNode } from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { Dato } from '../../api/dato'

// ─── Cómo se dibuja un dato que puede no estar ───────────────────────────────
//
// Estos dos componentes son la contraparte de pantalla de `Dato<T>`: el tipo
// hace imposible LEER un valor ausente, y estos hacen visible la ausencia en vez
// de dejar un hueco. Un banner que desaparece cuando su fetch falla es tan
// mentiroso como uno que imprime $0: el dueño no ve nada donde debería haber
// algo, y «no hay nada» es exactamente lo que quiere decir «no hay deuda».

export interface NoSeSabeProps {
  mensaje: string
  onReintentar?: () => void
  /**
   * `true` = caja del alto de un banner, para reemplazar una sección entera que
   * si no se evaporaría sin dejar rastro. El hueco ocupa lugar a propósito.
   */
  bloque?: boolean
}

/** El hueco honesto. Dice qué no se pudo leer y ofrece volver a pedirlo. */
export function NoSeSabe({ mensaje, onReintentar, bloque }: NoSeSabeProps): ReactElement {
  return (
    <div className={`flex items-start gap-2 rounded-xl border border-dashed border-warm-200 bg-warm-50 px-3 ${
      bloque ? 'py-5' : 'py-2.5'}`}>
      <AlertCircle size={15} className="shrink-0 mt-0.5 text-warm-400" />
      <p className="flex-1 text-xs text-warm-500 leading-relaxed">{mensaje}</p>
      {onReintentar && (
        <button onClick={onReintentar}
          className="shrink-0 flex items-center gap-1 min-h-[32px] px-2 rounded-lg
                     text-[11px] font-bold text-forest hover:bg-warm-100">
          <RefreshCw size={12} /> Reintentar
        </button>
      )}
    </div>
  )
}

export interface SegunDatoProps<T> {
  dato: Dato<T>
  cargando: ReactNode
  falla: (mensaje: string) => ReactNode
  /**
   * Opcional. Sin él, `sinBase` cae en `falla`: «no se pudo afirmar» sirve para
   * los dos, y así los recursos que nunca emiten `sinBase` no escriben una rama
   * muerta.
   */
  sinBase?: (porque: string) => ReactNode
  listo: (valor: T) => ReactNode
}

/**
 * Obliga a ESCRIBIR qué se ve en cada estado.
 *
 * `cargando` es un `ReactNode` y no una función porque no hay valor que pasarle:
 * si alguien tipea un número ahí, es un número inventado a mano y se ve en el
 * diff. El `switch` no tiene `default` a propósito — si mañana aparece un quinto
 * estado, el build se rompe acá y no en la tablet del dueño.
 */
export function SegunDato<T>({ dato, cargando, falla, sinBase, listo }: SegunDatoProps<T>): ReactElement {
  switch (dato.estado) {
    case 'cargando': return <>{cargando}</>
    case 'falla': return <>{falla(dato.mensaje)}</>
    case 'sinBase': return <>{(sinBase ?? falla)(dato.porque)}</>
    case 'listo': return <>{listo(dato.valor)}</>
  }
}
