import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Inbox, Tag } from 'lucide-react'
import api from '../../api/client'
import { detalleDeError, fechaCorta, plata } from '../plata/banco'
import { Bandeja, Categoria, EgresoSuelto } from '../plata/tipos'
import { Campo, CLS_INPUT, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE, ErrorCampo, teclas } from '../plata/campos'

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * EGRESOS SIN CATEGORIZAR — colgados de la fila que los nombra
 * ═════════════════════════════════════════════════════════════════════════════
 * Era el cuarto cajón, y se abría desde un CTA al pie del desglose de costos.
 * Ahora vive adentro de ese mismo desglose, colgando de la fila «Sin
 * categorizar»: la pregunta («¿qué es esa bolsa de gastos sin nombre?») y la
 * herramienta para contestarla están en el mismo lugar.
 *
 * ── QUÉ HACE ADOPTAR, Y POR QUÉ HAY QUE DECIRLO ────────────────────────────
 * Adoptar NO cambia ningún total: crea una obligación devengada más su pago
 * espejo, y el `MovimientoCaja` queda intacto — el cuadre del turno y el total
 * de costos del período no se mueven un peso. Sin esa frase, adoptar da miedo y
 * nadie ordena nada.
 *
 * ── LA FECHA ES LA DEL TECLEO, NO LA DE HOY ────────────────────────────────
 * Se precarga con el día en que se TECLEÓ el egreso en caja, que no siempre es
 * el mes al que pertenece el gasto. Corregirla MUEVE el costo de mes en el
 * resultado, y eso se avisa en el momento en que se está por corregir.
 */
export default function BannerEgresos({ categorias, desde, hasta, tiendaId, onCambio }: {
  categorias: Categoria[]
  /** El rango del período que se está mirando en Resultado. */
  desde: string
  hasta: string
  tiendaId: number | null
  onCambio: () => void
}) {
  const [bandeja, setBandeja] = useState<Bandeja | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [adoptando, setAdoptando] = useState<number | null>(null)

  const cargar = useCallback(() => {
    setCargando(true)
    const params: Record<string, string | number> = { desde, hasta }
    if (tiendaId) params.tienda_id = tiendaId
    return api.get<Bandeja>('/costos/egresos-sin-adoptar', { params })
      .then(r => { setBandeja(r.data); setError('') })
      .catch(e => { setBandeja(null); setError(detalleDeError(e, 'No se pudieron cargar los egresos.')) })
      .finally(() => setCargando(false))
  }, [desde, hasta, tiendaId])

  useEffect(() => { cargar() }, [cargar])

  const egresos = bandeja?.egresos ?? []

  return (
    <div className="border-t border-gold-200 bg-gold-50/60">
      <div className="px-4 py-2.5">
        <p className="text-xs font-bold text-gold-700">
          Categorizá lo que quedó suelto
          {bandeja && bandeja.totales.n > 0 && (
            <span className="font-mono tabular-nums"> · {plata(bandeja.totales.monto)} en{' '}
              {bandeja.totales.n} {bandeja.totales.n === 1 ? 'egreso' : 'egresos'} de caja</span>
          )}
        </p>
        <p className="text-[11px] text-gold-700/90 leading-relaxed mt-0.5">
          Son gastos que se registraron en caja con texto libre. Al adoptarlos les ponés una
          categoría y un mes. <b>El total de costos no cambia</b> ni se toca el cuadre del turno:
          la plata solo pasa de «no sé» a «nómina».
        </p>
      </div>

      <ErrorCampo msg={error} />
      {cargando && <p className="px-4 pb-3 text-[11px] text-warm-500 animate-pulse">Cargando…</p>}

      {!cargando && egresos.length > 0 && (
        <div className="divide-y divide-gold-200/40 bg-white/70">
          {egresos.map(e => (
            <div key={e.id}>
              <div className="flex items-center gap-2 px-4 py-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-warm-700 truncate">{e.concepto}</p>
                  <p className="text-[11px] text-warm-500 truncate">
                    {e.tienda_nombre || 'Sin sede'}
                    {e.fecha ? ` · tecleado el ${fechaCorta(e.fecha)}` : ''}
                    {e.barista_nombre ? ` · ${e.barista_nombre}` : ''}
                  </p>
                </div>
                <span className="font-mono font-bold text-sm tabular-nums text-warm-700 shrink-0">
                  {plata(e.valor)}
                </span>
                <button onClick={() => setAdoptando(a => (a === e.id ? null : e.id))}
                  className="shrink-0 flex items-center gap-1.5 text-[11px] font-bold text-white bg-forest hover:bg-forest-700 px-3 min-h-[38px] rounded-lg">
                  <Tag size={13} /> Adoptar
                </button>
              </div>
              {adoptando === e.id && (
                <FormAdopcion key={`ad-${e.id}`} egreso={e} categorias={categorias}
                  onCancelar={() => setAdoptando(null)}
                  onAdoptado={() => { setAdoptando(null); cargar(); onCambio() }} />
              )}
            </div>
          ))}
        </div>
      )}

      {!cargando && !error && egresos.length === 0 && (
        <div className="px-4 pb-3">
          <p className="text-[11px] text-warm-600 flex items-start gap-1.5">
            <Inbox size={13} className="mt-0.5 shrink-0 text-warm-400" />
            <span>
              No quedó ningún egreso suelto entre el {fechaCorta(desde)} y el {fechaCorta(hasta)}.
              Los pagos a proveedor <b>no aparecen acá</b>: ya están contados dentro de Compras, y
              adoptarlos los contaría dos veces.
            </span>
          </p>
        </div>
      )}
    </div>
  )
}

