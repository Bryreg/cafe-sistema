import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { conMiles, soloDigitos } from '../utils/plata'
import {
  ArrowLeft, Camera, TrendingDown, TrendingUp, Users,
  X, ChevronRight, ChevronDown, ChevronUp, Download, UserCheck,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface TurnoItem {
  id: number
  fecha_apertura: string
  fecha_cierre: string | null
  estado: string
  tipo_turno: string | null
  total_ventas: number
  total_efectivo: number
  total_tarjeta: number
  base_real: number
  efectivo_final_real: number | null
  datafono_real: number | null
  diferencia_apertura: number
  diferencia_cierre: number | null
  diferencia_tarjeta: number | null
  baristas: string[]
  imagen_cierre_url: string | null
}

interface Movimiento {
  id: number
  tipo: string
  concepto: string
  valor: number
  fecha: string
  imagen_url: string | null
}

interface Sede { id: number; nombre: string }

interface FilaTurno {
  id: number; fecha_apertura: string; fecha_cierre: string
  usuario_apertura: string; usuario_cierre: string
  base_real: number; total_ventas: number; total_efectivo: number; total_tarjeta: number
  diferencia_cierre: number; diferencia_tarjeta: number; justificacion_cierre: string | null
}
interface TotalesTornos {
  n_turnos: number; total_ventas: number; total_efectivo: number; total_tarjeta: number; con_diferencia: number
}
interface FilaBarista {
  usuario_id: number; nombre: string
  n_recibos: number; n_cierres: number
  n_diff_efectivo: number; n_diff_tarjeta: number
  suma_diff_efectivo: number; peor_diferencia: number
  ultimo_cuadre: string | null
}
interface FilaEntrega {
  id: number; fecha_hora: string; usuario: string
  efectivo_esperado: number; efectivo_real: number; diferencia_efectivo: number
  ventas_tarjeta_bold: number; diferencia_tarjeta: number; imagen_url: string | null
}
interface TotalesEntrega { n_entregas: number; con_diferencia_efectivo: number; con_diferencia_tarjeta: number }

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`
const fmtDiff = (v: number) => `${v > 0 ? '+' : ''}${fmt(v)}`

function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}
const fmtDate = (s: string) =>
  parseUTC(s).toLocaleDateString('es-CO', { weekday: 'short', day: '2-digit', month: 'short' })
const fmtTime = (s: string) =>
  parseUTC(s).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
const fmtDateTime = (s: string) => {
  const d = parseUTC(s)
  return `${d.toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })} ${d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}`
}
// Fecha-hora local completa y ordenable (para exports Excel): YYYY-MM-DD HH:MM en hora local.
const fmtLocalDT = (s: string) => {
  const d = parseUTC(s)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
// Hora LOCAL: toISOString es UTC y despues de las 19:00 Colombia devuelve manana.
const isoLocal = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const today = () => isoLocal(new Date())
const firstOfMonth = () => {
  const d = new Date()
  return isoLocal(new Date(d.getFullYear(), d.getMonth(), 1))
}

function cleanParams(params: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''))
}

async function exportarExcel(nombre: string, cabeceras: string[], filas: (string | number | null)[][]) {
  const XLSX = await import('xlsx')
  const ws = XLSX.utils.aoa_to_sheet([cabeceras, ...filas])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Datos')
  XLSX.writeFile(wb, `${nombre}.xlsx`)
}

function BtnExcel({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
      style={{ background: 'oklch(48% 0.15 155)' }}>
      <Download size={13} /> Excel
    </button>
  )
}

// ── Diff chip (operacional) ───────────────────────────────────────────────────

function DiffChip({ v, label }: { v: number; label: string }) {
  const ok = Math.round(v) === 0
  const pos = v > 0
  return (
    <div style={{ textAlign: 'center' }}>
      <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>{label}</p>
      <p style={{
        margin: '3px 0 0', fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
        color: ok ? 'oklch(35% 0.13 145)' : pos ? 'oklch(35% 0.13 240)' : 'oklch(42% 0.18 30)',
      }}>
        {fmtDiff(v)}
      </p>
    </div>
  )
}

// ── Lightbox ──────────────────────────────────────────────────────────────────

function Lightbox({ url, onClose }: { url: string; onClose: () => void }) {
  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,.88)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <button onClick={onClose}
        style={{ position: 'absolute', top: 16, right: 16, background: 'rgba(255,255,255,.15)', border: 'none', borderRadius: 999, padding: 8, cursor: 'pointer', color: '#fff' }}>
        <X size={20} />
      </button>
      <img src={url} alt="" style={{ maxWidth: '100%', maxHeight: '90vh', borderRadius: 12, objectFit: 'contain' }} onClick={e => e.stopPropagation()} />
    </div>
  )
}

// ── Ajuste de apertura (admin) ────────────────────────────────────────────────

function AjusteApertura({ turno, onDone }: { turno: TurnoItem; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [baseReal, setBaseReal] = useState('')
  const [cajaFuerte, setCajaFuerte] = useState('')
  const [motivo, setMotivo] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const inp: React.CSSProperties = {
    fontSize: 14, padding: '8px 10px', borderRadius: 8,
    border: '1.5px solid oklch(88% 0.006 75)', background: '#fff', fontFamily: 'inherit', width: '100%',
  }

  const guardar = async () => {
    if (baseReal.trim() === '') { setError('Ingresá la base real de la registradora'); return }
    setSaving(true); setError('')
    try {
      await api.post(`/caja/${turno.id}/ajustar-apertura`, {
        base_real: Number(baseReal) || 0,
        caja_fuerte: cajaFuerte.trim() === '' ? null : Number(cajaFuerte) || 0,
        motivo: motivo || null,
      })
      onDone()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo ajustar'); setSaving(false)
    }
  }

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid oklch(90% 0.05 55)', overflow: 'hidden' }}>
      <button onClick={() => setOpen(o => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', background: 'oklch(97% 0.03 55)', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'oklch(45% 0.12 50)' }}>Ajustar apertura (admin)</span>
        <span style={{ fontSize: 11, color: 'oklch(50% 0.05 55)' }}>base actual {fmt(turno.base_real)} · {open ? 'cerrar' : 'abrir'}</span>
      </button>
      {open && (
        <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p style={{ margin: 0, fontSize: 11.5, color: 'oklch(50% 0.01 60)' }}>
            Corregí si la caja fuerte quedó dentro de la base. La base debe ser SOLO el efectivo de la registradora.
          </p>
          <label style={{ fontSize: 11, color: 'oklch(50% 0.01 60)', fontWeight: 600 }}>Efectivo real de la registradora</label>
          <input type="text" inputMode="numeric" value={conMiles(baseReal)} onChange={e => setBaseReal(soloDigitos(e.target.value))} placeholder={`Actual: ${fmt(turno.base_real)}`} style={inp} />
          <label style={{ fontSize: 11, color: 'oklch(50% 0.01 60)', fontWeight: 600 }}>Caja fuerte (reserva aparte)</label>
          <input type="text" inputMode="numeric" value={conMiles(cajaFuerte)} onChange={e => setCajaFuerte(soloDigitos(e.target.value))} placeholder="$0" style={inp} />
          <input value={motivo} onChange={e => setMotivo(e.target.value)} placeholder="Motivo (opcional)" style={inp} />
          {error && <p style={{ margin: 0, fontSize: 12, color: 'oklch(42% 0.18 30)' }}>{error}</p>}
          <button onClick={guardar} disabled={saving}
            style={{ marginTop: 4, padding: '10px', borderRadius: 10, border: 'none', background: 'oklch(48% 0.15 155)', color: '#fff', fontWeight: 700, fontSize: 13, cursor: 'pointer', opacity: saving ? 0.6 : 1, fontFamily: 'inherit' }}>
            {saving ? 'Guardando...' : 'Guardar corrección'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Turno detail view ─────────────────────────────────────────────────────────

function TurnoDetalle({ turno, onBack, onFoto, isAdmin, onAdjusted }: { turno: TurnoItem; onBack: () => void; onFoto: (url: string) => void; isAdmin: boolean; onAdjusted: () => void }) {
  const [movs, setMovs] = useState<Movimiento[]>([])
  const [loadingMovs, setLoadingMovs] = useState(true)
  const cerrado = turno.estado === 'cerrado'

  useEffect(() => {
    api.get(`/caja/${turno.id}/movimientos`)
      .then(r => setMovs(r.data ?? []))
      .catch(() => setMovs([]))
      .finally(() => setLoadingMovs(false))
  }, [turno.id])

  const ingresos = movs.filter(m => m.tipo === 'ingreso')
  const egresos  = movs.filter(m => m.tipo === 'egreso')
  const totalIngresos = ingresos.reduce((s, m) => s + m.valor, 0)
  const totalEgresos  = egresos.reduce((s, m) => s + m.valor, 0)

  return (
    <div className="min-h-screen" style={{ background: '#f5f3ef', fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif' }}>
      <div style={{ background: '#fff', borderBottom: '1px solid oklch(92% 0.008 75)', padding: '12px 16px', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, maxWidth: 600, margin: '0 auto' }}>
          <button onClick={onBack} style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(55% 0.01 60)' }}>
            <ArrowLeft size={20} />
          </button>
          <div style={{ flex: 1 }}>
            <p style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'oklch(22% 0.02 60)' }}>
              {fmtDate(turno.fecha_apertura)}
            </p>
            <p style={{ margin: 0, fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 500 }}>
              {fmtTime(turno.fecha_apertura)}
              {turno.fecha_cierre ? ` → ${fmtTime(turno.fecha_cierre)}` : ' · en curso'}
              {turno.tipo_turno && <span style={{ color: 'oklch(50% 0.12 65)' }}> · {turno.tipo_turno}</span>}
            </p>
          </div>
          <span style={{
            padding: '4px 12px', borderRadius: 999, fontSize: 10.5, fontWeight: 700,
            background: cerrado ? 'oklch(95% 0.015 155)' : 'oklch(96% 0.08 145)',
            color: cerrado ? 'oklch(40% 0.08 155)' : 'oklch(30% 0.15 145)',
          }}>
            {cerrado ? 'Cerrado' : 'Abierto'}
          </span>
        </div>
      </div>

      <div style={{ maxWidth: 600, margin: '0 auto', padding: '12px 16px 40px', display: 'flex', flexDirection: 'column', gap: 10 }}>

        {isAdmin && <AjusteApertura turno={turno} onDone={onAdjusted} />}

        {turno.baristas.length > 0 && (
          <div style={{ background: '#fff', borderRadius: 16, padding: '12px 14px', border: '1px solid oklch(92% 0.008 75)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Users size={14} style={{ color: 'oklch(50% 0.08 155)', flexShrink: 0 }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: 'oklch(28% 0.02 60)' }}>
              {turno.baristas.join(' · ')}
            </span>
          </div>
        )}

        <div style={{ background: '#fff', borderRadius: 16, padding: '14px', border: '1px solid oklch(92% 0.008 75)' }}>
          <p style={{ margin: '0 0 10px', fontSize: 10, fontWeight: 700, color: 'oklch(55% 0.01 60)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Ventas del turno</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
            {[
              { label: 'Total ventas', value: fmt(turno.total_ventas), color: 'oklch(22% 0.02 60)' },
              { label: 'Efectivo',     value: fmt(turno.total_efectivo), color: 'oklch(30% 0.13 145)' },
              { label: 'Tarjeta Bold', value: fmt(turno.total_tarjeta), color: 'oklch(30% 0.12 240)' },
            ].map(r => (
              <div key={r.label} style={{ textAlign: 'center', padding: '8px 4px', background: 'oklch(97% 0.005 75)', borderRadius: 10 }}>
                <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>{r.label}</p>
                <p style={{ margin: '3px 0 0', fontSize: 14, fontWeight: 700, color: r.color, fontVariantNumeric: 'tabular-nums' }}>{r.value}</p>
              </div>
            ))}
          </div>
          {Math.round(turno.diferencia_apertura) !== 0 && (
            <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderRadius: 8, background: 'oklch(97% 0.04 55)' }}>
              {turno.diferencia_apertura > 0
                ? <TrendingUp size={12} style={{ color: 'oklch(38% 0.12 145)', flexShrink: 0 }} />
                : <TrendingDown size={12} style={{ color: 'oklch(42% 0.18 30)', flexShrink: 0 }} />}
              <span style={{ fontSize: 11.5, color: 'oklch(38% 0.08 60)', fontWeight: 500 }}>
                Diferencia apertura: <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtDiff(turno.diferencia_apertura)}</strong>
              </span>
            </div>
          )}
        </div>

        {cerrado && (
          <div style={{ background: '#fff', borderRadius: 16, border: '1px solid oklch(92% 0.008 75)', overflow: 'hidden' }}>
            <p style={{ margin: 0, padding: '12px 14px 0', fontSize: 10, fontWeight: 700, color: 'oklch(55% 0.01 60)', letterSpacing: '.1em', textTransform: 'uppercase' }}>
              Cuadre de cierre
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 2, padding: '10px 14px 14px' }}>
              <div style={{ textAlign: 'center' }}>
                <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>Efectivo contado</p>
                <p style={{ margin: '3px 0 0', fontSize: 14, fontWeight: 700, color: 'oklch(22% 0.02 60)', fontVariantNumeric: 'tabular-nums' }}>
                  {turno.efectivo_final_real !== null ? fmt(turno.efectivo_final_real) : '—'}
                </p>
              </div>
              {turno.diferencia_cierre !== null && <DiffChip v={turno.diferencia_cierre} label="Diff. caja" />}
              {turno.datafono_real !== null && (
                <div style={{ textAlign: 'center' }}>
                  <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>Datáfono</p>
                  <p style={{ margin: '3px 0 0', fontSize: 14, fontWeight: 700, color: 'oklch(30% 0.12 240)', fontVariantNumeric: 'tabular-nums' }}>
                    {fmt(turno.datafono_real)}
                  </p>
                </div>
              )}
              {turno.diferencia_tarjeta !== null && <DiffChip v={turno.diferencia_tarjeta} label="Diff. bold" />}
            </div>
            {turno.imagen_cierre_url ? (
              <button onClick={() => onFoto(turno.imagen_cierre_url!)}
                style={{ width: '100%', padding: 0, border: 'none', cursor: 'pointer', display: 'block', borderTop: '1px solid oklch(95% 0.005 75)' }}>
                <img src={turno.imagen_cierre_url} alt="Foto cuadre de caja"
                  style={{ width: '100%', height: 160, objectFit: 'cover', display: 'block' }} />
                <p style={{ margin: 0, padding: '7px 14px', fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 500, background: 'oklch(97% 0.005 75)', textAlign: 'center' }}>
                  Tocá para ver en tamaño completo
                </p>
              </button>
            ) : (
              <div style={{ borderTop: '1px solid oklch(95% 0.005 75)', padding: '9px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Camera size={12} style={{ color: 'oklch(70% 0.01 60)' }} />
                <span style={{ fontSize: 11, color: 'oklch(65% 0.01 60)' }}>Sin foto de cuadre</span>
              </div>
            )}
          </div>
        )}

        <div style={{ background: '#fff', borderRadius: 16, border: '1px solid oklch(92% 0.008 75)', overflow: 'hidden' }}>
          <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid oklch(95% 0.005 75)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <p style={{ margin: 0, fontSize: 10, fontWeight: 700, color: 'oklch(55% 0.01 60)', letterSpacing: '.1em', textTransform: 'uppercase' }}>
              Movimientos de caja
            </p>
            {movs.length > 0 && (
              <div style={{ display: 'flex', gap: 8 }}>
                {totalIngresos > 0 && <span style={{ fontSize: 11, fontWeight: 700, color: 'oklch(35% 0.13 145)', fontVariantNumeric: 'tabular-nums' }}>+{fmt(totalIngresos)}</span>}
                {totalEgresos  > 0 && <span style={{ fontSize: 11, fontWeight: 700, color: 'oklch(42% 0.18 30)', fontVariantNumeric: 'tabular-nums' }}>−{fmt(totalEgresos)}</span>}
              </div>
            )}
          </div>
          {loadingMovs ? (
            <p style={{ margin: 0, padding: '16px 14px', fontSize: 12, color: 'oklch(60% 0.01 60)', textAlign: 'center' }}>Cargando...</p>
          ) : movs.length === 0 ? (
            <p style={{ margin: 0, padding: '16px 14px', fontSize: 12, color: 'oklch(65% 0.01 60)', textAlign: 'center' }}>Sin movimientos en este turno</p>
          ) : (
            movs.map((m, i) => (
              <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: i < movs.length - 1 ? '1px solid oklch(97% 0.005 75)' : 'none' }}>
                <span style={{ width: 28, height: 28, borderRadius: 9, flexShrink: 0, background: m.tipo === 'ingreso' ? 'oklch(94% 0.05 145)' : 'oklch(96% 0.04 30)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {m.tipo === 'ingreso'
                    ? <TrendingUp size={13} style={{ color: 'oklch(35% 0.13 145)' }} />
                    : <TrendingDown size={13} style={{ color: 'oklch(42% 0.18 30)' }} />}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'oklch(22% 0.02 60)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.concepto}</p>
                  <p style={{ margin: 0, fontSize: 10.5, color: 'oklch(60% 0.01 60)', fontWeight: 500 }}>{fmtDateTime(m.fecha)}</p>
                </div>
                {m.imagen_url && (
                  <button onClick={() => onFoto(m.imagen_url!)} style={{ padding: 0, border: 'none', cursor: 'pointer', background: 'transparent', flexShrink: 0 }}>
                    <img src={m.imagen_url} alt="" style={{ width: 36, height: 36, borderRadius: 8, objectFit: 'cover' }} />
                  </button>
                )}
                <span style={{ fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', flexShrink: 0, color: m.tipo === 'ingreso' ? 'oklch(35% 0.13 145)' : 'oklch(42% 0.18 30)' }}>
                  {m.tipo === 'ingreso' ? '+' : '−'}{fmt(m.valor)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

// ── Historial: Turnos ─────────────────────────────────────────────────────────

function HistorialTurnos({ tiendaId, desde, hasta }: { tiendaId: number; desde: string; hasta: string }) {
  const [filas, setFilas] = useState<FilaTurno[] | null>(null)
  const [totales, setTotales] = useState<TotalesTornos | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/turnos', {
        params: cleanParams({ tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta }),
      })
      setFilas(data.filas)
      setTotales(data.totales)
      setExpanded(new Set())
    } finally { setLoading(false) }
  }

  useEffect(() => { cargar() }, [tiendaId, desde, hasta])

  const toggle = (id: number) => setExpanded(prev => {
    const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s
  })

  const exportar = () => {
    if (!filas) return
    exportarExcel(`turnos_${desde}_${hasta}`,
      ['Apertura', 'Cierre', 'Abrió', 'Cerró', 'Base real', 'Total ventas', 'Efectivo', 'Tarjeta', 'Diff. cierre', 'Diff. Bold', 'Justificación'],
      filas.map(f => [fmtLocalDT(f.fecha_apertura), fmtLocalDT(f.fecha_cierre), f.usuario_apertura, f.usuario_cierre,
        f.base_real, f.total_ventas, f.total_efectivo, f.total_tarjeta,
        f.diferencia_cierre, f.diferencia_tarjeta, f.justificacion_cierre ?? '']))
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex gap-2 flex-wrap items-center justify-between">
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {totales && totales.n_turnos > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Turnos',         val: totales.n_turnos,       mono: false, color: 'text-gray-800' },
            { label: 'Ventas totales', val: fmt(totales.total_ventas), mono: true, color: 'text-gray-800' },
            { label: 'Efectivo',       val: fmt(totales.total_efectivo), mono: true, color: 'text-green-700' },
            { label: 'Con diferencia', val: totales.con_diferencia, mono: false,
              color: totales.con_diferencia > 0 ? 'text-red-700' : 'text-green-700',
              bg: totales.con_diferencia > 0 ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200' },
          ].map(c => (
            <div key={c.label} className={`border rounded-xl p-3 text-center ${(c as any).bg ?? 'bg-white border-gray-200'}`}>
              <p className="text-xs text-gray-400">{c.label}</p>
              <p className={`text-base font-bold font-mono mt-0.5 ${c.color}`}>{c.val}</p>
            </div>
          ))}
        </div>
      )}

      {filas !== null && filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {filas.map(f => (
            <div key={f.id}>
              <button onClick={() => toggle(f.id)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-left">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-400">{fmtDateTime(f.fecha_apertura)} → {fmtDateTime(f.fecha_cierre)}</p>
                  <p className="text-sm font-semibold text-gray-700 truncate">{f.usuario_apertura}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-sm font-bold text-gray-800 font-mono">{fmt(f.total_ventas)}</span>
                  {Math.round(f.diferencia_cierre) !== 0
                    ? <span className="text-xs font-bold text-red-600">Δ{fmt(Math.abs(f.diferencia_cierre))}</span>
                    : <span className="text-xs font-bold text-green-600">✓</span>}
                  {expanded.has(f.id) ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                </div>
              </button>
              {expanded.has(f.id) && (
                <div className="bg-gray-50 border-t border-gray-100 px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                  <div><span className="text-gray-400">Base real:</span> <span className="font-semibold">{fmt(f.base_real)}</span></div>
                  <div><span className="text-gray-400">Efectivo:</span> <span className="font-semibold text-green-700">{fmt(f.total_efectivo)}</span></div>
                  <div><span className="text-gray-400">Tarjeta:</span> <span className="font-semibold text-blue-700">{fmt(f.total_tarjeta)}</span></div>
                  <div><span className="text-gray-400">Diff. Bold:</span> <span className={`font-semibold ${Math.round(f.diferencia_tarjeta) !== 0 ? 'text-red-600' : 'text-green-600'}`}>{Math.round(f.diferencia_tarjeta) !== 0 ? fmtDiff(f.diferencia_tarjeta) : '✓'}</span></div>
                  <div><span className="text-gray-400">Cerró:</span> <span className="font-semibold">{f.usuario_cierre}</span></div>
                  {f.justificacion_cierre && (
                    <div className="col-span-2"><span className="text-gray-400">Justif.:</span> <span className="italic text-gray-600">{f.justificacion_cierre}</span></div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {filas !== null && filas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-8">Sin turnos cerrados en el período.</p>
      )}
    </div>
  )
}

// ── Desglose de un cuadre (expandible) ────────────────────────────────────────

interface DesgloseCuadre {
  entrega_id: number
  tipo: string
  fecha_hora: string | null
  barista: string | null
  base: number
  base_separada?: boolean
  ventas_efectivo: number
  ingresos: number
  egresos: number
  caja_fuerte: number
  efectivo_esperado: number
  efectivo_real: number
  diferencia_efectivo: number
  tiene_snapshot: boolean
  movimientos: { tipo: string; concepto: string; valor: number; fecha: string | null }[]
}

function CuadreDesglose({ entregaId }: { entregaId: number }) {
  const [d, setD] = useState<DesgloseCuadre | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.get(`/caja/entrega/${entregaId}/desglose`)
      .then(r => setD(r.data))
      .catch(() => setD(null))
      .finally(() => setLoading(false))
  }, [entregaId])

  const box: React.CSSProperties = { background: 'oklch(98% 0.004 75)', borderTop: '1px solid oklch(94% 0.006 75)', padding: '12px 16px' }
  if (loading) return <div style={box}><p style={{ margin: 0, fontSize: 12, color: 'oklch(60% 0.01 60)' }}>Cargando desglose…</p></div>
  if (!d) return <div style={box}><p style={{ margin: 0, fontSize: 12, color: 'oklch(60% 0.01 60)' }}>No se pudo cargar el desglose.</p></div>

  const salidas = d.movimientos.filter(m => m.tipo === 'egreso')
  const line = (label: string, value: string, color = 'oklch(28% 0.02 60)', bold = false) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0' }}>
      <span style={{ fontSize: 12.5, color: bold ? 'oklch(22% 0.02 60)' : 'oklch(45% 0.01 60)', fontWeight: bold ? 700 : 500 }}>{label}</span>
      <span style={{ fontSize: bold ? 15 : 13, fontWeight: bold ? 700 : 600, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )

  return (
    <div style={box}>
      <p style={{ margin: '0 0 6px', fontSize: 10, fontWeight: 700, color: 'oklch(55% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>
        Desglose al momento del cuadre{d.fecha_hora ? ` · ${fmtTime(d.fecha_hora)}` : ''}
      </p>
      {d.base_separada ? (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 8px', margin: '2px 0', borderRadius: 8, background: 'oklch(95% 0.045 70)' }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'oklch(48% 0.12 65)' }}>
            Venta de ayer separada — guardada sin contar
          </span>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: 'oklch(48% 0.12 65)', fontVariantNumeric: 'tabular-nums', textDecoration: 'line-through' }}>{fmt(d.base)}</span>
        </div>
      ) : (
        line('Con lo que empezó (base)', fmt(d.base))
      )}
      {line('+ Ventas en efectivo', fmt(d.ventas_efectivo), 'oklch(35% 0.13 145)')}
      {d.ingresos > 0 && line('+ Otros ingresos', fmt(d.ingresos), 'oklch(35% 0.13 145)')}
      {line('− Salidas de efectivo', `−${fmt(d.egresos)}`, 'oklch(42% 0.18 30)')}
      {salidas.length > 0 && (
        <div style={{ margin: '2px 0 4px', paddingLeft: 12, borderLeft: '2px solid oklch(92% 0.008 75)' }}>
          {salidas.map((m, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '2px 0' }}>
              <span style={{ fontSize: 11.5, color: 'oklch(55% 0.01 60)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {m.concepto}{m.fecha ? ` · ${fmtTime(m.fecha)}` : ''}
              </span>
              <span style={{ fontSize: 11.5, color: 'oklch(42% 0.18 30)', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>−{fmt(m.valor)}</span>
            </div>
          ))}
        </div>
      )}
      <div style={{ borderTop: '1px solid oklch(92% 0.008 75)', marginTop: 4, paddingTop: 4 }}>
        {line(d.base_separada ? '= A contar en la registradora' : '= Debería haber en caja', fmt(d.efectivo_esperado), 'oklch(22% 0.02 60)', true)}
      </div>
      {line('Contó la barista', fmt(d.efectivo_real))}
      {line('Diferencia',
        Math.round(d.diferencia_efectivo) === 0 ? '✓ cuadra' : fmtDiff(d.diferencia_efectivo),
        Math.round(d.diferencia_efectivo) === 0 ? 'oklch(35% 0.13 145)' : 'oklch(42% 0.18 30)', true)}
      {d.caja_fuerte > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6, paddingTop: 6, borderTop: '1px dashed oklch(92% 0.008 75)' }}>
          <span style={{ fontSize: 11.5, color: 'oklch(55% 0.01 60)' }}>Caja fuerte (aparte, no cuenta)</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'oklch(45% 0.01 60)', fontVariantNumeric: 'tabular-nums' }}>{fmt(d.caja_fuerte)}</span>
        </div>
      )}
      {!d.tiene_snapshot && (
        <p style={{ margin: '6px 0 0', fontSize: 10.5, color: 'oklch(60% 0.01 60)', fontStyle: 'italic' }}>
          Cuadre previo a esta función — desglose reconstruido, puede no ser exacto.
        </p>
      )}
    </div>
  )
}

// ── Historial: Baristas ───────────────────────────────────────────────────────

function HistorialBaristas({ tiendaId, desde, hasta }: { tiendaId: number; desde: string; hasta: string }) {
  const [cuadresFilas, setCuadresFilas]     = useState<FilaEntrega[] | null>(null)
  const [cuadresTotales, setCuadresTotales] = useState<TotalesEntrega | null>(null)
  const [baristasFilas, setBaristasFilas]   = useState<FilaBarista[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [expandido, setExpandido] = useState<number | null>(null)

  const cargar = async () => {
    setLoading(true)
    try {
      const params = cleanParams({ tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta })
      const [entRes, barRes] = await Promise.all([
        api.get('/informes/entregas', { params }),
        api.get('/informes/baristas', { params }),
      ])
      setCuadresFilas(entRes.data.filas)
      setCuadresTotales(entRes.data.totales)
      setBaristasFilas(barRes.data.filas)
    } finally { setLoading(false) }
  }

  useEffect(() => { cargar() }, [tiendaId, desde, hasta])

  const exportar = () => {
    if (!cuadresFilas) return
    exportarExcel(`cuadres_${desde}_${hasta}`,
      ['Fecha/Hora', 'Barista', 'Efectivo esperado', 'Efectivo real', 'Diferencia efectivo', 'Total Bold', 'Diferencia Bold'],
      cuadresFilas.map(f => [fmtLocalDT(f.fecha_hora), f.usuario, f.efectivo_esperado, f.efectivo_real, f.diferencia_efectivo, f.ventas_tarjeta_bold, f.diferencia_tarjeta]))
  }

  const totalCuadres = (f: FilaBarista) => f.n_recibos + f.n_cierres
  const pctDiff = (f: FilaBarista) => totalCuadres(f) > 0 ? Math.round((f.n_diff_efectivo / totalCuadres(f)) * 100) : 0

  return (
    <div className="space-y-4 p-4">
      <div className="flex gap-2 flex-wrap items-center justify-between">
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {cuadresFilas && cuadresFilas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {baristasFilas !== null && baristasFilas.length > 0 && (
        <>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Desempeño por barista</p>
          <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
            {baristasFilas.map((f, i) => (
              <div key={f.usuario_id} className="px-4 py-3 flex items-center gap-3">
                <span className="text-sm font-mono text-gray-300 w-5 shrink-0">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-800">{f.nombre}</p>
                  <p className="text-xs text-gray-400">
                    {f.n_recibos} llegadas · {f.n_cierres} cierres
                    {f.ultimo_cuadre && <span> · último {fmtDateTime(f.ultimo_cuadre)}</span>}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  {f.n_diff_efectivo === 0 ? (
                    <span className="text-xs font-bold text-green-600 bg-green-50 px-2 py-0.5 rounded-full">Sin diferencias</span>
                  ) : (
                    <>
                      <span className="text-xs font-bold text-red-600 bg-red-50 px-2 py-0.5 rounded-full">
                        {f.n_diff_efectivo} diff · {pctDiff(f)}%
                      </span>
                      <span className="text-xs text-gray-500">
                        Σ {fmt(f.suma_diff_efectivo)} · peor {fmt(f.peor_diferencia)}
                      </span>
                    </>
                  )}
                  {f.n_diff_tarjeta > 0 && (
                    <span className="text-xs text-blue-500">{f.n_diff_tarjeta} diff Bold</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {cuadresTotales && (
        <>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mt-2">Cuadres de llegada</p>
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
              <p className="text-xs text-gray-400">Total cuadres</p>
              <p className="text-lg font-bold text-gray-800">{cuadresTotales.n_entregas}</p>
            </div>
            <div className={`border rounded-xl p-3 text-center ${cuadresTotales.con_diferencia_efectivo > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
              <p className="text-xs text-gray-400">Diff. efectivo</p>
              <p className={`text-lg font-bold ${cuadresTotales.con_diferencia_efectivo > 0 ? 'text-red-700' : 'text-green-700'}`}>{cuadresTotales.con_diferencia_efectivo}</p>
            </div>
            <div className={`border rounded-xl p-3 text-center ${cuadresTotales.con_diferencia_tarjeta > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
              <p className="text-xs text-gray-400">Diff. Bold</p>
              <p className={`text-lg font-bold ${cuadresTotales.con_diferencia_tarjeta > 0 ? 'text-red-700' : 'text-green-700'}`}>{cuadresTotales.con_diferencia_tarjeta}</p>
            </div>
          </div>
        </>
      )}

      {cuadresFilas !== null && cuadresFilas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="divide-y divide-gray-50">
            {cuadresFilas.map(f => (
              <div key={f.id}>
                <div onClick={() => setExpandido(expandido === f.id ? null : f.id)}
                  className="px-4 py-3 flex items-start justify-between gap-3 cursor-pointer hover:bg-gray-50">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-400">{fmtDateTime(f.fecha_hora)}</p>
                    <p className="text-sm font-semibold text-gray-700">{f.usuario}</p>
                    <p className="text-xs text-gray-500">
                      Real: <span className="font-semibold text-gray-800">{fmt(f.efectivo_real)}</span>
                      {' · '}esp: {fmt(f.efectivo_esperado)}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${Math.round(f.diferencia_efectivo) === 0 ? 'text-green-700 bg-green-50' : 'text-red-700 bg-red-50'}`}>
                      {Math.round(f.diferencia_efectivo) === 0 ? '✓' : fmtDiff(f.diferencia_efectivo)}
                    </span>
                    {Math.round(f.diferencia_tarjeta) !== 0 && (
                      <span className="text-xs text-red-600 font-semibold">Bold Δ{fmtDiff(f.diferencia_tarjeta)}</span>
                    )}
                    {f.imagen_url && (
                      <a href={f.imagen_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
                        className="text-xs text-blue-500 hover:underline">foto</a>
                    )}
                    <span className="text-[10px] text-gray-400">{expandido === f.id ? 'ocultar ▲' : 'ver desglose ▼'}</span>
                  </div>
                </div>
                {expandido === f.id && <CuadreDesglose entregaId={f.id} />}
              </div>
            ))}
          </div>
        </div>
      )}

      {cuadresFilas !== null && cuadresFilas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-8">Sin cuadres en el período.</p>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

// ── Timeline de un turno (expandible) + resumen de baristas ──────────────────

interface TimelineEvento {
  tipo: string; subtipo?: string; titulo: string; fecha: string | null
  barista: string | null; detalle: string | null; monto: number | null
  esperado?: number; contado?: number; diferencia?: number
  base_separada?: boolean; imagen_url?: string | null; entrega_id?: number
}
interface ResumenBarista {
  barista: string; entro: string | null; salio: string | null; diferencia_cuadre: number | null
}

const EVENTO_ICON: Record<string, { dot: string; ring: string }> = {
  apertura_turno: { dot: 'oklch(48% 0.15 155)', ring: 'oklch(94% 0.04 155)' },
  barista_entra:  { dot: 'oklch(50% 0.13 145)', ring: 'oklch(95% 0.04 145)' },
  barista_sale:   { dot: 'oklch(60% 0.05 60)',  ring: 'oklch(95% 0.008 75)' },
  cuadre:         { dot: 'oklch(52% 0.14 50)',  ring: 'oklch(96% 0.04 55)' },
  cierre_turno:   { dot: 'oklch(42% 0.18 30)',  ring: 'oklch(96% 0.04 30)' },
}

function TurnoTimelineCard({ turno, onFoto, onDetalle, esDiaAnterior, onCerrarPendiente }: {
  turno: TurnoItem; onFoto: (url: string) => void; onDetalle: () => void
  esDiaAnterior: (iso: string) => boolean; onCerrarPendiente: () => void
}) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<{ eventos: TimelineEvento[]; resumen_baristas: ResumenBarista[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const cerrado = turno.estado === 'cerrado'
  const diffCierre = turno.diferencia_cierre
  const hayDiff = diffCierre !== null && Math.round(diffCierre) !== 0

  useEffect(() => {
    if (!open || data) return
    setLoading(true)
    api.get(`/caja/turno/${turno.id}/timeline`)
      .then(r => setData(r.data))
      .catch(() => setData({ eventos: [], resumen_baristas: [] }))
      .finally(() => setLoading(false))
  }, [open]) // eslint-disable-line

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid oklch(92% 0.008 75)', boxShadow: '0 1px 3px rgba(0,0,0,.04)', overflow: 'hidden' }}>
      {/* Cabecera: apertura, quién y base */}
      <button onClick={() => setOpen(o => !o)}
        style={{ width: '100%', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left', padding: '12px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ margin: 0, fontSize: 13.5, fontWeight: 700, color: 'oklch(22% 0.02 60)' }}>{fmtDate(turno.fecha_apertura)}</p>
            <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 500 }}>
              Abrió {fmtTime(turno.fecha_apertura)}{turno.fecha_cierre ? ` → cerró ${fmtTime(turno.fecha_cierre)}` : ' · en curso'}
              {turno.tipo_turno && <span style={{ color: 'oklch(50% 0.12 65)' }}> · {turno.tipo_turno}</span>}
            </p>
          </div>
          {open ? <ChevronUp size={16} style={{ color: 'oklch(60% 0.01 60)', flexShrink: 0, marginTop: 2 }} />
                : <ChevronDown size={16} style={{ color: 'oklch(60% 0.01 60)', flexShrink: 0, marginTop: 2 }} />}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'oklch(45% 0.01 60)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <UserCheck size={12} style={{ color: 'oklch(50% 0.08 155)' }} /> Abrió con base <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{fmt(turno.base_real)}</strong>
          </span>
          {turno.baristas.length > 0 && (
            <span style={{ fontSize: 11, color: 'oklch(45% 0.01 60)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <Users size={12} style={{ color: 'oklch(60% 0.01 60)' }} /> {turno.baristas.join(' · ')}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.02 60)', fontVariantNumeric: 'tabular-nums' }}>{fmt(turno.total_ventas)}</span>
            {cerrado && diffCierre !== null && (
              <span style={{ fontSize: 11.5, fontWeight: 700, fontVariantNumeric: 'tabular-nums', padding: '1px 8px', borderRadius: 999,
                color: !hayDiff ? 'oklch(35% 0.13 145)' : diffCierre > 0 ? 'oklch(35% 0.13 240)' : 'oklch(42% 0.18 30)',
                background: !hayDiff ? 'oklch(95% 0.04 145)' : diffCierre > 0 ? 'oklch(95% 0.04 240)' : 'oklch(96% 0.04 30)' }}>{fmtDiff(diffCierre)}</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {turno.imagen_cierre_url && <Camera size={12} style={{ color: 'oklch(55% 0.08 155)' }} />}
            {!cerrado && esDiaAnterior(turno.fecha_apertura) && (
              <span role="button" onClick={e => { e.stopPropagation(); onCerrarPendiente() }}
                style={{ padding: '3px 10px', borderRadius: 999, fontSize: 10, fontWeight: 800, background: 'oklch(54% 0.18 25)', color: '#fff', cursor: 'pointer' }}>
                Cerrar turno pendiente
              </span>
            )}
            <span style={{ padding: '2px 9px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: cerrado ? 'oklch(95% 0.015 155)' : 'oklch(96% 0.08 145)', color: cerrado ? 'oklch(40% 0.08 155)' : 'oklch(30% 0.15 145)' }}>
              {cerrado ? 'Cerrado' : 'Abierto'}
            </span>
          </div>
        </div>
      </button>

      {/* Desplegado: timeline + resumen */}
      {open && (
        <div style={{ borderTop: '1px solid oklch(95% 0.005 75)', background: 'oklch(98% 0.004 75)', padding: '12px 14px' }}>
          {loading ? (
            <p style={{ fontSize: 12, color: 'oklch(60% 0.01 60)', textAlign: 'center', padding: '12px 0' }}>Cargando…</p>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.6fr) minmax(0,1fr)', gap: 14 }}
              className="cuadre-timeline-grid">
              {/* Timeline */}
              <div>
                <p style={{ margin: '0 0 8px', fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: 'oklch(55% 0.01 60)' }}>Línea de tiempo</p>
                <div style={{ position: 'relative', paddingLeft: 18 }}>
                  <div style={{ position: 'absolute', left: 5, top: 4, bottom: 4, width: 2, background: 'oklch(92% 0.008 75)' }} />
                  {(data?.eventos ?? []).map((e, i) => {
                    const ic = EVENTO_ICON[e.tipo] ?? EVENTO_ICON.barista_entra
                    const esCuadre = e.tipo === 'cuadre'
                    const dif = e.diferencia ?? 0
                    return (
                      <div key={i} style={{ position: 'relative', paddingBottom: 12 }}>
                        <span style={{ position: 'absolute', left: -18, top: 2, width: 12, height: 12, borderRadius: 999, background: ic.dot, boxShadow: `0 0 0 3px ${ic.ring}` }} />
                        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                          <p style={{ margin: 0, fontSize: 12.5, fontWeight: 600, color: 'oklch(28% 0.02 60)' }}>{e.titulo}</p>
                          <span style={{ fontSize: 10.5, color: 'oklch(62% 0.01 60)', flexShrink: 0 }}>{e.fecha ? fmtTime(e.fecha) : ''}</span>
                        </div>
                        {e.barista && !esCuadre && (
                          <p style={{ margin: '1px 0 0', fontSize: 11, color: 'oklch(55% 0.01 60)' }}>{e.barista}</p>
                        )}
                        {e.detalle && !esCuadre && (
                          <p style={{ margin: '1px 0 0', fontSize: 11, color: 'oklch(50% 0.01 60)' }}>{e.detalle}</p>
                        )}
                        {esCuadre && (
                          <div style={{ marginTop: 4, background: '#fff', border: '1px solid oklch(93% 0.008 75)', borderRadius: 10, padding: '7px 10px' }}>
                            {e.barista && <p style={{ margin: '0 0 4px', fontSize: 11, color: 'oklch(50% 0.01 60)', fontWeight: 600 }}>{e.barista}{e.base_separada ? ' · venta de ayer separada' : ''}</p>}
                            <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
                              <span style={{ fontSize: 11, color: 'oklch(55% 0.01 60)' }}>Debía: <strong style={{ fontVariantNumeric: 'tabular-nums', color: 'oklch(30% 0.02 60)' }}>{fmt(e.esperado ?? 0)}</strong></span>
                              <span style={{ fontSize: 11, color: 'oklch(55% 0.01 60)' }}>Contó: <strong style={{ fontVariantNumeric: 'tabular-nums', color: 'oklch(30% 0.02 60)' }}>{fmt(e.contado ?? 0)}</strong></span>
                              <span style={{ fontSize: 11, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                                color: Math.round(dif) === 0 ? 'oklch(35% 0.13 145)' : dif > 0 ? 'oklch(35% 0.13 240)' : 'oklch(42% 0.18 30)' }}>
                                {Math.round(dif) === 0 ? '✓ cuadró' : fmtDiff(dif)}
                              </span>
                            </div>
                            {e.imagen_url && (
                              <button onClick={() => onFoto(e.imagen_url!)}
                                style={{ marginTop: 5, fontSize: 10.5, color: 'oklch(45% 0.12 240)', background: 'transparent', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', gap: 4 }}>
                                <Camera size={11} /> Ver foto del cuadre
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                  {(data?.eventos ?? []).length === 0 && (
                    <p style={{ fontSize: 11.5, color: 'oklch(60% 0.01 60)' }}>Sin eventos registrados.</p>
                  )}
                </div>
              </div>

              {/* Resumen de baristas */}
              <div>
                <p style={{ margin: '0 0 8px', fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: 'oklch(55% 0.01 60)' }}>Baristas del turno</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(data?.resumen_baristas ?? []).map((b, i) => (
                    <div key={i} style={{ background: '#fff', border: '1px solid oklch(93% 0.008 75)', borderRadius: 10, padding: '8px 10px' }}>
                      <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: 'oklch(28% 0.02 60)' }}>{b.barista}</p>
                      <p style={{ margin: '2px 0 0', fontSize: 10.5, color: 'oklch(55% 0.01 60)' }}>
                        {b.entro ? `Entró ${fmtTime(b.entro)}` : '—'}{b.salio ? ` · Salió ${fmtTime(b.salio)}` : ' · en turno'}
                      </p>
                      {b.diferencia_cuadre !== null && (
                        <p style={{ margin: '3px 0 0', fontSize: 10.5, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                          color: Math.round(b.diferencia_cuadre) === 0 ? 'oklch(35% 0.13 145)' : b.diferencia_cuadre > 0 ? 'oklch(35% 0.13 240)' : 'oklch(42% 0.18 30)' }}>
                          Cuadre: {Math.round(b.diferencia_cuadre) === 0 ? '✓ exacto' : fmtDiff(b.diferencia_cuadre)}
                        </p>
                      )}
                    </div>
                  ))}
                  {(data?.resumen_baristas ?? []).length === 0 && (
                    <p style={{ fontSize: 11.5, color: 'oklch(60% 0.01 60)' }}>Sin baristas registradas.</p>
                  )}
                </div>
                <button onClick={onDetalle}
                  style={{ marginTop: 10, width: '100%', fontSize: 11.5, fontWeight: 700, color: 'oklch(40% 0.08 155)', background: 'oklch(96% 0.02 155)', border: '1px solid oklch(90% 0.03 155)', borderRadius: 10, padding: '7px 0', cursor: 'pointer', fontFamily: 'inherit' }}>
                  Ver detalle completo →
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function CuadreTurnos() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.rol === 'admin'
  const tiendaId = user?.tienda_id ?? 1

  // Operacional
  const [turnos, setTurnos]   = useState<TurnoItem[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<TurnoItem | null>(null)
  const [fotoUrl, setFotoUrl] = useState<string | null>(null)
  const [filtroOp, setFiltroOp] = useState<'todos' | 'cerrados' | 'abiertos'>('todos')

  // Mode
  const [modo, setModo] = useState<'operacional' | 'historial'>('operacional')

  // Historial
  const [sedes, setSedes] = useState<Sede[]>([])
  const [histTiendaId, setHistTiendaId] = useState<number>(tiendaId)
  const [histTab, setHistTab] = useState<'turnos' | 'baristas'>('turnos')
  const [desde, setDesde] = useState(firstOfMonth)
  const [hasta, setHasta]  = useState(today)

  // La sede activa (histTiendaId) gobierna AMBAS vistas: antes Operacional cargaba
  // fijo la sede del admin y Palmetto solo se veía en Historial.
  useEffect(() => {
    setLoading(true)
    api.get(`/caja/historial/${histTiendaId}`)
      .then(r => setTurnos(r.data))
      .catch(() => null)
      .finally(() => setLoading(false))
  }, [histTiendaId])

  useEffect(() => {
    if (isAdmin) {
      api.get('/auth/tiendas').then(({ data }) => {
        setSedes(data)
        if (data.length > 0) setHistTiendaId(data[0].id)
      }).catch(() => {})
    }
  }, [isAdmin])

  // Turno abierto de un día anterior = huérfano (quedó sin cuadre de salida).
  const esDiaAnterior = (iso: string) => {
    const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
    const d = new Date(s.endsWith('Z') ? s : s + 'Z')
    const h = new Date()
    return d.getFullYear() < h.getFullYear() ||
      (d.getFullYear() === h.getFullYear() && (d.getMonth() < h.getMonth() ||
        (d.getMonth() === h.getMonth() && d.getDate() < h.getDate())))
  }
  const cerrarPendiente = async (t: TurnoItem) => {
    if (!window.confirm(`¿Cerrar el turno del ${fmtDate(t.fecha_apertura)} con el esperado (diferencia 0)? La diferencia real la captura el cuadre inicial siguiente.`)) return
    try {
      await api.post(`/caja/${t.id}/cerrar-administrativo`)
      api.get(`/caja/historial/${histTiendaId}`).then(r => setTurnos(r.data)).catch(() => null)
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo cerrar')
    }
  }

  const visibles = turnos.filter(t =>
    filtroOp === 'todos' ? true :
    filtroOp === 'cerrados' ? t.estado === 'cerrado' :
    t.estado === 'abierto'
  )

  // Detail view (takes over full screen)
  if (selected) {
    return (
      <>
        <TurnoDetalle turno={selected} onBack={() => setSelected(null)} onFoto={setFotoUrl}
          isAdmin={isAdmin}
          onAdjusted={() => {
            setSelected(null)
            api.get(`/caja/historial/${histTiendaId}`).then(r => setTurnos(r.data)).catch(() => null)
          }} />
        {fotoUrl && <Lightbox url={fotoUrl} onClose={() => setFotoUrl(null)} />}
      </>
    )
  }

  const btnBase: React.CSSProperties = {
    padding: '5px 18px', borderRadius: 999, border: 'none', cursor: 'pointer',
    fontSize: 12, fontWeight: 700, fontFamily: 'inherit', transition: 'all .15s',
  }
  const btnActive: React.CSSProperties = { ...btnBase, background: 'oklch(30% 0.06 155)', color: '#fff' }
  const btnInactive: React.CSSProperties = { ...btnBase, background: 'oklch(94% 0.005 75)', color: 'oklch(50% 0.01 60)' }

  return (
    <div className="min-h-screen" style={{ background: '#f5f3ef', fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif' }}>

      {/* Header */}
      <div style={{ background: '#fff', borderBottom: '1px solid oklch(92% 0.008 75)', padding: '12px 16px', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, maxWidth: 720, margin: '0 auto' }}>
          <button onClick={() => navigate(-1)} style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(55% 0.01 60)' }}>
            <ArrowLeft size={20} />
          </button>
          <p style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'oklch(22% 0.02 60)', flex: 1 }}>Cuadres de turno</p>
        </div>

        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 6, marginTop: 10, maxWidth: 720, margin: '10px auto 0' }}>
          <button onClick={() => setModo('operacional')} style={modo === 'operacional' ? btnActive : btnInactive}>
            Operacional
          </button>
          <button onClick={() => setModo('historial')} style={modo === 'historial' ? btnActive : btnInactive}>
            Historial
          </button>
        </div>

        {/* Sede selector (admin) — gobierna las DOS vistas */}
        {isAdmin && sedes.length > 1 && (
          <div style={{ display: 'flex', gap: 6, marginTop: 8, maxWidth: 720, margin: '8px auto 0', flexWrap: 'wrap' }}>
            {sedes.map(s => (
              <button key={s.id} onClick={() => setHistTiendaId(s.id)}
                style={histTiendaId === s.id
                  ? { ...btnBase, background: 'oklch(52% 0.14 50)', color: '#fff', padding: '4px 12px', fontSize: 11 }
                  : { ...btnBase, background: 'oklch(96% 0.005 75)', color: 'oklch(50% 0.01 60)', padding: '4px 12px', fontSize: 11 }}>
                {s.nombre}
              </button>
            ))}
          </div>
        )}

        {/* Operacional sub-filter */}
        {modo === 'operacional' && (
          <div style={{ display: 'flex', gap: 6, marginTop: 8, maxWidth: 720, margin: '8px auto 0' }}>
            {(['todos', 'cerrados', 'abiertos'] as const).map(f => (
              <button key={f} onClick={() => setFiltroOp(f)}
                style={filtroOp === f
                  ? { ...btnBase, background: 'oklch(50% 0.08 155)', color: '#fff', padding: '4px 12px', fontSize: 11 }
                  : { ...btnBase, background: 'oklch(96% 0.005 75)', color: 'oklch(50% 0.01 60)', padding: '4px 12px', fontSize: 11 }}>
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        )}

        {/* Historial controls */}
        {modo === 'historial' && (
          <div style={{ maxWidth: 720, margin: '8px auto 0', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {/* Date range */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <label style={{ fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 600 }}>Desde</label>
              <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
                style={{ fontSize: 12, padding: '4px 8px', borderRadius: 8, border: '1.5px solid oklch(88% 0.006 75)', background: '#fff', fontFamily: 'inherit' }} />
              <label style={{ fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 600 }}>Hasta</label>
              <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
                style={{ fontSize: 12, padding: '4px 8px', borderRadius: 8, border: '1.5px solid oklch(88% 0.006 75)', background: '#fff', fontFamily: 'inherit' }} />
            </div>

            {/* Sub-tabs */}
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => setHistTab('turnos')}
                style={histTab === 'turnos'
                  ? { ...btnBase, background: 'oklch(30% 0.06 155)', color: '#fff', padding: '4px 14px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }
                  : { ...btnBase, background: 'oklch(96% 0.005 75)', color: 'oklch(50% 0.01 60)', padding: '4px 14px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }}>
                <ChevronRight size={12} /> Turnos
              </button>
              <button onClick={() => setHistTab('baristas')}
                style={histTab === 'baristas'
                  ? { ...btnBase, background: 'oklch(30% 0.06 155)', color: '#fff', padding: '4px 14px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }
                  : { ...btnBase, background: 'oklch(96% 0.005 75)', color: 'oklch(50% 0.01 60)', padding: '4px 14px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }}>
                <UserCheck size={12} /> Baristas
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Content */}
      {modo === 'operacional' ? (
        <div style={{ maxWidth: 720, margin: '0 auto', padding: '12px 16px 32px' }}>
          {loading ? (
            <p style={{ textAlign: 'center', color: 'oklch(60% 0.01 60)', fontSize: 13, marginTop: 40 }}>Cargando...</p>
          ) : visibles.length === 0 ? (
            <p style={{ textAlign: 'center', color: 'oklch(60% 0.01 60)', fontSize: 13, marginTop: 40 }}>Sin turnos registrados</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {visibles.map(t => (
                <TurnoTimelineCard key={t.id} turno={t} onFoto={setFotoUrl}
                  onDetalle={() => setSelected(t)}
                  esDiaAnterior={esDiaAnterior}
                  onCerrarPendiente={() => cerrarPendiente(t)} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          {histTab === 'turnos'
            ? <HistorialTurnos   tiendaId={histTiendaId} desde={desde} hasta={hasta} />
            : <HistorialBaristas tiendaId={histTiendaId} desde={desde} hasta={hasta} />}
        </div>
      )}

      {fotoUrl && <Lightbox url={fotoUrl} onClose={() => setFotoUrl(null)} />}
    </div>
  )
}
