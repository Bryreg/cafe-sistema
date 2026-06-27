import { useEffect, useState, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Menu, X, Check, Circle, AlertTriangle, ClipboardList, Megaphone,
  Trash2, Package, ShoppingCart, Coins, Truck, Thermometer, ArrowRightLeft, Lock, LogOut,
  Calculator, CalendarClock, Banknote, Receipt,
} from 'lucide-react'
import { dark } from '../constants/darkTheme'
import MovimientoCajaModal from './MovimientoCajaModal'

const fmt = (v: number) => `$${(v || 0).toLocaleString('es-CO')}`

interface Pendiente {
  plantilla_id: number; clave: string; nombre: string; categoria: string
  esperadas: number; hechas: number; pendientes: number; requiere_valor: boolean; requiere_evidencia: boolean
}
interface Novedad {
  id: number; titulo: string; nivel: string; categoria: string; requiere_seguimiento: boolean
}

const QUICK = [
  { label: 'Ventas',          to: '/historial-ventas', icon: Receipt },
  { label: 'Recibir',         to: '/ingresos',       icon: Truck },
  { label: 'Merma',           to: '/mermas',         icon: Trash2 },
  { label: 'Inventario',      to: '/inventario',     icon: Package },
  { label: 'Pedido',          to: '/pedido',         icon: ShoppingCart },
  { label: 'Sencilla',        to: '/sencilla',       icon: Coins },
  { label: 'Consignaciones',  to: '/consignaciones', icon: ArrowRightLeft },
]