/** Dos campos: entran en la propia fila. */
function FormAdopcion({ egreso, categorias, onCancelar, onAdoptado }: {
  egreso: EgresoSuelto
  categorias: Categoria[]
  onCancelar: () => void
  onAdoptado: () => void
}) {
  const [categoriaId, setCategoriaId] = useState(String(categorias[0]?.id ?? ''))
  // Arranca en el día en que se TECLEÓ el egreso. Nunca en «hoy»: el gasto puede
  // ser de otro mes, y hoy sería una fecha inventada por el formulario.
  const [devengo, setDevengo] = useState(egreso.fecha ?? '')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const listo = !!categoriaId && !!devengo
  const adoptar = async () => {
    if (!listo) return
    setGuardando(true); setError('')
    try {
      await api.post(`/costos/egresos/${egreso.id}/adoptar`, {
        categoria_id: Number(categoriaId),
        fecha_devengo: devengo,
      })
      onAdoptado()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo adoptar. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="px-4 py-3 bg-forest-50 border-y border-forest-100 space-y-2"
      onKeyDown={teclas({ listo, guardar: adoptar, cancelar: onCancelar })}>
      <div className="grid grid-cols-2 gap-2 items-end max-w-lg">
        <Campo label="Categoría del gasto">
          <select value={categoriaId} autoFocus onChange={e => setCategoriaId(e.target.value)}
            className={CLS_INPUT}>
            {categorias.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
        </Campo>
        <Campo label="A qué día pertenece">
          <input type="date" value={devengo} onChange={e => setDevengo(e.target.value)}
            className={CLS_INPUT} />
        </Campo>
      </div>
      <p className="text-[11px] text-gold-700 bg-gold-50 border border-gold-200 rounded-lg px-2.5 py-1.5 flex items-start gap-1.5">
        <AlertCircle size={12} className="mt-0.5 shrink-0" />
        <span>
          La fecha viene del día en que se <b>tecleó</b> el egreso en caja, que no siempre es el
          mes al que pertenece el gasto. Si la corregís, el costo <b>se mueve de mes</b> en el
          resultado. El movimiento de caja queda intacto: el cuadre del turno no cambia.
        </span>
      </p>
      <ErrorCampo msg={error} />
      <div className="flex gap-2">
        <button onClick={onCancelar} className={CLS_BOTON_SUAVE}>Cancelar</button>
        <button onClick={adoptar} disabled={guardando || !listo} className={CLS_BOTON_GUARDAR}>
          {guardando ? 'Guardando…' : 'Adoptar como obligación'}
        </button>
      </div>
    </div>
  )
}
