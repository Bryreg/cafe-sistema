import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Camera, TrendingDown, TrendingUp, Users, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'

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

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`
const fmtDiff = (v: number) => `${v > 0 ? '+' : ''}${fmt(v)}`

function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}
function fmtDate(s: string) {
  const d = parseUTC(s)
  return d.toLocaleDateString('es-CO', { weekday: 'short', day: '2-digit', month: 'short' })
}
function fmtTime(s: string) {
  return parseUTC(s).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}

export default function CuadreTurnos() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const tiendaId = user?.tienda_id ?? 1

  const [turnos, setTurnos] = useState<TurnoItem[]>([])
  const [loading, setLoading] = useState(true)
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

  return (
    <div className="min-h-screen" style={{ background: '#f5f3ef', fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif' }}>

      {/* Header */}
      <div style={{ background: '#fff', borderBottom: '1px solid oklch(92% 0.008 75)', padding: '12px 16px', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, maxWidth: 600, margin: '0 auto' }}>
          <button onClick={() => navigate(-1)} style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(55% 0.01 60)' }}>
            <ArrowLeft size={20} />
          </button>
          <div style={{ flex: 1 }}>
            <p style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'oklch(22% 0.02 60)' }}>Cuadres de turno</p>
            <p style={{ margin: 0, fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 500 }}>Historial y fotos de cierre</p>
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

      {/* Content */}
      <div style={{ maxWidth: 600, margin: '0 auto', padding: '12px 16px 32px' }}>
        {loading ? (
          <p style={{ textAlign: 'center', color: 'oklch(60% 0.01 60)', fontSize: 13, marginTop: 40 }}>Cargando...</p>
        ) : visibles.length === 0 ? (
          <p style={{ textAlign: 'center', color: 'oklch(60% 0.01 60)', fontSize: 13, marginTop: 40 }}>Sin turnos registrados</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {visibles.map(t => {
              const cerrado = t.estado === 'cerrado'
              const diffCierre = t.diferencia_cierre ?? null
              const diffTarjeta = t.diferencia_tarjeta ?? null
              const hayDiff = diffCierre !== null && Math.round(diffCierre) !== 0
              const hayDiffTarjeta = diffTarjeta !== null && Math.round(diffTarjeta) !== 0

              return (
                <div key={t.id} style={{ background: '#fff', borderRadius: 18, overflow: 'hidden', border: '1px solid oklch(92% 0.008 75)', boxShadow: '0 1px 4px rgba(0,0,0,.05)' }}>

                  {/* Top bar */}
                  <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid oklch(95% 0.005 75)' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                      <div>
                        <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.02 60)' }}>
                          {fmtDate(t.fecha_apertura)}
                        </p>
                        <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(55% 0.01 60)', fontWeight: 500 }}>
                          {fmtTime(t.fecha_apertura)}{t.fecha_cierre ? ` → ${fmtTime(t.fecha_cierre)}` : ' → en curso'}
                          {t.tipo_turno && <span style={{ marginLeft: 6, color: 'oklch(50% 0.12 65)' }}>· {t.tipo_turno}</span>}
                        </p>
                      </div>
                      <span style={{
                        padding: '3px 10px', borderRadius: 999, fontSize: 10.5, fontWeight: 700,
                        background: cerrado ? 'oklch(95% 0.015 155)' : 'oklch(96% 0.08 145)',
                        color: cerrado ? 'oklch(40% 0.08 155)' : 'oklch(30% 0.15 145)',
                      }}>
                        {cerrado ? 'Cerrado' : 'Abierto'}
                      </span>
                    </div>

                    {t.baristas.length > 0 && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 7 }}>
                        <Users size={11} style={{ color: 'oklch(60% 0.01 60)', flexShrink: 0 }} />
                        <span style={{ fontSize: 11.5, color: 'oklch(40% 0.01 60)', fontWeight: 500 }}>
                          {t.baristas.join(' · ')}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Financials */}
                  <div style={{ padding: '10px 14px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: cerrado ? 10 : 0 }}>
                      {[
                        { label: 'Ventas', value: fmt(t.total_ventas) },
                        { label: 'Efectivo', value: fmt(t.total_efectivo) },
                        { label: 'Tarjeta', value: fmt(t.total_tarjeta) },
                      ].map(r => (
                        <div key={r.label}>
                          <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>{r.label}</p>
                          <p style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.02 60)', fontVariantNumeric: 'tabular-nums' }}>{r.value}</p>
                        </div>
                      ))}
                    </div>

                    {cerrado && t.efectivo_final_real !== null && (
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, paddingTop: 8, borderTop: '1px solid oklch(95% 0.005 75)' }}>
                        <div>
                          <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>Contado</p>
                          <p style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.02 60)', fontVariantNumeric: 'tabular-nums' }}>{fmt(t.efectivo_final_real)}</p>
                        </div>
                        <div>
                          <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>Diff. caja</p>
                          <p style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: !hayDiff ? 'oklch(35% 0.12 145)' : diffCierre! > 0 ? 'oklch(35% 0.12 240)' : 'oklch(45% 0.18 30)' }}>
                            {diffCierre !== null ? fmtDiff(diffCierre) : '—'}
                          </p>
                        </div>
                        <div>
                          <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(60% 0.01 60)', letterSpacing: '.08em', textTransform: 'uppercase' }}>Diff. bold</p>
                          <p style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: !hayDiffTarjeta ? 'oklch(35% 0.12 145)' : 'oklch(45% 0.18 30)' }}>
                            {diffTarjeta !== null ? fmtDiff(diffTarjeta) : '—'}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Diferencia de apertura */}
                    {Math.round(t.diferencia_apertura) !== 0 && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 8, padding: '5px 8px', borderRadius: 8, background: 'oklch(97% 0.03 55)' }}>
                        {t.diferencia_apertura > 0
                          ? <TrendingUp size={11} style={{ color: 'oklch(40% 0.12 145)', flexShrink: 0 }} />
                          : <TrendingDown size={11} style={{ color: 'oklch(45% 0.18 30)', flexShrink: 0 }} />}
                        <span style={{ fontSize: 11, color: 'oklch(40% 0.08 60)', fontWeight: 500 }}>
                          Diferencia apertura: <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtDiff(t.diferencia_apertura)}</strong>
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Foto */}
                  {t.imagen_cierre_url ? (
                    <button
                      onClick={() => setFotoUrl(t.imagen_cierre_url)}
                      style={{ width: '100%', padding: 0, border: 'none', cursor: 'pointer', display: 'block', borderTop: '1px solid oklch(95% 0.005 75)' }}
                    >
                      <img
                        src={t.imagen_cierre_url}
                        alt="Foto cuadre de caja"
                        style={{ width: '100%', height: 120, objectFit: 'cover', display: 'block' }}
                      />
                    </button>
                  ) : cerrado && (
                    <div style={{ borderTop: '1px solid oklch(95% 0.005 75)', padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Camera size={12} style={{ color: 'oklch(70% 0.01 60)' }} />
                      <span style={{ fontSize: 11, color: 'oklch(65% 0.01 60)' }}>Sin foto de cuadre</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Lightbox */}
      {fotoUrl && (
        <div
          onClick={() => setFotoUrl(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
        >
          <button onClick={() => setFotoUrl(null)} style={{ position: 'absolute', top: 16, right: 16, background: 'rgba(255,255,255,.15)', border: 'none', borderRadius: 999, padding: 8, cursor: 'pointer', color: '#fff' }}>
            <X size={20} />
          </button>
          <img src={fotoUrl} alt="Foto cuadre" style={{ maxWidth: '100%', maxHeight: '90vh', borderRadius: 12, objectFit: 'contain' }} onClick={e => e.stopPropagation()} />
        </div>
      )}
    </div>
  )
}
