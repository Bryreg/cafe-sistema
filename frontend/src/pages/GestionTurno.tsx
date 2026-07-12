import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Users, CheckCircle, Circle, ChevronRight, AlertTriangle,
  Clock, X, Check, LogOut, Package, BarChart2, Sun, Sunset, Moon,
  Cake, Wallet, Receipt, Megaphone, Truck, Trash2, ShoppingCart, Coins,
} from 'lucide-react'
import { dark } from '../constants/darkTheme'
import NovedadesButton from '../components/NovedadesModal'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
const fmtHora = (iso: string) => {
  const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  const d = new Date(s.endsWith('Z') ? s : s + 'Z')
  return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}
const hoyLocal = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
const esHoy = (iso?: string | null) => {
  if (!iso) return false
  const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  const d = new Date(s.endsWith('Z') ? s : s + 'Z')
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` === hoyLocal()
}

/** Comunicados del administrador — visibles arriba del hub, no escondidos. */
/** Persigue (sin bloquear) cuando un preparable quedó NEGATIVO: se vendieron
 *  granizados sin registrar la preparación de la mezcla. */
function PreparacionPendienteBanner() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [negativos, setNegativos] = useState<{ nombre: string; stock: number; unidad: string }[]>([])
  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/inventario/preparables/${user.tienda_id}`)
      .then(r => setNegativos((r.data ?? [])
        .filter((p: any) => (p.stock_actual ?? 0) < -0.01)
        .map((p: any) => ({ nombre: p.nombre, stock: Math.round(p.stock_actual), unidad: p.unidad_medida }))))
      .catch(() => {})
  }, [user?.tienda_id])
  if (negativos.length === 0) return null
  return (
    <div className="rounded-2xl p-4 mb-3 flex items-start gap-3"
      style={{ background: dark.amberTint, border: `1px solid ${dark.amberDim}` }}>
      <span className="text-lg leading-none">⚠</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-bold" style={{ color: dark.amber }}>
          Se está vendiendo sin mezcla registrada
        </p>
        <p className="text-xs mt-0.5" style={{ color: dark.amber }}>
          {negativos.map(n => `${n.nombre}: ${n.stock} ${n.unidad}`).join(' · ')} — si prepararon una tanda, regístrenla.
        </p>
      </div>
      <button onClick={() => navigate('/preparaciones')}
        className="shrink-0 text-xs font-bold px-3 py-2 rounded-xl"
        style={{ background: dark.amber, color: dark.bg }}>
        Registrar
      </button>
    </div>
  )
}

function ComunicadosBarista() {
  const [items, setItems] = useState<any[]>([])
  useEffect(() => {
    api.get('/comunicados/mis-comunicados').then(r => setItems(r.data ?? [])).catch(() => {})
  }, [])
  const marcarLeido = async (id: number) => {
    setItems(prev => prev.filter(c => c.id !== id))
    try { await api.post(`/comunicados/${id}/leer`) } catch { /* noop */ }
  }
  if (items.length === 0) return null
  return (
    <div className="space-y-2">
      {items.map(c => {
        const urgente = c.urgente
        return (
          <div key={c.id} className="rounded-2xl p-4 flex items-start gap-3"
            style={{ background: urgente ? dark.dangerTint : dark.amberTint, border: `1px solid ${urgente ? dark.dangerDim : dark.amberDim}` }}>
            <Megaphone size={16} style={{ color: urgente ? dark.danger : dark.amber, flexShrink: 0, marginTop: 2 }} />
            <div className="flex-1 min-w-0">
              {c.titulo && <p className="text-[13px] font-bold" style={{ color: urgente ? dark.danger : dark.amber }}>{c.titulo}</p>}
              <p className="text-[13px]" style={{ color: dark.ink }}>{c.mensaje}</p>
              <p className="text-[10px] mt-1" style={{ color: dark.inkSubtle }}>
                {c.creado_por ? `— ${c.creado_por}` : 'Administrador'}{urgente ? ' · URGENTE' : ''}
              </p>
            </div>
            <button onClick={() => marcarLeido(c.id)}
              className="text-[11px] font-bold px-2.5 py-1 rounded-full shrink-0"
              style={{ background: '#fff', color: dark.inkMuted, border: `1px solid ${dark.border}` }}>
              Entendido
            </button>
          </div>
        )
      })}
    </div>
  )
}

