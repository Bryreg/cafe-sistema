import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'

export type ToastTone = 'success' | 'danger' | 'warm'

const TONE: Record<ToastTone, { box: string; icon: typeof Info }> = {
  success: { box: 'bg-success-50 border-success-200 text-success-700', icon: CheckCircle2 },
  danger:  { box: 'bg-danger-50 border-danger-200 text-danger-700',    icon: AlertTriangle },
  warm:    { box: 'bg-warm-100 border-warm-200 text-warm-600',         icon: Info },
}

export interface ToastProps {
  tone?: ToastTone
  children: ReactNode
  /** Ms hasta auto-cierre. Si se omite, no se cierra solo. */
  duration?: number
  /** Llamado al expirar `duration`. */
  onDismiss?: () => void
  className?: string
}

/**
 * Aviso transitorio inline (banner). Tonos success/danger/warm con su ícono.
 * Reemplaza los banners "Cobro cancelado" / "Error" repetidos en POS.
 * Si pasás `duration`, llama `onDismiss` al expirar (el padre controla el unmount).
 */
export default function Toast({ tone = 'warm', children, duration, onDismiss, className = '' }: ToastProps) {
  useEffect(() => {
    if (!duration || !onDismiss) return
    const id = setTimeout(onDismiss, duration)
    return () => clearTimeout(id)
  }, [duration, onDismiss])

  const t = TONE[tone]
  const Icon = t.icon

  return (
    <div className={`flex items-center gap-2 border rounded-xl px-4 py-3 text-sm font-semibold ${t.box} ${className}`}>
      <Icon size={14} className="shrink-0" />
      <span>{children}</span>
    </div>
  )
}
