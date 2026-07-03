import { useEffect, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { CheckCircle2, Circle, ArrowLeft, ArrowRight, AlertTriangle, ClipboardCheck } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import NivelEnvase from './NivelEnvase'

interface InvItem {
  producto_id: number
  producto_nombre: string
  unidad_medida: string
  stock_actual: number
  categoria?: string
  fraccionable?: boolean
  envase?: 'bolsa' | 'botella' | null
  /** Gramos por unidad sellada (bolsa de café 2500). Activa el conteo en gramos. */
  contenido_por_unidad?: number | null
}

/** Conteo en GRAMOS para fraccionables con contenido conocido: bolsas cerradas ×
 *  contenido + gramos pesados de la abierta (gramera). El total viaja en gramos. */
function ConteoGramos({ contenido, onTotal }: { contenido: number; onTotal: (t: number) => void }) {
  const [cerradas, setCerradas] = useState('')
  const [abierta, setAbierta] = useState('')
  const tocado = cerradas !== '' || abierta !== ''
  const total = (Number(cerradas) || 0) * contenido + (Number(abierta) || 0)

  const set = (c: string, a: string) => {
    setCerradas(c); setAbierta(a)
    const t = (Number(c) || 0) * contenido + (Number(a) || 0)
    onTotal(t)
  }

  const inp: CSSProperties = {
    background: dark.surfaceAlt, border: `2px solid ${dark.border}`, color: dark.ink,
    fontFamily: '"JetBrains Mono", monospace',
  }
  return (
    <div className="flex items-end gap-3 flex-wrap">
      <div>
        <p className="text-[10px] mb-1" style={{ color: dark.inkSubtle }}>Bolsas cerradas (×{Math.round(contenido)} gr)</p>
        <input type="number" inputMode="numeric" min={0} value={cerradas} placeholder="0"
          onChange={e => set(e.target.value, abierta)}
          className="w-20 text-right rounded-lg px-2 py-1.5 text-sm font-bold outline-none" style={inp} />
      </div>
      <div>
        <p className="text-[10px] mb-1" style={{ color: dark.inkSubtle }}>Abierta — pesala (gr)</p>
        <input type="number" inputMode="numeric" min={0} value={abierta} placeholder="0"
          onChange={e => set(cerradas, e.target.value)}
          className="w-24 text-right rounded-lg px-2 py-1.5 text-sm font-bold outline-none" style={inp} />
      </div>
      {tocado && (
        <p className="text-[13px] font-bold pb-1.5 font-mono tabular-nums" style={{ color: dark.green }}>
          = {Math.round(total).toLocaleString('es-CO')} gr
        </p>
      )}
    </div>
  )
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

  const [searchParams] = useSearchParams()
  const isKioskClose = searchParams.get('kiosk') === '1'
  const isApertura = tipo === 'apertura'
  const paso = isApertura ? 'Paso 2 de 3' : 'Conteo de cierre'
  const titulo = isApertura ? 'Conteo de apertura' : 'Conteo de cierre'
  const subtitulo = isApertura
    ? 'Verifica el stock físico contra el sistema.'
    : 'Independiente del cuadre de caja: el cuadre con foto se hace desde el celular.'
  const ctaLabel = isApertura ? 'Confirmar conteo — seguir al cuadre de caja' : 'Confirmar conteo de cierre'
  const backPath = isApertura ? '/gestion-turno' : '/gestion-turno'
  // Apertura: baristas → conteo → cuadre inicial (efectivo del día anterior, sin foto).
  // Cierre: el conteo es INDEPENDIENTE del cuadre — se hace en PC y vuelve a gestión;
  // el cuadre con foto y el cierre del turno se hacen desde el celular (Salida).
  const nextPath = isApertura ? '/cuadre-inicial' : (isKioskClose ? '/salida-efectivo' : '/gestion-turno')

  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/inventario/tienda/${user.tienda_id}`)
      .then(r => setItems(r.data))
      .finally(() => setLoading(false))
  }, [user?.tienda_id])

  const getVal  = (id: number, ref: number) => conteos[id] !== undefined ? Number(conteos[id]) : ref
  const getDiff = (id: number, ref: number) => getVal(id, ref) - ref

  const todoOk = () => {
    // Confirmación explícita: este atajo fija todo al stock del sistema y permite cerrar
    // sin contar físicamente, lo que oculta diferencias reales si se usa a la ligera.
    if (!window.confirm('¿Confirmás que contaste físicamente y todo coincide con el sistema?')) return
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

      <div className="flex-1 px-4 max-w-4xl mx-auto w-full space-y-4 pt-5"
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
                background: dark.greenTint, color: dark.green,
              }}>
                ✓ {totalOk} correctos
              </span>
            )}
            {totalDifs > 0 && (
              <span className="px-3 py-1 rounded-full text-xs font-bold" style={{
                background: dark.dangerTint, color: dark.danger,
              }}>
                ⚠ {totalDifs} diferencia{totalDifs > 1 ? 's' : ''}
              </span>
            )}
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl"
            style={{ background: dark.dangerTint, color: dark.danger, border: `1px solid ${dark.dangerDim}` }}>
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Botón todo OK */}
        <button
          onClick={todoOk}
          className="w-full py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-colors"
          style={{
            background: dark.greenTint,
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
          <div className="rounded-2xl overflow-hidden grid grid-cols-1 lg:grid-cols-2" style={{
            background: dark.surface,
            border: `1px solid ${dark.border}`,
          }}>
            {items.map(item => {
              const val    = conteos[item.producto_id]
              const diff   = val !== undefined ? Number(val) - item.stock_actual : null
              const filled = val !== undefined

              let rowBg = 'transparent'
              if (filled && diff === 0) rowBg = 'oklch(94% 0.04 155 / 0.5)'
              if (filled && diff !== 0) rowBg = 'oklch(95% 0.04 25 / 0.5)'

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
                    {!item.fraccionable && (
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
                    )}
                  </div>
                  {item.fraccionable && (item.contenido_por_unidad ?? 0) > 0 ? (
                    <div className="mt-2.5 ml-7">
                      <ConteoGramos
                        contenido={item.contenido_por_unidad as number}
                        onTotal={t => {
                          setConteos(prev => ({ ...prev, [item.producto_id]: String(t) }))
                          setIsDirty(true)
                        }}
                      />
                    </div>
                  ) : item.fraccionable ? (
                    <div className="mt-2.5 ml-7">
                      <NivelEnvase
                        envase={item.envase === 'botella' ? 'botella' : 'bolsa'}
                        unidad={item.unidad_medida}
                        selladas={Math.floor(Number(val ?? 0))}
                        nivel={Number(val ?? 0) - Math.floor(Number(val ?? 0))}
                        onChange={(s, n) => {
                          setConteos(prev => ({ ...prev, [item.producto_id]: String(s + n) }))
                          setIsDirty(true)
                        }}
                      />
                    </div>
                  ) : null}
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
            background: dark.amberTint,
            border: `1px solid ${dark.amberDim}`,
            color: dark.amber,
          }}>
            <strong>{totalDifs} diferencia{totalDifs > 1 ? 's' : ''}</strong> registradas. Se guardará en el reporte.
          </div>
        )}
      </div>

      {/* CTA sticky */}
      <div className="fixed bottom-0 left-0 right-0 p-4 max-w-4xl mx-auto" style={{
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
