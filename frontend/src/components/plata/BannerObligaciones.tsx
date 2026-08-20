import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle, CalendarClock, CalendarDays, CheckCircle, Clock, Lock, Pencil,
  Receipt, Tag, Trash2, Wallet, X,
} from 'lucide-react'
import api from '../../api/client'
import { hoyBogota } from '../../utils/fechaLocal'
import { Dato, datoCargando, datoFalla, datoListo, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { CuentaBanco, detalleDeError, fechaCorta, plata } from './banco'
import {
  Categoria, CORPORATIVO, Listado, Obligacion, Pago, Tienda,
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

/** Una de las tres cifras de arriba. Gris cuando no hay cifra que poner. */
function Kpi({ label, valor, color = 'text-warm-700', apagado = false }: {
  label: string; valor: ReactNode; color?: string; apagado?: boolean
}) {
  return (
    <div className="px-3 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">{label}</p>
      <p className={`text-base font-bold font-mono tabular-nums leading-tight ${
        apagado ? 'text-warm-400' : color}`}>
        {valor}
      </p>
    </div>
  )
}

/** Los tres KPIs sin cifra: «…» mientras se piden, «—» cuando no volvieron. */
function KpisMudos({ marca }: { marca: string }) {
  return (<>
    <Kpi label="Total causado" valor={marca} apagado />
    <Kpi label="Ya pagado" valor={marca} apagado />
    <Kpi label="Falta pagar" valor={marca} apagado />
  </>)
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
 *
 * ── LO QUE SE FUE ──────────────────────────────────────────────────────────
 * El bloque «sin fecha de pago» vivía acá y salía de `agenda.sin_fecha`, que es
 * OTRO fetch. Se mudó entero al bloque «lo que hay que pagar», que es la única
 * lista de la página: por eso este banner ya no necesita la agenda.
 */
export default function BannerObligaciones({
  categorias, tiendas, cuentas, onCambio, refreshKey = 0,
}: {
  categorias: Fuente<Categoria[]>
  tiendas: Fuente<Tienda[]>
  cuentas: Fuente<CuentaBanco[]>
  /** Cambió algo que otros bloques leen (agenda, flujo, resultado). */
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

  const [datos, setDatos] = useState<Dato<Listado>>(datoCargando)
  /** SOLO errores de MUTACIÓN (anular, repetir, fechar). Lo que falló al LEER
   *  vive adentro de `datos`, que es quien decide qué se dibuja en su lugar. */
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')

  const [detalle, setDetalle] = useState<number | null>(null)
  const [editando, setEditando] = useState<number | null>(null)
  const [pagando, setPagando] = useState<number | null>(null)
  const [confirmando, setConfirmando] = useState<string | null>(null)

  const cargar = useCallback(() => {
    setDatos(datoCargando)
    const params: Record<string, string | number | boolean> = {}
    if (sede === CORPORATIVO) params.solo_corporativas = true
    else if (sede) params.tienda_id = Number(sede)
    if (fCategoria) params.categoria = fCategoria
    if (fEstado) params.estado = fEstado
    if (desde) params.desde = desde
    if (hasta) params.hasta = hasta
    return api.get<Listado>('/costos/obligaciones', { params })
      .then(r => setDatos(datoListo(r.data)))
      .catch(e => setDatos(datoFalla(detalleDeError(e, 'No se pudieron leer las obligaciones.'))))
    // `refreshKey` sube desde la página cuando se pagó algo en OTRO bloque de
    // esta misma página. Va adentro de las deps de `cargar` —no solo del
    // efecto— porque el efecto depende de la identidad de `cargar`: sin esto el
    // prop queda declarado y muerto, la lista sigue mostrando el saldo entero y
    // se puede pagar dos veces la misma obligación (`registrar_pago` no valida
    // contra el saldo).
  }, [sede, fCategoria, fEstado, desde, hasta, refreshKey])

  useEffect(() => { cargar() }, [cargar])

  /** Después de cada mutación: la lista de acá Y el resto de la página. */
  const refrescar = () => { cargar(); onCambio() }

  const obligaciones = useMemo(() => mapDato(datos, d => d.obligaciones), [datos])

  // Corte por categoría sobre LO FILTRADO: es el desglose de los tres KPIs de
  // arriba, así que tiene que moverse con ellos.
  const porCategoria = useMemo(() => mapDato(obligaciones, os => {
    const acc: Record<string, { clave: string; nombre: string; monto: number }> = {}
    os.forEach(o => {
      const g = acc[o.categoria_clave] ?? { clave: o.categoria_clave, nombre: o.categoria_nombre, monto: 0 }
      g.monto += o.monto
      acc[o.categoria_clave] = g
    })
    return Object.values(acc).sort((a, b) => b.monto - a.monto)
  }), [obligaciones])

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

  const hayFiltros = !!(desde || hasta || sede || fCategoria || fEstado)

  return (
    <Banner
      titulo="Obligaciones — el arriendo, la nómina y los servicios"
      sub={datos.estado === 'listo'
        ? <>Debés {plata(datos.valor.totales.saldo)} de {plata(datos.valor.totales.monto)} causados
            {' '}en {datos.valor.totales.n} {datos.valor.totales.n === 1 ? 'obligación' : 'obligaciones'}</>
        : datos.estado === 'cargando'
          ? 'Leyendo lo que se debe…'
          : 'No se pudo leer cuánto debés — mirá el detalle acá abajo'}
    >
      {/* ── La carga, SIEMPRE montada ─────────────────────────────────────── */}
      <FormObligacion categorias={categorias} tiendas={tiendas} onListo={() => refrescar()} />

      {/* ── Los tres números que se leen juntos ───────────────────────────── */}
      {/* «—», no «$0». Sin lista cargada no hay cifra que mostrar, y un cero acá
          se lee como «no debés nada»: la dirección tranquilizadora sobre un dato
          que nadie midió. */}
      <div className="grid grid-cols-3 divide-x divide-warm-100 border-b border-warm-100">
        <SegunDato
          dato={datos}
          cargando={<KpisMudos marca="…" />}
          falla={() => <KpisMudos marca="—" />}
          listo={d => (<>
            <Kpi label="Total causado" valor={plata(d.totales.monto)} />
            <Kpi label="Ya pagado" valor={plata(d.totales.pagado)} color="text-success-600" />
            <Kpi label="Falta pagar" valor={plata(d.totales.saldo)} color="text-danger-700" />
          </>)}
        />
      </div>

      {/* ── «Sin fecha de pago» YA NO VIVE ACÁ ───────────────────────────────
          Se mudó ENTERO al bloque «lo que hay que pagar», que es la única lista
          de la página: ahí está su renglón, su total aparte y el mismo
          `PATCH /costos/obligaciones/{id}` que se hacía desde este banner.

          Tenerlo en los dos lugares no era redundancia inofensiva: eran dos
          formularios de fecha para la misma obligación, y el que quedaba
          abierto en el que no se tocó seguía mostrando la fecha vieja. Una
          acción, un lugar. */}

      {/* ── Filtros ───────────────────────────────────────────────────────────
          Tocar una categoría filtra: con las categorías ya listadas, tener
          además un select separado era pedir el mismo dato dos veces. */}
      <div className="px-3 py-2 border-b border-warm-100 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {[{ v: '', l: 'Todas las sedes' }, { v: CORPORATIVO, l: 'Corporativo' }].map(op => (
            <button key={op.v || 'todas'} onClick={() => setSede(op.v)}
              className={`min-h-[38px] px-3 rounded-full text-[11px] font-bold border transition-colors ${
                sede === op.v ? 'bg-forest text-white border-forest'
                  : 'bg-white border-warm-200 text-warm-500'}`}>
              {op.l}
            </button>
          ))}
          {/* Las sedes son OTRO fetch. Sin este renglón, el catálogo caído dejaba
              dos chips y ninguna sede — igual que un negocio de una sola sede. */}
          <SegunDato
            dato={tiendas.dato}
            cargando={null}
            falla={() => (
              <button onClick={tiendas.recargar}
                className="min-h-[38px] px-3 rounded-full text-[11px] font-bold border border-dashed border-warm-300 bg-warm-50 text-warm-500">
                No se pudieron leer las sedes · Reintentar
              </button>
            )}
            listo={ts => (<>
              {ts.map(t => (
                <button key={t.id} onClick={() => setSede(String(t.id))}
                  className={`min-h-[38px] px-3 rounded-full text-[11px] font-bold border transition-colors ${
                    sede === String(t.id) ? 'bg-forest text-white border-forest'
                      : 'bg-white border-warm-200 text-warm-500'}`}>
                  {t.nombre}
                </button>
              ))}
            </>)}
          />
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

        {/* Los chips de categoría son el desglose de una lista que sí llegó: sin
            ella no hay nada que desglosar, y el hueco de abajo ya lo dice. */}
        {porCategoria.estado === 'listo' && porCategoria.valor.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <button onClick={() => setFCategoria('')}
              className={`min-h-[34px] px-2.5 rounded-lg text-[11px] font-bold border ${
                !fCategoria ? 'bg-warm-700 text-white border-warm-700' : 'bg-white border-warm-200 text-warm-500'}`}>
              Todas
            </button>
            {porCategoria.valor.map(c => (
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
      <SegunDato
        dato={obligaciones}
        cargando={<p className="px-4 py-6 text-center text-sm text-warm-400 animate-pulse">Cargando…</p>}
        falla={m => (
          <div className="px-4 py-4">
            <NoSeSabe bloque onReintentar={cargar}
              mensaje={`${m} — no se sabe qué obligaciones hay ni cuánto falta pagar. Esta lista `
                + 'vacía no quiere decir que no debas nada.'} />
          </div>
        )}
        listo={os => os.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <Receipt size={24} className="text-warm-300 mx-auto mb-2" />
            <p className="text-sm text-warm-500">
              {hayFiltros
                ? 'No hay obligaciones con esos filtros'
                : 'Todavía no cargaste ninguna obligación'}
            </p>
            <p className="text-[11px] text-warm-400 mt-1">
              Acá va el arriendo, la nómina y los servicios — aunque se paguen fuera del turno.
              La fila de arriba los carga.
            </p>
          </div>
        ) : (<>
          {os.map(o => {
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
                      {/* CORREGIR Y REPETIR SOLO SI LA FILA ES DEL DUEÑO.
                          `editable_a_mano` lo decide el backend con la misma lista
                          que usa para rechazar la edición, así que acá no hay una
                          segunda regla que se pueda despegar.

                          Estas dos filas son del SISTEMA: la declaración del
                          impoconsumo (monto medido sobre la venta real, fecha del
                          calendario de la DIAN) y las viejas de proveedores. Con
                          «Corregir» a la vista, dos taps devolvían el doble conteo
                          —el select ni siquiera podía mostrar la categoría real, así
                          que abría en blanco y guardaba la primera de la lista— y el
                          piso del mes del devengo subía $12.447.999. Y el server
                          ahora contesta 400: dejar el botón sería enseñarle al dueño
                          que los botones de esta pantalla no significan nada.

                          PAGAR Y ANULAR SIGUEN. Pagar es el punto de toda la fila, y
                          anular es la salida cuando el número del contador es otro:
                          se anula y se vuelve a agendar con esa cifra.

                          `!== false` Y NO A SECAS, y la diferencia es una ventana
                          de deploy entera. Esto es una PWA con service worker: hay
                          minutos en que la tablet corre el bundle NUEVO contra el
                          backend VIEJO, y ahí `editable_a_mano` llega `undefined`.
                          Con la pregunta por verdad, `undefined` es falsy y TODAS
                          las filas —arriendo, servicios, contador— se dibujaban con
                          el candado: el dueño no podía corregir nada y la pantalla
                          no le decía por qué. El default seguro va al revés — el
                          candado solo cuando el server lo AFIRMA— y no afloja
                          ninguna guarda: la guarda real es el 400 del server, que
                          sigue ahí. Y no abre nada nuevo: el backend que no manda
                          el campo es el MISMO que todavía no trae ni la fila del
                          impoconsumo ni el 400, o sea que en esa ventana la
                          pantalla queda exactamente como estaba antes del deploy
                          en vez de estrenar un candado sobre todo. */}
                      {o.editable_a_mano !== false ? (<>
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
                      </>) : (
                        /* EL HUECO SE DICE, no se deja mudo (regla 4): dos botones
                           que desaparecen sin explicación se leen como una pantalla
                           rota. Y dice qué hacer en su lugar. */
                        <span className="flex items-center gap-1.5 text-[11px] text-warm-400 leading-snug">
                          <Lock size={11} className="shrink-0" />
                          La carga el sistema: no se corrige ni se repite a mano. Si el número
                          es otro, anulala y volvé a agendarla.
                        </span>
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
        </>)}
      />

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
 * vez de inventarle un concepto — y cuando la lista NO VOLVIÓ se dice otra cosa,
 * porque «está fuera de los filtros» sería una explicación falsa que manda a
 * tocar filtros que no tienen la culpa.
 */
function PagosDelPeriodo({ obligaciones }: { obligaciones: Dato<Obligacion[]> }) {
  const hoy = hoyBogota()
  const hace30 = (() => {
    const d = new Date(hoy + 'T00:00:00'); d.setDate(d.getDate() - 30)
    return d.toLocaleDateString('en-CA')
  })()
  const [desde, setDesde] = useState(hace30)
  const [hasta, setHasta] = useState(hoy)
  const [pagos, setPagos] = useState<Dato<Pago[]>>(datoCargando)
  const [abierto, setAbierto] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!abierto) return
    let vivo = true
    setPagos(datoCargando)
    api.get<Pago[]>('/costos/pagos', { params: { desde, hasta } })
      .then(r => { if (vivo) setPagos(datoListo(r.data)) })
      .catch(e => {
        if (vivo) setPagos(datoFalla(detalleDeError(e, 'No se pudieron leer los pagos del período.')))
      })
    return () => { vivo = false }
  }, [abierto, desde, hasta, tick])

  const nombre = (p: Pago) => {
    if (p.factura_id) return 'Factura de proveedor'
    if (obligaciones.estado !== 'listo') return 'Obligación — su nombre no se pudo leer'
    const o = obligaciones.valor.find(x => x.id === p.obligacion_id)
    return o ? o.concepto : 'Obligación fuera de los filtros de arriba'
  }

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
          <SegunDato
            dato={pagos}
            cargando={<p className="text-[11px] text-warm-400 animate-pulse">Buscando los pagos…</p>}
            falla={m => (
              <NoSeSabe onReintentar={() => setTick(n => n + 1)}
                mensaje={`${m} — no se sabe qué salió en ese rango.`} />
            )}
            listo={ps => ps.length === 0 ? (
              <p className="text-[11px] text-warm-500">No salió ningún pago en ese rango.</p>
            ) : (<>
              <div className="rounded-xl border border-warm-200 divide-y divide-warm-100 max-h-64 overflow-y-auto">
                {ps.map(p => (
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
                Salieron <b className="font-mono tabular-nums">
                  {plata(ps.reduce((s, p) => s + p.monto, 0))}
                </b> en {ps.length} {ps.length === 1 ? 'pago' : 'pagos'}, por el día en que salió la
                plata (no por el día en que se registró). Los anulados no cuentan.
              </p>
            </>)}
          />
        </div>
      )}
    </div>
  )
}
