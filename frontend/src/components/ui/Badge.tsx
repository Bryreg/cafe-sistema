import type { ReactNode } from 'react'
import type { Tone } from './Pill'

const TONE: Record<Tone, string> = {
  success: 'bg-success-50 text-success-700 border-success-200',
  danger:  'bg-danger-50 text-danger-700 border-danger-200',
  warm:    'bg-warm-100 text-warm-600 border-warm-200',
  clay:    'bg-clay-50 text-clay-600 border-clay-200',
  gold:    'bg-gold-50 text-gold-700 border-gold-200',
}

export interface BadgeProps {
  tone?: Tone
  children: ReactNode
  className?: string
}

/**
 * Etiqueta cuadrada con borde (`rounded-md border`). Para tags de categoría
 * tipo "Bebidas / Pastelería" o estados con marco. A diferencia de Pill,
 * tiene borde y esquinas menos redondeadas.
 */
export default function Badge({ tone = 'warm', children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[10px] font-bold uppercase tracking-wide ${TONE[tone]} ${className}`}
    >
      {children}
    </span>
  )
}
