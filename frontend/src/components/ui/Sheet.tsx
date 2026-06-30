import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export interface SheetProps {
  /** Controla visibilidad. Cuando es false no renderiza nada. */
  open: boolean
  /** Cierre por backdrop, botón X o tecla Escape. */
  onClose: () => void
  /** Título opcional en el header. Si se omite, no se renderiza header. */
  title?: ReactNode
  /** Si false, deshabilita cierre por backdrop/Escape/X (ej. durante un cobro). */
  dismissable?: boolean
  /** Muestra el drag-handle superior (mobile). Default true. */
  showHandle?: boolean
  children: ReactNode
}

/**
 * Modal responsive: bottom-sheet en mobile (`items-end rounded-t-3xl`),
 * dialog centrado en desktop (`sm:items-center sm:rounded-3xl sm:max-w-md`).
 * Maneja backdrop, cierre por Escape y respeta el safe-area inferior.
 * Reemplaza los bottom-sheets repetidos en CheckoutModal / Inventario.
 */
export default function Sheet({
  open,
  onClose,
  title,
  dismissable = true,
  showHandle = true,
  children,
}: SheetProps) {
  useEffect(() => {
    if (!open || !dismissable) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, dismissable, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-end justify-center sm:items-center"
      onClick={dismissable ? onClose : undefined}
    >
      <div
        className="w-full max-w-lg bg-white rounded-t-3xl sm:rounded-3xl sm:max-w-md sm:mb-0 flex flex-col"
        style={{ maxHeight: '92svh' }}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Handle + title — no scrollan, siempre visible */}
        <div className="flex-shrink-0">
          {showHandle && (
            <div className="flex justify-center pt-3 pb-1 sm:hidden">
              <div className="w-10 h-1 rounded-full bg-warm-200" />
            </div>
          )}

          {title != null && (
            <div className="flex items-center justify-between px-5 pt-2 pb-4 border-b border-warm-100">
              <p className="text-base font-bold text-bark-800">{title}</p>
              <button
                type="button"
                onClick={onClose}
                disabled={!dismissable}
                aria-label="Cerrar"
                className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <X size={18} />
              </button>
            </div>
          )}
        </div>

        {/* Contenido — scrolleable cuando supera el viewport */}
        <div
          className="px-5 pt-4 overflow-y-auto flex-1 min-h-0"
          style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 1.5rem)' }}
        >
          {children}
        </div>
      </div>
    </div>
  )
}
