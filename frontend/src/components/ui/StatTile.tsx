import type { ReactNode } from 'react'

export type StatTint = 'neutral' | 'success' | 'danger' | 'clay' | 'gold'

const TINT: Record<StatTint, { value: string; chip: string }> = {
  neutral: { value: 'text-bark-800',   chip: 'bg-warm-100 text-warm-600' },
  success: { value: 'text-success-700', chip: 'bg-success-50 text-success-700' },
  danger:  { value: 'text-danger-700',  chip: 'bg-danger-50 text-danger-700' },
  clay:    { value: 'text-clay-600',    chip: 'bg-clay-50 text-clay-600' },
  gold:    { value: 'text-gold-700',    chip: 'bg-gold-50 text-gold-700' },
}

export interface StatTileProps {
  /** Label superior en mayúsculas (ej. "Total a cobrar"). */
  label: string
  /** Valor principal. Se renderiza en mono + tabular-nums para alinear cifras. */
  value: ReactNode
  /** Texto secundario opcional debajo del valor. */
  sublabel?: ReactNode
  /** Color de acento del valor. Default: neutral. */
  tint?: StatTint
  className?: string
}

/**
 * Tile de KPI / estadística. Valor en `font-mono tabular-nums` para alinear
 * dinero. Reemplaza los bloques "Total a cobrar / $X" repetidos en POS y Checkout.
 */
export default function StatTile({ label, value, sublabel, tint = 'neutral', className = '' }: StatTileProps) {
  const t = TINT[tint]
  return (
    <div className={`bg-white rounded-2xl border border-warm-200 p-4 ${className}`}>
      <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-1">{label}</p>
      <p className={`font-mono tabular-nums text-2xl font-bold leading-none ${t.value}`}>{value}</p>
      {sublabel != null && (
        <p className="text-xs text-warm-500 mt-1.5">{sublabel}</p>
      )}
    </div>
  )
}
