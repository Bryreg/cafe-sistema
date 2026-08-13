import { useEffect, useState } from 'react'
import api from '../../api/client'
import {
  AlertTriangle, ChevronDown, ChevronRight, Download, Info,
} from 'lucide-react'
import { Aviso } from './SemanaGrid'
import {
  fmtHoras, fmtPesos, MESES, type BaristaResumen, type EstadoDia, type Resumen,
} from './tipos'

/**
 * Resumen del mes: por barista, horas por categoría, novedades y PLANEADO vs
 * REAL. Los dos números se muestran siempre — nunca uno solo en silencio.
 */

interface Props { tiendaId: number; anio: number; mes: number }

const ESTADO_LABEL: Record<EstadoDia, string> = {
  ok: 'Trabajó',
  no_programado: 'Trabajó sin estar programada',
  sin_marcacion: 'Sin marcación y sin novedad',
  cubrio_otra_sede: 'Marcó en la otra sede',
  novedad_remunerada: 'Novedad que se paga',
  novedad_no_remunerada: 'Novedad que no se paga',
  libre: 'Libre',
}

const ESTADO_COLOR: Record<EstadoDia, string> = {
  ok: 'text-forest-700 bg-forest-50',
  no_programado: 'text-clay-600 bg-clay-50',
  // Ámbar, no rojo: el sistema sabe que falta un REGISTRO, no que faltó la
  // persona. El rojo de peligro es una acusación que el dato no sostiene.
  sin_marcacion: 'text-clay-700 bg-clay-50',
  cubrio_otra_sede: 'text-forest-700 bg-forest-50',
  novedad_remunerada: 'text-warm-600 bg-warm-100',
  novedad_no_remunerada: 'text-warm-600 bg-warm-100',
  libre: 'text-warm-400 bg-warm-50',
}