/** Resumen del día para la barista: qué recibieron, qué dieron de baja, qué pidieron. */
function ResumenDiaBarista({ tiendaId }: { tiendaId: number }) {
  const [recibidos, setRecibidos] = useState<any[]>([])
  const [mermas, setMermas] = useState<any[]>([])
  const [pedidos, setPedidos] = useState<any[]>([])
  const [sencillas, setSencillas] = useState<any[]>([])

  useEffect(() => {
    api.get(`/facturas/tienda/${tiendaId}`).then(r =>
      setRecibidos((r.data ?? []).filter((f: any) => esHoy(f.fecha_registro)))).catch(() => {})
    api.get(`/mermas/tienda/${tiendaId}`).then(r =>
      setMermas((r.data ?? []).filter((m: any) => esHoy(m.fecha_registro)))).catch(() => {})
    api.get(`/solicitudes/pedido/tienda/${tiendaId}`).then(r =>
      setPedidos((r.data ?? []).filter((s: any) => esHoy(s.fecha_solicitud)))).catch(() => {})
    api.get(`/solicitudes/sencilla/tienda/${tiendaId}`).then(r =>
      setSencillas((r.data ?? []).filter((s: any) => esHoy(s.fecha_solicitud)))).catch(() => {})
  }, [tiendaId])

  const totalRecibido = recibidos.reduce((s, f) => s + (f.valor_total ?? 0), 0)
  const nada = recibidos.length === 0 && mermas.length === 0 && pedidos.length === 0 && sencillas.length === 0
  const MERMA_LBL: Record<string, string> = { consumo: 'Consumo', traslado: 'Traslado', 'daño': 'Daño' }

  return (
    <div className="rounded-2xl overflow-hidden lg:col-span-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
      <p className="px-4 pt-4 pb-1 text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
        Lo que hicieron hoy
      </p>
      {nada ? (
        <p className="px-4 pb-4 text-[12px]" style={{ color: dark.inkSubtle }}>Todavía sin actividad registrada hoy.</p>
      ) : (
        <div className="px-4 pb-3">
          {/* Recibidos */}
          {recibidos.length > 0 && (
            <div className="py-2">
              <div className="flex items-center gap-2 mb-1.5">
                <Truck size={13} style={{ color: dark.green }} />
                <p className="text-[12px] font-bold" style={{ color: dark.ink }}>Recibido de proveedores · {fmt(Math.round(totalRecibido))}</p>
              </div>
              {recibidos.map(f => (
                <div key={f.id} className="flex items-center justify-between py-1 pl-5">
                  <span className="text-[12px] truncate" style={{ color: dark.inkMuted }}>
                    {f.proveedor}{f.numero_factura ? ` · Fact. ${f.numero_factura}` : ''} · {fmtHora(f.fecha_registro)}
                  </span>
                  <span className="text-[12px] font-mono font-bold shrink-0" style={{ color: dark.ink }}>{fmt(Math.round(f.valor_total ?? 0))}</span>
                </div>
              ))}
            </div>
          )}
          {/* Mermas / consumo */}
          {mermas.length > 0 && (
            <div className="py-2" style={{ borderTop: `1px solid ${dark.border}` }}>
              <div className="flex items-center gap-2 mb-1.5">
                <Trash2 size={13} style={{ color: dark.amber }} />
                <p className="text-[12px] font-bold" style={{ color: dark.ink }}>Bajas y consumo · {mermas.length}</p>
              </div>
              {mermas.map(m => (
                <div key={m.id} className="flex items-center justify-between py-1 pl-5">
                  <span className="text-[12px] truncate" style={{ color: dark.inkMuted }}>
                    <span style={{ color: dark.amber, fontWeight: 600 }}>{MERMA_LBL[m.tipo] ?? m.tipo}</span> · {m.producto_nombre ?? `#${m.producto_id}`}
                    {m.quien ? ` · consumió ${m.quien}` : ''}
                  </span>
                  <span className="text-[12px] font-mono font-bold shrink-0" style={{ color: dark.ink }}>{Math.round(m.cantidad)} {m.unidad_medida ?? ''}</span>
                </div>
              ))}
            </div>
          )}
          {/* Solicitudes */}
          {(pedidos.length > 0 || sencillas.length > 0) && (
            <div className="py-2" style={{ borderTop: `1px solid ${dark.border}` }}>
              <div className="flex items-center gap-2 mb-1.5">
                <ShoppingCart size={13} style={{ color: dark.green }} />
                <p className="text-[12px] font-bold" style={{ color: dark.ink }}>Solicitudes al admin</p>
              </div>
              {pedidos.map(s => (
                <div key={`p${s.id}`} className="flex items-center justify-between py-1 pl-5">
                  <span className="text-[12px]" style={{ color: dark.inkMuted }}>Pedido · {(s.items?.length ?? 0)} producto{(s.items?.length ?? 0) !== 1 ? 's' : ''}</span>
                  <span className="text-[11px] shrink-0" style={{ color: dark.inkSubtle }}>{s.estado}</span>
                </div>
              ))}
              {sencillas.map(s => (
                <div key={`s${s.id}`} className="flex items-center justify-between py-1 pl-5">
                  <span className="text-[12px] flex items-center gap-1.5" style={{ color: dark.inkMuted }}>
                    <Coins size={11} /> Sencilla · {fmt(Math.round(s.monto_solicitado ?? 0))}{s.motivo ? ` · ${s.motivo}` : ''}
                  </span>
                  <span className="text-[11px] shrink-0" style={{ color: dark.inkSubtle }}>{s.estado}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// fecha_apertura viene en UTC naïve → normalizamos a Z y calculamos transcurrido
function tiempoEnTurno(desde: string): string {
  try {
    const s = desde.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
    const t = new Date(s.endsWith('Z') ? s : s + 'Z').getTime()
    const min = Math.max(0, Math.floor((Date.now() - t) / 60000))
    const h = Math.floor(min / 60), m = min % 60
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  } catch { return '—' }
}

type TipoTurno = 'apertura' | 'intermedio' | 'cierre'
interface Barista { id: number; nombre: string; rol: string; tienda_id: number | null }
interface ImpulsoItem { lote_id: number; producto_nombre: string; cantidad_restante: number; dias_en_inventario: number; urgente: boolean }

const TURNOS: { tipo: TipoTurno; label: string; desc: string; Icon: typeof Sun }[] = [
  { tipo: 'apertura',    label: 'Apertura',    desc: 'Primer turno del día',   Icon: Sun    },
  { tipo: 'intermedio',  label: 'Intermedio',  desc: 'Relevo de turno',         Icon: Sunset },
  { tipo: 'cierre',      label: 'Cierre',      desc: 'Último turno del día',    Icon: Moon   },
]

export default function GestionTurno() {
  const { tiendaId, resetKiosk, isKiosk } = useAuth()
  const { turno, loading, refresh } = useTurno()
  const navigate = useNavigate()

  const [baristas, setBaristas] = useState<Barista[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [tipoTurno, setTipoTurno] = useState<TipoTurno | null>(null)
  const [cajaFuerte, setCajaFuerte] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [impulso, setImpulso] = useState<ImpulsoItem[]>([])

  // step: null = no form | 'tipo' = elegir tipo | 'baristas' = elegir baristas + confirmar
  const [step, setStep] = useState<null | 'tipo' | 'baristas'>(null)

  useEffect(() => {
    // /auth/baristas filtra por la sede del token y excluye el usuario kiosko
    api.get('/auth/baristas').then(({ data }) => {
      setBaristas(data)
    }).catch(() => {})
    if (tiendaId) {
      // Recordatorio de pastelería por impulsar (qué ofrecer según días en inventario)
      api.get(`/inventario/pasteleria-impulso/${tiendaId}`)
        .then(r => setImpulso(r.data))
        .catch(() => {})
    }
  }, [tiendaId])

  const toggleBarista = (id: number) =>
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const elegirTipo = (tipo: TipoTurno) => {
    setTipoTurno(tipo)
    setStep('baristas')
  }

  const cancelar = () => {
    setStep(null); setTipoTurno(null)
    setSelected([]); setCajaFuerte(''); setError('')
  }

  const abrirTurno = async () => {
    if (!tiendaId || !tipoTurno) return
    setSaving(true); setError('')
    try {
      const { data } = await api.post('/caja/abrir', {
        tienda_id: tiendaId,
        tipo_turno: tipoTurno,
        base_real: null, // cuadre diferido: el efectivo se cuenta despues del conteo
        caja_fuerte: Number(cajaFuerte) || 0,
        justificacion_apertura: null,
        barista_ids: selected.length > 0 ? selected : null,
      })
      cancelar()
      await refresh()
      // Orden del flujo: baristas → conteo de inventario → cuadre inicial → POS.
      // Si el dia ya tiene conteo (turno intermedio/cierre) se salta directo al cuadre.
      navigate(data?.es_operativo ? '/pos'
        : data?.dia_tiene_conteo_apertura ? '/cuadre-inicial'
        : '/conteo-apertura')
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
      <header className="px-4 pt-4 pb-3 flex items-center gap-2 w-full max-w-5xl mx-auto" style={{ background: dark.bg }}>
        <div className="flex-1">
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Gestión de turno
          </p>
          <p className="text-[16px] font-bold" style={{ color: dark.ink }}>
            {turno
              ? `Turno ${turno.tipo_turno ?? 'activo'}`
              : step === 'tipo' ? 'Seleccionar turno'
              : step === 'baristas' ? `Turno ${tipoTurno} — baristas`
              : 'Sin turno activo'}
          </p>
        </div>
        {!step && <NovedadesButton rol="barista" variant="dark" />}
        {isKiosk && !step && (
          <button onClick={resetKiosk} className="p-2 rounded-lg opacity-40 hover:opacity-70 transition-opacity"
            style={{ color: dark.inkSubtle }}>
            <LogOut size={16} />
          </button>
        )}
        {step && (
          <button onClick={cancelar} className="p-2 rounded-lg" style={{ color: dark.inkSubtle }}>
            <X size={18} />
          </button>
        )}
      </header>

      <div className="flex-1 px-4 space-y-4 w-full max-w-5xl mx-auto pb-8">

        {/* Comunicados del admin — visibles siempre, con o sin turno */}
        {!step && <PreparacionPendienteBanner />}
        {!step && <ComunicadosBarista />}

        {/* ── CON TURNO ACTIVO ── */}
        {turno && !step && (
          <>
            {/* Gate: estado operativo del turno */}
            {turno.es_operativo ? (
              <button
                onClick={() => navigate('/pos')}
                className="w-full py-4 rounded-2xl font-bold text-[15px] text-white flex items-center justify-center gap-2"
                style={{ background: dark.green }}>
                <Check size={18} strokeWidth={2.5} /> Ir al POS
              </button>
            ) : (
              <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.amberDim}` }}>
                <p className="text-[12px] font-bold flex items-center gap-2" style={{ color: dark.amber }}>
                  <AlertTriangle size={13} /> POS bloqueado — completá para vender
                </p>
                <button onClick={() => navigate('/conteo-apertura')}
                  disabled={turno.tiene_conteo_apertura || turno.dia_tiene_conteo_apertura}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left"
                  style={{ background: dark.surfaceAlt }}>
                  {(turno.tiene_conteo_apertura || turno.dia_tiene_conteo_apertura)
                    ? <Check size={15} style={{ color: dark.green }} />
                    : <Circle size={15} style={{ color: dark.amber }} />}
                  <span className="text-[13px] font-semibold" style={{ color: dark.ink }}>1. Conteo de inventario</span>
                </button>
                <button onClick={() => navigate('/cuadre-inicial')}
                  disabled={turno.tiene_cuadre_llegada}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left"
                  style={{ background: dark.surfaceAlt }}>
                  {turno.tiene_cuadre_llegada
                    ? <Check size={15} style={{ color: dark.green }} />
                    : <Circle size={15} style={{ color: dark.amber }} />}
                  <span className="text-[13px] font-semibold" style={{ color: dark.ink }}>2. Cuadre inicial de caja</span>
                </button>
              </div>
            )}

            {/* Tarjetas de estado — 2 columnas en desktop para no apilar vertical */}
            <div className="lg:grid lg:grid-cols-2 lg:gap-4 lg:items-start space-y-4 lg:space-y-0">

            {/* Resumen del día: recibidos, bajas/consumo, solicitudes */}
            {tiendaId && <ResumenDiaBarista tiendaId={tiendaId} />}

            {/* Baristas en turno */}
            {turno.baristas.length > 0 && (
              <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: dark.inkSubtle }}>
                  Baristas en turno
                </p>
                <div className="flex flex-wrap gap-2">
                  {turno.baristas.map(b => (
                    <span key={b} className="px-3 py-1 rounded-full text-xs font-semibold"
                      style={{ background: dark.amberTint, color: dark.amber }}>
                      {b}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Ventas del día + tiempo en turno */}
            <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <div className="flex items-center justify-between mb-2">
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
                  Ventas del día
                </p>
                <span className="flex items-center gap-1 text-[11px] font-semibold" style={{ color: dark.inkMuted }}>
                  <Clock size={11} /> {tiempoEnTurno(turno.fecha_apertura)} en turno
                </span>
              </div>
              <p className="text-[32px] font-bold font-mono leading-none" style={{ color: dark.ink, letterSpacing: '-1px' }}>
                {fmt(turno.total_ventas ?? 0)}
              </p>
              <div className="grid grid-cols-3 gap-2 mt-3 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
                {[
                  { l: 'Efectivo', v: fmt(turno.total_efectivo ?? 0), Icon: Wallet },
                  { l: 'Tarjeta',  v: fmt(turno.total_tarjeta ?? 0), Icon: Receipt },
                  { l: 'En caja',  v: fmt(turno.efectivo_esperado_actual ?? 0), Icon: Wallet },
                ].map(row => (
                  <div key={row.l}>
                    <p className="text-[10px] flex items-center gap-1" style={{ color: dark.inkSubtle }}>
                      <row.Icon size={10} /> {row.l}
                    </p>
                    <p className="text-[13px] font-semibold font-mono mt-0.5" style={{ color: dark.ink }}>{row.v}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Pastelería por impulsar — recordatorio según días en inventario */}
            {impulso.length > 0 && (
              <div className="rounded-2xl overflow-hidden" style={{ background: dark.surface, border: `1px solid ${dark.amberDim}` }}>
                <div className="px-4 py-2.5 flex items-center gap-2" style={{ background: dark.amberTint }}>
                  <Cake size={14} style={{ color: dark.amber }} />
                  <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: dark.amber }}>
                    Pastelería por impulsar · {impulso.length}
                  </p>
                </div>
                <div>
                  {impulso.slice(0, 6).map((it, i) => (
                    <div key={it.lote_id} className="flex items-center gap-3 px-4 py-2.5"
                      style={{ borderTop: i > 0 ? `1px solid ${dark.border}` : undefined }}>
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-semibold truncate" style={{ color: dark.ink }}>{it.producto_nombre}</p>
                        <p className="text-[11px]" style={{ color: dark.inkSubtle }}>
                          {it.cantidad_restante} {it.cantidad_restante === 1 ? 'unidad' : 'unidades'} disponibles
                        </p>
                      </div>
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full flex-shrink-0"
                        style={{ background: it.urgente ? dark.dangerTint : dark.amberTint, color: it.urgente ? dark.danger : dark.amber }}>
                        {it.urgente ? '¡Último día!' : `${it.dias_en_inventario}d`}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Flujo de acciones */}
            <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${dark.border}` }}>
              {[
                { label: 'Conteo de cierre', done: turno.tiene_conteo_cierre, to: '/conteo-cierre', icon: CheckCircle, note: 'Solo al cerrar el día' },
              ].map((item, i) => (
                <button
                  key={item.label}
                  onClick={() => navigate(item.to)}
                  className="w-full flex items-center gap-3 px-4 py-3.5 text-left transition-colors"
                  style={{
                    background: item.done ? 'oklch(94% 0.03 155 / 0.5)' : dark.surface,
                    borderTop: i > 0 ? `1px solid ${dark.border}` : undefined,
                  }}
                >
                  <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
                    style={{ background: item.done ? dark.green : dark.surfaceAlt }}>
                    {item.done
                      ? <Check size={14} color="#fff" strokeWidth={2.5} />
                      : <Circle size={14} style={{ color: dark.inkSubtle }} />}
                  </div>
                  <div className="flex-1">
                    <p className="text-[13px] font-semibold" style={{ color: item.done ? dark.green : dark.ink }}>
                      {item.label}
                    </p>
                    {item.note && !item.done && (
                      <p className="text-[11px] mt-0.5" style={{ color: dark.amber }}>{item.note}</p>
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
                { label: 'Inventario',     to: '/inventario', icon: Package   },
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

            </div>
          </>
        )}

        {/* ── SIN TURNO + sin form ── */}
        {!turno && !step && (
          <div className="space-y-4">
            <div className="rounded-2xl p-8 text-center" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <Clock size={32} style={{ color: dark.inkSubtle }} className="mx-auto mb-3" />
              <p className="text-[15px] font-bold mb-1" style={{ color: dark.ink }}>No hay turno activo</p>
              <p className="text-[12px]" style={{ color: dark.inkSubtle }}>Abre un turno para comenzar a vender</p>
            </div>
            <button
              onClick={() => setStep('tipo')}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white"
              style={{ background: dark.green }}>
              Abrir turno
            </button>
          </div>
        )}

        {/* ── PASO 1: elegir tipo de turno ── */}
        {step === 'tipo' && (
          <div className="space-y-3">
            <p className="text-[12px]" style={{ color: dark.inkSubtle }}>
              ¿Qué turno vas a iniciar?
            </p>
            {TURNOS.map(({ tipo, label, desc, Icon }) => (
              <button
                key={tipo}
                onClick={() => elegirTipo(tipo)}
                className="w-full flex items-center gap-4 px-4 py-4 rounded-2xl text-left transition-all active:scale-95"
                style={{ background: dark.surface, border: `1px solid ${dark.border}` }}
              >
                <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                  style={{ background: dark.amberTint }}>
                  <Icon size={18} style={{ color: dark.amber }} />
                </div>
                <div className="flex-1">
                  <p className="text-[14px] font-bold capitalize" style={{ color: dark.ink }}>{label}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: dark.inkSubtle }}>{desc}</p>
                </div>
                <ChevronRight size={16} style={{ color: dark.inkSubtle }} />
              </button>
            ))}
          </div>
        )}

        {/* ── PASO 2: baristas + base ── */}
        {step === 'baristas' && (
          <div className="space-y-4">

            {/* Tipo seleccionado (badge) */}
            <div className="flex items-center gap-2">
              <span className="px-3 py-1 rounded-full text-xs font-bold capitalize"
                style={{ background: dark.amberDim, color: dark.amber }}>
                {tipoTurno}
              </span>
              <button
                onClick={() => setStep('tipo')}
                className="text-[11px]"
                style={{ color: dark.inkSubtle }}>
                cambiar
              </button>
            </div>

            {/* Baristas + efectivo lado a lado en desktop */}
            <div className="lg:grid lg:grid-cols-2 lg:gap-4 lg:items-start space-y-4 lg:space-y-0">

            {/* Selección de baristas */}
            <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest mb-3 flex items-center gap-2"
                style={{ color: dark.inkSubtle }}>
                <Users size={12} /> Baristas en este turno
              </p>
              {baristas.length === 0 ? (
                <p className="text-[12px]" style={{ color: dark.inkSubtle }}>
                  No hay baristas configurados para esta sede.
                </p>
              ) : (
                baristas.map(b => (
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
                ))
              )}
            </div>

            {/* Caja fuerte — reserva fija aparte, NO entra en el cuadre de la registradora.
                El efectivo de la registradora se cuenta DESPUÉS del conteo (cuadre inicial). */}
            <div className="space-y-2">
              <div className="rounded-2xl p-4 space-y-1.5" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
                  Caja fuerte / reserva (opcional)
                </p>
                <p className="text-[11px]" style={{ color: dark.inkSubtle }}>
                  Efectivo que se guarda aparte, por si pasa algo extraordinario. Se registra pero
                  <strong> no</strong> cuenta en “debería haber en caja”.
                </p>
                <input
                  type="number" min="0" step="1000" inputMode="numeric"
                  value={cajaFuerte}
                  onChange={e => setCajaFuerte(e.target.value)}
                  placeholder="$0"
                  className="w-full bg-transparent text-[18px] font-mono font-semibold outline-none pt-1"
                  style={{ color: dark.ink }}
                />
              </div>
              <div className="rounded-2xl p-3.5" style={{ background: dark.amberTint, border: `1px solid ${dark.amberDim}` }}>
                <p className="text-[12px]" style={{ color: dark.amber }}>
                  Después de abrir: <strong>conteo de inventario</strong> y luego el
                  <strong> cuadre inicial de caja</strong> (el efectivo que dejó el día anterior).
                </p>
              </div>
            </div>

            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
                style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
                <AlertTriangle size={13} /> {error}
              </div>
            )}

            <button
              onClick={abrirTurno}
              disabled={saving || selected.length === 0}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-50 flex items-center justify-center gap-2"
              style={{ background: dark.green }}>
              <Check size={18} strokeWidth={2.5} />
              {saving ? 'Abriendo...' : selected.length === 0 ? 'Elegí quién entra al turno' : 'Confirmar apertura'}
            </button>
          </div>
        )}
      </div>

    </div>
  )
}
