import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Sparkles, X, BookOpen } from 'lucide-react'
import { novedadesParaRol, contarNoVistas, marcarVistas, Novedad, TipoNovedad } from '../constants/novedades'

const TIPO: Record<TipoNovedad, { label: string; cls: string }> = {
  nuevo:  { label: 'Nuevo',  cls: 'bg-green-100 text-green-700' },
  mejora: { label: 'Mejora', cls: 'bg-blue-100 text-blue-700' },
  cambio: { label: 'Cambio', cls: 'bg-amber-100 text-amber-700' },
}

const fmtFecha = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })
}

interface Props {
  rol: 'barista' | 'admin'
  /** 'light' = hub admin (fondo claro) · 'dark' = kiosko barista */
  variant?: 'light' | 'dark'
}

export default function NovedadesButton({ rol, variant = 'light' }: Props) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [noVistas, setNoVistas] = useState(() => contarNoVistas(rol))
  const novedades = useMemo(() => novedadesParaRol(rol), [rol])

  const abrir = () => {
    setOpen(true)
    marcarVistas()
    setNoVistas(0)
  }

  const grupos = useMemo(() => {
    const g = new Map<string, Novedad[]>()
    for (const n of novedades) {
      if (!g.has(n.fecha)) g.set(n.fecha, [])
      g.get(n.fecha)!.push(n)
    }
    return [...g.entries()]
  }, [novedades])

  return (
    <>
      <button onClick={abrir} aria-label="Novedades"
        className={`relative p-1.5 rounded-lg transition-colors ${
          variant === 'dark' ? 'text-amber-400/80 hover:text-amber-300' : 'text-warm-400 hover:text-forest'
        }`}>
        <Sparkles size={16} />
        {noVistas > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-0.5 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
            {noVistas > 9 ? '9+' : noVistas}
          </span>
        )}
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4"
          onClick={() => setOpen(false)}>
          <div className="bg-white sm:rounded-2xl rounded-t-2xl w-full max-w-lg max-h-[85vh] flex flex-col"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <Sparkles size={16} className="text-amber-500" />
                <h3 className="text-base font-bold text-gray-800">Novedades del sistema</h3>
              </div>
              <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {grupos.map(([fecha, items]) => (
                <div key={fecha}>
                  <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-2">{fmtFecha(fecha)}</p>
                  <div className="space-y-3">
                    {items.map((n, i) => (
                      <div key={i} className="rounded-xl border border-gray-100 bg-gray-50/60 px-3.5 py-3">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${TIPO[n.tipo].cls}`}>
                            {TIPO[n.tipo].label}
                          </span>
                          <p className="text-sm font-semibold text-gray-800">{n.titulo}</p>
                        </div>
                        <p className="text-xs text-gray-600 leading-relaxed">{n.detalle}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="px-5 py-3 border-t border-gray-100">
              <button onClick={() => { setOpen(false); navigate('/guia') }}
                className="w-full flex items-center justify-center gap-2 text-sm font-semibold text-forest bg-forest-50 hover:bg-forest-100 py-2.5 rounded-xl">
                <BookOpen size={15} /> Ver guía rápida de uso
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