export default function OperativeBanner() {
  const { user, tiendaId, isKiosk, resetKiosk } = useAuth()
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  // En el POS el fondo lo ocupan el dock + banner de rutinas → el botón va por encima.
  const onPos = useLocation().pathname === '/pos'

  const [open, setOpen] = useState(false)
  const [modal, setModal] = useState<null | 'rutinas' | 'novedad' | 'recepcion' | 'temperatura' | 'caja'>(null)
  const [pendientes, setPendientes] = useState<Pendiente[]>([])
  const [novedades, setNovedades] = useState<Novedad[]>([])

  const cargar = useCallback(() => {
    if (!tiendaId) return
    api.get(`/rutinas/pendientes?tienda_id=${tiendaId}`).then(r => setPendientes(r.data)).catch(() => {})
    api.get(`/novedades/pendientes?tienda_id=${tiendaId}`).then(r => setNovedades(r.data)).catch(() => {})
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar, open])

  // No mostrar para admin ni sin sesión.
  if (!user || user.rol === 'admin') return null

  const rutinasPendientes = pendientes.reduce((acc, p) => acc + p.pendientes, 0)
  const totalPend = rutinasPendientes + novedades.length
  const dotColor = turno?.es_operativo ? dark.green : turno ? dark.amber : dark.inkSubtle

  const go = (to: string) => { setOpen(false); navigate(to) }

  return (
    <>
      {/* Botón flotante (colapsado) */}
      <button
        onClick={() => setOpen(true)}
        className="fixed left-3 z-50 flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-full shadow-lg"
        style={{ bottom: onPos ? 116 : 16, background: dark.surface, border: `1px solid ${dark.border}` }}
        aria-label="Panel del turno"
      >
        <Menu size={16} style={{ color: dark.ink }} />
        <span className="text-[12px] font-bold" style={{ color: dark.ink }}>Menú</span>
        <span className="w-2 h-2 rounded-full" style={{ background: dotColor }} />
        {totalPend > 0 && (
          <span className="text-[10px] font-bold px-1.5 rounded-full" style={{ background: dark.amberDim, color: '#fff' }}>
            {totalPend}
          </span>
        )}
      </button>

      {/* Panel lateral */}
      {open && (
        <div className="fixed inset-0 z-50 flex" onClick={() => setOpen(false)}>
          <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.5)' }} />
          <div
            className="relative w-[88%] max-w-sm h-full overflow-auto"
            style={{ background: dark.bg, borderRight: `1px solid ${dark.border}` }}
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 pt-4 pb-3 sticky top-0"
              style={{ background: dark.bg, borderBottom: `1px solid ${dark.border}` }}>
              <p className="text-[13px] font-bold" style={{ color: dark.ink }}>Estado del turno</p>
              <button onClick={() => setOpen(false)} style={{ color: dark.inkSubtle }}><X size={18} /></button>
            </div>

            <div className="p-4 space-y-4">
              {/* Estado del turno */}
              {turno ? (
                <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ background: dotColor }} />
                    <span className="text-[13px] font-bold capitalize" style={{ color: dark.ink }}>
                      Turno {turno.tipo_turno || 'activo'}
                    </span>
                    <span className="ml-auto text-[11px] font-semibold"
                      style={{ color: turno.es_operativo ? dark.green : dark.amber }}>
                      {turno.es_operativo ? 'operativo' : 'pendiente'}
                    </span>
                  </div>
                  {turno.baristas?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {turno.baristas.map(b => (
                        <span key={b} className="px-2 py-0.5 rounded-full text-[11px] font-semibold"
                          style={{ background: dark.amberDim, color: dark.amber }}>{b}</span>
                      ))}
                    </div>
                  )}
                  <div className="flex justify-between text-[12px] pt-1" style={{ color: dark.inkMuted }}>
                    <span>Ventas del día</span>
                    <span className="font-mono font-semibold" style={{ color: dark.ink }}>{fmt(turno.total_ventas)}</span>
                  </div>
                  {!turno.es_operativo && (
                    <button onClick={() => go('/gestion-turno')}
                      className="w-full mt-1 py-2 rounded-xl text-[12px] font-bold"
                      style={{ background: dark.amberDim, color: '#fff' }}>
                      Completar cuadre + conteo
                    </button>
                  )}
                </div>
              ) : (
                <button onClick={() => go('/gestion-turno')}
                  className="w-full py-3 rounded-2xl text-[13px] font-bold text-white" style={{ background: dark.greenDim }}>
                  Abrir turno
                </button>
              )}

              {/* Navegación principal (reemplaza el bottom nav) */}
              <div className="grid grid-cols-3 gap-2">
                <button onClick={() => go('/pos')} disabled={!turno?.es_operativo}
                  className="rounded-xl py-2.5 flex flex-col items-center gap-1 disabled:opacity-40"
                  style={{ background: dark.greenDim, color: '#fff' }}>
                  <Calculator size={16} /><span className="text-[11px] font-bold">POS</span>
                </button>
                <button onClick={() => go('/gestion-turno')}
                  className="rounded-xl py-2.5 flex flex-col items-center gap-1"
                  style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}>
                  <CalendarClock size={16} style={{ color: dark.amber }} /><span className="text-[11px] font-bold">Turno</span>
                </button>
                <button onClick={() => turno && setModal('caja')} disabled={!turno}
                  className="rounded-xl py-2.5 flex flex-col items-center gap-1 disabled:opacity-40"
                  style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}>
                  <Banknote size={16} style={{ color: dark.amber }} /><span className="text-[11px] font-bold">Caja</span>
                </button>
              </div>

              {/* Novedades pendientes (continuidad / handoff) */}
              {novedades.length > 0 && (
                <div className="rounded-2xl p-3" style={{ background: dark.amberTint, border: `1px solid ${dark.amberDim}` }}>
                  <p className="text-[11px] font-bold mb-2 flex items-center gap-1.5" style={{ color: dark.amber }}>
                    <AlertTriangle size={12} /> Novedades sin resolver ({novedades.length})
                  </p>
                  <div className="space-y-1.5">
                    {novedades.slice(0, 4).map(n => (
                      <div key={n.id} className="flex items-center gap-2 text-[12px]" style={{ color: dark.ink }}>
                        <Circle size={8} style={{ color: n.nivel === 'urgente' ? dark.danger : dark.amber }} />
                        <span className="flex-1 truncate">{n.titulo}</span>
                        <button onClick={async () => { await api.patch(`/novedades/${n.id}/resolver`); cargar() }}
                          className="text-[11px] font-semibold" style={{ color: dark.green }}>resolver</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Registros rápidos (modales — no navegan, no pierden contexto) */}
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
                  Registrar
                </p>
                <div className="grid grid-cols-3 gap-2">
                  <button onClick={() => setModal('rutinas')}
                    className="rounded-2xl p-3 text-left" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                    <ClipboardList size={18} style={{ color: dark.amber }} />
                    <p className="text-[12px] font-bold mt-1.5" style={{ color: dark.ink }}>Rutinas</p>
                    <p className="text-[11px]" style={{ color: rutinasPendientes ? dark.amber : dark.inkSubtle }}>
                      {rutinasPendientes ? `${rutinasPendientes} pend.` : 'al día'}
                    </p>
                  </button>
                  <button onClick={() => setModal('novedad')}
                    className="rounded-2xl p-3 text-left" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                    <Megaphone size={18} style={{ color: dark.amber }} />
                    <p className="text-[12px] font-bold mt-1.5" style={{ color: dark.ink }}>Novedad</p>
                    <p className="text-[11px]" style={{ color: dark.inkSubtle }}>registrar</p>
                  </button>
                  <button onClick={() => setModal('temperatura')}
                    className="rounded-2xl p-3 text-left" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                    <Thermometer size={18} style={{ color: dark.amber }} />
                    <p className="text-[12px] font-bold mt-1.5" style={{ color: dark.ink }}>Temp.</p>
                    <p className="text-[11px]" style={{ color: dark.inkSubtle }}>registrar</p>
                  </button>
                </div>
              </div>

              {/* Herramientas operativas (única lista — el POS las abre como panel) */}
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
                  Herramientas
                </p>
                <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${dark.border}` }}>
                  {QUICK.map((q, i) => (
                    <button key={q.to} onClick={() => go(q.to)}
                      className="w-full flex items-center gap-3 px-4 py-3"
                      style={{ background: dark.surface, borderTop: i > 0 ? `1px solid ${dark.border}` : undefined }}>
                      <q.icon size={16} style={{ color: dark.inkMuted }} />
                      <span className="text-[13px]" style={{ color: dark.ink }}>{q.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Continuidad */}
              {turno && (
                <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${dark.border}` }}>
                  <button onClick={() => go('/entrega')}
                    className="w-full flex items-center gap-3 px-4 py-3" style={{ background: dark.surface }}>
                    <ArrowRightLeft size={16} style={{ color: dark.inkMuted }} />
                    <span className="text-[13px]" style={{ color: dark.ink }}>Cambio de turno (entrega)</span>
                  </button>
                  <button onClick={() => go('/conteo-cierre')}
                    className="w-full flex items-center gap-3 px-4 py-3" style={{ background: dark.surface, borderTop: `1px solid ${dark.border}` }}>
                    <Lock size={16} style={{ color: dark.inkMuted }} />
                    <span className="text-[13px]" style={{ color: dark.ink }}>Cerrar turno</span>
                  </button>
                </div>
              )}

              {isKiosk && (
                <button onClick={resetKiosk}
                  className="w-full flex items-center justify-center gap-2 py-2 text-[12px]" style={{ color: dark.inkSubtle }}>
                  <LogOut size={14} /> Desactivar dispositivo
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {modal === 'rutinas' && (
        <RutinasModal pendientes={pendientes} tiendaId={tiendaId} onClose={() => setModal(null)} onDone={() => { cargar(); refresh() }} />
      )}
      {modal === 'novedad' && (
        <NovedadModal tiendaId={tiendaId} onClose={() => setModal(null)} onDone={() => { cargar() }} />
      )}
      {modal === 'recepcion' && (
        <RecepcionModal tiendaId={tiendaId} onClose={() => setModal(null)} onDone={() => { refresh() }} />
      )}
      {modal === 'temperatura' && (
        <TemperaturaModal tiendaId={tiendaId} onClose={() => setModal(null)} onDone={() => {}} />
      )}
      {modal === 'caja' && turno && (
        <MovimientoCajaModal turnoId={turno.id} onClose={() => setModal(null)} />
      )}
    </>
  )
}

