import { ReactNode, useEffect } from 'react'
import { X } from 'lucide-react'

/**
 * Cajón de drill-down: pantalla completa por encima de Plata.
 *
 * Existe para que las herramientas que NO son una de las tres pantallas del
 * módulo (Obligaciones, Pagos a proveedores, el detalle del flujo, los egresos
 * sin categorizar) sigan estando enteras sin volver a ser pestañas de primer
 * nivel. Cinco pestañas arriba es exactamente lo que hacía que nadie encontrara
 * nada; un cajón se abre cuando se lo pide y desaparece cuando no.
 */
export default function Drawer({ open, titulo, subtitulo, onClose, children }: {
  open: boolean
  titulo: string
  subtitulo?: string
  onClose: () => void
  children: ReactNode
}) {
  // Escape cierra, y con el cajón abierto el fondo no scrollea: si scrolleara,
  // el gesto de leer la lista movería la página de atrás.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const previo = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previo
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose}>
      <div className="absolute inset-x-0 bottom-0 top-8 sm:top-16 bg-warm-50 rounded-t-3xl flex flex-col"
        onClick={e => e.stopPropagation()} role="dialog" aria-label={titulo}>
        <div className="flex items-start gap-3 px-4 py-3 border-b border-warm-200 bg-white rounded-t-3xl">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold text-warm-700 truncate">{titulo}</h2>
            {subtitulo && <p className="text-[11px] text-warm-500 leading-snug">{subtitulo}</p>}
          </div>
          <button onClick={onClose} aria-label="Cerrar"
            className="shrink-0 p-2 -mr-1 rounded-xl text-warm-500 hover:bg-warm-100">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  )
}