export default function ResumenMensual({ tiendaId, anio, mes }: Props) {
  const [data, setData] = useState<Resumen | null>(null)
  const [loading, setLoading] = useState(true)
  const [abierta, setAbierta] = useState<number | null>(null)

  useEffect(() => {
    setLoading(true)
    api.get<Resumen>('/horarios/resumen', { params: { tienda_id: tiendaId, anio, mes } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [tiendaId, anio, mes])

  const descargar = async () => {
    const r = await api.get('/horarios/resumen.csv', {
      params: { tienda_id: tiendaId, anio, mes }, responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([r.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `horas-${anio}-${String(mes).padStart(2, '0')}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return <p className="text-sm text-warm-400 py-10 text-center animate-pulse">Calculando el mes…</p>
  }
  if (!data) return <Aviso tono="error">No se pudo cargar el resumen del mes.</Aviso>

  const t = data.totales

  return (
    <div className="space-y-3">
      {/* ── Encabezado + export ── */}
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-bold text-warm-700">
          {MESES[data.mes - 1]} {data.anio}
        </h2>
        <div className="flex-1" />
        <button
          onClick={descargar}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-warm-200 text-warm-600 hover:bg-warm-100"
        >
          <Download size={14} /> Bajar CSV para el contador
        </button>
      </div>

      {/* ── Totales ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <Tarjeta titulo="Horas planeadas" valor={fmtHoras(t.total_planeado)} />
        <Tarjeta titulo="Horas reales" valor={fmtHoras(t.total_real)} />
        <Tarjeta
          titulo="Horas a pagar"
          valor={fmtHoras(t.total_acreditado)}
          pie="reales + novedades que se pagan"
        />
        <Tarjeta titulo="Estimado" valor={fmtPesos(t.estimado)} pie="solo tiempo trabajado" />
      </div>

      {/* ── Cómo se liquida y qué NO cubre ── */}
      <div className="bg-white rounded-2xl border border-warm-200 p-4 space-y-2">
        <div className="flex items-start gap-2">
          <Info size={14} className="text-warm-500 shrink-0 mt-0.5" />
          <p className="text-xs text-warm-600">{data.base_liquidacion_detalle}</p>
        </div>
        {data.advertencias.map((a, i) => (
          <p key={i} className="text-[11px] text-warm-400 pl-6">{a}</p>
        ))}
        <div className="pl-6 flex flex-wrap gap-x-4 gap-y-1 pt-1">
          {data.semanas.map(s => (
            <span key={s.lunes} className="text-[11px] text-warm-400 font-mono">
              semana {s.lunes}: máx {s.jornada_max_semanal} h
              {s.confirmar_contador && ' *'}
            </span>
          ))}
        </div>
        {data.semanas.some(s => s.confirmar_contador) && (
          <p className="text-[11px] text-warm-400 pl-6">
            * tasa cargada pero todavía sin confirmar con el contador.
          </p>
        )}
      </div>

      {(t.dias_sin_marcacion > 0 || t.tramos_sin_salida > 0 || t.sin_contrato > 0) && (
        <Aviso tono="info">
          {t.dias_sin_marcacion > 0 && (
            <span className="block">
              Hay {t.dias_sin_marcacion} día(s) con turno asignado, sin marcación y sin
              novedad cargada. Puede ser una falta o una novedad que nadie registró.
            </span>
          )}
          {t.tramos_sin_salida > 0 && (
            <span className="block">
              {t.tramos_sin_salida} turno(s) sin salida marcada: esas horas no se contaron.
            </span>
          )}
          {t.sin_contrato > 0 && (
            <span className="block">
              {t.sin_contrato} barista(s) sin sueldo cargado: sus horas están, su estimado da $0.
            </span>
          )}
        </Aviso>
      )}

      {/* ── Por barista ── */}
      <div className="space-y-2">
        {data.baristas.map(b => (
          <FilaResumen
            key={b.usuario_id}
            barista={b}
            categorias={data.categorias}
            abierta={abierta === b.usuario_id}
            onToggle={() => setAbierta(abierta === b.usuario_id ? null : b.usuario_id)}
          />
        ))}
      </div>
    </div>
  )
}

function Tarjeta({ titulo, valor, pie }: { titulo: string; valor: string; pie?: string }) {
  return (
    <div className="bg-white rounded-2xl border border-warm-200 px-3 py-2.5">
      <p className="text-[11px] font-semibold text-warm-400">{titulo}</p>
      <p className="text-lg font-bold text-warm-700 font-mono">{valor}</p>
      {pie && <p className="text-[10px] text-warm-400">{pie}</p>}
    </div>
  )
}

function FilaResumen({ barista, categorias, abierta, onToggle }: {
  barista: BaristaResumen
  categorias: { clave: string; label: string }[]
  abierta: boolean
  onToggle: () => void
}) {
  const b = barista
  const dif = b.diferencia_horas
  const conCategorias = categorias.filter(c => (b.horas_acreditadas[c.clave] ?? 0) > 0)

  return (
    <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
      <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-warm-50">
        {abierta ? <ChevronDown size={16} className="text-warm-400" />
                 : <ChevronRight size={16} className="text-warm-400" />}
        <span className="flex-1 text-sm font-bold text-warm-700">{b.nombre}</span>

        <span className="text-xs text-warm-400 hidden sm:block">
          plan {fmtHoras(b.total_planeado)}
        </span>
        <span className="text-sm font-mono font-semibold text-warm-700">
          {fmtHoras(b.total_acreditado)}
        </span>
        {Math.abs(dif) > 0.01 && (
          <span className={`text-xs font-mono font-semibold ${
            dif > 0 ? 'text-clay-600' : 'text-danger-700'}`}>
            {dif > 0 ? '+' : ''}{dif.toFixed(1)}
          </span>
        )}
        <span className="text-sm font-mono text-warm-600 w-24 text-right">
          {fmtPesos(b.estimado.total)}
        </span>
        {b.dias_sin_marcacion.length > 0 && (
          <AlertTriangle size={14} className="text-danger-500" />
        )}
      </button>

      {abierta && (
        <div className="border-t border-warm-100 px-4 py-3 space-y-3">
          {/* Horas por categoría */}
          <div>
            <p className="text-xs font-bold text-warm-500 mb-1">Horas que se pagan</p>
            {conCategorias.length === 0 ? (
              <p className="text-xs text-warm-400">No hay horas en el mes.</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
                {conCategorias.map(c => (
                  <div key={c.clave} className="flex justify-between text-xs">
                    <span className="text-warm-500">{c.label}</span>
                    <span className="font-mono text-warm-700">
                      {fmtHoras(b.horas_acreditadas[c.clave])}
                      <span className="text-warm-400 ml-2">
                        {fmtPesos(b.estimado.detalle[c.clave] ?? 0)}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[11px] text-warm-400 mt-1">
              {b.tiene_contrato
                ? `Hora ordinaria: ${fmtPesos(b.estimado.valor_hora_ordinaria)} (sueldo ${fmtPesos(b.salario_mensual)} ÷ el divisor de la tasa).`
                : 'Sin sueldo cargado: el estimado queda en $0. Cargalo en la pestaña Sueldos.'}
            </p>
          </div>

          {/* Planeado vs real */}
          <div className="grid grid-cols-3 gap-2">
            <Mini titulo="Planeado" valor={fmtHoras(b.total_planeado)} />
            <Mini titulo="Marcado" valor={fmtHoras(b.total_real)} />
            <Mini titulo="Diferencia" valor={`${dif > 0 ? '+' : ''}${dif.toFixed(1)} h`} />
          </div>

          {b.tramos_sin_salida > 0 && (
            <p className="text-[11px] text-danger-700">
              {b.tramos_sin_salida} turno(s) sin salida marcada: esas horas no se contaron.
            </p>
          )}

          {/* Novedades */}
          {b.novedades.length > 0 && (
            <div>
              <p className="text-xs font-bold text-warm-500 mb-1">Novedades</p>
              <ul className="space-y-0.5">
                {b.novedades.map(n => (
                  <li key={n.id} className="text-xs text-warm-600">
                    <span className="font-mono text-warm-400">
                      {n.fecha_desde}→{n.fecha_hasta}
                    </span>{' '}
                    {n.label}
                    <span className="text-warm-400">
                      {' '}· {n.acredita_horas ? 'cuenta horas' : 'no cuenta horas'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Día por día */}
          <div>
            <p className="text-xs font-bold text-warm-500 mb-1">Día por día</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-warm-400">
                    <th className="text-left font-semibold py-1">Fecha</th>
                    <th className="text-right font-semibold">Plan</th>
                    <th className="text-right font-semibold">Marcado</th>
                    <th className="text-left font-semibold pl-3">Qué pasó</th>
                  </tr>
                </thead>
                <tbody>
                  {b.dias.map(d => (
                    <tr key={d.fecha} className="border-t border-warm-100">
                      <td className="py-1 font-mono text-warm-600">{d.fecha}</td>
                      <td className="text-right font-mono text-warm-500">
                        {d.horas_planeadas || '–'}
                      </td>
                      <td className="text-right font-mono text-warm-700">
                        {d.horas_reales || '–'}
                      </td>
                      <td className="pl-3">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${ESTADO_COLOR[d.estado]}`}>
                          {ESTADO_LABEL[d.estado]}
                        </span>
                        {d.novedad && (
                          <span className="text-warm-400 ml-1">{d.novedad.label}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Mini({ titulo, valor }: { titulo: string; valor: string }) {
  return (
    <div className="rounded-xl bg-warm-50 px-2 py-1.5 text-center">
      <p className="text-[10px] text-warm-400 font-semibold">{titulo}</p>
      <p className="text-sm font-mono font-bold text-warm-700">{valor}</p>
    </div>
  )
}
