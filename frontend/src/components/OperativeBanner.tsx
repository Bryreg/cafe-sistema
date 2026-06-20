import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Menu, X, Check, Circle, AlertTriangle, ClipboardList, Megaphone,
  Trash2, Package, ShoppingCart, Coins, Truck, ArrowRightLeft, Lock, LogOut,
} from 'lucide-react'
import { dark } from '../constants/darkTheme'

const fmt = (v: number) => `$${(v || 0).toLocaleString('es-CO')}`

interface Pendiente {
  plantilla_id: number; clave: string; nombre: string; categoria: string
  esperadas: number; hechas: number; pendientes: number; requiere_valor: boolean; requiere_evidencia: boolean
}
interface Novedad {
  id: number; titulo: string; nivel: string; categoria: string; requiere_seguimiento: boolean
}

const QUICK = [
  { label: 'Merma',       to: '/mermas',     icon: Trash2 },
  { label: 'Inventario',  to: '/inventario', icon: Package },
  { label: 'Pedido',      to: '/pedido',     icon: ShoppingCart },
  { label: 'Sencilla',    to: '/sencilla',   icon: Coins },
  { label: 'Recibir',     to: '/ingresos',   icon: Truck },
]

export default function OperativeBanner() {
  const { user, tiendaId, isKiosk, resetKiosk } = useAuth()
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()

  const [open, setOpen] = useState(false)
  const [modal, setModal] = useState<null | 'rutinas' | 'novedad'>(null)
  const [pendientes, setPendientes] = useState<Pendiente[]>([])
  const [novedades, setNovedades] = useState<Novedad[]>([])

  const cargar = useCallback(() => {
    if (!tiendaId) return
    api.get(`/rutinas/pendientes?tienda_id=${tiendaId}`).then(r => setPendientes(r.data)).catch(() => {})
    api.get(`/novedades/pendientes?tienda_id=${tiendaId}`).then(r => setNovedades(r.data)).catch(() => {})
  }, [tiendaId])

  useEffect(() => { if (open) cargar() }, [open, cargar])

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
        className="fixed top-3 left-3 z-40 flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-full shadow-lg"
        style={{ background: dark.surface, border: `1px solid ${dark.border}` }}
        aria-label="Panel del turno"
      >
        <Menu size={16} style={{ color: dark.ink }} />
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

              {/* Novedades pendientes (continuidad / handoff) */}
              {novedades.length > 0 && (
                <div className="rounded-2xl p-3" style={{ background: 'oklch(20% 0.06 55)', border: `1px solid ${dark.amberDim}` }}>
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

              {/* Pendientes + acciones nuevas */}
              <div className="grid grid-cols-2 gap-2">
                <button onClick={() => setModal('rutinas')}
                  className="rounded-2xl p-3 text-left" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                  <ClipboardList size={18} style={{ color: dark.amber }} />
                  <p className="text-[12px] font-bold mt-1.5" style={{ color: dark.ink }}>Rutinas</p>
                  <p className="text-[11px]" style={{ color: rutinasPendientes ? dark.amber : dark.inkSubtle }}>
                    {rutinasPendientes ? `${rutinasPendientes} pendientes` : 'al día'}
                  </p>
                </button>
                <button onClick={() => setModal('novedad')}
                  className="rounded-2xl p-3 text-left" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                  <Megaphone size={18} style={{ color: dark.amber }} />
                  <p className="text-[12px] font-bold mt-1.5" style={{ color: dark.ink }}>Novedad</p>
                  <p className="text-[11px]" style={{ color: dark.inkSubtle }}>registrar</p>
                </button>
              </div>

              {/* Accesos rápidos */}
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
