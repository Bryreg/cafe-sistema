import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import { useAuth } from '../contexts/AuthContext'
import { useBaristaActiva } from '../contexts/BaristaActivaContext'
import { CalendarDays, Star } from 'lucide-react'
import {
  aFecha, aISO, fmtHoras, sumarDias, type Novedad, type TurnoProgramado,
} from '../components/horarios/tipos'

/**
 * Lo que ve la barista: SUS turnos, los publicados.
 *
 * En el kiosko compartido el usuario logueado es el dispositivo, así que se
 * consulta por la barista activa del selector. Con login individual (celular)
 * el usuario ya es la persona y no hace falta nada más.
 */

interface Respuesta {
  usuario_id: number
  desde: string
  hasta: string
  turnos: TurnoProgramado[]
  novedades: Novedad[]
  festivos: string[]
}

const DIAS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
  'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

export default function MiHorario() {
  const { user } = useAuth()
  const { baristaActiva } = useBaristaActiva()
  const [data, setData] = useState<Respuesta | null>(null)
  const [loading, setLoading] = useState(true)

  // Kiosko compartido → la barista activa. Login individual → el propio usuario.
  const esKiosko = localStorage.getItem('kiosk') === 'true'
  const usuarioId = esKiosko ? baristaActiva?.id : user?.user_id

  const hoy = aISO(new Date())
  const hasta = aISO(sumarDias(new Date(), 20))

  useEffect(() => {
    if (!usuarioId) { setLoading(false); return }
    setLoading(true)
    api.get<Respuesta>('/horarios/mi-horario', {
      params: { usuario_id: usuarioId, desde: hoy, hasta },
    })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [usuarioId])

  const totalSemana = useMemo(() => {
    if (!data) return 0
    const limite = aISO(sumarDias(new Date(), 7))
    return data.turnos
      .filter(t => t.fecha <= limite)
      .reduce((acc, t) => acc + t.horas, 0)
  }, [data])

  const novedadDe = (fecha: string) =>
    data?.novedades.find(n => n.fecha_desde <= fecha && fecha <= n.fecha_hasta) ?? null

  return (
    <BaristaLayout title="Mi horario" backTo="/" width="form">
      {!usuarioId && (
        <p className="text-sm text-warm-500">
          Elegí tu nombre en el selector de barista activa para ver tu horario.
        </p>
      )}

      {usuarioId && loading && (
        <p className="text-sm text-warm-400 animate-pulse py-8 text-center">Cargando tu horario…</p>
      )}

      {usuarioId && !loading && data && (
        <div className="space-y-3">
          <div className="bg-white rounded-2xl border border-warm-200 px-4 py-3 flex items-center gap-3">
            <CalendarDays size={18} className="text-forest" />
            <div className="flex-1">
              <p className="text-sm font-bold text-warm-700">Los próximos 20 días</p>
              <p className="text-xs text-warm-400">
                Estos son los turnos que ya te enviaron. Si cambia alguno, te llega un aviso.
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] text-warm-400 font-semibold">esta semana</p>
              <p className="text-sm font-mono font-bold text-warm-700">{fmtHoras(totalSemana)}</p>
            </div>
          </div>

          {data.turnos.length === 0 && (
            <div className="bg-white rounded-2xl border border-warm-200 px-4 py-10 text-center">
              <p className="text-sm text-warm-500">Todavía no tenés turnos enviados.</p>
              <p className="text-xs text-warm-400 mt-1">
                Cuando el admin envíe el horario de la semana, te va a llegar un aviso.
              </p>
            </div>
          )}

          <div className="space-y-2">
            {data.turnos.map(t => {
              const d = aFecha(t.fecha)
              const esFestivo = data.festivos.includes(t.fecha)
              const esDomingo = d.getDay() === 0
              const nov = novedadDe(t.fecha)
              return (
                <div
                  key={t.id}
                  className={`bg-white rounded-2xl border px-4 py-3 flex items-center gap-3 ${
                    nov ? 'border-clay-200' : 'border-warm-200'
                  }`}
                >
                  <div className="text-center w-12 shrink-0">
                    <p className="text-lg font-bold text-warm-700 leading-none">{d.getDate()}</p>
                    <p className="text-[10px] text-warm-400 uppercase">
                      {MESES_CORTOS[d.getMonth()]}
                    </p>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-warm-700">
                      {DIAS[d.getDay()]}
                      {(esFestivo || esDomingo) && (
                        <span className="ml-1.5 inline-flex items-center gap-0.5 text-[10px] font-bold text-clay-600">
                          <Star size={9} /> {esFestivo ? 'festivo' : 'domingo'}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-warm-500 font-mono">
                      {t.hora_inicio} a {t.hora_fin}
                      {t.cruza_medianoche && ' (del día siguiente)'} · {fmtHoras(t.horas)}
                    </p>
                    {nov && (
                      <p className="text-xs text-clay-600 mt-0.5">
                        {nov.label} cargada para este día
                      </p>
                    )}
                    {t.nota && <p className="text-xs text-warm-400 mt-0.5">{t.nota}</p>}
                  </div>
                </div>
              )
            })}
          </div>

          {data.novedades.length > 0 && (
            <div className="bg-white rounded-2xl border border-warm-200 p-4">
              <p className="text-sm font-bold text-warm-700 mb-2">Tus novedades</p>
              <ul className="space-y-1">
                {data.novedades.map(n => (
                  <li key={n.id} className="text-xs text-warm-600">
                    <span className="font-mono text-warm-400">
                      {n.fecha_desde}→{n.fecha_hasta}
                    </span>{' '}
                    {n.label}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </BaristaLayout>
  )
}
