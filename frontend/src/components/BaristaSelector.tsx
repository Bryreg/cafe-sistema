import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Check, User } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import { useBaristaActiva } from '../contexts/BaristaActivaContext'

/**
 * Selector compacto "Operando: [nombre] ▾".
 *
 * Muestra la barista REAL que opera el kiosko y permite cambiarla entre las
 * baristas del turno activo. El cambio persiste (localStorage) y el interceptor
 * de axios envía X-Barista-Id en cada request, atribuyendo cada escritura a la
 * barista correcta sin tocar el auth del dispositivo.
 */
export default function BaristaSelector() {
  const { baristaActiva, setBaristaActiva, baristasTurno } = useBaristaActiva()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  // Sin baristas en el turno no hay nada que operar/cambiar.
  if (baristasTurno.length === 0) return null

  const single = baristasTurno.length === 1

  return (
    <div ref={ref} className="relative flex-shrink-0">
      <button
        onClick={() => !single && setOpen(o => !o)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-bold transition-colors max-w-[160px]"
        style={{
          background: dark.surfaceAlt,
          color: dark.inkMuted,
          border: `1px solid ${dark.border}`,
          cursor: single ? 'default' : 'pointer',
        }}
        aria-label="Barista operando"
      >
        <User size={13} style={{ color: dark.amber }} />
        <span className="truncate" style={{ color: dark.ink }}>
          {baristaActiva?.nombre ?? '—'}
        </span>
        {!single && <ChevronDown size={13} />}
      </button>

      {open && !single && (
        <div
          className="absolute right-0 mt-1 z-50 rounded-xl overflow-hidden shadow-lg min-w-[180px]"
          style={{ background: dark.surface, border: `1px solid ${dark.border}` }}
        >
          <p
            className="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-widest"
            style={{ color: dark.inkSubtle }}
          >
            Operando
          </p>
          {baristasTurno.map(b => {
            const activa = b.id === baristaActiva?.id
            return (
              <button
                key={b.id}
                onClick={() => { setBaristaActiva(b); setOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-[13px] text-left transition-colors"
                style={{
                  background: activa ? dark.greenTint : dark.surface,
                  color: dark.ink,
                }}
              >
                <span className="flex-1 truncate font-semibold">{b.nombre}</span>
                {activa && <Check size={14} style={{ color: dark.green }} />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
