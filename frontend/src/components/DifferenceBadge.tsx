import { CheckCircle2, XCircle } from 'lucide-react'

const fmt = (v: number) => `$${Math.abs(v).toLocaleString('es-CO')}`

interface DifferenceBadgeProps {
  diferencia: number
  dark?: boolean
  showZero?: boolean
}

export default function DifferenceBadge({ diferencia, dark = false, showZero = true }: DifferenceBadgeProps) {
  if (!showZero && diferencia === 0) return null
  const ok = diferencia === 0

  if (ok) return (
    <span className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-full ${
      dark ? 'bg-green-900/40 text-green-400' : 'bg-green-100 text-green-700'
    }`}>
      <CheckCircle2 size={11} /> Cuadra
    </span>
  )

  return (
    <span className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-full ${
      dark ? 'bg-red-900/40 text-red-400' : 'bg-red-100 text-red-700'
    }`}>
      <XCircle size={11} />
      {diferencia > 0 ? '+' : '-'}{fmt(diferencia)}
    </span>
  )
}
