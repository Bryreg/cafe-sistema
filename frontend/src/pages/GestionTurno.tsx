import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Users, CheckCircle, Circle, ChevronRight, AlertTriangle,
  Clock, DollarSign, X, Check, LogOut, Package, BarChart2,
} from 'lucide-react'
import { dark } from '../constants/darkTheme'
import BaristaBottomNav from '../components/BaristaBottomNav'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

interface Barista { id: number; nombre: string; rol: string; tienda_id: number | null }

export default function GestionTurno() {
  const { tiendaId, resetKiosk, isKiosk } = useAuth()
  const { turno, loading, refresh } = useTurno()
  const navigate = useNavigate()

  const [baristas, setBaristas] = useState<Barista[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [baseReal, setBaseReal] = useState('')
  const [justificacion, setJustificacion] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [showAbrirForm, setShowAbrirForm] = useState(false)

  useEffect(() => {
    api.get('/auth/usuarios').then(({ data }) => {
      setBaristas(data.filter((u: Barista) => u.rol === 'barista' && u.tienda_id === tiendaId))
    }).catch(() => {})
  }, [tiendaId])

  const toggleBarista = (id: number) =>
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const abrirTurno = async () => {
    if (!tiendaId) return
    setSaving(true); setError('')
    try {
      await api.post('/caja/abrir', {
        tienda_id: tiendaId,
        base_real: Number(baseReal) || 0,
        justificacion_apertura: justificacion || null,
        barista_ids: selected.length > 0 ? selected : null,
      })
      setShowAbrirForm(false)
      setSelected([]); setBaseReal(''); setJustificacion('')
      await refresh()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al abrir turno')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: dark.bg }}>
      <p className="text-sm animate-pulse" style={{ color: dark.inkSubtle }}>Cargando...</p>
    </div>
  )

  return (
    <div className="min-h-screen flex flex-col pb-24" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="px-4 pt-4 pb-3 flex items-center gap-2" style={{ background: dark.bg }}>
        <div className="flex-1">
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Gestión de turno
          </p>
          <p className="text-[16px] font-bold" style={{ color: dark.ink }}>
            {turno ? 'Turno activo' : 'Sin turno activo'}
          </p>
        </div>
        {isKiosk && (
          <button onClick={resetKiosk} className="p-2 rounded-lg opacity-40 hover:opacity-70 transition-opacity"
            style={{ color: dark.inkSubtle }}>
            <LogOut size={16} />
          </button>
        )}
      </header>

      <div className="flex-1 px-4 space-y-4">

        {/* ── CON TURNO ACTIVO ── */}
        {turno && (
          <>
            {/* Baristas en turno */}
            {turno.baristas.length > 0 && (
              <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: dark.inkSubtle }}>
                  Baristas en turno
                </p>
                <div className="flex flex-wrap gap-2">
                  {turno.baristas.map(b => (
                    <span key={b} className="px-3 py-1 rounded-full text-xs font-semibold"
                      style={{ background: dark.amberDim, color: dark.amber }}>
                      {b}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Ventas del día */}
            <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
                Ventas del día
              </p>
              <p className="text-[32px] font-bold font-mono leading-none" style={{ color: dark.ink, letterSpacing: '-1px' }}>
                {fmt(turno.total_ventas ?? 0)}
              </p>
              <div className="flex gap-4 mt-3 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
                {[
                  { l: 'Efectivo', v: fmt(turno.total_efectivo ?? 0) },
                  { l: 'Tarjeta', v: fmt(turno.total_tarjeta ?? 0) },
                ].map(row => (
                  <div key={row.l}>
                    <p className="text-[10px]" style={{ color: dark.inkSubtle }}>{row.l}</p>
                    <p className="text-[14px] font-semibold font-mono" style={{ color: dark.ink }}>{row.v}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Flujo de acciones */}
            <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${dark.border}` }}>
              {[
                {
                  label: 'Conteo de apertura',
                  done: turno.tiene_conteo_apertura,
                  to: '/conteo-apertura',
                  icon: Package,
                  required: true,
                },
                {
                  label: 'Cuadre de llegada',
                  done: !!turno.ultima_entrega_fecha,
                  to: '/cuadre-llegada',
                  icon: DollarSign,
                  required: false,
                },
                {
                  label: 'Conteo de cierre',
                  done: turno.tiene_conteo_cierre,
                  to: '/conteo-cierre',
                  icon: CheckCircle,
                  required: false,
                },
                {
                  label: 'Entrega / cierre de turno',
                  done: false,
                  to: '/entrega',
                  icon: Clock,
                  required: false,
                },
              ].map((item, i) => (
                <button
                  key={item.label}
                  onClick={() => navigate(item.to)}
                  className="w-full flex items-center gap-3 px-4 py-3.5 text-left transition-colors"
                  style={{
                    background: item.done ? 'oklch(18% 0.03 155 / 0.3)' : dark.surface,
                    borderTop: i > 0 ? `1px solid ${dark.border}` : undefined,
                  }}
                >
                  <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
                    style={{ background: item.done ? dark.greenDim : 'rgba(255,255,255,0.06)' }}>
                    {item.done
                      ? <Check size={14} color="#fff" strokeWidth={2.5} />
                      : <Circle size={14} style={{ color: dark.inkSubtle }} />
                    }
                  </div>
                  <div className="flex-1">
                    <p className="text-[13px] font-semibold" style={{ color: item.done ? dark.green : dark.ink }}>
                      {item.label}
                    </p>
                    {item.required && !item.done && (
                      <p className="text-[11px] mt-0.5" style={{ color: dark.amber }}>Recomendado antes de vender</p>
                    )}
                  </div>
                  <ChevronRight size={15} style={{ color: dark.inkSubtle }} />
                </button>
              ))}
            </div>

            {/* Más herramientas */}
            <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${dark.border}` }}>
              {[
                { label: 'Mis ventas hoy', to: '/ventas-hoy', icon: BarChart2 },
                { label: 'Inventario', to: '/inventario', icon: Package },
              ].map((item, i) => (
                <button key={item.label} onClick={() => navigate(item.to)}
                  className="w-full flex items-center gap-3 px-4 py-3.5"
                  style={{ background: dark.surface, borderTop: i > 0 ? `1px solid ${dark.border}` : undefined }}>
                  <item.icon size={16} style={{ color: dark.inkSubtle }} />
                  <span className="flex-1 text-[13px]" style={{ color: dark.ink }}>{item.label}</span>
                  <ChevronRight size={15} style={{ color: dark.inkSubtle }} />
                </button>
              ))}
            </div>
          </>
        )}

        {/* ── SIN TURNO ── */}
        {!turno && !showAbrirForm && (
          <div className="space-y-4">
            <div className="rounded-2xl p-8 text-center" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <Clock size={32} style={{ color: dark.inkSubtle }} className="mx-auto mb-3" />
              <p className="text-[15px] font-bold mb-1" style={{ color: dark.ink }}>No hay turno activo</p>
              <p className="text-[12px]" style={{ color: dark.inkSubtle }}>
                Abre un turno para comenzar a vender
              </p>
            </div>
            <button
              onClick={() => setShowAbrirForm(true)}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white"
              style={{ background: dark.greenDim }}>
              Abrir turno
            </button>
          </div>
        )}

        {/* ── FORMULARIO ABRIR TURNO ── */}
        {!turno && showAbrirForm && (
          <div className="space-y-4">

            <div className="flex items-center justify-between">
              <p className="text-[14px] font-bold" style={{ color: dark.ink }}>Abrir turno</p>
              <button onClick={() => setShowAbrirForm(false)} style={{ color: dark.inkSubtle }}>
                <X size={18} />
              </button>
            </div>

            {/* Selección de baristas */}
            <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest mb-3 flex items-center gap-2" style={{ color: dark.inkSubtle }}>
                <Users size={12} /> Baristas en este turno
              </p>
              {baristas.length === 0 && (
                <p className="text-[12px]" style={{ color: dark.inkSubtle }}>
                  No hay baristas configurados para esta sede.
                </p>
              )}
              {baristas.map(b => (
                <button
                  key={b.id}
                  onClick={() => toggleBarista(b.id)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all"
                  style={{
                    background: selected.includes(b.id) ? dark.greenDim + '44' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${selected.includes(b.id) ? dark.greenDim : 'transparent'}`,
                  }}
                >
                  <div className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold"
                    style={{ background: selected.includes(b.id) ? dark.greenDim : dark.border, color: '#fff' }}>
                    {selected.includes(b.id) ? <Check size={12} /> : b.nombre[0]}
                  </div>
                  <span className="text-[13px] font-semibold" style={{ color: dark.ink }}>{b.nombre}</span>
                </button>
              ))}
            </div>

            {/* Base de caja */}
            <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
                Base de caja
              </p>
              <div className="flex items-center gap-2">
                <span className="text-[20px] font-bold" style={{ color: dark.inkMuted }}>$</span>
                <input
                  type="number"
                  inputMode="numeric"
                  value={baseReal}
                  onChange={e => setBaseReal(e.target.value)}
                  placeholder="0"
                  className="flex-1 text-[28px] font-bold font-mono bg-transparent outline-none"
                  style={{ color: dark.ink }}
                />
              </div>
            </div>

            {/* Justificación (si hay diferencia con la base anterior) */}
            <div>
              <textarea
                value={justificacion}
                onChange={e => setJustificacion(e.target.value)}
                placeholder="Justificación (si hay diferencia con el turno anterior)"
                rows={2}
                className="w-full rounded-xl px-3 py-2.5 text-sm resize-none outline-none"
                style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
                style={{ background: 'oklch(20% 0.08 25)', border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
                <AlertTriangle size={13} /> {error}
              </div>
            )}

            <button
              onClick={abrirTurno}
              disabled={saving}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-50 flex items-center justify-center gap-2"
              style={{ background: dark.greenDim }}>
              <Check size={18} strokeWidth={2.5} />
              {saving ? 'Abriendo...' : 'Confirmar apertura'}
            </button>
          </div>
        )}
      </div>

      <BaristaBottomNav />
    </div>
  )
}
