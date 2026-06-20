import { useNavigate } from 'react-router-dom'
import { X } from 'lucide-react'
import { dark } from '../constants/darkTheme'

/**
 * Cajón lateral que se monta SOBRE la pantalla de fondo (route-as-overlay).
 *
 * Lo usa App.tsx: cuando una ruta-herramienta se abre con
 * `navigate(to, { state: { background } })`, el `<Routes>` base sigue
 * pintando la pantalla de fondo (el POS, con el carrito vivo) y este Drawer
 * pinta la herramienta encima. Cerrar = volver atrás (descarta el overlay y
 * deja el POS exactamente como estaba).
 *
 * El POS queda atenuado y visible detrás; tocar el backdrop cierra el cajón.
 */
export default function Drawer({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const close = () => navigate(-1)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop: deja ver el POS atenuado detrás */}
      <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.35)' }} onClick={close} />

      {/* Panel del cajón */}
      <div
        className="relative h-full w-[90%] max-w-xl overflow-y-auto shadow-2xl"
        style={{ background: dark.bg, borderLeft: `1px solid ${dark.border}` }}
        onClick={e => e.stopPropagation()}
      >
        {/* Cerrar — fijo arriba a la derecha, no choca con el header propio de la página */}
        <button
          onClick={close}
          className="fixed top-3 right-3 z-[55] w-9 h-9 rounded-full flex items-center justify-center shadow-lg"
          style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
          aria-label="Cerrar cajón"
        >
          <X size={18} />
        </button>
        {children}
      </div>
    </div>
  )
}
