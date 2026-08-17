import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle, CalendarClock, CalendarDays, CheckCircle, Clock, Pencil, Receipt,
  Tag, Trash2, Wallet, X,
} from 'lucide-react'
import api from '../../api/client'
import { hoyBogota } from '../../utils/fechaLocal'
import { CuentaBanco, detalleDeError, fechaCorta, plata } from './banco'
import {
  Agenda, AgendaSinFecha, Categoria, CORPORATIVO, Listado, Obligacion, Pago, Tienda,
} from './tipos'
import { Banner, CLS_INPUT, ComoSeCalcula, ErrorCampo } from './campos'
import FormObligacion from './FormObligacion'
import FormPagoObligacion from './FormPagoObligacion'

const ESTADO: Record<string, { label: string; cls: string; Icon: typeof CheckCircle }> = {
  pagada:    { label: 'Pagada',    cls: 'bg-success-50 text-success-600 border-success-200', Icon: CheckCircle },
  parcial:   { label: 'Parcial',   cls: 'bg-gold-50 text-gold-700 border-gold-200',          Icon: Clock },
  pendiente: { label: 'Pendiente', cls: 'bg-danger-50 text-danger-700 border-danger-200',    Icon: AlertCircle },
  anulada:   { label: 'Anulada',   cls: 'bg-warm-100 text-warm-500 border-warm-200',         Icon: X },
}

/** Confirmación EN LA FILA, no `window.confirm`.
 *
 *  El confirm nativo se ve fuera de la app, no dice cuál fila disparó y en la
 *  tablet aparece arriba de todo, lejos del dedo. Estas tres acciones (anular
 *  una obligación, anular un pago, repetir el mes que viene) mueven plata: la
 *  pregunta tiene que verse pegada a la fila que se está por tocar. */
function Confirmar({ texto, cta, onSi, onNo, tono = 'rojo' }: {
  texto: string; cta: string; onSi: () => void; onNo: () => void
  tono?: 'rojo' | 'verde'
}) {
  return (
    <span className="flex flex-wrap items-center gap-2 text-[11px]">
      <span className={tono === 'rojo' ? 'text-danger-700' : 'text-warm-600'}>{texto}</span>
      <button onClick={onSi}
        className={`min-h-[36px] px-3 rounded-lg font-bold text-white ${
          tono === 'rojo' ? 'bg-danger-500 hover:bg-danger-600' : 'bg-forest hover:bg-forest-700'}`}>
        {cta}
      </button>
      <button onClick={onNo} className="min-h-[36px] px-2 rounded-lg font-bold text-warm-500">No</button>
    </span>
  )
}

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * OBLIGACIONES — el arriendo, la nómina y los servicios, a la vista
 * ═════════════════════════════════════════════════════════════════════════════
 * Era un CAJÓN, y adentro del cajón la carga estaba a 3 clicks detrás de un
 * modal y anular un pago a 4 detrás de una «x» diminuta. Pedido textual: «no
 * quiero desplegar pestañas para agregar una obligación».
 *
 * Ahora la fila de carga está montada arriba y la lista abajo. Todo lo que
 * estaba adentro del cajón sigue existiendo: los tres KPIs, el corte por
 * categoría con TODAS las categorías (no las 3 primeras: si el arriendo queda
 * cuarto, la pantalla que existía para contestar «cuánto de arriendo» lo
 * escondía), los cuatro filtros, repetir, anular, registrar pago y anular pago.
 *
 * ── LO QUE SE GANÓ ─────────────────────────────────────────────────────────
 * EDITAR. El backend acepta los diez campos por PATCH desde siempre y el
 * frontend mandaba uno solo, así que corregir el monto del arriendo obligaba a
 * anular y volver a cargar — perdiendo de vista los pagos ya registrados.
 *
 * ── LOS DOS FILTROS QUE NO SON DECORATIVOS ─────────────────────────────────
 * «Anuladas» es el ÚNICO camino a una obligación dada de baja: no aparece en la
 * agenda ni en el libro, así que sin este filtro una anulada por error es
 * irrecuperable a la vista.
 * «Corporativo» NO es lo mismo que «todas»: el arriendo y la nómina no
 * pertenecen a ninguna sede, y necesitan una opción propia para poder aislarlos.
 */
