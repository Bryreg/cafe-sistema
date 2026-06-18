import type { ReactNode } from 'react'

export type Tone = 'success' | 'danger' | 'warm' | 'clay' | 'gold'

const TONE: Record<Tone, string> = {
  success: 'bg-success-50 text-success-700',
  danger:  'bg-danger-50 text-danger-700',
  warm:    'bg-warm-100 text-warm-600',
  clay:    'bg-clay-50 text-clay-600',
  gold:    'bg-gold-50 text-gold-700',
}

export interface PillProps {
  tone?: Tone
  children: ReactNode
  className?: string
}

/**
 * Etiqueta de estado redondeada (`rounded-full`). Para chips de monto,
 * contadores y badges flotantes. Numérico → mono tabular automático no se
 * fuerza; agregá `font-mono tabular-nums` por className si es una cifra.
 */
export default function Pill({ tone = 'warm', children, className = '' }: PillProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${TONE[tone]} ${className}`}
    >
      {children}
    </span>
  )
}
