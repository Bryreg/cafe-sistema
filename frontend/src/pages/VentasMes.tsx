import { useEffect, useState } from 'react'
import { CalendarDays } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import { StatTile, Card, SectionLabel } from '../components/ui'

// ─── Types ───────────────────────────────────────────────────────────────────

interface DiaMes {
  fecha: string
  total: number
}

// Respuesta de GET /pos/analytics/contador (solo los campos que usa esta vista).
// Sin tienda_id el backend scopea a la tienda de la sesión (barista/kiosko).
interface ContadorMes {
  anio: number
  mes: number
  dias: DiaMes[]
  total_mes: number
  promedio_venta_diaria: number
  dias_periodo: number
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v || 0).toLocaleString('es-CO')}`

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

// Fecha LOCAL del kiosko (Colombia): toISOString es UTC y después de las 19:00
// devuelve mañana — mismo patrón de hoy() en Ingresos.
function hoyLocal() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const fmtDia = (iso: string) => {
  const [, m, d] = iso.split('-')
  return `${d}/${m}`
}

// ─── Componente principal ─────────────────────────────────────────────────────

export default function VentasMes() {
  const { user } = useAuth()
  const { turno } = useTurno()

  const [data, setData] = useState<ContadorMes | null>(null)
  const [meta, setMeta] = useState(0)
  const [loading, setLoading] = useState(true)

  const now = new Date()
  const anio = now.getFullYear()
  const mes = now.getMonth() + 1

  useEffect(() => {
    // La meta es opcional: si falla (o no hay tienda en sesión) el hero cae al
    // modo "sin meta" — el contador sí es obligatorio para pintar la página.
    const metaReq: Promise<number> = user?.tienda_id
      ? api.get(`/auth/config/meta-ventas/${user.tienda_id}`).then(r => Number(r.data?.meta) || 0).catch(() => 0)
      : Promise.resolve(0)
    Promise.all([
      api.get<ContadorMes>('/pos/analytics/contador', { params: { anio, mes } }),
      metaReq,
    ])
      .then(([c, m]) => { setData(c.data); setMeta(m) })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [user?.tienda_id]) // eslint-disable-line react-hooks/exhaustive-deps  (anio/mes son del montaje)

  // El informe agrupa por DÍA OPERATIVO, no por la fecha del dispositivo. El día a
  // mostrar es el del turno abierto cuando lo hay (a las 00:30 el día operativo
  // sigue siendo el de ayer, y con la fecha local no habría renglón: mostraba $0
  // con la caja vendiendo); si no hay turno, el día de hoy.
  // Se usa el renglón del INFORME, no turno.total_ventas: en un día con turno de
  // apertura y turno de cierre, el turno solo trae lo suyo, así que el número
  // bajaría al relevar y saltaría al cerrar. El informe trae el día completo.
  const diaAMostrar = turno?.dia_operativo_fecha || hoyLocal()
  const ventaHoy = data?.dias.find(d => d.fecha === diaAMostrar)?.total ?? 0
  const etiquetaHoy = 'Ventas del día'

  const totalMes = data?.total_mes ?? 0
  const diasEnMes = new Date(anio, mes, 0).getDate()
  const diasRestantes = Math.max(0, diasEnMes - now.getDate())
  const pct = meta > 0 ? (totalMes / meta) * 100 : 0
  const metaCumplida = meta > 0 && totalMes >= meta
  const faltan = Math.max(0, meta - totalMes)
  // Ritmo: cuánto hay que vender por día en lo que queda del mes para llegar.
  const ritmo = meta > 0 ? Math.ceil(faltan / Math.max(1, diasRestantes)) : 0
  const maxDia = Math.max(1, ...(data?.dias.map(d => d.total) ?? [1]))

  return (
    <BaristaLayout title="Ventas del mes">
      {loading ? (
        <div className="flex flex-col gap-3">
          <div className="h-32 rounded-2xl bg-warm-100 animate-pulse" />
          <div className="grid grid-cols-2 gap-3">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="h-24 rounded-2xl bg-warm-100 animate-pulse" />
            ))}
          </div>
        </div>
      ) : !data ? (
        /* Falla de red o backend caído: estado vacío silencioso (kiosko). */
        <Card className="flex flex-col items-center gap-2 py-10">
          <CalendarDays size={32} className="text-warm-200" />
          <p className="text-sm text-warm-400 font-semibold text-center">
            No se pudieron cargar las ventas del mes. Intentá de nuevo más tarde.
          </p>
        </Card>
      ) : (
        <>
          {/* ── Hero: meta del mes ── */}
          <Card padding="lg" className="mb-6">
            <SectionLabel className="mb-2">Meta del mes · {MESES[mes - 1]}</SectionLabel>
            {meta > 0 ? (
              <>
                <div className="flex items-baseline justify-between gap-2 flex-wrap mb-3">
                  <p className="font-mono tabular-nums text-3xl font-bold text-bark-800 leading-none">
                    {fmt(totalMes)}
                  </p>
                  <p className="text-sm font-semibold text-warm-500">de {fmt(meta)}</p>
                </div>
                <div className="h-3 rounded-full bg-warm-100 overflow-hidden mb-2">
                  <div
                    className={`h-full rounded-full ${metaCumplida ? 'bg-success-500' : 'bg-forest'}`}
                    style={{ width: `${Math.min(100, pct)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-warm-500">{Math.round(pct)}%</span>
                  {metaCumplida ? (
                    <span className="text-xs font-bold text-success-700">¡Meta cumplida!</span>
                  ) : (
                    <span className="text-xs font-semibold text-warm-500">faltan {fmt(faltan)}</span>
                  )}
                </div>
              </>
            ) : (
              <>
                <p className="font-mono tabular-nums text-3xl font-bold text-bark-800 leading-none mb-2">
                  {fmt(totalMes)}
                </p>
                <p className="text-xs text-warm-400">El administrador aún no definió la meta del mes.</p>
              </>
            )}
          </Card>

          {/* ── KPIs del mes ── */}
          <div className="grid grid-cols-2 gap-3 mb-6">
            <StatTile
              label={etiquetaHoy}
              value={fmt(ventaHoy)}
              tint="success"
            />
            <StatTile
              label="Promedio diario"
              value={fmt(data.promedio_venta_diaria)}
              sublabel={`${data.dias_periodo} días del mes`}
              tint="neutral"
            />
            {meta > 0 && (
              <StatTile
                label="Ritmo para la meta"
                value={fmt(ritmo)}
                sublabel="por día para llegar"
                tint="clay"
              />
            )}
            <StatTile
              label="Días restantes"
              value={diasRestantes}
              sublabel={`de ${diasEnMes} del mes`}
              tint="neutral"
            />
          </div>

          {/* ── Tendencia diaria (mini barras) ── */}
          {data.dias.length > 0 && (
            <>
              <SectionLabel className="mb-2">Tendencia diaria</SectionLabel>
              <Card>
                <div className="flex items-end gap-[3px] h-24">
                  {data.dias.map(d => (
                    <div key={d.fecha} className="flex-1 flex flex-col items-center justify-end" title={`${fmtDia(d.fecha)} · ${fmt(d.total)}`}>
                      <div
                        className="w-full rounded-t bg-forest"
                        style={{ height: `${(d.total / maxDia) * 100}%`, minHeight: 3 }}
                      />
                    </div>
                  ))}
                </div>
                <div className="flex justify-between mt-1 text-[9px] text-warm-400">
                  <span>{fmtDia(data.dias[0].fecha)}</span>
                  <span>{fmtDia(data.dias[data.dias.length - 1].fecha)}</span>
                </div>
              </Card>
            </>
          )}
        </>
      )}

      {/* Spacing for bottom nav */}
      <div className="h-4" />
    </BaristaLayout>
  )
}
