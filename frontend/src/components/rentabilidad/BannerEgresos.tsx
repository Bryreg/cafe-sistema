import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Inbox, Tag } from 'lucide-react'
import api from '../../api/client'
import { type Fuente, useDato } from '../../api/useDato'
import { NoSeSabe, SegunDato } from '../ui'
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
  /** El catálogo del `<select>` del formulario. `Fuente`, no array: un catálogo
   *  que no volvió dibujado como lista vacía se lee «no hay ninguna categoría
   *  cargada», y ahí el dueño va a crear una que ya existe. */
  categorias: Fuente<Categoria[]>
  /** El rango del período que se está mirando en Resultado. */
  desde: string
  hasta: string
  tiendaId: number | null
  onCambio: () => void
}) {
  const [adoptando, setAdoptando] = useState<number | null>(null)

  const params = useMemo(() => {
    const p: Record<string, string | number> = { desde, hasta }
    if (tiendaId) p.tienda_id = tiendaId
    return p
  }, [desde, hasta, tiendaId])

  const bandeja = useDato<Bandeja>(
    () => api.get('/costos/egresos-sin-adoptar', { params }), 'los egresos sin categorizar',
    'No se pudieron cargar los egresos.', [desde, hasta, tiendaId])

  return (
    <div className="border-t border-gold-200 bg-gold-50/60">
      <div className="px-4 py-2.5">
        <p className="text-xs font-bold text-gold-700">
          Categorizá lo que quedó suelto
          {bandeja.dato.estado === 'listo' && bandeja.dato.valor.totales.n > 0 && (
            <span className="font-mono tabular-nums"> · {plata(bandeja.dato.valor.totales.monto)} en{' '}
              {bandeja.dato.valor.totales.n}{' '}
              {bandeja.dato.valor.totales.n === 1 ? 'egreso' : 'egresos'} de caja</span>
          )}
        </p>
        <p className="text-[11px] text-gold-700/90 leading-relaxed mt-0.5">
          Son gastos que se registraron en caja con texto libre. Al adoptarlos les ponés una
          categoría y un mes. <b>El total de costos no cambia</b> ni se toca el cuadre del turno:
          la plata solo pasa de «no sé» a «nómina».
        </p>
      </div>

      <SegunDato dato={bandeja.dato}
        cargando={<p className="px-4 pb-3 text-[11px] text-warm-500 animate-pulse">Cargando…</p>}
        falla={m => (
          <div className="px-4 pb-3">
            <NoSeSabe mensaje={m} onReintentar={bandeja.recargar} />
          </div>
        )}
        listo={b => b.egresos.length > 0 ? (
          <div className="divide-y divide-gold-200/40 bg-white/70">
            {b.egresos.map(e => (
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
                    onAdoptado={() => { setAdoptando(null); bandeja.recargar(); onCambio() }} />
                )}
              </div>
            ))}
          </div>
        ) : (
          /* El vacío MEDIDO: el backend contestó y no había ninguno. Solo por eso
             se puede afirmar «no quedó ningún egreso suelto». */
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
        )} />
    </div>
  )
}

/**
 * Dos campos: entran en la propia fila.
 *
 * ── EL FORMULARIO NO SE ESCONDE NUNCA ──────────────────────────────────────
 * Si el catálogo de categorías no volvió, el `<select>` queda vacío pero el
 * formulario sigue montado, con el aviso arriba y su «Reintentar». Esconderlo
 * detrás de un gate por estado le rompería el trabajo al dueño: la fecha —que no
 * depende del catálogo— se puede corregir igual, y el catálogo puede llegar un
 * segundo después sin que él tenga que volver a abrir nada.
 */
function FormAdopcion({ egreso, categorias, onCancelar, onAdoptado }: {
  egreso: EgresoSuelto
  categorias: Fuente<Categoria[]>
  onCancelar: () => void
  onAdoptado: () => void
}) {
  const lista = categorias.dato.estado === 'listo' ? categorias.dato.valor : []
  const [categoriaId, setCategoriaId] = useState('')
  // Arranca en el día en que se TECLEÓ el egreso. Nunca en «hoy»: el gasto puede
  // ser de otro mes, y hoy sería una fecha inventada por el formulario.
  const [devengo, setDevengo] = useState(egreso.fecha ?? '')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  // El catálogo puede llegar DESPUÉS de que la fila se abrió (o después de un
  // «Reintentar»): sin esto el select quedaba en blanco para siempre y el botón
  // de guardar nunca se habilitaba, con las categorías ya en pantalla.
  useEffect(() => {
    if (!categoriaId && lista.length > 0) setCategoriaId(String(lista[0].id))
  }, [categoriaId, lista])

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
      {/* Arriba del select, nunca en su lugar. */}
      <SegunDato dato={categorias.dato}
        cargando={null}
        falla={m => <NoSeSabe mensaje={`${m} Sin ellas no se puede adoptar, pero la fecha se puede corregir igual.`}
          onReintentar={categorias.recargar} />}
        listo={() => null} />
      <div className="grid grid-cols-2 gap-2 items-end max-w-lg">
        <Campo label="Categoría del gasto">
          <select value={categoriaId} autoFocus onChange={e => setCategoriaId(e.target.value)}
            className={CLS_INPUT}>
            {/* Sin catálogo el select queda con esta única opción, que dice lo
                que pasa en vez de fingir una lista vacía. */}
            {lista.length === 0 && <option value="">— sin categorías cargadas —</option>}
            {lista.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
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
