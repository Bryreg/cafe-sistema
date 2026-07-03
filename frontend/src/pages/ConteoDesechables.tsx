import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Check, AlertTriangle, ClipboardList } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { dark } from '../constants/darkTheme'

interface ItemDesechable {
  producto_id: number
  producto_nombre: string
  unidad_medida: string
  proveedor: string
  stock_actual: number
}

/** Formato de desechables: la barista lo llena SOLO cuando el admin lo solicita.
 *  Productos agrupados por proveedor (como la planilla de Excel). */
export default function ConteoDesechables() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState<ItemDesechable[]>([])
  const [pendiente, setPendiente] = useState<boolean | null>(null)
  const [conteos, setConteos] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!user?.tienda_id) return
    Promise.all([
      api.get(`/conteos/desechables/pendiente/${user.tienda_id}`),
      api.get(`/inventario/desechables/${user.tienda_id}`),
    ]).then(([p, inv]) => {
      setPendiente(!!p.data.pendiente)
      setItems(inv.data)
    }).catch(() => setPendiente(false))
      .finally(() => setLoading(false))
  }, [user?.tienda_id])

  const grupos = items.reduce<Record<string, ItemDesechable[]>>((acc, i) => {
    (acc[i.proveedor] = acc[i.proveedor] ?? []).push(i)
    return acc
  }, {})

  const llenados = Object.keys(conteos).filter(k => conteos[Number(k)] !== '').length

  const confirmar = async () => {
    setSaving(true); setError('')
    try {
      const lista = items
        .filter(i => conteos[i.producto_id] !== undefined && conteos[i.producto_id] !== '')
        .map(i => ({ producto_id: i.producto_id, cantidad_real: Number(conteos[i.producto_id]) }))
      await api.post('/conteos/desechables', { tienda_id: user?.tienda_id, tipo: 'desechables', items: lista })
      setDone(true)
      setTimeout(() => navigate('/gestion-turno'), 1500)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar el conteo')
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3" style={{ background: dark.bg }}>
        <div className="w-14 h-14 rounded-full flex items-center justify-center" style={{ background: dark.greenTint }}>
          <Check size={28} style={{ color: dark.green }} strokeWidth={2.5} />
        </div>
        <p className="text-[15px] font-bold" style={{ color: dark.ink }}>Formato de desechables enviado</p>
        <p className="text-[12px]" style={{ color: dark.inkSubtle }}>El administrador ya lo puede revisar</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>
      <header className="flex items-center gap-3 px-4 pb-3 header-safe sticky top-0 z-10"
        style={{ background: dark.surface, borderBottom: `1px solid ${dark.border}` }}>
        <button onClick={() => navigate('/gestion-turno')} className="p-2 rounded-xl" style={{ color: dark.inkMuted }} aria-label="Volver">
          <ArrowLeft size={18} />
        </button>
        <span className="flex-1 text-sm font-bold" style={{ color: dark.ink }}>Conteo de desechables</span>
        <span className="text-xs" style={{ color: dark.inkSubtle }}>{user?.nombre?.split(' ')[0]}</span>
      </header>

      <div className="flex-1 px-4 py-4 max-w-2xl mx-auto w-full space-y-4">
        {loading ? (
          <p className="text-sm text-center py-10 animate-pulse" style={{ color: dark.inkSubtle }}>Cargando…</p>
        ) : pendiente === false ? (
          <div className="rounded-2xl p-6 text-center" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            <ClipboardList size={26} className="mx-auto mb-2" style={{ color: dark.inkSubtle }} />
            <p className="text-sm font-semibold" style={{ color: dark.ink }}>No hay formato pendiente</p>
            <p className="text-xs mt-1" style={{ color: dark.inkSubtle }}>
              El conteo de desechables se llena solo cuando el administrador lo solicita.
            </p>
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-center py-10" style={{ color: dark.inkSubtle }}>No hay productos de desechables configurados.</p>
        ) : (
          <>
            <p className="text-[12px]" style={{ color: dark.inkSubtle }}>
              El administrador pidió la existencia de desechables. Contá y anotá cada producto;
              los que no tengas, dejalos vacíos o en 0.
            </p>

            {Object.entries(grupos).map(([prov, lista]) => (
              <div key={prov} className="rounded-2xl overflow-hidden" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                <p className="px-4 py-2 text-[10px] font-bold uppercase tracking-widest"
                  style={{ background: dark.surfaceAlt, color: dark.inkMuted }}>
                  {prov}
                </p>
                {lista.map(item => (
                  <div key={item.producto_id} className="flex items-center gap-3 px-4 py-3"
                    style={{ borderTop: `1px solid ${dark.border}` }}>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold" style={{ color: dark.ink }}>{item.producto_nombre}</p>
                    </div>
                    <input
                      type="number" inputMode="decimal" min={0}
                      value={conteos[item.producto_id] ?? ''}
                      onChange={e => setConteos(prev => ({ ...prev, [item.producto_id]: e.target.value }))}
                      placeholder="0"
                      className="w-20 text-right rounded-lg px-2 py-1.5 text-sm font-bold outline-none"
                      style={{
                        background: dark.surfaceAlt,
                        border: `2px solid ${conteos[item.producto_id] ? dark.greenDim : dark.border}`,
                        color: dark.ink, fontFamily: '"JetBrains Mono", monospace',
                      }}
                    />
                    <span className="text-xs w-8" style={{ color: dark.inkSubtle }}>{item.unidad_medida}</span>
                  </div>
                ))}
              </div>
            ))}

            {error && (
              <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
                style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
                <AlertTriangle size={13} /> {error}
              </div>
            )}

            <button onClick={confirmar} disabled={saving || llenados === 0}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40"
              style={{ background: dark.green }}>
              {saving ? 'Enviando…' : `Enviar formato (${llenados}/${items.length} contados)`}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
