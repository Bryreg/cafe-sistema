import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Check, Loader2, Save } from 'lucide-react'
import { Aviso } from './SemanaGrid'
import { fmtPesos, type Contrato } from './tipos'

/**
 * Sueldo mensual por barista. Solo sirve para el ESTIMADO en pesos del resumen:
 * si está en cero, las horas se siguen contando igual y el estimado da $0.
 */

interface Props { tiendaId: number }

export default function SueldosPanel({ tiendaId }: Props) {
  const [items, setItems] = useState<Contrato[]>([])
  const [loading, setLoading] = useState(true)
  const [guardando, setGuardando] = useState<number | null>(null)
  const [guardado, setGuardado] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api.get<Contrato[]>('/horarios/contratos', { params: { tienda_id: tiendaId } })
      .then(r => setItems(r.data))
      .catch(() => setError('No se pudieron cargar los sueldos.'))
      .finally(() => setLoading(false))
  }, [tiendaId])

  const patch = (usuarioId: number, cambios: Partial<Contrato>) => {
    setItems(prev => prev.map(c => (c.usuario_id === usuarioId ? { ...c, ...cambios } : c)))
    setGuardado(null)
  }

  const guardar = async (c: Contrato) => {
    setGuardando(c.usuario_id); setError(null)
    try {
      await api.put(`/horarios/contratos/${c.usuario_id}`, {
        salario_mensual: c.salario_mensual,
        horas_semana_pactadas: c.horas_semana_pactadas,
        fecha_ingreso: c.fecha_ingreso,
        activo: c.activo,
        nota: c.nota,
      })
      setGuardado(c.usuario_id)
      patch(c.usuario_id, { tiene_contrato: true })
    } catch { setError('No se pudo guardar.') }
    finally { setGuardando(null) }
  }

  if (loading) {
    return <p className="text-sm text-warm-400 py-10 text-center animate-pulse">Cargando…</p>
  }

  return (
    <div className="space-y-3">
      {error && <Aviso tono="error">{error}</Aviso>}

      <div className="bg-white rounded-2xl border border-warm-200 p-4">
        <p className="text-sm font-bold text-warm-700">Para qué sirve esto</p>
        <p className="text-xs text-warm-500 mt-1">
          El sueldo mensual se divide por el «divisor hora/mes» de la tasa vigente para sacar
          el valor de la hora ordinaria, y sobre ese valor se aplican los recargos. Es un
          ESTIMADO del tiempo trabajado: no incluye auxilio de transporte, prestaciones,
          seguridad social ni deducciones.
        </p>
      </div>

      <div className="bg-white rounded-2xl border border-warm-200 divide-y divide-warm-100">
        {items.map(c => (
          <div key={c.usuario_id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <span className="text-sm font-semibold text-warm-700 min-w-[8rem]">{c.nombre}</span>

            <label className="flex items-center gap-1.5">
              <span className="text-[11px] font-semibold text-warm-400">Sueldo mensual</span>
              <input
                type="text" inputMode="numeric"
                value={(c.salario_mensual || 0).toLocaleString('es-CO')}
                onChange={e => patch(c.usuario_id, {
                  salario_mensual: Number(e.target.value.replace(/[^\d]/g, '')) || 0,
                })}
                className="w-32 border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono text-right"
              />
            </label>

            <label className="flex items-center gap-1.5">
              <span className="text-[11px] font-semibold text-warm-400">Horas/semana pactadas</span>
              <input
                type="number" step="any"
                value={c.horas_semana_pactadas ?? ''}
                placeholder="máx. de la tasa"
                onChange={e => patch(c.usuario_id, {
                  horas_semana_pactadas: e.target.value === '' ? null : Number(e.target.value),
                })}
                className="w-20 border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono text-right"
              />
            </label>

            <span className="text-xs text-warm-400 font-mono">
              {c.salario_mensual > 0 ? `≈ ${fmtPesos(c.salario_mensual / 240)}/h` : '—'}
            </span>

            <div className="flex-1" />
            <button
              onClick={() => guardar(c)}
              disabled={guardando === c.usuario_id}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-forest text-white hover:bg-forest/90 disabled:opacity-40"
            >
              {guardando === c.usuario_id
                ? <Loader2 size={12} className="animate-spin" />
                : <Save size={12} />}
              Guardar
            </button>
            {guardado === c.usuario_id && (
              <span className="flex items-center gap-1 text-xs text-forest-700">
                <Check size={12} /> ok
              </span>
            )}
          </div>
        ))}
      </div>

      <p className="text-[11px] text-warm-400">
        El «≈ por hora» de arriba usa el divisor 240 como referencia rápida. El cálculo real
        usa el divisor de la tasa vigente en cada semana, que podés ver y editar en «Tasas».
      </p>
    </div>
  )
}
