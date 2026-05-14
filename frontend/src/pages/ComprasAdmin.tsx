import { useEffect, useState, useCallback } from 'react'
import api from '../api/client'
import { CheckCircle, AlertTriangle, ClipboardList, ShoppingCart, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface ConteoItem {
  id: number
  producto_id: number
  producto_nombre: string
  categoria: string
  unidad_medida: string
  cantidad_sistema: number
  cantidad_real: number
  diferencia: number
}

interface Conteo {
  id: number
  tienda_id: number
  fecha_conteo: string
  ajustado: boolean
  nota: string | null
  usuario_nombre: string
  items: ConteoItem[]
}

interface PanelItem {
  producto_id: number
  nombre: string
  categoria: string
  unidad_medida: string
  stock_actual: number
  stock_minimo: number
  alerta: boolean
  nivel: 'agotado' | 'bajo' | 'ok'
  cantidad_sugerida: number
}

interface Tienda { id: number; nombre: string }

const CAT_LABEL: Record<string, string> = {
  pasteleria: 'Pastelería',
  bebida: 'Bebidas',
  insumo: 'Insumos',
}

const NIVEL_STYLE: Record<string, string> = {
  agotado: 'bg-red-100 text-red-700 border-red-200',
  bajo: 'bg-amber-50 text-amber-700 border-amber-200',
  ok: 'bg-green-50 text-green-700 border-green-100',
}

// ─── Componente ───────────────────────────────────────────────────────────────

export default function ComprasAdmin() {
  const [tab, setTab] = useState<'conteos' | 'panel'>('conteos')
  const [conteos, setConteos] = useState<Conteo[]>([])
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaPanel, setTiendaPanel] = useState<number | null>(null)
  const [panel, setPanel] = useState<PanelItem[]>([])
  const [filtroPanel, setFiltroPanel] = useState<'todos' | 'alertas'>('alertas')
  const [expandido, setExpandido] = useState<number | null>(null)
  const [ajustando, setAjustando] = useState<number | null>(null)
  const [copiado, setCopiado] = useState(false)
  const [error, setError] = useState('')
  const [loadingPanel, setLoadingPanel] = useState(false)

  const cargarConteos = useCallback(async () => {
    try {
      const { data } = await api.get<Conteo[]>('/compras/conteo/pendientes')
      setConteos(data)
    } catch { /* silencioso */ }
  }, [])

  const cargarTiendas = useCallback(async () => {
    try {
      const { data } = await api.get('/inventario/admin/resumen')
      setTiendas(data.tiendas)
      // Usar forma funcional para evitar closure sobre tiendaPanel del primer render
      setTiendaPanel(prev => prev ?? (data.tiendas[0]?.id ?? null))
    } catch { /* silencioso */ }
  }, [])

  useEffect(() => {
    cargarConteos()
    cargarTiendas()
  }, [])

  useEffect(() => {
    if (!tiendaPanel) return
    setLoadingPanel(true)
    api.get<{ productos: PanelItem[] }>(`/compras/panel/${tiendaPanel}`)
      .then(r => setPanel(r.data.productos))
      .finally(() => setLoadingPanel(false))
  }, [tiendaPanel])

  // ── Ajustar stock ────────────────────────────────────────────────────────

  const ajustar = async (conteoId: number) => {
    setAjustando(conteoId); setError('')
    try {
      await api.post(`/compras/conteo/${conteoId}/ajustar`)
      await cargarConteos()
      if (tiendaPanel) {
        const { data } = await api.get<{ productos: PanelItem[] }>(`/compras/panel/${tiendaPanel}`)
        setPanel(data.productos)
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al ajustar')
    } finally { setAjustando(null) }
  }

  // ── Generar lista de pedido ──────────────────────────────────────────────

  const generarLista = () => {
    const tienda = tiendas.find(t => t.id === tiendaPanel)
    const alertas = panel.filter(p => p.nivel !== 'ok')
    if (alertas.length === 0) return

    const lineas = [
      `*PEDIDO ${tienda?.nombre.toUpperCase() ?? ''} — ${new Date().toLocaleDateString('es-CO')}*`,
      '',
      ...Object.entries(CAT_LABEL).flatMap(([cat, label]) => {
        const items = alertas.filter(p => p.categoria === cat)
        if (items.length === 0) return []
        return [
          `*${label}*`,
          ...items.map(p =>
            p.cantidad_sugerida > 0
              ? `• ${p.nombre}: ${Math.round(p.cantidad_sugerida)} ${p.unidad_medida} (stock: ${Math.round(p.stock_actual)})`
              : `• ${p.nombre}: AGOTADO — definir cantidad`
          ),
          '',
        ]
      }),
    ]

    const texto = lineas.join('\n')
    navigator.clipboard.writeText(texto).then(() => {
      setCopiado(true)
      setTimeout(() => setCopiado(false), 3000)
    }).catch(() => {
      // Fallback para navegadores sin permiso de clipboard
      const ta = document.createElement('textarea')
      ta.value = texto
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 3000)
    })
  }

  // ── Render helpers ───────────────────────────────────────────────────────

  const alertasPanel = panel.filter(p => p.nivel !== 'ok')
  const panelFiltrado = filtroPanel === 'alertas' ? alertasPanel : panel
  const porCategoriaPanel = Object.entries(CAT_LABEL).map(([key, label]) => ({
    key, label, items: panelFiltrado.filter(p => p.categoria === key),
  })).filter(g => g.items.length > 0)

  return (
    <div className="space-y-4">

      {/* Tabs */}
      <div className="flex gap-2">
        {([['conteos', 'Conteos Pendientes', ClipboardList], ['panel', 'Panel de Pedido', ShoppingCart]] as const).map(
          ([key, label, Icon]) => (
            <button key={key} onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold transition-colors ${
                tab === key ? 'bg-amber-600 text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'
              }`}>
              <Icon size={14} /> {label}
              {key === 'conteos' && conteos.length > 0 && (
                <span className="ml-1 bg-red-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center">
                  {conteos.length}
                </span>
              )}
            </button>
          )
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-600 rounded-xl px-4 py-3 text-sm">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      {/* ── TAB: Conteos pendientes ── */}
      {tab === 'conteos' && (
        <div className="space-y-3">
          {conteos.length === 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl px-4 py-8 text-center">
              <CheckCircle size={28} className="text-green-400 mx-auto mb-2" />
              <p className="text-sm text-gray-500">No hay conteos pendientes de ajuste</p>
            </div>
          )}

          {conteos.map(c => (
            <div key={c.id} className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
              {/* Header */}
              <button
                onClick={() => setExpandido(expandido === c.id ? null : c.id)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors">
                <div className="text-left">
                  <p className="text-sm font-semibold text-gray-800">
                    Conteo #{c.id} — Tienda {c.tienda_id}
                  </p>
                  <p className="text-xs text-gray-400">
                    {new Date(c.fecha_conteo).toLocaleDateString('es-CO', {
                      day: '2-digit', month: 'short', year: 'numeric',
                    })} · Por: {c.usuario_nombre}
                  </p>
                  {c.nota && <p className="text-xs text-amber-700 mt-0.5 font-medium">Nota: {c.nota}</p>}
                </div>
                {expandido === c.id ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
              </button>

              {/* Detalle */}
              {expandido === c.id && (
                <div className="border-t border-gray-100">
                  <div className="px-4 py-2 bg-gray-50 grid grid-cols-4 text-xs font-bold text-gray-400 uppercase tracking-wide">
                    <span className="col-span-2">Producto</span>
                    <span className="text-center">Sistema</span>
                    <span className="text-center">Real</span>
                  </div>
                  <div className="divide-y divide-gray-50">
                    {c.items.map(item => {
                      const dif = item.diferencia
                      const difColor = dif < 0 ? 'text-red-600' : dif > 0 ? 'text-blue-600' : 'text-gray-400'
                      return (
                        <div key={item.id} className="px-4 py-2.5 grid grid-cols-4 items-center">
                          <div className="col-span-2">
                            <p className="text-sm font-medium text-gray-800">{item.producto_nombre}</p>
                            <p className="text-xs text-gray-400">{item.unidad_medida}</p>
                          </div>
                          <p className="text-sm text-center text-gray-500">{Math.round(item.cantidad_sistema)}</p>
                          <div className="text-center">
                            <p className="text-sm font-bold text-gray-800">{Math.round(item.cantidad_real)}</p>
                            {dif !== 0 && (
                              <p className={`text-xs font-semibold ${difColor}`}>
                                {dif > 0 ? `+${Math.round(dif)}` : Math.round(dif)}
                              </p>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  <div className="px-4 py-3 border-t border-gray-100">
                    <button
                      onClick={() => ajustar(c.id)}
                      disabled={ajustando === c.id}
                      className="w-full bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm transition-colors">
                      {ajustando === c.id ? 'Ajustando stock...' : 'Aprobar y Ajustar Stock'}
                    </button>
                    <p className="text-xs text-gray-400 text-center mt-1.5">
                      Esto actualiza el inventario a las cantidades reales contadas
                    </p>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── TAB: Panel de pedido ── */}
      {tab === 'panel' && (
        <div className="space-y-4">

          {/* Selector de tienda + filtro */}
          <div className="flex items-center gap-3 flex-wrap">
            {tiendas.map(t => (
              <button key={t.id} onClick={() => setTiendaPanel(t.id)}
                className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${
                  tiendaPanel === t.id ? 'bg-amber-600 text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'
                }`}>{t.nombre}</button>
            ))}
            <div className="ml-auto flex gap-2">
              {(['todos', 'alertas'] as const).map(f => (
                <button key={f} onClick={() => setFiltroPanel(f)}
                  className={`text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                    filtroPanel === f ? 'bg-gray-700 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                  }`}>{f === 'todos' ? 'Todos' : 'Solo alertas'}</button>
              ))}
            </div>
          </div>

          {/* Resumen */}
          {alertasPanel.length > 0 && (
            <div className="flex items-center justify-between bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
              <p className="text-sm font-semibold text-amber-800">
                {alertasPanel.filter(p => p.nivel === 'agotado').length} agotados ·{' '}
                {alertasPanel.filter(p => p.nivel === 'bajo').length} stock bajo
              </p>
              <button onClick={generarLista}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-bold transition-colors">
                {copiado ? <><Check size={13} /> Copiado</> : <><Copy size={13} /> Generar lista</>}
              </button>
            </div>
          )}

          {loadingPanel && (
            <p className="text-sm text-gray-400 text-center py-4 animate-pulse">Cargando stock...</p>
          )}

          {!loadingPanel && porCategoriaPanel.map(grupo => (
            <div key={grupo.key} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100">
                <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">{grupo.label}</p>
              </div>
              <div className="divide-y divide-gray-50">
                {grupo.items.map(p => (
                  <div key={p.producto_id}
                    className={`flex items-center gap-3 px-4 py-3 border-l-4 ${
                      p.nivel === 'agotado' ? 'border-red-400' :
                      p.nivel === 'bajo' ? 'border-amber-400' : 'border-transparent'
                    }`}>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800">{p.nombre}</p>
                      <p className="text-xs text-gray-400">mín {Math.round(p.stock_minimo)} {p.unidad_medida}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className={`text-base font-bold ${
                        p.nivel === 'agotado' ? 'text-red-600' :
                        p.nivel === 'bajo' ? 'text-amber-600' : 'text-gray-700'
                      }`}>{Math.round(p.stock_actual)}</p>
                      <p className="text-xs text-gray-400">{p.unidad_medida}</p>
                    </div>
                    {p.nivel !== 'ok' && p.cantidad_sugerida > 0 && (
                      <div className={`shrink-0 px-2.5 py-1 rounded-lg border text-xs font-bold ${NIVEL_STYLE[p.nivel]}`}>
                        pedir {Math.round(p.cantidad_sugerida)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}

          {!loadingPanel && panelFiltrado.length === 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl px-4 py-8 text-center">
              <CheckCircle size={28} className="text-green-400 mx-auto mb-2" />
              <p className="text-sm text-gray-500">Todo el stock está sobre el mínimo</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