export default function BannerObligaciones({
  categorias, tiendas, cuentas, agenda, onCambio, refreshKey = 0,
}: {
  categorias: Categoria[]
  tiendas: Tienda[]
  cuentas: CuentaBanco[]
  /** Para el bloque «sin fecha de pago», que no sale de la lista filtrada. */
  agenda: Agenda | null
  /** Cambió algo que otros banners leen (agenda, flujo, resultado). */
  onCambio: () => void
  /** Sube cuando se pagó algo desde OTRO banner de esta misma página: sin esta
   *  señal la lista seguía con el saldo viejo y dejaba pagar dos veces. */
  refreshKey?: number
}) {
  const hoy = hoyBogota()

  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [sede, setSede] = useState('')
  const [fCategoria, setFCategoria] = useState('')
  const [fEstado, setFEstado] = useState('')

  const [data, setData] = useState<Listado | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')

  const [detalle, setDetalle] = useState<number | null>(null)
  const [editando, setEditando] = useState<number | null>(null)
  const [pagando, setPagando] = useState<number | null>(null)
  const [confirmando, setConfirmando] = useState<string | null>(null)
  const [fechando, setFechando] = useState<AgendaSinFecha | null>(null)
  const [fVence, setFVence] = useState('')

  const cargar = useCallback(() => {
    setCargando(true); setError('')
    const params: Record<string, string | number | boolean> = {}
    if (sede === CORPORATIVO) params.solo_corporativas = true
    else if (sede) params.tienda_id = Number(sede)
    if (fCategoria) params.categoria = fCategoria
    if (fEstado) params.estado = fEstado
    if (desde) params.desde = desde
    if (hasta) params.hasta = hasta
    return api.get<Listado>('/costos/obligaciones', { params })
      .then(r => setData(r.data))
      .catch(e => { setData(null); setError(detalleDeError(e, 'No se pudieron cargar los costos.')) })
      .finally(() => setCargando(false))
    // `refreshKey` sube desde LaPlataView cuando se pagó algo en OTRO banner de
    // esta misma página. Va adentro de las deps de `cargar` —no solo del
    // efecto— porque el efecto depende de la identidad de `cargar`: sin esto el
    // prop queda declarado y muerto, la lista sigue mostrando el saldo entero y
    // se puede pagar dos veces la misma obligación (`registrar_pago` no valida
    // contra el saldo).
  }, [sede, fCategoria, fEstado, desde, hasta, refreshKey])

  useEffect(() => { cargar() }, [cargar])

  /** Después de cada mutación: la lista de acá Y el resto de la página. */
  const refrescar = () => { cargar(); onCambio() }

  const obligaciones = data?.obligaciones ?? []

  // Corte por categoría sobre LO FILTRADO: es el desglose de los tres KPIs de
  // arriba, así que tiene que moverse con ellos.
  const porCategoria = useMemo(() => {
    const acc: Record<string, { clave: string; nombre: string; monto: number }> = {}
    obligaciones.forEach(o => {
      const g = acc[o.categoria_clave] ?? { clave: o.categoria_clave, nombre: o.categoria_nombre, monto: 0 }
      g.monto += o.monto
      acc[o.categoria_clave] = g
    })
    return Object.values(acc).sort((a, b) => b.monto - a.monto)
  }, [obligaciones])

  const anularObligacion = async (o: Obligacion) => {
    setConfirmando(null); setError('')
    try { await api.delete(`/costos/obligaciones/${o.id}`); refrescar() }
    catch (e) { setError(detalleDeError(e, 'No se pudo anular.')) }
  }

  const anularPago = async (p: Pago) => {
    setConfirmando(null); setError('')
    try { await api.delete(`/costos/pagos/${p.id}`); refrescar() }
    catch (e) { setError(detalleDeError(e, 'No se pudo anular el pago.')) }
  }

  // El backend es IDEMPOTENTE por serie y mes y contesta `ya_existia`: un doble
  // toque no cobra el arriendo dos veces. Ese aviso hay que conservarlo o el
  // dueño no sabe si la segunda vez hizo algo.
  const repetir = async (o: Obligacion) => {
    setConfirmando(null); setError(''); setAviso('')
    try {
      const { data: copia } = await api.post<Obligacion & { ya_existia: boolean }>(
        `/costos/obligaciones/${o.id}/repetir`)
      setAviso(copia.ya_existia
        ? `«${copia.concepto}» del ${fechaCorta(copia.fecha_devengo)} ya existía: no se duplicó.`
        : `Copiada: «${copia.concepto}» con devengo ${fechaCorta(copia.fecha_devengo)}.`)
      refrescar()
    } catch (e) { setError(detalleDeError(e, 'No se pudo repetir.')) }
  }

  const guardarFecha = async () => {
    if (!fechando || !fVence) return
    setError('')
    try {
      await api.patch(`/costos/obligaciones/${fechando.id}`, { fecha_vencimiento: fVence })
      setFechando(null); refrescar()
    } catch (e) { setError(detalleDeError(e, 'No se pudo guardar la fecha.')) }
  }

  const sinFecha = agenda?.sin_fecha ?? []

  return (
    <Banner
      titulo="Obligaciones — el arriendo, la nómina y los servicios"
      sub={data
        ? <>Debés {plata(data.totales.saldo)} de {plata(data.totales.monto)} causados
            {' '}en {data.totales.n} {data.totales.n === 1 ? 'obligación' : 'obligaciones'}</>
        : 'Cargá acá lo que se paga aunque no haya turno abierto'}
    >
      {/* ── La carga, SIEMPRE montada ─────────────────────────────────────── */}
      <FormObligacion categorias={categorias} tiendas={tiendas} onListo={() => refrescar()} />

      {/* ── Los tres números que se leen juntos ───────────────────────────── */}
      {/* «—», no «$0». Sin lista cargada no hay cifra que mostrar, y un cero acá
          se lee como «no debés nada»: la dirección tranquilizadora sobre un dato
          que nadie midió. */}
      <div className="grid grid-cols-3 divide-x divide-warm-100 border-b border-warm-100">
        <div className="px-3 py-2.5">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Total causado</p>
          <p className="text-base font-bold font-mono tabular-nums text-warm-700 leading-tight">
            {data ? plata(data.totales.monto) : '—'}
          </p>
        </div>
        <div className="px-3 py-2.5">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Ya pagado</p>
          <p className="text-base font-bold font-mono tabular-nums text-success-600 leading-tight">
            {data ? plata(data.totales.pagado) : '—'}
          </p>
        </div>
        <div className="px-3 py-2.5">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Falta pagar</p>
          <p className="text-base font-bold font-mono tabular-nums text-danger-700 leading-tight">
            {data ? plata(data.totales.saldo) : '—'}
          </p>
        </div>
      </div>

      {/* ── Sin fecha de pago ─────────────────────────────────────────────────
          «Vence» es opcional en el alta, así que el caso normal terminaba
          invisible: cuenta en el resultado del mes pero no se agenda ni entra a
          la proyección. Sin este bloque el dueño concluye que no se guardó. */}
      {sinFecha.length > 0 && (
        <div className="border-b border-gold-200 bg-gold-50">
          <div className="flex items-baseline justify-between gap-2 px-4 py-2">
            <p className="text-xs font-bold text-gold-700">
              Sin fecha de pago — no entran a la agenda ni a la proyección
            </p>
            <p className="font-mono font-bold text-xs text-gold-700 tabular-nums shrink-0">
              {plata(agenda?.totales.sin_fecha ?? 0)}
            </p>
          </div>
          <div className="divide-y divide-gold-200/40">
            {sinFecha.map(i => (
              <div key={`sf-${i.id}`}>
                <div className="flex items-center gap-2 px-4 py-2">
                  <span className="shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg bg-white text-gold-700 border border-gold-200">
                    <Tag size={11} /> {i.categoria_nombre || 'Sin categoría'}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-warm-700 truncate">{i.concepto}</p>
                    <p className="text-[11px] text-warm-500 truncate">
                      {i.tienda_nombre || 'Corporativo'} · devengo {fechaCorta(i.fecha_devengo)}
                    </p>
                  </div>
                  <span className="font-mono font-bold text-sm text-warm-700 shrink-0 tabular-nums">
                    {plata(i.monto)}
                  </span>
                  <button
                    onClick={() => {
                      setFechando(f => (f?.id === i.id ? null : i))
                      setFVence(i.fecha_devengo || hoy)
                    }}
                    className="shrink-0 flex items-center gap-1.5 text-[11px] font-bold text-white bg-gold-600 hover:bg-gold-500 px-3 min-h-[38px] rounded-lg">
                    <CalendarClock size={13} /> Poner fecha
                  </button>
                </div>
                {/* Un solo campo: no merece un modal. */}
                {fechando?.id === i.id && (
                  <div className="px-4 pb-3 flex flex-wrap items-end gap-2">
                    <label className="block">
                      <span className="block text-[10px] font-bold uppercase tracking-wide text-warm-500 mb-1">
                        ¿Para cuándo hay que pagarlo?
                      </span>
                      <input type="date" value={fVence} autoFocus
                        onChange={e => setFVence(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') guardarFecha() }}
                        className={`${CLS_INPUT} w-auto`} />
                    </label>
                    <button onClick={guardarFecha} disabled={!fVence}
                      className="min-h-[44px] px-4 rounded-xl bg-forest hover:bg-forest-700 disabled:opacity-40 text-white text-sm font-bold">
                      Guardar
                    </button>
                    <button onClick={() => setFechando(null)}
                      className="min-h-[44px] px-3 rounded-xl text-sm font-bold text-warm-500">
                      Cancelar
                    </button>
                    <p className="w-full text-[11px] text-warm-500 leading-snug">
                      Con esta fecha el costo entra al día que le toca en la agenda. El mes al que
                      pertenece (el devengo) <b>no cambia</b>.
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Filtros ───────────────────────────────────────────────────────────
          Tocar una categoría filtra: con las categorías ya listadas, tener
          además un select separado era pedir el mismo dato dos veces. */}
      <div className="px-3 py-2 border-b border-warm-100 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {[{ v: '', l: 'Todas las sedes' },
            { v: CORPORATIVO, l: 'Corporativo' },
            ...tiendas.map(t => ({ v: String(t.id), l: t.nombre }))].map(op => (
            <button key={op.v || 'todas'} onClick={() => setSede(op.v)}
              className={`min-h-[38px] px-3 rounded-full text-[11px] font-bold border transition-colors ${
                sede === op.v ? 'bg-forest text-white border-forest'
                  : 'bg-white border-warm-200 text-warm-500'}`}>
              {op.l}
            </button>
          ))}
          <select value={fEstado} onChange={e => setFEstado(e.target.value)}
            aria-label="Estado" className="min-h-[38px] border border-warm-200 rounded-full px-3 text-[11px] font-bold bg-white text-warm-600">
            <option value="">Todo estado</option>
            <option value="pendiente">Pendiente</option>
            <option value="parcial">Parcial</option>
            <option value="pagada">Pagada</option>
            <option value="anulada">Anuladas</option>
          </select>
          <label className="flex items-center gap-1 text-[11px] text-warm-500 ml-auto">
            <span className="hidden sm:inline">Devengo</span>
            <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
              aria-label="Devengo desde"
              className="min-h-[38px] border border-warm-200 rounded-lg px-2 text-[11px] bg-white" />
            <span className="text-warm-400">→</span>
            <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
              aria-label="Devengo hasta"
              className="min-h-[38px] border border-warm-200 rounded-lg px-2 text-[11px] bg-white" />
          </label>
        </div>

        {porCategoria.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <button onClick={() => setFCategoria('')}
              className={`min-h-[34px] px-2.5 rounded-lg text-[11px] font-bold border ${
                !fCategoria ? 'bg-warm-700 text-white border-warm-700' : 'bg-white border-warm-200 text-warm-500'}`}>
              Todas
            </button>
            {porCategoria.map(c => (
              <button key={c.clave}
                onClick={() => setFCategoria(f => (f === c.clave ? '' : c.clave))}
                className={`min-h-[34px] px-2.5 rounded-lg text-[11px] font-bold border ${
                  fCategoria === c.clave ? 'bg-warm-700 text-white border-warm-700'
                    : 'bg-white border-warm-200 text-warm-600'}`}>
                {c.nombre} <span className="font-mono tabular-nums opacity-70">{plata(c.monto)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <div className="px-3 py-2"><ErrorCampo msg={error} /></div>}
      {aviso && (
        <p className="px-4 py-2 text-[11px] font-semibold text-forest bg-forest-50 border-b border-forest-100">
          {aviso}
        </p>
      )}

      {/* ── La lista ──────────────────────────────────────────────────────── */}
      {cargando && <p className="px-4 py-6 text-center text-sm text-warm-400 animate-pulse">Cargando…</p>}

      {!cargando && obligaciones.map(o => {
        const e = ESTADO[o.estado] ?? ESTADO.pendiente
        const pagosVivos = o.pagos.filter(p => !p.anulado)
        return (
          <div key={o.id} className="border-b border-warm-100 last:border-0">
            <div className="px-3 py-2.5">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-bold text-warm-700 truncate">{o.concepto}</p>
                  <p className="text-[11px] text-warm-500 truncate">
                    {o.categoria_nombre} · {o.tienda_nombre || 'Corporativo'}
                    {o.beneficiario ? ` · ${o.beneficiario}` : ''}
                    {' · devengo '}{fechaCorta(o.fecha_devengo)}
                    {o.fecha_vencimiento ? ` · vence ${fechaCorta(o.fecha_vencimiento)}` : ''}
                  </p>
                </div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 shrink-0 border ${e.cls}`}>
                  <e.Icon size={11} /> {e.label}
                </span>
              </div>

              <div className="flex items-center gap-3 mt-1 text-xs flex-wrap font-mono tabular-nums">
                <span className="text-warm-500">Monto <b className="text-warm-700">{plata(o.monto)}</b></span>
                <span className="text-warm-500">Pagado <b className="text-success-600">{plata(o.pagado)}</b></span>
                {o.saldo > 0 && (
                  <span className="text-warm-500">Saldo <b className="text-danger-700">{plata(o.saldo)}</b></span>
                )}
                {pagosVivos.length > 0 && (
                  <button onClick={() => setDetalle(d => (d === o.id ? null : o.id))}
                    className="font-sans text-[11px] font-bold text-warm-500 hover:text-warm-700">
                    {detalle === o.id ? '▾' : '▸'} Pagos ({pagosVivos.length})
                  </button>
                )}
              </div>

              {/* La traza de la plata que salió, y el único lugar donde se ve el
                  método de pago. Los anulados se filtran: siguen en la base como
                  historia, pero no cuentan. */}
              {detalle === o.id && pagosVivos.length > 0 && (
                <div className="mt-1.5 ml-1 pl-3 border-l-2 border-warm-100 space-y-1">
                  {pagosVivos.map(p => (
                    <div key={p.id} className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="text-warm-600 truncate">
                        {fechaCorta(p.fecha_pago)} · {p.metodo}{p.nota ? ` · ${p.nota}` : ''}
                      </span>
                      <span className="flex items-center gap-2 shrink-0">
                        <span className="font-mono font-bold tabular-nums text-warm-700">{plata(p.monto)}</span>
                        {confirmando === `pago-${p.id}` ? (
                          <Confirmar texto="¿Anular este pago?" cta="Anular"
                            onSi={() => anularPago(p)} onNo={() => setConfirmando(null)} />
                        ) : (
                          <button onClick={() => setConfirmando(`pago-${p.id}`)}
                            aria-label={`Anular el pago de ${plata(p.monto)}`}
                            className="p-2 rounded-lg text-warm-400 hover:text-danger-600 hover:bg-danger-50">
                            <Trash2 size={12} />
                          </button>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Acciones. «Anulada» no ofrece ninguna: ya está dada de baja. */}
              {o.estado !== 'anulada' && (
                <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                  {o.saldo > 0 && (
                    <button onClick={() => { setPagando(p => (p === o.id ? null : o.id)); setEditando(null) }}
                      className="flex items-center gap-1.5 text-[11px] font-bold text-white bg-forest hover:bg-forest-700 px-3 min-h-[38px] rounded-lg">
                      <Wallet size={13} /> Registrar pago
                    </button>
                  )}
                  <button onClick={() => { setEditando(x => (x === o.id ? null : o.id)); setPagando(null) }}
                    className="flex items-center gap-1.5 text-[11px] font-bold text-forest bg-forest-50 hover:bg-forest-100 px-3 min-h-[38px] rounded-lg">
                    <Pencil size={12} /> Corregir
                  </button>
                  {confirmando === `rep-${o.id}` ? (
                    <Confirmar tono="verde"
                      texto={`¿Crear la copia del mes que viene por ${plata(o.monto)}?`} cta="Copiar"
                      onSi={() => repetir(o)} onNo={() => setConfirmando(null)} />
                  ) : (
                    <button onClick={() => setConfirmando(`rep-${o.id}`)}
                      title="Crea la copia del mes siguiente. Es idempotente: tocarlo dos veces no duplica."
                      className="flex items-center gap-1.5 text-[11px] font-bold text-warm-600 bg-warm-100 hover:bg-warm-200 px-3 min-h-[38px] rounded-lg">
                      <CalendarDays size={13} /> Repetir mes que viene
                    </button>
                  )}
                  {confirmando === `anu-${o.id}` ? (
                    <Confirmar
                      texto="Sale de la lista y de los totales; los pagos quedan como traza."
                      cta="Anular" onSi={() => anularObligacion(o)} onNo={() => setConfirmando(null)} />
                  ) : (
                    <button onClick={() => setConfirmando(`anu-${o.id}`)}
                      className="ml-auto flex items-center gap-1 text-[11px] font-bold text-danger-600 hover:bg-danger-50 border border-danger-200 px-2.5 min-h-[38px] rounded-lg">
                      <Trash2 size={12} /> Anular
                    </button>
                  )}
                </div>
              )}
            </div>

            {pagando === o.id && (
              <FormPagoObligacion
                obligacionId={o.id}
                concepto={o.concepto}
                detalle={[o.categoria_nombre, o.tienda_nombre || 'Corporativo', o.beneficiario || '']
                  .filter(Boolean).join(' · ')}
                saldo={o.saldo}
                cuentas={cuentas}
                onCancelar={() => setPagando(null)}
                onPagado={av => {
                  setPagando(null); refrescar()
                  // El pago se guardó pero la salida del banco falló: el aviso
                  // llega desde el formulario porque ahí muere al desmontarse.
                  if (av) setAviso(av)
                }} />
            )}
            {editando === o.id && (
              <FormObligacion key={`ed-${o.id}`} categorias={categorias} tiendas={tiendas}
                editando={o}
                onCancelar={() => setEditando(null)}
                onListo={() => { setEditando(null); refrescar() }} />
            )}
          </div>
        )
      })}

      {!cargando && !error && obligaciones.length === 0 && (
        <div className="px-4 py-8 text-center">
          <Receipt size={24} className="text-warm-300 mx-auto mb-2" />
          <p className="text-sm text-warm-500">
            {desde || hasta || sede || fCategoria || fEstado
              ? 'No hay obligaciones con esos filtros'
              : 'Todavía no cargaste ninguna obligación'}
          </p>
          <p className="text-[11px] text-warm-400 mt-1">
            Acá va el arriendo, la nómina y los servicios — aunque se paguen fuera del turno.
            La fila de arriba los carga.
          </p>
        </div>
      )}

      <PagosDelPeriodo obligaciones={obligaciones} />

      <ComoSeCalcula titulo="¿Qué es el devengo y por qué el saldo del banco no baja solo?">
        <p>
          El <b>devengo</b> es el mes al que pertenece el costo y manda en el resultado: el
          arriendo de agosto pesa en agosto aunque se pague el 5 de septiembre. El{' '}
          <b>vencimiento</b> es cuándo hay que pagarlo y manda en la agenda y en la proyección.
          Son dos fechas distintas a propósito.
        </p>
        <p>
          Registrar un pago tacha el vencimiento, pero <b>no mueve el libro del banco</b>: al libro
          solo entra lo que se teclea. Por eso el formulario de pago ofrece cargar la salida en el
          mismo gesto cuando la plata sale de la cuenta.
        </p>
        <p>
          «Repetir mes que viene» copia el costo con el devengo y el vencimiento un mes adelante.
          Es idempotente por serie y mes: tocarlo dos veces no cobra el arriendo dos veces, avisa
          que ya existía.
        </p>
      </ComoSeCalcula>
    </Banner>
  )
}

/**
 * «Lo que ya salió»: los pagos de un rango, por fecha de pago.
 *
 * `GET /costos/pagos` existe desde siempre y el frontend NUNCA lo llamaba: los
 * pagos solo se veían de a uno, desplegando cada obligación. Es la vista que
 * contesta «¿qué pagué esta semana?».
 *
 * EL NOMBRE SE RESUELVE POR ID CONTRA LA LISTA QUE YA ESTÁ EN PANTALLA, no por
 * parecido de texto: el pago trae `obligacion_id` y nada más. Cuando ese id no
 * está en la lista cargada (porque los filtros la recortan) se dice eso mismo en
 * vez de inventarle un concepto.
 */
function PagosDelPeriodo({ obligaciones }: { obligaciones: Obligacion[] }) {
  const hoy = hoyBogota()
  const hace30 = (() => {
    const d = new Date(hoy + 'T00:00:00'); d.setDate(d.getDate() - 30)
    return d.toLocaleDateString('en-CA')
  })()
  const [desde, setDesde] = useState(hace30)
  const [hasta, setHasta] = useState(hoy)
  const [pagos, setPagos] = useState<Pago[] | null>(null)
  const [abierto, setAbierto] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!abierto) return
    api.get<Pago[]>('/costos/pagos', { params: { desde, hasta } })
      .then(r => { setPagos(r.data); setError('') })
      .catch(e => { setPagos(null); setError(detalleDeError(e, 'No se pudieron cargar los pagos.')) })
  }, [abierto, desde, hasta])

  const nombre = (p: Pago) => {
    if (p.factura_id) return 'Factura de proveedor'
    const o = obligaciones.find(x => x.id === p.obligacion_id)
    return o ? o.concepto : 'Obligación fuera de los filtros de arriba'
  }
  const total = (pagos ?? []).reduce((s, p) => s + p.monto, 0)

  return (
    <div className="border-t border-warm-100">
      <button onClick={() => setAbierto(a => !a)}
        className="w-full px-4 py-2.5 text-left text-[11px] font-bold text-warm-500 hover:bg-warm-50">
        {abierto ? '▾' : '▸'} Lo que ya salió — los pagos del período
      </button>
      {abierto && (
        <div className="px-4 pb-3 space-y-2">
          <div className="flex items-center gap-1.5 text-[11px] text-warm-500">
            <span>Pagado entre</span>
            <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
              aria-label="Pagos desde"
              className="min-h-[38px] border border-warm-200 rounded-lg px-2 text-[11px] bg-white" />
            <span>y</span>
            <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
              aria-label="Pagos hasta"
              className="min-h-[38px] border border-warm-200 rounded-lg px-2 text-[11px] bg-white" />
          </div>
          <ErrorCampo msg={error} />
          {pagos && pagos.length > 0 && (
            <>
              <div className="rounded-xl border border-warm-200 divide-y divide-warm-100 max-h-64 overflow-y-auto">
                {pagos.map(p => (
                  <div key={p.id} className="flex items-center gap-2 px-3 py-2 text-[11px]">
                    <span className="text-warm-500 w-16 shrink-0">{fechaCorta(p.fecha_pago)}</span>
                    <span className="min-w-0 flex-1 text-warm-700 truncate">{nombre(p)}</span>
                    <span className="text-warm-400 shrink-0 capitalize">{p.metodo}</span>
                    <span className="font-mono font-bold tabular-nums text-warm-700 shrink-0">
                      {plata(p.monto)}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-warm-500">
                Salieron <b className="font-mono tabular-nums">{plata(total)}</b> en {pagos.length}{' '}
                {pagos.length === 1 ? 'pago' : 'pagos'}, por el día en que salió la plata (no por
                el día en que se registró). Los anulados no cuentan.
              </p>
            </>
          )}
          {pagos && pagos.length === 0 && !error && (
            <p className="text-[11px] text-warm-500">No salió ningún pago en ese rango.</p>
          )}
        </div>
      )}
    </div>
  )
}
