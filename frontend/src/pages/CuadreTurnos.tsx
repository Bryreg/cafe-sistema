import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Camera, TrendingDown, TrendingUp, Users,
  X, ChevronRight,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'

// ── Types ────────────────────────────────────────────────────────────────────

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

// ── Helpers ──────────────────────────────────────────────────────────────────

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

// ── Diff chip ─────────────────────────────────────────────────────────────────

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

// ── Detail view ───────────────────────────────────────────────────────────────

function TurnoDetalle({
  turno, onBack, onFoto,
}: {
  turno: TurnoItem
  onBack: () => void
  onFoto: (url: string) => void
}) {
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

      {/* Header */}
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

        {/* Baristas */}
        {turno.baristas.length > 0 && (
          <div style={{ background: '#fff', borderRadius: 16, padding: '12px 14px', border: '1px solid oklch(92% 0.008 75)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Users size={14} style={{ color: 'oklch(50% 0.08 155)', flexShrink: 0 }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: 'oklch(28% 0.02 60)' }}>
              {turno.baristas.join(' · ')}
            </span>
          </div>
        )}

        {/* Ventas */}
        <div style={{ background: '#fff', borderRadius: 16, padding: '14px', border: '1px solid oklch(92% 0.008 75)' }}>
          <p style={{ margin: '0 0 10px', fontSize: 10, fontWeight: 700, color: 'oklch(55% 0.01 60)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Ventas del turno</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
            {[
              { label: 'Total ventas', value: fmt(turno.total_ventas), color: 'oklch(22% 0.02 60)' },
              { label: 'Efectivo', value: fmt(turno.total_efectivo), color: 'oklch(30% 0.13 145)' },
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

        {/* Cuadre de cierre */}
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

            {/* Foto */}
            {turno.imagen_cierre_url ? (
              <button
                onClick={() => onFoto(turno.imagen_cierre_url!)}
                style={{ width: '100%', padding: 0, border: 'none', cursor: 'pointer', display: 'block', borderTop: '1px solid oklch(95% 0.005 75)' }}
              >
                <img
                  src={turno.imagen_cierre_url}
                  alt="Foto cuadre de caja"
                  style={{ width: '100%', height: 160, objectFit: 'cover', display: 'block' }}
                />
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

        {/* Movimientos */}
        <div style={{ background: '#fff', borderRadius: 16, border: '1px solid oklch(92% 0.008 75)', overflow: 'hidden' }}>
          <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid oklch(95% 0.005 75)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <p style={{ margin: 0, fontSize: 10, fontWeight: 700, color: 'oklch(55% 0.01 60)', letterSpacing: '.1em', textTransform: 'uppercase' }}>
              Movimientos de caja
            </p>
            {movs.length > 0 && (
              <div style={{ display: 'flex', gap: 8 }}>
                {totalIngresos > 0 && (
                  <span style={{ fontSize: 11, fontWeight: 700, color: 'oklch(35% 0.13 145)', fontVariantNumeric: 'tabular-nums' }}>
                    +{fmt(totalIngresos)}
                  </span>
                )}
                {totalEgresos > 0 && (
                  <span style={{ fontSize: 11, fontWeight: 700, color: 'oklch(42% 0.18 30)', fontVariantNumeric: 'tabular-nums' }}>
                    −{fmt(totalEgresos)}
                  </span>
                )}
              </div>
            )}
          </div>

          {loadingMovs ? (
            <p style={{ margin: 0, padding: '16px 14px', fontSize: 12, color: 'oklch(60% 0.01 60)', textAlign: 'center' }}>Cargando...</p>
          ) : movs.length === 0 ? (
            <p style={{ margin: 0, padding: '16px 14px', fontSize: 12, color: 'oklch(65% 0.01 60)', textAlign: 'center' }}>Sin movimientos en este turno</p>
          ) : (
            movs.map((m, i) => (
              <div key={m.id} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
                borderBottom: i < movs.length - 1 ? '1px solid oklch(97% 0.005 75)' : 'none',
              }}>
                <span style={{
                  width: 28, height: 28, borderRadius: 9, flexShrink: 0,
                  background: m.tipo === 'ingreso' ? 'oklch(94% 0.05 145)' : 'oklch(96% 0.04 30)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {m.tipo === 'ingreso'
                    ? <TrendingUp size={13} style={{ color: 'oklch(35% 0.13 145)' }} />
                    : <TrendingDown size={13} style={{ color: 'oklch(42% 0.18 30)' }} />}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'oklch(22% 0.02 60)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {m.concepto}
                  </p>
                  <p style={{ margin: 0, fontSize: 10.5, color: 'oklch(60% 0.01 60)', fontWeight: 500 }}>
                    {fmtDateTime(m.fecha)}
                  </p>
                </div>
                {m.imagen_url && (
                  <button onClick={() => onFoto(m.imagen_url!)} style={{ padding: 0, border: 'none', cursor: 'pointer', background: 'transparent', flexShrink: 0 }}>
                    <img src={m.imagen_url} alt="" style={{ width: 36, height: 36, borderRadius: 8, objectFit: 'cover' }} />
                  </button>
                )}
                <span style={{
                  fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', flexShrink: 0,
                  color: m.tipo === 'ingreso' ? 'oklch(35% 0.13 145)' : 'oklch(42% 0.18 30)',
                }}>
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

// ── Main list ─────────────────────────────────────────────────────────────────

export default function CuadreTurnos() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const tiendaId = user?.tienda_id ?? 1

  const [turnos, setTurnos] = useState<TurnoItem[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<TurnoItem | null>(null)
  const [fotoUrl, setFotoUrl] = useState<string | null>(null)
  const [filtro, setFiltro] = useState<'todos' | 'cerrados' | 'abiertos'>('todos')

  useEffect(() => {
    api.get(`/caja/historial/${tiendaId}`)
      .then(r => setTurnos(r.data))
      .catch(() => null)
      .finally(() => setLoading(false))
  }, [tiendaId])

  const visibles = turnos.filter(t =>
    filtro === 'todos' ? true :
    filtro === 'cerrados' ? t.estado === 'cerrado' :
    t.estado === 'abierto'
  )

  // ── Detail view ──────────────────────────────────────────────────────────
  if (selected) {
    return (
      <>
        <TurnoDetalle
          turno={selected}
          onBack={() => setSelected(null)}
          onFoto={setFotoUrl}
        />
        {fotoUrl && <Lightbox url={fotoUrl} onClose={() => setFotoUrl(null)} />}
      </>
    )
  }

  // ── List view ─────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen" style={{ background: '#f5f3ef', fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif' }}>

      {/* Header */}
      <div style={{ background: '#fff', borderBottom: '1px solid oklch(92% 0.008 75)', padding: '12px 16px', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, maxWidth: 600, margin: '0 auto' }}>
          <button onClick={() => navigate(-1)} style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(55% 0.01 60)' }}>
            <ArrowLeft size={20} />
          </button>
          <div style={{ flex: 1 }}>
            <p style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'oklch(22% 0.02 60)' }}>Turnos y cuadres</p>
            <p style={{ margin: 0, fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 500 }}>
              {turnos.length > 0 ? `${turnos.length} turnos · tocá uno para ver el detalle` : 'Historial de turnos'}
            </p>
          </div>
        </div>

        {/* Filtro */}
        <div style={{ display: 'flex', gap: 6, marginTop: 10, maxWidth: 600, margin: '10px auto 0' }}>
          {(['todos', 'cerrados', 'abiertos'] as const).map(f => (
            <button key={f} onClick={() => setFiltro(f)}
              style={{
                padding: '5px 14px', borderRadius: 999, border: 'none', cursor: 'pointer',
                fontSize: 11.5, fontWeight: 700, fontFamily: 'inherit',
                background: filtro === f ? 'oklch(30% 0.06 155)' : 'oklch(94% 0.005 75)',
                color: filtro === f ? '#fff' : 'oklch(50% 0.01 60)',
              }}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div style={{ maxWidth: 600, margin: '0 auto', padding: '12px 16px 32px' }}>
        {loading ? (
          <p style={{ textAlign: 'center', color: 'oklch(60% 0.01 60)', fontSize: 13, marginTop: 40 }}>Cargando...</p>
        ) : visibles.length === 0 ? (
          <p style={{ textAlign: 'center', color: 'oklch(60% 0.01 60)', fontSize: 13, marginTop: 40 }}>Sin turnos registrados</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {visibles.map(t => {
              const cerrado = t.estado === 'cerrado'
              const diffCierre = t.diferencia_cierre
              const hayDiff = diffCierre !== null && Math.round(diffCierre) !== 0
              const hayFoto = !!t.imagen_cierre_url

              return (
                <button
                  key={t.id}
                  onClick={() => setSelected(t)}
                  style={{
                    width: '100%', background: '#fff', borderRadius: 16, border: '1px solid oklch(92% 0.008 75)',
                    padding: '12px 14px', cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
                    boxShadow: '0 1px 3px rgba(0,0,0,.04)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: 0, fontSize: 13.5, fontWeight: 700, color: 'oklch(22% 0.02 60)' }}>
                        {fmtDate(t.fecha_apertura)}
                      </p>
                      <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 500 }}>
                        {fmtTime(t.fecha_apertura)}{t.fecha_cierre ? ` → ${fmtTime(t.fecha_cierre)}` : ' · en curso'}
                        {t.tipo_turno && <span style={{ color: 'oklch(50% 0.12 65)' }}> · {t.tipo_turno}</span>}
                      </p>
                    </div>
                    <ChevronRight size={16} style={{ color: 'oklch(65% 0.01 60)', flexShrink: 0, marginTop: 2 }} />
                  </div>

                  {t.baristas.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 7 }}>
                      <Users size={11} style={{ color: 'oklch(60% 0.01 60)', flexShrink: 0 }} />
                      <span style={{ fontSize: 11.5, color: 'oklch(42% 0.01 60)', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {t.baristas.join(' · ')}
                      </span>
                    </div>
                  )}

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
                    <div style={{ display: 'flex', gap: 10 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.02 60)', fontVariantNumeric: 'tabular-nums' }}>
                        {fmt(t.total_ventas)}
                      </span>
                      {cerrado && diffCierre !== null && (
                        <span style={{
                          fontSize: 11.5, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                          color: !hayDiff ? 'oklch(35% 0.13 145)' : diffCierre > 0 ? 'oklch(35% 0.13 240)' : 'oklch(42% 0.18 30)',
                          padding: '1px 8px', borderRadius: 999,
                          background: !hayDiff ? 'oklch(95% 0.04 145)' : diffCierre > 0 ? 'oklch(95% 0.04 240)' : 'oklch(96% 0.04 30)',
                        }}>
                          {fmtDiff(diffCierre)}
                        </span>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      {hayFoto && <Camera size={12} style={{ color: 'oklch(55% 0.08 155)' }} />}
                      <span style={{
                        padding: '2px 9px', borderRadius: 999, fontSize: 10, fontWeight: 700,
                        background: cerrado ? 'oklch(95% 0.015 155)' : 'oklch(96% 0.08 145)',
                        color: cerrado ? 'oklch(40% 0.08 155)' : 'oklch(30% 0.15 145)',
                      }}>
                        {cerrado ? 'Cerrado' : 'Abierto'}
                      </span>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {fotoUrl && <Lightbox url={fotoUrl} onClose={() => setFotoUrl(null)} />}
    </div>
  )
}

// ── Lightbox ──────────────────────────────────────────────────────────────────

function Lightbox({ url, onClose }: { url: string; onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,.88)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
    >
      <button onClick={onClose} style={{ position: 'absolute', top: 16, right: 16, background: 'rgba(255,255,255,.15)', border: 'none', borderRadius: 999, padding: 8, cursor: 'pointer', color: '#fff' }}>
        <X size={20} />
      </button>
      <img src={url} alt="" style={{ maxWidth: '100%', maxHeight: '90vh', borderRadius: 12, objectFit: 'contain' }} onClick={e => e.stopPropagation()} />
    </div>
  )
}
