import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Sparkles, Package, Eye, StickyNote, Trash2, CheckCircle,
  Check, Lock, AlertTriangle, Circle,
} from 'lucide-react'
import { dark } from '../constants/darkTheme'
import api from '../api/client'
import type { RutinaEstado, BitacoraEntry } from '../hooks/useRutinasEstado'
import type { Turno } from '../contexts/TurnoContext'

interface Props {
  turno: Turno
  estados: RutinaEstado[]
  bitacora: BitacoraEntry[]
  onRegistrar: (clave: string) => Promise<void>
  onClose: () => void
  tiendaId: number
}

interface AlertaStockItem {
  producto_id: number
  producto: string
  unidad: string
  stock_actual: number
  stock_critico: number
  stock_minimo: number
  estado: 'agotado' | 'critico' | 'bajo'
}

interface VerifPendiente {
  id: number
  producto_nombre: string
  unidad: string
  cantidad_conteo: number
  cantidad_sistema: number
}

/** Verificaciones de conteo pedidas por el admin: la barista recuenta el producto
 *  puntual y responde con el valor real (+ nota opcional). */
function VerificacionesConteo({ tiendaId }: { tiendaId: number }) {
  const [pendientes, setPendientes] = useState<VerifPendiente[]>([])
  const [valores, setValores] = useState<Record<number, string>>({})
  const [notas, setNotas] = useState<Record<number, string>>({})
  const [enviando, setEnviando] = useState<number | null>(null)

  const cargar = () => {
    api.get(`/conteos/verificaciones/${tiendaId}`, { params: { estado: 'solicitada' } })
      .then(r => setPendientes(r.data ?? []))
      .catch(() => setPendientes([]))
  }
  useEffect(() => { cargar() }, [tiendaId]) // eslint-disable-line react-hooks/exhaustive-deps

  const responder = async (id: number) => {
    const cantidad = Number(valores[id])
    if (Number.isNaN(cantidad) || valores[id] === undefined || valores[id] === '') return
    setEnviando(id)
    try {
      const fd = new FormData()
      fd.append('cantidad', String(cantidad))
      if ((notas[id] ?? '').trim()) fd.append('nota', notas[id].trim())
      await api.post(`/conteos/verificaciones/${id}/responder`, fd)
      cargar()
    } finally { setEnviando(null) }
  }

  if (pendientes.length === 0) return null

  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <p style={{ ...LBL, color: dark.amber }}>Verificar conteo — pedido del admin</p>
        <span style={{ fontSize: 10, fontWeight: 700, color: 'white', background: dark.amber, borderRadius: 999, padding: '1px 7px' }}>
          {pendientes.length}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {pendientes.map(v => (
          <div key={v.id} className="rounded-2xl border p-3"
            style={{ background: dark.amberTint, borderColor: dark.amberDim }}>
            <p className="m-0 font-bold" style={{ fontSize: 13, color: dark.ink }}>{v.producto_nombre}</p>
            <p className="m-0 mt-0.5" style={{ fontSize: 11, color: dark.inkMuted }}>
              Contá de nuevo este producto. El conteo dijo <strong className="font-mono">{v.cantidad_conteo}</strong>
              {' '}(el sistema decía {v.cantidad_sistema}).
            </p>
            <div className="flex items-center gap-2 mt-2">
              <input
                type="number" min="0" step="0.5" inputMode="decimal"
                value={valores[v.id] ?? ''}
                onChange={e => setValores(s => ({ ...s, [v.id]: e.target.value }))}
                placeholder="Recuento"
                className="w-24 rounded-xl px-2.5 py-2 text-[14px] font-mono font-bold outline-none"
                style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
              />
              <input
                value={notas[v.id] ?? ''}
                onChange={e => setNotas(s => ({ ...s, [v.id]: e.target.value }))}
                placeholder="Nota (opcional)"
                className="flex-1 min-w-0 rounded-xl px-2.5 py-2 text-[12px] outline-none"
                style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
              />
              <button
                onClick={() => responder(v.id)}
                disabled={enviando === v.id || valores[v.id] === undefined || valores[v.id] === ''}
                className="px-3 py-2 rounded-xl text-[12px] font-bold text-white disabled:opacity-40 shrink-0"
                style={{ background: dark.green }}>
                {enviando === v.id ? '...' : 'Responder'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function AlertasStockTurno({ tiendaId }: { tiendaId: number }) {
  const [items, setItems] = useState<AlertaStockItem[]>([])

  useEffect(() => {
    api.get(`/inventario/alertas/${tiendaId}`).then(r => setItems(r.data)).catch(() => {})
  }, [tiendaId])

  const urgentes = items.filter(i => i.estado === 'agotado' || i.estado === 'critico')
  if (urgentes.length === 0) return null

  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <p style={{ ...LBL, color: dark.danger }}>Stock crítico</p>
        <span style={{ fontSize: 10, fontWeight: 700, color: 'white', background: dark.danger, borderRadius: 999, padding: '1px 7px' }}>
          {urgentes.length}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {urgentes.map(a => (
          <div
            key={a.producto_id}
            className="flex items-center gap-3 rounded-2xl border"
            style={{
              padding: '9px 12px',
              background: a.estado === 'agotado' ? dark.dangerTint : 'oklch(22% 0.04 55)',
              borderColor: a.estado === 'agotado' ? '#fecaca' : 'oklch(35% 0.08 55)',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <p className="m-0 font-bold truncate" style={{ fontSize: 12.5, color: a.estado === 'agotado' ? '#7f1d1d' : dark.amber }}>
                {a.producto}
              </p>
              <p className="m-0 mt-0.5" style={{ fontSize: 10.5, color: a.estado === 'agotado' ? '#b91c1c' : 'oklch(70% 0.12 55)' }}>
                {a.estado === 'agotado'
                  ? `Agotado — 0 ${a.unidad}`
                  : `Crítico — ${Math.round(a.stock_actual)}/${Math.round(a.stock_critico)} ${a.unidad}`}
              </p>
            </div>
            <span style={{
              fontSize: 9, fontWeight: 800, textTransform: 'uppercase' as const, letterSpacing: '.06em',
              color: a.estado === 'agotado' ? 'white' : dark.amber,
              background: a.estado === 'agotado' ? dark.danger : 'oklch(30% 0.06 55)',
              padding: '3px 7px', borderRadius: 999,
            }}>
              {a.estado === 'agotado' ? 'Agotado' : 'Crítico'}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

/** Conteo de desechables: lo ARRANCA la barista, cuando tiene un hueco.
 *
 *  Antes este card solo aparecía si el admin pedía el formato, y el arranque era
 *  suyo. Los desechables están fuera del conteo diario, así que eso significaba
 *  que si nadie se acordaba no se contaban nunca — y cuando sí lo pedía, le caía
 *  a la barista en el momento que a ella le tocara, que podía ser el peor del
 *  día. Un conteo hecho entre clientes son números inventados.
 *
 *  Por eso ahora el card está SIEMPRE, y es el botón de arranque. Sigue
 *  distinguiendo quién lo abrió: si lo pidió el admin (o salió de la
 *  programación, si alguien la prende) se ve en ámbar como algo que hay que
 *  hacer; si no hay nada abierto, se ve neutro como una acción disponible.
 */
function DesechablesPendiente({ tiendaId }: { tiendaId: number }) {
  const [pendiente, setPendiente] = useState<boolean | null>(null)
  const [automatica, setAutomatica] = useState(false)
  const [arrancando, setArrancando] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    api.get(`/conteos/desechables/pendiente/${tiendaId}`)
      .then(r => { setPendiente(!!r.data?.pendiente); setAutomatica(!!r.data?.automatica) })
      .catch(() => setPendiente(false))
  }, [tiendaId])

  const arrancar = async () => {
    setArrancando(true)
    try {
      const fd = new FormData()
      fd.append('tienda_id', String(tiendaId))
      await api.post('/conteos/desechables/iniciar', fd)
      navigate('/conteo-desechables')
    } catch {
      setArrancando(false)
    }
  }

  // Mientras no se sabe, no se dibuja nada: un card que aparece y cambia de
  // color al segundo es peor que uno que llega un instante después.
  if (pendiente === null) return null

  const abierto = pendiente
  return (
    <button type="button"
      onClick={abierto ? () => navigate('/conteo-desechables') : arrancar}
      disabled={arrancando}
      className="w-full flex items-center gap-3 rounded-2xl border px-4 py-3 text-left"
      style={{
        background: abierto ? dark.amberTint : dark.surface,
        borderColor: abierto ? dark.amberDim : dark.border,
        cursor: arrancando ? 'default' : 'pointer',
        opacity: arrancando ? 0.6 : 1,
      }}>
      <Package size={16} style={{ color: abierto ? dark.amber : dark.inkMuted, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p className="m-0 font-bold" style={{ fontSize: 13, color: abierto ? dark.amber : dark.ink }}>
          {abierto
            ? (automatica ? 'Toca contar los desechables' : 'El admin pidió el conteo de desechables')
            : 'Conteo de desechables'}
        </p>
        <p className="m-0 mt-0.5" style={{ fontSize: 11, color: dark.inkMuted }}>
          {abierto
            ? 'Tocá para llenar el formato (agrupado por proveedor)'
            : 'Cuando tengas un momento tranquilo. Vasos, tapas y aseo.'}
        </p>
      </div>
      <span className="rounded-xl font-bold text-white"
        style={{ padding: '5px 10px', fontSize: 11, background: abierto ? dark.amber : dark.inkMuted }}>
        {arrancando ? '...' : abierto ? 'Llenar' : 'Contar'}
      </span>
    </button>
  )
}

interface FacturaRecibida {
  id: number
  proveedor: string
  numero_factura: string | null
  valor_total: number
  fecha_registro: string
  barista_nombre: string
  items: { id: number; producto_nombre: string; cantidad: number; unidad_medida: string }[]
}

/** Local YYYY-MM-DD of a backend UTC-naive timestamp. */
function fechaLocalDe(iso: string): string {
  const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  const d = new Date(s.endsWith('Z') ? s : s + 'Z')
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Facturas ingresadas HOY: la barista revisa el valor y los productos del recibido. */
function RecibidosHoy({ tiendaId }: { tiendaId: number }) {
  const [facturas, setFacturas] = useState<FacturaRecibida[]>([])
  const [abierta, setAbierta] = useState<number | null>(null)

  useEffect(() => {
    api.get(`/facturas/tienda/${tiendaId}`).then(r => {
      const hoy = fechaLocalDe(new Date().toISOString())
      setFacturas((r.data as FacturaRecibida[]).filter(
        f => f.fecha_registro && fechaLocalDe(f.fecha_registro) === hoy,
      ))
    }).catch(() => {})
  }, [tiendaId])

  if (facturas.length === 0) return null
  const plata = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <p style={LBL}>Recibidos de hoy</p>
        <span style={{ fontSize: 10, fontWeight: 700, color: 'white', background: dark.green, borderRadius: 999, padding: '1px 7px' }}>
          {facturas.length}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {facturas.map(f => (
          <div key={f.id} className="rounded-2xl border" style={{ background: dark.surface, borderColor: dark.border }}>
            <button
              onClick={() => setAbierta(a => (a === f.id ? null : f.id))}
              className="w-full flex items-center gap-3 text-left"
              style={{ padding: '10px 12px', background: 'transparent', border: 'none', cursor: 'pointer' }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <p className="m-0 font-bold truncate" style={{ fontSize: 12.5, color: dark.ink }}>
                  {f.proveedor}{f.numero_factura ? ` · Fact. ${f.numero_factura}` : ''}
                </p>
                <p className="m-0 mt-0.5" style={{ fontSize: 10.5, color: dark.inkSubtle }}>
                  {fmtHora(f.fecha_registro)} · {f.items.length} producto{f.items.length !== 1 ? 's' : ''}
                  {f.barista_nombre ? ` · ${f.barista_nombre}` : ''}
                </p>
              </div>
              <span className="font-bold font-mono tabular-nums" style={{ fontSize: 13, color: dark.green }}>
                {plata(f.valor_total)}
              </span>
            </button>
            {abierta === f.id && (
              <div style={{ padding: '0 12px 10px', borderTop: `1px solid ${dark.border}` }}>
                {f.items.map(i => (
                  <div key={i.id} className="flex items-center justify-between" style={{ padding: '6px 0' }}>
                    <span style={{ fontSize: 11.5, color: dark.inkMuted }}>{i.producto_nombre}</span>
                    <span className="font-bold font-mono tabular-nums" style={{ fontSize: 11.5, color: dark.ink }}>
                      {Math.round(i.cantidad)} {i.unidad_medida}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

/** Actividad del día: mermas y solicitudes — el Panel de Turno como dashboard de
 *  lo que las baristas hicieron hoy (recibidos ya tiene su sección propia). */
function ActividadHoy({ tiendaId }: { tiendaId: number }) {
  const [mermas, setMermas] = useState<any[]>([])
  const [pedidos, setPedidos] = useState<any[]>([])
  const [sencillas, setSencillas] = useState<any[]>([])

  useEffect(() => {
    const hoy = fechaLocalDe(new Date().toISOString())
    const esHoy = (iso?: string | null) => !!iso && fechaLocalDe(iso) === hoy
    api.get(`/mermas/tienda/${tiendaId}`).then(r =>
      setMermas((r.data ?? []).filter((m: any) => esHoy(m.fecha_registro)))).catch(() => {})
    api.get(`/solicitudes/pedido/tienda/${tiendaId}`).then(r =>
      setPedidos((r.data ?? []).filter((s: any) => esHoy(s.fecha_solicitud ?? s.fecha)))).catch(() => {})
    api.get(`/solicitudes/sencilla/tienda/${tiendaId}`).then(r =>
      setSencillas((r.data ?? []).filter((s: any) => esHoy(s.fecha_solicitud ?? s.fecha)))).catch(() => {})
  }, [tiendaId])

  if (mermas.length === 0 && pedidos.length === 0 && sencillas.length === 0) return null
  const MERMA_LBL: Record<string, string> = { consumo: 'Consumo', traslado: 'Traslado', 'daño': 'Daño' }

  return (
    <section>
      <p style={LBL} className="mb-2">Actividad de hoy</p>
      <div className="rounded-2xl border overflow-hidden" style={{ background: dark.surface, borderColor: dark.border }}>
        {mermas.map(m => (
          <div key={`m${m.id}`} className="flex items-center gap-2 px-4 py-2" style={{ borderBottom: `1px solid ${dark.border}` }}>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0"
              style={{ background: dark.amberTint, color: dark.amber }}>
              {MERMA_LBL[m.tipo] ?? 'Merma'}
            </span>
            <span className="flex-1 truncate" style={{ fontSize: 12, color: dark.inkMuted }}>
              {m.producto_nombre ?? `#${m.producto_id}`}
              {m.quien ? ` · consumió ${m.quien}` : ''}
            </span>
            <span className="font-mono font-bold shrink-0" style={{ fontSize: 12, color: dark.ink }}>
              {Math.round(m.cantidad)} {m.unidad_medida ?? ''}
            </span>
          </div>
        ))}
        {pedidos.map(s => (
          <div key={`p${s.id}`} className="flex items-center gap-2 px-4 py-2" style={{ borderBottom: `1px solid ${dark.border}` }}>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0"
              style={{ background: dark.greenTint, color: dark.green }}>Pedido</span>
            <span className="flex-1 truncate" style={{ fontSize: 12, color: dark.inkMuted }}>
              {(s.items?.length ?? 0)} producto{(s.items?.length ?? 0) !== 1 ? 's' : ''} solicitados
            </span>
            <span className="shrink-0" style={{ fontSize: 11, color: dark.inkSubtle }}>{s.estado}</span>
          </div>
        ))}
        {sencillas.map(s => (
          <div key={`s${s.id}`} className="flex items-center gap-2 px-4 py-2" style={{ borderBottom: `1px solid ${dark.border}` }}>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0"
              style={{ background: 'oklch(95% 0.015 245)', color: 'oklch(35% 0.12 245)' }}>Sencilla</span>
            <span className="flex-1 truncate" style={{ fontSize: 12, color: dark.inkMuted }}>
              ${Math.round(s.monto_solicitado ?? 0).toLocaleString('es-CO')}{s.motivo ? ` · ${s.motivo}` : ''}
            </span>
            <span className="shrink-0" style={{ fontSize: 11, color: dark.inkSubtle }}>{s.estado}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

const RUTINAS = [
  { k: 'limpieza', label: 'Limpieza',  Icon: Sparkles,   track: true },
  { k: 'surtido',  label: 'Surtido',   Icon: Package,    track: true },
  { k: 'vitrina',  label: 'Vitrina',   Icon: Eye,        track: true },
  { k: 'novedad',  label: 'Novedad',   Icon: StickyNote, track: false },
  { k: 'merma_op', label: 'Merma',     Icon: Trash2,     track: false },
]

function ago(m: number | null): string {
  if (m === null) return '—'
  if (m === 0) return 'recién'
  if (m < 60) return `hace ${m}m`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r > 0 ? `hace ${h}h ${r}m` : `hace ${h}h`
}

function fmtHora(iso: string): string {
  try {
    const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
    const d = new Date(s.endsWith('Z') ? s : s + 'Z')
    return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.slice(11, 16)
  }
}

function dotColor(status: string | null): string {
  if (status === 'ok')    return '#22c55e'
  if (status === 'warn')  return '#f59e0b'
  if (status === 'alert') return '#ef4444'
  return '#cbd5e1'
}

function TipoLabel({ tipo }: { tipo: string | null }) {
  const map: Record<string, string> = { apertura: 'Apertura', intermedio: 'Intermedio', cierre: 'Cierre' }
  return <>{map[tipo ?? ''] ?? 'Turno'}</>
}

const LBL = { fontSize: 10, fontWeight: 800, textTransform: 'uppercase' as const, letterSpacing: '.05em', color: dark.inkSubtle, margin: 0 }

export default function PanelTurno({ turno, estados, bitacora, onRegistrar, tiendaId }: Props) {
  const [tapping, setTapping] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  const tap = async (k: string) => {
    if (tapping) return
    setTapping(k)
    try {
      await onRegistrar(k)
      setFlash(k)
      setTimeout(() => setFlash(null), 1800)
    } finally {
      setTapping(null)
    }
  }

  const byKey = Object.fromEntries(estados.map(e => [e.clave, e]))
  const alerts = estados.filter(e => e.track && e.status === 'alert')

  // Obligatorios de apertura
  const obligAp = [
    { k: 'cuadre',  label: 'Cuadre de llegada',    done: turno.tiene_cuadre_llegada,    ts: turno.fecha_apertura },
    { k: 'conteo',  label: 'Conteo de apertura',   done: turno.tiene_conteo_apertura,   ts: turno.ts_conteo_apertura ?? turno.fecha_apertura },
  ]
  const obligCierre = [
    { k: 'conteo_c', label: 'Conteo de cierre',     done: turno.tiene_conteo_cierre, ts: turno.ts_conteo_cierre },
    { k: 'cuadre_c', label: 'Cuadre de caja',       done: false,                     ts: null },
    { k: 'entrega',  label: 'Entrega de efectivo',  done: false,                     ts: null },
    { k: 'cierre_t', label: 'Cierre de turno',      done: turno.estado === 'cerrado', ts: null },
  ]
  const apDone  = obligAp.filter(o => o.done).length
  const cierreDone = obligCierre.filter(o => o.done).length
  const total = obligAp.length + obligCierre.length
  const done  = apDone + cierreDone

  return (
    <div className="flex flex-col" style={{ background: dark.bg }}>

      {/* ── Header (sticky dentro del scroll del host) ── */}
      <div
        className="sticky top-0 z-10 px-5 py-4"
        style={{ background: 'oklch(18% 0.01 55)', color: '#f8f5f0' }}
      >
        <div className="flex items-center">
          <span style={{ fontSize: 15, fontWeight: 800 }}>Panel de Turno</span>
        </div>
        <div className="flex items-center gap-2 mt-3 flex-wrap">
          <span style={{ fontSize: 13, fontWeight: 700 }}><TipoLabel tipo={turno.tipo_turno} /></span>
          <span style={{ fontSize: 12, opacity: .6 }}>· inició {fmtHora(turno.fecha_apertura)}</span>
          {turno.baristas.length > 0 && (
            <>
              <span style={{ width: 3, height: 3, borderRadius: 99, background: 'rgba(255,255,255,.3)', flexShrink: 0 }} />
              {turno.baristas.map(b => (
                <span key={b} style={{ fontSize: 11, fontWeight: 600, background: 'rgba(255,255,255,.12)', borderRadius: 999, padding: '2px 8px' }}>
                  {b}
                </span>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ── Body (scrollea con el host) ── */}
      <div style={{ padding: 16 }}>
        <div className="flex flex-col gap-5">

          {/* Stock crítico (Módulo 6) */}
          <VerificacionesConteo tiendaId={tiendaId} />
          <DesechablesPendiente tiendaId={tiendaId} />
          <AlertasStockTurno tiendaId={tiendaId} />
          <RecibidosHoy tiendaId={tiendaId} />
          <ActividadHoy tiendaId={tiendaId} />

          {/* Alertas */}
          {alerts.length > 0 && (
            <section className="flex flex-col gap-2">
              {alerts.map(a => (
                <div
                  key={a.clave}
                  className="flex items-center gap-3 rounded-2xl border"
                  style={{ padding: '11px 14px', background: dark.dangerTint, borderColor: '#fecaca' }}
                >
                  <AlertTriangle size={16} style={{ color: dark.danger, flexShrink: 0 }} />
                  <div className="flex-1 min-w-0">
                    <p className="m-0 font-bold" style={{ fontSize: 13, color: '#7f1d1d' }}>{a.nombre} pendiente</p>
                    <p className="m-0 mt-0.5" style={{ fontSize: 11, color: '#b91c1c' }}>
                      sin registrar {ago(a.minutos)} · esperado c/{a.every ? `${Math.round(a.every / 60)}h` : '—'}
                    </p>
                  </div>
                  <button
                    onClick={() => tap(a.clave)}
                    disabled={!!tapping}
                    className="rounded-xl font-bold text-white transition-all active:scale-95"
                    style={{ padding: '5px 10px', fontSize: 11, background: dark.danger }}
                  >
                    Registrar
                  </button>
                </div>
              ))}
            </section>
          )}

          {/* Obligatorios */}
          <section>
            <div className="flex items-center justify-between mb-2.5">
              <p style={LBL}>Procesos obligatorios</p>
              <span
                className="rounded-full font-bold tabular-nums"
                style={{
                  fontSize: 10, padding: '2px 7px',
                  background: done === total ? dark.greenTint : dark.amberTint,
                  color: done === total ? dark.green : dark.amber,
                }}
              >
                {done}/{total}
              </span>
            </div>
            <div
              className="rounded-2xl border"
              style={{ background: dark.surface, borderColor: dark.border, padding: '4px 14px' }}
            >
              <p className="mt-2 mb-1" style={{ fontSize: 11, fontWeight: 800, color: dark.green }}>
                ☀ Apertura{apDone === obligAp.length ? ' · completa' : ''}
              </p>
              {obligAp.map(o => (
                <div key={o.k} className="flex items-center gap-2.5" style={{ padding: '7px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                  <span
                    className="flex items-center justify-center rounded-lg flex-shrink-0"
                    style={{
                      width: 22, height: 22,
                      background: o.done ? dark.greenTint : dark.surfaceAlt,
                      color: o.done ? dark.green : dark.inkSubtle,
                    }}
                  >
                    {o.done ? <Check size={12} /> : <Circle size={12} />}
                  </span>
                  <span className="flex-1 font-semibold" style={{ fontSize: 13, color: dark.ink }}>{o.label}</span>
                  {o.done && o.ts && (
                    <span className="font-mono" style={{ fontSize: 11, color: dark.inkSubtle }}>{fmtHora(o.ts)}</span>
                  )}
                </div>
              ))}

              <p className="mt-3 mb-1" style={{ fontSize: 11, fontWeight: 800, color: dark.inkSubtle }}>
                🌙 Cierre · al finalizar
              </p>
              {obligCierre.map(o => (
                <div key={o.k} className="flex items-center gap-2.5" style={{ padding: '7px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                  <span
                    className="flex items-center justify-center rounded-lg flex-shrink-0"
                    style={{ width: 22, height: 22, background: o.done ? dark.greenTint : dark.surfaceAlt, color: o.done ? dark.green : dark.inkSubtle }}
                  >
                    {o.done ? <Check size={12} /> : <Lock size={11} />}
                  </span>
                  <span className="flex-1 font-semibold" style={{ fontSize: 13, color: o.done ? dark.ink : dark.inkSubtle }}>
                    {o.label}
                  </span>
                  {o.done && o.ts && (
                    <span className="font-mono" style={{ fontSize: 11, color: dark.inkSubtle }}>{fmtHora(o.ts)}</span>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Botones rápidos — solo rutinas reales (Novedad/Merma viven en su propia herramienta) */}
          <section>
            <p style={{ ...LBL, marginBottom: 10 }}>Registrar rutina · 1 clic</p>
            <div className="grid grid-cols-3 gap-2.5">
              {RUTINAS.filter(d => d.track).map(({ k, label, Icon, track }) => {
                const estado = byKey[k]
                const isAlert = track && estado?.status === 'alert'
                const isFlash = flash === k
                const isBusy = tapping === k
                return (
                  <button
                    key={k}
                    onClick={() => tap(k)}
                    disabled={!!tapping}
                    className="flex flex-col items-center justify-center gap-2 rounded-2xl border-2 transition-all active:scale-95"
                    style={{
                      padding: '13px 6px',
                      background: isFlash ? dark.greenTint : isAlert ? dark.dangerTint : dark.surface,
                      borderColor: isFlash ? dark.green : isAlert ? '#fca5a5' : dark.border,
                      opacity: isBusy ? 0.55 : 1,
                    }}
                  >
                    {isFlash
                      ? <CheckCircle size={20} style={{ color: dark.green }} />
                      : <Icon size={20} style={{ color: isAlert ? dark.danger : dark.inkMuted }} />
                    }
                    <span style={{ fontSize: 11, fontWeight: 700, color: dark.ink, textAlign: 'center', lineHeight: 1.2 }}>
                      {label}
                    </span>
                  </button>
                )
              })}
            </div>
          </section>

          {/* Últimas rutinas */}
          <section>
            <p style={{ ...LBL, marginBottom: 10 }}>Últimas rutinas</p>
            <div
              className="rounded-2xl border"
              style={{ background: dark.surface, borderColor: dark.border, padding: '4px 14px' }}
            >
              {RUTINAS.filter(d => d.track).map(({ k, label }) => {
                const e = byKey[k]
                return (
                  <div key={k} className="flex items-center gap-3" style={{ padding: '10px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                    <span className="rounded-full flex-shrink-0" style={{ width: 8, height: 8, background: dotColor(e?.status ?? null) }} />
                    <span className="flex-1 font-semibold" style={{ fontSize: 13, color: dark.ink }}>{label}</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: dotColor(e?.status ?? null) }}>
                      {ago(e?.minutos ?? null)}
                    </span>
                  </div>
                )
              })}
              <div className="flex gap-5" style={{ padding: '10px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                <span style={{ fontSize: 12, color: dark.inkMuted }}>
                  Novedades: <strong style={{ color: dark.ink }}>{byKey['novedad']?.count ?? 0}</strong>
                </span>
                <span style={{ fontSize: 12, color: dark.inkMuted }}>
                  Mermas: <strong style={{ color: dark.ink }}>{byKey['merma_op']?.count ?? 0}</strong>
                </span>
              </div>
            </div>
          </section>

          {/* Bitácora */}
          {bitacora.length > 0 && (
            <section>
              <p style={{ ...LBL, marginBottom: 12 }}>Bitácora del turno</p>
              <div style={{ position: 'relative', paddingLeft: 20 }}>
                <div
                  style={{
                    position: 'absolute', left: 5, top: 4, bottom: 4,
                    width: 2, background: dark.border, borderRadius: 1,
                  }}
                />
                {bitacora.map((e, i) => (
                  <div key={i} style={{ position: 'relative', paddingBottom: 12 }}>
                    <span
                      style={{
                        position: 'absolute', left: -20, top: 3,
                        width: 10, height: 10, borderRadius: 99,
                        background: e.hito ? dark.green : 'oklch(68% 0.15 65)',
                        border: `2px solid ${dark.bg}`,
                      }}
                    />
                    <div className="flex gap-2 items-baseline">
                      <span className="font-mono font-bold flex-shrink-0" style={{ fontSize: 11, color: dark.inkSubtle, minWidth: 36 }}>
                        {fmtHora(e.fecha)}
                      </span>
                      <span style={{ fontSize: 13, color: dark.ink, fontWeight: e.hito ? 700 : 500 }}>
                        {e.txt}
                        {e.by && <span style={{ color: dark.inkSubtle, fontWeight: 400 }}> · {e.by}</span>}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
