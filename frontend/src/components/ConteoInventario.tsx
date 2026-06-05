import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { CheckCircle2, Circle, ArrowLeft, ArrowRight, AlertTriangle, ClipboardCheck } from 'lucide-react'
import { dark } from '../constants/darkTheme'

interface InvItem {
  producto_id: number
  producto_nombre: string
  unidad_medida: string
  stock_actual: number
  categoria?: string
}

interface Props {
  tipo: 'apertura' | 'cierre'
}

export default function ConteoInventario({ tipo }: Props) {
  const { user } = useAuth()
  const { refresh } = useTurno()
  const navigate = useNavigate()
  const [items, setItems] = useState<InvItem[]>([])
  const [conteos, setConteos] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [isDirty, setIsDirty] = useState(false)
  const [error, setError] = useState('')

  const isApertura = tipo === 'apertura'
  const paso = isApertura ? 'Paso 2 de 5' : 'Paso 4 de 5'
  const titulo = isApertura ? 'Conteo de apertura' : 'Conteo de cierre'
  const subtitulo = isApertura
    ? 'Verifica el stock físico contra el sistema.'
    : 'Verifica el stock físico al finalizar el turno.'
  const ctaLabel = isApertura ? 'Confirmar conteo de apertura' : 'Confirmar y continuar al cierre'
  const backPath = isApertura ? '/apertura' : '/hub'
  const nextPath = isApertura ? '/hub' : '/cierre'

  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/inventario/tienda/${user.tienda_id}`)
      .then(r => setItems(r.data))
      .finally(() => setLoading(false))
  }, [user?.tienda_id])

  const getVal  = (id: number, ref: number) => conteos[id] !== undefined ? Number(conteos[id]) : ref
  const getDiff = (id: number, ref: number) => getVal(id, ref) - ref

  const todoOk = () => {
    const filled: Record<number, string> = {}
    items.forEach(i => { filled[i.producto_id] = String(i.stock_actual) })
    setConteos(filled)
    setIsDirty(true)
  }

  const confirmar = async () => {
    setSaving(true); setError('')
    try {
      const itemsList = items.map(i => ({
        producto_id: i.producto_id,
        cantidad_real: getVal(i.producto_id, i.stock_actual),
      }))
      await api.post('/conteos/', { tienda_id: user?.tienda_id, tipo, items: itemsList })
      await refresh()
      navigate(nextPath)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar conteo')
    } finally {
      setSaving(false)
    }
  }

  const totalDifs = items.filter(i =>
    conteos[i.producto_id] !== undefined && getDiff(i.producto_id, i.stock_actual) !== 0
  ).length
  const totalOk = items.filter(i =>
    conteos[i.producto_id] !== undefined && getDiff(i.producto_id, i.stock_actual) === 0
  ).length
  const progreso = items.length > 0 ? Math.round((Object.keys(conteos).length / items.length) * 100) : 0

  const canConfirm = isDirty && !saving

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="flex items-center gap-3 px-4 pb-3 header-safe sticky top-0 z-10"
        style={{ background: dark.surface, borderBottom: `1px solid ${dark.border}` }}>
        <button
          onClick={() => navigate(backPath)}
          className="p-2 rounded-xl transition-colors"
          style={{ color: dark.inkMuted }}
          onMouseEnter={e => (e.currentTarget.style.background = dark.surfaceAlt)}
          onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          aria-label="Volver"
        >
          <ArrowLeft size={18} />
        </button>
        <span className="flex-1 text-sm font-bold" style={{ color: dark.ink }}>
          {titulo}
        </span>
        <span className="text-xs" style={{ color: dark.inkSubtle }}>
          {user?.nombre?.split(' ')[0]}
        </span>
      </header>

      {/* Progress bar */}
      <div className="h-1 w-full" style={{ background: dark.border }}>
        <div className="h-1 transition-all duration-500" style={{
          width: `${progreso}%`,
          background: `linear-gradient(90deg, ${dark.amberDim}, ${dark.amber})`,
        }} />
      </div>

      <div className="flex-1 px-4 max-w-lg mx-auto w-full space-y-4 pt-5"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 16px) + 6rem)' }}>

        {/* Título */}
        <div>
          <p className="text-xs font-bold uppercase tracking-widest mb-1" style={{ color: dark.amberDim }}>
            {paso}
          </p>
          <h1 className="text-xl font-bold" style={{ color: dark.ink }}>{titulo}</h1>
          <p className="text-sm mt-0.5" style={{ color: dark.inkMuted }}>{subtitulo}</p>
        </div>

        {/* Contador de progreso */}
        {Object.keys(conteos).length > 0 && (
          <div className="flex gap-2">
            {totalOk > 0 && (
              <span className="px-3 py-1 rounded-full text-xs font-bold" style={{
                background: 'oklch(18% 0.05 155)', color: dark.green,
              }}>
                ✓ {totalOk} correctos
              </span>
            )}
            {totalDifs > 0 && (
              <span className="px-3 py-1 rounded-full text-xs font-bold" style={{
                background: 'oklch(18% 0.05 25)', color: dark.danger,
              }}>
                ⚠ {totalDifs} diferencia{totalDifs > 1 ? 's' : ''}
              </span>
            )}
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl"
            style={{ background: 'oklch(18% 0.05 25)', color: dark.danger, border: `1px solid ${dark.dangerDim}` }}>
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Botón todo OK */}
        <button
          onClick={todoOk}
          className="w-full py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-colors"
          style={{
            background: 'oklch(18% 0.05 155)',
            color: dark.green,
            border: `2px dashed ${dark.greenDim}`,
          }}
        >
          <CheckCircle2 size={16} /> Todo coincide con sistema
        </button>

        {/* Lista de productos */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <p className="text-sm animate-pulse" style={{ color: dark.inkSubtle }}>Cargando productos...</p>
          </div>
        ) : (
          <div className="rounded-2xl overflow-hidden" style={{
            background: dark.surface,
            border: `1px solid ${dark.border}`,
          }}>
            {items.map(item => {
              const val    = conteos[item.producto_id]
              const diff   = val !== undefined ? Number(val) - item.stock_actual : null
              const filled = val !== undefined

              let rowBg = 'transparent'
              if (filled && diff === 0) rowBg = 'oklch(16% 0.04 155 / 0.5)'
              if (filled && diff !== 0) rowBg = 'oklch(16% 0.04 25 / 0.5)'

              return (
                <div key={item.producto_id} className="px-4 py-3.5 transition-colors"
                  style={{
                    background: rowBg,
                    borderBottom: `1px solid ${dark.border}`,
                  }}>
                  <div className="flex items-center gap-3">
                    <div className="shrink-0">
                      {filled && diff === 0
                        ? <CheckCircle2 size={18} style={{ color: dark.green }} />
                        : filled && diff !== 0
                        ? <AlertTriangle size={18} style={{ color: dark.danger }} />
                        : <Circle size={18} style={{ color: dark.inkSubtle }} />
                      }
                    </div>
                    <div className="flex-1 min-w-0">
                      <label
                        htmlFor={`conteo-${item.producto_id}`}
                        className="text-sm font-semibold leading-tight block"
                        style={{ color: dark.ink }}
                      >
                        {item.producto_nombre}
                      </label>
                      <p className="text-xs mt-0.5" style={{ color: dark.inkSubtle }}>
                        Sistema: {item.stock_actual} {item.unidad_medida}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <input
                        id={`conteo-${item.producto_id}`}
                        type="number"
                        inputMode="decimal"
                        value={val ?? ''}
                        onChange={e => {
                          setConteos(prev => ({ ...prev, [item.producto_id]: e.target.value }))
                          setIsDirty(true)
                        }}
                        placeholder={String(item.stock_actual)}
                        className="w-20 text-right rounded-lg px-2 py-1.5 text-sm font-bold outline-none transition-colors"
                        style={{
                          background: dark.surfaceAlt,
                          border: `2px solid ${
                            diff !== null && diff !== 0 ? dark.dangerDim
                            : diff === 0 ? dark.greenDim
                            : dark.border
                          }`,
                          color: diff !== null && diff !== 0 ? dark.danger : diff === 0 ? dark.green : dark.ink,
                          fontFamily: '"JetBrains Mono", monospace',
                        }}
                      />
                      <span className="text-xs w-7 text-left" style={{ color: dark.inkSubtle }}>
                        {item.unidad_medida}
                      </span>
                    </div>
                  </div>
                  {diff !== null && diff !== 0 && (
                    <p className="text-xs font-medium mt-1 ml-7" style={{ color: dark.danger }}>
                      Diferencia: {diff > 0 ? '+' : ''}{diff} {item.unidad_medida}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {totalDifs > 0 && (
          <div className="px-4 py-3 rounded-xl text-sm" style={{
            background: 'oklch(16% 0.04 65)',
            border: `1px solid ${dark.amberDim}`,
            color: dark.amber,
          }}>
            <strong>{totalDifs} diferencia{totalDifs > 1 ? 's' : ''}</strong> registradas. Se guardará en el reporte.
          </div>
        )}
      </div>

      {/* CTA sticky */}
      <div className="fixed bottom-0 left-0 right-0 p-4 max-w-lg mx-auto" style={{
        background: `linear-gradient(to top, ${dark.bg} 70%, transparent)`,
        paddingBottom: 'env(safe-area-inset-bottom, 16px)',
      }}>
        {!isDirty && !saving && (
          <p className="text-center text-xs mb-2" style={{ color: dark.inkSubtle }}>
            Ingresá al menos un valor para continuar
          </p>
        )}
        <button
          onClick={confirmar}
          disabled={!canConfirm}
          className="w-full font-bold py-4 rounded-2xl text-base flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          style={{
            background: canConfirm
              ? `linear-gradient(135deg, ${dark.amberDim}, ${dark.amber})`
              : dark.surfaceAlt,
            color: canConfirm ? dark.bg : dark.inkSubtle,
            opacity: canConfirm ? 1 : 0.6,
            cursor: canConfirm ? 'pointer' : 'not-allowed',
          }}
        >
          <ClipboardCheck size={18} />
          {saving ? 'Guardando...' : ctaLabel}
          {!saving && canConfirm && <ArrowRight size={18} />}
        </button>
      </div>
    </div>
  )
}