// ── Modal: registrar rutina ───────────────────────────────────────────────
function RutinasModal({ pendientes, tiendaId, onClose, onDone }: {
  pendientes: Pendiente[]; tiendaId: number | null; onClose: () => void; onDone: () => void
}) {
  const [saving, setSaving] = useState<number | null>(null)
  const registrar = async (p: Pendiente) => {
    if (!tiendaId) return
    let valor: string | null = null
    if (p.requiere_valor) {
      valor = window.prompt(`Valor para "${p.nombre}" (ej. temperatura):`)
      if (valor === null) return
    }
    setSaving(p.plantilla_id)
    try {
      const form = new FormData()
      form.append('tienda_id', String(tiendaId))
      form.append('plantilla_id', String(p.plantilla_id))
      if (valor !== null && valor !== '') form.append('valor', valor)
      await api.post('/rutinas/eventos', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      onDone()
    } catch { /* noop */ } finally { setSaving(null) }
  }
  return (
    <ModalShell title="Rutinas del turno" onClose={onClose}>
      {pendientes.length === 0 && <p className="text-[13px]" style={{ color: dark.inkSubtle }}>No hay rutinas configuradas.</p>}
      <div className="space-y-2">
        {pendientes.map(p => (
          <div key={p.plantilla_id} className="flex items-center gap-3 px-3 py-2.5 rounded-xl"
            style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            <div className="flex-1">
              <p className="text-[13px] font-semibold" style={{ color: dark.ink }}>{p.nombre}</p>
              <p className="text-[11px]" style={{ color: p.pendientes ? dark.amber : dark.green }}>
                {p.hechas}/{p.esperadas} hechas
              </p>
            </div>
            <button onClick={() => registrar(p)} disabled={saving === p.plantilla_id}
              className="px-3 py-1.5 rounded-lg text-[12px] font-bold text-white disabled:opacity-50"
              style={{ background: dark.greenDim }}>
              {saving === p.plantilla_id ? '...' : <Check size={14} />}
            </button>
          </div>
        ))}
      </div>
    </ModalShell>
  )
}

// ── Modal: registrar novedad ──────────────────────────────────────────────
function NovedadModal({ tiendaId, onClose, onDone }: {
  tiendaId: number | null; onClose: () => void; onDone: () => void
}) {
  const [titulo, setTitulo] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [categoria, setCategoria] = useState('incidente')
  const [nivel, setNivel] = useState('info')
  const [seguimiento, setSeguimiento] = useState(false)
  const [saving, setSaving] = useState(false)

  const guardar = async () => {
    if (!tiendaId || !titulo.trim()) return
    setSaving(true)
    try {
      const form = new FormData()
      form.append('tienda_id', String(tiendaId))
      form.append('titulo', titulo.trim())
      form.append('categoria', categoria)
      form.append('nivel', nivel)
      if (descripcion.trim()) form.append('descripcion', descripcion.trim())
      form.append('requiere_seguimiento', String(seguimiento))
      await api.post('/novedades', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      onDone(); onClose()
    } catch { /* noop */ } finally { setSaving(false) }
  }

  const input = { background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }
  return (
    <ModalShell title="Registrar novedad" onClose={onClose}>
      <div className="space-y-3">
        <input value={titulo} onChange={e => setTitulo(e.target.value)} placeholder="¿Qué pasó? (título)"
          className="w-full rounded-xl px-3 py-2.5 text-sm outline-none" style={input} />
        <textarea value={descripcion} onChange={e => setDescripcion(e.target.value)} placeholder="Detalle (opcional)"
          rows={3} className="w-full rounded-xl px-3 py-2.5 text-sm outline-none resize-none" style={input} />
        <div className="grid grid-cols-2 gap-2">
          <select value={categoria} onChange={e => setCategoria(e.target.value)}
            className="rounded-xl px-3 py-2.5 text-sm outline-none" style={input}>
            {['incidente', 'equipo', 'personal', 'cliente', 'seguridad', 'otro'].map(c =>
              <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={nivel} onChange={e => setNivel(e.target.value)}
            className="rounded-xl px-3 py-2.5 text-sm outline-none" style={input}>
            {['info', 'importante', 'urgente'].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <label className="flex items-center gap-2 text-[13px]" style={{ color: dark.inkMuted }}>
          <input type="checkbox" checked={seguimiento} onChange={e => setSeguimiento(e.target.checked)} />
          Requiere seguimiento (pasa al siguiente turno)
        </label>
        <button onClick={guardar} disabled={!titulo.trim() || saving}
          className="w-full py-3 rounded-xl text-[14px] font-bold text-white disabled:opacity-50" style={{ background: dark.greenDim }}>
          {saving ? 'Guardando...' : 'Registrar novedad'}
        </button>
      </div>
    </ModalShell>
  )
}

// ── Modal: recibir mercancía (recepción rápida de 1 ítem, sana stock negativo) ──
function RecepcionModal({ tiendaId, onClose, onDone }: {
  tiendaId: number | null; onClose: () => void; onDone: () => void
}) {
  const [items, setItems] = useState<{ producto_id: number; producto_nombre: string; stock_actual: number }[]>([])
  const [productoId, setProductoId] = useState<number | ''>('')
  const [cantidad, setCantidad] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!tiendaId) return
    api.get(`/inventario/tienda/${tiendaId}`).then(r => setItems(r.data)).catch(() => {})
  }, [tiendaId])

  const guardar = async () => {
    if (!tiendaId || !productoId || !cantidad) return
    setSaving(true); setError('')
    try {
      const { data: rec } = await api.post('/recepciones', { tienda_id: tiendaId, proveedor: 'Recepción rápida' })
      await api.post(`/recepciones/${rec.id}/items`, { producto_id: Number(productoId), cantidad_recibida: Number(cantidad) })
      await api.post(`/recepciones/${rec.id}/confirmar`)
      onDone(); onClose()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al recibir')
    } finally { setSaving(false) }
  }

  const sel = items.find(i => i.producto_id === Number(productoId))
  const input = { background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }
  return (
    <ModalShell title="Recibir mercancía" onClose={onClose}>
      <div className="space-y-3">
        <select value={productoId} onChange={e => setProductoId(Number(e.target.value))}
          className="w-full rounded-xl px-3 py-2.5 text-sm outline-none" style={input}>
          <option value="">Elegí un producto…</option>
          {items.map(i => (
            <option key={i.producto_id} value={i.producto_id}>{i.producto_nombre} (stock {i.stock_actual})</option>
          ))}
        </select>
        <input type="number" inputMode="numeric" value={cantidad} onChange={e => setCantidad(e.target.value)}
          placeholder="Cantidad recibida" className="w-full rounded-xl px-3 py-2.5 text-sm outline-none" style={input} />
        {sel && sel.stock_actual < 0 && cantidad !== '' && (
          <p className="text-[12px]" style={{ color: dark.amber }}>
            Stock {sel.stock_actual} → quedará {sel.stock_actual + Number(cantidad)} (sana el negativo)
          </p>
        )}
        {error && <p className="text-[12px]" style={{ color: dark.danger }}>{error}</p>}
        <button onClick={guardar} disabled={!productoId || !cantidad || saving}
          className="w-full py-3 rounded-xl text-[14px] font-bold text-white disabled:opacity-50" style={{ background: dark.greenDim }}>
          {saving ? 'Recibiendo...' : 'Confirmar recepción'}
        </button>
      </div>
    </ModalShell>
  )
}

// ── Modal: registrar temperatura ──────────────────────────────────────────
function TemperaturaModal({ tiendaId, onClose, onDone }: {
  tiendaId: number | null; onClose: () => void; onDone: () => void
}) {
  const [equipos, setEquipos] = useState<{ id: number; nombre: string; temp_min: number; temp_max: number }[]>([])
  const [equipoId, setEquipoId] = useState<number | ''>('')
  const [valor, setValor] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!tiendaId) return
    api.get(`/temperaturas/equipos?tienda_id=${tiendaId}`).then(r => setEquipos(r.data)).catch(() => {})
  }, [tiendaId])

  const guardar = async () => {
    if (!tiendaId || !equipoId || valor === '') return
    setSaving(true); setError('')
    try {
      await api.post('/temperaturas/lecturas', { tienda_id: tiendaId, equipo_id: Number(equipoId), valor: Number(valor) })
      onDone(); onClose()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar')
    } finally { setSaving(false) }
  }

  const eq = equipos.find(e => e.id === Number(equipoId))
  const fuera = !!eq && valor !== '' && (Number(valor) < eq.temp_min || Number(valor) > eq.temp_max)
  const input = { background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }
  return (
    <ModalShell title="Registrar temperatura" onClose={onClose}>
      <div className="space-y-3">
        {equipos.length === 0 && <p className="text-[13px]" style={{ color: dark.inkSubtle }}>No hay equipos configurados.</p>}
        <select value={equipoId} onChange={e => setEquipoId(Number(e.target.value))}
          className="w-full rounded-xl px-3 py-2.5 text-sm outline-none" style={input}>
          <option value="">Elegí un equipo…</option>
          {equipos.map(e => <option key={e.id} value={e.id}>{e.nombre} ({e.temp_min}° a {e.temp_max}°)</option>)}
        </select>
        <input type="number" inputMode="decimal" value={valor} onChange={e => setValor(e.target.value)}
          placeholder="Temperatura °C" className="w-full rounded-xl px-3 py-2.5 text-sm outline-none"
          style={{ ...input, borderColor: fuera ? dark.danger : dark.border }} />
        {fuera && <p className="text-[12px]" style={{ color: dark.danger }}>⚠ Fuera del rango seguro</p>}
        {error && <p className="text-[12px]" style={{ color: dark.danger }}>{error}</p>}
        <button onClick={guardar} disabled={!equipoId || valor === '' || saving}
          className="w-full py-3 rounded-xl text-[14px] font-bold text-white disabled:opacity-50" style={{ background: dark.greenDim }}>
          {saving ? 'Guardando...' : 'Registrar lectura'}
        </button>
      </div>
    </ModalShell>
  )
}

function ModalShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.6)' }} />
      <div className="relative w-full max-w-md rounded-2xl p-5"
        style={{ background: dark.bg, border: `1px solid ${dark.border}` }} onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[14px] font-bold" style={{ color: dark.ink }}>{title}</p>
          <button onClick={onClose} style={{ color: dark.inkSubtle }}><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}
