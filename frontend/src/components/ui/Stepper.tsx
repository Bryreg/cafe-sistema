import { Minus, Plus } from 'lucide-react'

export interface StepperProps {
  /** Valor actual mostrado en el centro. */
  value: number
  /** Decrementar. Se deshabilita solo cuando value <= min. */
  onDec: () => void
  /** Incrementar. */
  onInc: () => void
  /** Mínimo permitido. Default 0. Al alcanzarlo, el botón − se deshabilita. */
  min?: number
  /** Máximo opcional. Al alcanzarlo, el botón + se deshabilita. */
  max?: number
  className?: string
}

/**
 * Control −/cantidad/+ del carrito (patrón POS). El botón + usa acento verde
 * (success), el − es neutro con borde. Esquinas redondeadas, active:scale.
 */
export default function Stepper({ value, onDec, onInc, min = 0, max, className = '' }: StepperProps) {
  const decDisabled = value <= min
  const incDisabled = max != null && value >= max

  return (
    <div className={`flex items-center gap-1 ${className}`}>
      <button
        type="button"
        onClick={onDec}
        disabled={decDisabled}
        aria-label="Disminuir"
        className="w-7 h-7 rounded-lg border-2 border-warm-200 flex items-center justify-center text-warm-500 hover:border-warm-300 active:scale-90 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Minus size={12} />
      </button>
      <span className="w-6 text-center text-sm font-bold text-bark-800 tabular-nums">{value}</span>
      <button
        type="button"
        onClick={onInc}
        disabled={incDisabled}
        aria-label="Aumentar"
        className="w-7 h-7 rounded-lg border-2 border-success-500 bg-success-500 flex items-center justify-center text-white active:scale-90 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Plus size={12} />
      </button>
    </div>
  )
}
