import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle, Camera, CalendarClock, CheckCircle, Clock, Download, Pencil,
  Receipt, Search, Trash2, Wallet,
} from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { detalleDeError, fechaCorta, plata } from './banco'
import { DashboardFacturas, Factura, Tienda } from './tipos'
import {
  Banner, Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE,
  ComoSeCalcula, ErrorCampo,
} from './campos'

const ESTADO: Record<string, { label: string; cls: string; Icon: typeof CheckCircle }> = {
  pagado:    { label: 'Pagada',    cls: 'bg-success-50 text-success-600 border-success-200', Icon: CheckCircle },
  parcial:   { label: 'Parcial',   cls: 'bg-gold-50 text-gold-700 border-gold-200',          Icon: Clock },
  pendiente: { label: 'Pendiente', cls: 'bg-danger-50 text-danger-700 border-danger-200',    Icon: AlertCircle },
}

/** Los timestamps del backend llegan como medianoche COLOMBIA en UTC: cortar a
 *  YYYY-MM-DD y leer ese día tal cual evita que el navegador lo corra un día. */
const dia = (s: string | null) => (s ? s.slice(0, 10) : null)

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * LO QUE LE DEBO A LOS PROVEEDORES — el banner que el pedido nombra
 * ═════════════════════════════════════════════════════════════════════════════
 * «Tampoco quiero que los pagos a proveedores queden escondidos». Era un cajón
 * a dos clicks, y adentro vivían las ÚNICAS puertas de toda la app para editar
 * (`PATCH /facturas/{id}`) y eliminar (`DELETE /facturas/{id}`) una factura:
 * verificado, no se llaman desde ningún otro lado. Un cajón borrado sin
 * inventariar se habría llevado eso puesto.
 *
 * ── ABRE EN «SIN PAGAR» ────────────────────────────────────────────────────
 * La pregunta del dueño es «cuánto debo», no «qué facturé». Por eso el filtro
 * de estado arranca en «Sin pagar» y las VENCIDAS van primero: es plata que
 * vence, que es exactamente lo que el pedido dice que no puede estar escondido.
 *
 * ── EL PAGO VA POR `PATCH /facturas/{id}/pago` Y NO POR `/costos/pagos` ────
 * Es el único camino que mueve `FacturaCompra.valor_pagado`. Registrar el pago
 * de una factura por la puerta de las obligaciones lo guardaría sin mover el
 * saldo: el pago se vería como si no hubiera pasado.
 */
export default function BannerProveedores({ tiendas, facturaObjetivo, onObjetivoAtendido, onCambio }: {
  tiendas: Tienda[]
  /** Id que llegó desde el banner de vencidos: abre esa factura y baja hasta ella. */
  facturaObjetivo: number | null
  onObjetivoAtendido: () => void
  onCambio: () => void
}) {
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [data, setData] = useState<DashboardFacturas | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')

  // Filtros de cliente sobre lo ya traído.
  const [busqueda, setBusqueda] = useState('')
  const [fProveedor, setFProveedor] = useState('')
  // '' = todas · 'deuda' = lo que todavía se debe (el DEFAULT) · un estado exacto.
  const [fEstado, setFEstado] = useState<'' | 'deuda' | 'pagado' | 'parcial' | 'pendiente'>('deuda')

  const [abierta, setAbierta] = useState<number | null>(null)
  const [pagando, setPagando] = useState<number | null>(null)
  const [editando, setEditando] = useState<number | null>(null)
  const [borrando, setBorrando] = useState<number | null>(null)

  const refLista = useRef<HTMLDivElement>(null)

  const cargar = useCallback(() => {
    setCargando(true)
    const params: Record<string, string | number> = {}
    if (tiendaId) params.tienda_id = tiendaId
    if (desde) params.desde = desde
    if (hasta) params.hasta = hasta
    return api.get<DashboardFacturas>('/facturas/dashboard', { params })
      .then(r => { setData(r.data); setError('') })
      .catch(e => { setData(null); setError(detalleDeError(e, 'No se pudieron cargar las facturas.')) })
      .finally(() => setCargando(false))
  }, [tiendaId, desde, hasta])

  useEffect(() => { cargar() }, [cargar])

  const refrescar = () => { cargar(); onCambio() }

  // Un ref POR FILA: el tooltip promete «Bajá hasta esta factura», y hacer
  // scroll al contenedor de la lista lo cumplía solo de rebote, porque las
  // vencidas se ordenan primero.
  const refsFila = useRef<Record<number, HTMLDivElement | null>>({})

  // Llegó desde «Vencido»: abrir esa factura, ofrecer el pago y bajar hasta ella.
  // Se sacan los filtros que podrían estarla escondiendo — mandar al dueño a una
  // fila que no está en pantalla es peor que no mandarlo.
  // LOS SEIS FILTROS, no tres. Se limpiaban solo los de cliente (búsqueda,
  // proveedor, estado) y quedaban los de SERVIDOR —sede y el rango de
  // «Recibidas»—, que son justamente los que recortan la respuesta del backend:
  // con cualquiera puesto, el salto hacía scroll a una lista donde la factura
  // NO estaba, abría un id que no se renderiza, y no decía nada. El comentario
  // prometía lo contrario de lo que hacía el código.
  useEffect(() => {
    if (facturaObjetivo == null) return
    setBusqueda(''); setFProveedor(''); setFEstado('')
    setTiendaId(null); setDesde(''); setHasta('')
    setAbierta(facturaObjetivo); setPagando(facturaObjetivo)
    onObjetivoAtendido()
  }, [facturaObjetivo, onObjetivoAtendido])

  // El scroll va DESPUÉS de que la lista se repidió: limpiar los filtros de
  // servidor dispara un refetch, y bajar antes lleva a la lista vieja.
  useEffect(() => {
    if (abierta == null || cargando) return
    const fila = refsFila.current[abierta]
    if (fila) fila.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [abierta, cargando])

  const proveedores = useMemo(
    () => [...new Set((data?.facturas ?? []).map(f => f.proveedor))].sort(), [data])

  const facturas = useMemo(() => {
    const q = busqueda.trim().toLowerCase()
    const filtradas = (data?.facturas ?? []).filter(f =>
      (!fProveedor || f.proveedor === fProveedor)
      && (fEstado === '' || (fEstado === 'deuda' ? f.estado_pago !== 'pagado' : f.estado_pago === fEstado))
      && (!q || f.proveedor.toLowerCase().includes(q)
        || (f.numero_factura || '').toLowerCase().includes(q)
        || f.items.some(i => i.producto_nombre.toLowerCase().includes(q))))
    // ORDEN, no afirmación: primero lo vencido (bandera del backend), después lo
    // que tiene una fecha explícita, y al final lo que solo tiene plazo. La fecha
    // que se muestra en cada fila sigue la misma precedencia que usa la agenda:
    // la programada manda sobre el vencimiento, y el plazo es el último recurso.
    const clave = (f: Factura) => dia(f.fecha_programada) ?? dia(f.fecha_vencimiento) ?? '9999-12-31'
    return [...filtradas].sort((a, b) =>
      Number(b.vencida) - Number(a.vencida) || clave(a).localeCompare(clave(b)))
  }, [data, busqueda, fProveedor, fEstado])

  const t = data?.totales
  const nVencidas = (data?.facturas ?? []).filter(f => f.vencida).length

  const eliminar = async (f: Factura) => {
    setBorrando(null); setError('')
    try { await api.delete(`/facturas/${f.id}`); refrescar() }
    catch (e) { setError(detalleDeError(e, 'No se pudo eliminar la factura.')) }
  }

  return (
    <Banner
      titulo="Lo que le debo a los proveedores"
      sub={t
        ? <>Falta pagar <b className="font-mono tabular-nums">{plata(t.pendiente)}</b> · ya pagaste{' '}
            <span className="font-mono tabular-nums">{plata(t.pagado)}</span> de{' '}
            <span className="font-mono tabular-nums">{plata(t.facturado)}</span> en {t.n_facturas}{' '}
            {t.n_facturas === 1 ? 'factura' : 'facturas'}
            {nVencidas > 0 && <> · <b className="text-danger-700">{nVencidas} vencida{nVencidas === 1 ? '' : 's'}</b></>}
          </>
        : 'Las facturas que entraron y cuánto se les debe'}
      accion={t && t.facturado > 0 && (
        <span className="text-xs font-mono font-bold tabular-nums text-success-600">
          {Math.round(t.pagado / t.facturado * 100)}% pagado
        </span>
      )}
    >
      {/* Filtros. La caja de búsqueda arriba de todo: es lo único que hace usable
          una lista larga, y busca también DENTRO de los ítems de cada factura. */}
      <div className="px-3 py-2 border-b border-warm-100 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="relative flex-1 min-w-[190px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-warm-400" />
            <input value={busqueda} onChange={e => setBusqueda(e.target.value)}
              placeholder="Buscar proveedor, número de factura o producto…"
              className={`${CLS_INPUT} pl-9`} />
          </div>
          <select value={fEstado} onChange={e => setFEstado(e.target.value as typeof fEstado)}
            aria-label="Estado de pago"
            className="min-h-[38px] border border-warm-200 rounded-full px-3 text-[11px] font-bold bg-white text-warm-600">
            <option value="deuda">Sin pagar</option>
            <option value="">Todas</option>
            <option value="pendiente">Pendiente</option>
            <option value="parcial">Parcial</option>
            <option value="pagado">Pagada</option>
          </select>
          <select value={fProveedor} onChange={e => setFProveedor(e.target.value)}
            aria-label="Proveedor"
            className="min-h-[38px] border border-warm-200 rounded-full px-3 text-[11px] font-bold bg-white text-warm-600">
            <option value="">Todos los proveedores</option>
            {proveedores.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {[{ v: null, l: 'Todas las sedes' }, ...tiendas.map(x => ({ v: x.id, l: x.nombre }))].map(op => (
            <button key={op.v ?? 'todas'} onClick={() => setTiendaId(op.v)}
              className={`min-h-[38px] px-3 rounded-full text-[11px] font-bold border transition-colors ${
                tiendaId === op.v ? 'bg-forest text-white border-forest'
                  : 'bg-white border-warm-200 text-warm-500'}`}>
              {op.l}
            </button>
          ))}
          <label className="flex items-center gap-1 text-[11px] text-warm-500 ml-auto">
            <span className="hidden sm:inline">Recibidas</span>
            <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
              aria-label="Recibidas desde"
              className="min-h-[38px] border border-warm-200 rounded-lg px-2 text-[11px] bg-white" />
            <span className="text-warm-400">→</span>
            <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
              aria-label="Recibidas hasta"
              className="min-h-[38px] border border-warm-200 rounded-lg px-2 text-[11px] bg-white" />
          </label>
        </div>
      </div>

      {error && <div className="px-3 py-2"><ErrorCampo msg={error} /></div>}
      {cargando && <p className="px-4 py-6 text-center text-sm text-warm-400 animate-pulse">Cargando…</p>}

      {/* ── La lista ──────────────────────────────────────────────────────── */}
      <div ref={refLista} className="divide-y divide-warm-100">
        {!cargando && facturas.map(f => {
          const e = ESTADO[f.estado_pago]
          const vence = dia(f.fecha_programada) ?? dia(f.fecha_vencimiento)
          return (
            <div key={f.id} ref={el => { refsFila.current[f.id] = el }}
              className={f.vencida ? 'bg-danger-50/40' : ''}>
              <div className="flex items-start gap-2 px-3 py-2.5">
                {f.imagen_url ? (
                  <a href={f.imagen_url} target="_blank" rel="noreferrer" className="shrink-0"
                    title="Ver la foto de la factura">
                    <img src={f.imagen_url} alt={`Factura de ${f.proveedor}`}
                      className="h-12 w-12 object-cover rounded-lg border border-warm-200 hover:opacity-80" />
                  </a>
                ) : (
                  <div className="h-12 w-12 shrink-0 rounded-lg border border-dashed border-warm-200 flex items-center justify-center text-[9px] text-warm-400">
                    sin foto
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-bold text-warm-700 truncate min-w-0 flex-1">{f.proveedor}</p>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 shrink-0 border ${e.cls}`}>
                      <e.Icon size={11} /> {e.label}
                    </span>
                  </div>
                  <p className="text-[11px] text-warm-500 truncate">
                    {f.numero_factura ? `Fact. ${f.numero_factura} · ` : ''}
                    {f.tienda_nombre || ''}
                    {f.fecha_recibido ? ` · recibida ${fechaCorta(dia(f.fecha_recibido)!)}` : ''}
                  </p>
                  {/* La línea de cuándo pagarla es la MISMA que alimenta la
                      agenda: la fecha que vos elegís manda sobre las dos. */}
                  {(f.fecha_vencimiento || f.fecha_programada || f.plazo_dias != null) && (
                    <p className={`text-[11px] flex items-center gap-1 ${
                      f.vencida ? 'text-danger-700 font-bold' : 'text-warm-500'}`}>
                      <CalendarClock size={11} />
                      {f.fecha_programada ? `La pagás el ${fechaCorta(dia(f.fecha_programada)!)}`
                        : f.fecha_vencimiento ? `Vence ${fechaCorta(dia(f.fecha_vencimiento)!)}`
                        : `Plazo ${f.plazo_dias} días desde que la recibiste`}
                      {f.vencida && ' · VENCIDA'}
                    </p>
                  )}
                  <div className="flex items-center gap-3 mt-0.5 text-xs flex-wrap font-mono tabular-nums">
                    <span className="text-warm-500">Total <b className="text-warm-700">{plata(f.valor_total)}</b></span>
                    <span className="text-warm-500">Pagado <b className="text-success-600">{plata(f.valor_pagado)}</b></span>
                    {f.saldo > 0 && (
                      <span className="text-warm-500">Saldo <b className="text-danger-700">{plata(f.saldo)}</b></span>
                    )}
                    {f.forma_pago_real && (
                      <span className="font-sans text-[10px] px-2 py-0.5 rounded-full font-bold bg-forest-50 text-forest border border-forest-100">
                        Pagada con {f.forma_pago_real}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Acciones: pagar adelante (es la que se busca), el resto detrás
                  del detalle. */}
              <div className="flex items-center gap-1.5 px-3 pb-2.5 flex-wrap">
                {f.estado_pago !== 'pagado' && (
                  <button onClick={() => { setPagando(p => (p === f.id ? null : f.id)); setEditando(null) }}
                    className="flex items-center gap-1.5 text-[11px] font-bold text-white bg-forest hover:bg-forest-700 px-3 min-h-[38px] rounded-lg">
                    <Wallet size={13} /> Registrar pago
                  </button>
                )}
                <button onClick={() => setAbierta(a => (a === f.id ? null : f.id))}
                  className="flex items-center gap-1 text-[11px] font-bold text-warm-600 bg-warm-100 hover:bg-warm-200 px-3 min-h-[38px] rounded-lg">
                  {abierta === f.id ? '▾' : '▸'} Detalle
                  {f.items.length > 0 && ` · ${f.items.length} producto${f.items.length === 1 ? '' : 's'}`}
                </button>
                {f.imagen_soporte_url ? (
                  <a href={f.imagen_soporte_url} download target="_blank" rel="noreferrer"
                    className="flex items-center gap-1 text-[11px] font-bold text-success-600 border border-success-200 bg-success-50 px-2.5 min-h-[38px] rounded-lg">
                    <Download size={12} /> Soporte de pago
                  </a>
                ) : (
                  <span className="text-[11px] text-warm-400 px-1">Sin soporte de pago</span>
                )}
              </div>

              {pagando === f.id && (
                <FormPagoFactura key={`pf-${f.id}`} factura={f}
                  onCancelar={() => setPagando(null)}
                  onPagado={() => { setPagando(null); refrescar() }} />
              )}

              {abierta === f.id && (
                <div className="px-3 pb-3 space-y-2 bg-warm-50/60 border-t border-warm-100 pt-2.5">
                  {f.items.length > 0 ? (
                    <div className="rounded-xl border border-warm-200 bg-white divide-y divide-warm-100">
                      {f.items.map(i => (
                        <div key={i.id} className="flex items-center justify-between gap-2 px-3 py-1.5 text-[11px]">
                          <span className="min-w-0 truncate text-warm-700">{i.producto_nombre}</span>
                          <span className="font-mono tabular-nums font-semibold text-warm-700 shrink-0">
                            {Math.round(i.cantidad)} {i.unidad_medida}
                            {i.precio_unitario ? ` · ${plata(i.precio_unitario)} c/u` : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-warm-500">
                      Esta factura no tiene productos cargados: entró como un total sin detalle, así
                      que no aporta costos de insumo.
                    </p>
                  )}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {f.imagen_url && (
                      <a href={f.imagen_url} download target="_blank" rel="noreferrer"
                        className="flex items-center gap-1 text-[11px] font-bold text-warm-600 border border-warm-200 bg-white px-2.5 min-h-[38px] rounded-lg">
                        <Download size={12} /> Descargar la factura
                      </a>
                    )}
                    <button onClick={() => { setEditando(x => (x === f.id ? null : f.id)); setPagando(null) }}
                      className="flex items-center gap-1 text-[11px] font-bold text-forest bg-forest-50 hover:bg-forest-100 px-3 min-h-[38px] rounded-lg">
                      <Pencil size={12} /> Corregir la factura
                    </button>
                    {/* LA ACCIÓN MÁS DESTRUCTIVA DEL MÓDULO: toca inventario,
                        lotes y caja. Por eso vive acá adentro y no al lado de
                        «Registrar pago». */}
                    {borrando === f.id ? (
                      <span className="flex flex-wrap items-center gap-2 text-[11px] text-danger-700">
                        Se revierte TODO: la entrada de inventario, los lotes y el egreso de caja
                        si se pagó en efectivo.
                        <button onClick={() => eliminar(f)}
                          className="min-h-[36px] px-3 rounded-lg font-bold text-white bg-danger-500 hover:bg-danger-600">
                          Eliminar
                        </button>
                        <button onClick={() => setBorrando(null)}
                          className="min-h-[36px] px-2 rounded-lg font-bold text-warm-500">No</button>
                      </span>
                    ) : (
                      <button onClick={() => setBorrando(f.id)}
                        className="ml-auto flex items-center gap-1 text-[11px] font-bold text-danger-600 border border-danger-200 hover:bg-danger-50 px-2.5 min-h-[38px] rounded-lg">
                        <Trash2 size={12} /> Eliminar
                      </button>
                    )}
                  </div>
                </div>
              )}

              {editando === f.id && (
                <FormEditarFactura key={`ef-${f.id}`} factura={f}
                  onCancelar={() => setEditando(null)}
                  onGuardado={() => { setEditando(null); refrescar() }} />
              )}
            </div>
          )
        })}
      </div>

      {!cargando && !error && facturas.length === 0 && (
        <div className="px-4 py-8 text-center">
          <Receipt size={24} className="text-warm-300 mx-auto mb-2" />
          {/* Con el filtro por defecto en «Sin pagar», el vacío es una BUENA
              noticia y hay que escribirla como tal. */}
          <p className="text-sm text-warm-500">
            {fEstado === 'deuda' && !busqueda && !fProveedor
              ? 'No le debés nada a ningún proveedor en este rango.'
              : 'No hay facturas con esos filtros.'}
          </p>
          <p className="text-[11px] text-warm-400 mt-1">
            Las facturas las cargan las baristas al recibir la mercadería, con la foto del papel.
          </p>
        </div>
      )}

      <ComoSeCalcula titulo="¿Cómo se decide cuándo vence una factura?">
        <p>
          Hay tres formas de fechar el pago y una precedencia fija: <b>la fecha que vos elegís</b>{' '}
          («la vas a pagar el») manda sobre la fecha de vencimiento, y esa manda sobre el plazo en
          días contado desde que la recibiste. Sin ninguna de las tres, la factura existe y se debe,
          pero <b>no entra a la agenda ni a la proyección</b>: se le pone una desde «Corregir la
          factura».
        </p>
        <p>
          «VENCIDA» lo decide el backend, no la pantalla: es tener saldo y que la fecha de pago ya
          haya pasado. Las vencidas van primero en la lista sin importar el filtro.
        </p>
        <p>
          El rango «Recibidas» filtra por el día en que entró la mercadería, que es la misma base
          que usa «Compras proveedor» en Resultado — ahí está el desglose por proveedor del
          período.
        </p>
      </ComoSeCalcula>
    </Banner>
  )
}

/**
 * Registrar el pago de una FACTURA — inline, en su propia fila.
 *
 * Va por `PATCH /facturas/{id}/pago` con FormData porque acepta la foto del
 * soporte. Es el ÚNICO camino que mueve `valor_pagado`.
 *
 * «Efectivo (sale del cajón)» se rotula así a propósito: esa opción TIENE efecto
 * sobre la caja de la sede, no es solo una etiqueta descriptiva.
 */
function FormPagoFactura({ factura, onCancelar, onPagado }: {
  factura: Factura
  onCancelar: () => void
  onPagado: () => void
}) {
  const [monto, setMonto] = useState(String(Math.round(factura.saldo)))
  const [forma, setForma] = useState('transferencia')
  const [soporte, setSoporte] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const listo = Number(monto) > 0
  const registrar = async () => {
    if (!listo) return
    setGuardando(true); setError('')
    try {
      const fd = new FormData()
      fd.append('monto', monto)
      fd.append('forma_pago', forma)
      if (soporte) fd.append('imagen', soporte)
      await api.patch(`/facturas/${factura.id}/pago`, fd)
      onPagado()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo registrar el pago. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="px-3 py-3 bg-forest-50 border-y border-forest-100 space-y-2">
      <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
        Pagarle a {factura.proveedor} · saldo{' '}
        <span className="font-mono tabular-nums text-danger-700">{plata(factura.saldo)}</span>
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 items-end">
        <Campo label="Monto a pagar">
          <input type="text" inputMode="numeric" value={conMiles(monto)} autoFocus
            onChange={e => setMonto(soloDigitos(e.target.value))}
            aria-label="Monto a pagar" className={CLS_INPUT_PLATA} />
        </Campo>
        <Campo label="Forma de pago">
          <select value={forma} onChange={e => setForma(e.target.value)} className={CLS_INPUT}>
            <option value="efectivo">Efectivo (sale del cajón)</option>
            <option value="transferencia">Bancos</option>
            <option value="cheque">Cheque</option>
            <option value="otro">Otro</option>
          </select>
        </Campo>
        <Campo label="Foto del soporte (opcional)">
          <label className={`${CLS_INPUT} flex items-center gap-2 cursor-pointer text-warm-500 truncate`}>
            <Camera size={15} className="shrink-0" />
            <span className="truncate">{soporte ? soporte.name : 'Adjuntar comprobante'}</span>
            <input type="file" accept="image/*" capture="environment" className="hidden"
              onChange={e => setSoporte(e.target.files?.[0] ?? null)} />
          </label>
        </Campo>
      </div>
      <p className="text-[11px] text-warm-500 leading-snug">
        Con «Efectivo» la plata sale del cajón de la sede y el sistema lo registra como egreso de
        caja. Con «Bancos» no: el saldo del banco baja cuando cargues la salida en el libro.
      </p>
      <ErrorCampo msg={error} />
      <div className="flex gap-2">
        <button onClick={onCancelar} className={CLS_BOTON_SUAVE}>Cancelar</button>
        <button onClick={registrar} disabled={guardando || !listo} className={`${CLS_BOTON_GUARDAR} flex-1`}>
          {guardando ? 'Guardando…' : 'Confirmar pago'}
        </button>
      </div>
    </div>
  )
}

/**
 * Corregir una factura entera — inline.
 *
 * Es el ÚNICO lugar de toda la app donde se puede editar una factura y el único
 * donde se le pone la fecha que la mete en la agenda. Se conserva completo:
 * proveedor, número, fecha, tipo de pago, las tres formas de fechar el pago,
 * cantidades y precios por ítem, quitar un ítem, total y ya pagado.
 *
 * LAS TRES FECHAS VAN SIEMPRE, Y EN NULL CUANDO SE VACÍAN: así se puede BORRAR
 * una fecha programada puesta por error, que es la que manda sobre las otras dos.
 */
function FormEditarFactura({ factura, onCancelar, onGuardado }: {
  factura: Factura
  onCancelar: () => void
  onGuardado: () => void
}) {
  const [proveedor, setProveedor] = useState(factura.proveedor)
  const [numero, setNumero] = useState(factura.numero_factura ?? '')
  const [fecha, setFecha] = useState(dia(factura.fecha_recibido) ?? '')
  const [tipoPago, setTipoPago] = useState(factura.tipo_pago)
  const [vence, setVence] = useState(dia(factura.fecha_vencimiento) ?? '')
  const [plazo, setPlazo] = useState(factura.plazo_dias != null ? String(factura.plazo_dias) : '')
  const [programada, setProgramada] = useState(dia(factura.fecha_programada) ?? '')
  const [total, setTotal] = useState(String(Math.round(factura.valor_total)))
  const [pagado, setPagado] = useState(String(Math.round(factura.valor_pagado)))
  const [items, setItems] = useState(factura.items.map(i => ({
    id: i.id, nombre: i.producto_nombre, unidad: i.unidad_medida,
    cantidad: String(i.cantidad), precio: String(Math.round(i.precio_unitario || 0)),
  })))
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const listo = Number(total) > 0
  const guardar = async () => {
    if (!listo) return
    setGuardando(true); setError('')
    try {
      await api.patch(`/facturas/${factura.id}`, {
        valor_total: Number(total),
        valor_pagado: Number(pagado) || 0,
        proveedor: proveedor.trim() || undefined,
        numero_factura: numero.trim(),
        fecha_recibido: fecha || undefined,
        tipo_pago: tipoPago || undefined,
        fecha_vencimiento: vence || null,
        plazo_dias: plazo === '' ? null : Number(plazo),
        fecha_programada: programada || null,
        items: items.map(i => ({
          id: i.id, cantidad: Number(i.cantidad) || 0, precio_unitario: Number(i.precio) || 0,
        })),
      })
      onGuardado()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo corregir la factura. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="px-3 py-3 bg-warm-50 border-y border-warm-200 space-y-2">
      <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
        Corregir la factura de {factura.proveedor}
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
        <Campo label="Proveedor" ancho="col-span-2">
          <input value={proveedor} onChange={e => setProveedor(e.target.value)} className={CLS_INPUT} />
        </Campo>
        <Campo label="N° de factura">
          <input value={numero} onChange={e => setNumero(e.target.value)} className={CLS_INPUT} />
        </Campo>
        <Campo label="Fecha recibida">
          <input type="date" value={fecha} onChange={e => setFecha(e.target.value)} className={CLS_INPUT} />
        </Campo>
        <Campo label="Tipo de pago">
          <select value={tipoPago} onChange={e => setTipoPago(e.target.value)} className={CLS_INPUT}>
            <option value="contado">Contado (efectivo)</option>
            <option value="transferencia">Transferencia</option>
            <option value="credito">Crédito</option>
          </select>
        </Campo>
        <Campo label="Vence">
          <input type="date" value={vence} onChange={e => setVence(e.target.value)} className={CLS_INPUT} />
        </Campo>
        <Campo label="Plazo (días)">
          <input type="number" inputMode="numeric" min={0} value={plazo} placeholder="30"
            onChange={e => setPlazo(e.target.value)} className={`${CLS_INPUT} font-mono`} />
        </Campo>
        <Campo label="La vas a pagar el">
          <input type="date" value={programada} onChange={e => setProgramada(e.target.value)} className={CLS_INPUT} />
        </Campo>
      </div>
      <p className="text-[11px] text-warm-500 leading-snug">
        Sin fecha de vencimiento se calcula con el plazo desde el día que la recibiste. La fecha
        que <b>vos</b> elegís para pagarla manda sobre las otras dos. Sin ninguna de las tres, la
        factura no entra a la agenda ni a la proyección.
      </p>

      {items.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 mb-1">
            Productos ingresados
          </p>
          <div className="rounded-xl border border-warm-200 bg-white divide-y divide-warm-100">
            {items.map(it => (
              <div key={it.id} className="flex items-center gap-2 px-2.5 py-1.5">
                <span className="flex-1 min-w-0 text-[11px] text-warm-700 truncate">{it.nombre}</span>
                <input type="number" inputMode="decimal" min={0} value={it.cantidad}
                  aria-label={`Cantidad de ${it.nombre}`}
                  onChange={e => setItems(p => p.map(x => x.id === it.id ? { ...x, cantidad: e.target.value } : x))}
                  className="w-16 min-h-[38px] text-right rounded-lg border-2 border-warm-200 px-2 text-xs font-bold font-mono tabular-nums focus:outline-none focus:border-forest" />
                <span className="text-[10px] text-warm-400 w-8 shrink-0">{it.unidad}</span>
                <input type="text" inputMode="numeric" value={conMiles(it.precio)} placeholder="c/u"
                  aria-label={`Precio unitario de ${it.nombre}`}
                  onChange={e => setItems(p => p.map(x => x.id === it.id ? { ...x, precio: soloDigitos(e.target.value) } : x))}
                  className="w-20 min-h-[38px] text-right rounded-lg border-2 border-warm-200 px-2 text-xs font-mono tabular-nums focus:outline-none focus:border-forest" />
                <button onClick={() => setItems(p => p.filter(x => x.id !== it.id))}
                  aria-label={`Quitar ${it.nombre}`} title="Quitar el producto (revierte su entrada de inventario)"
                  className="p-2 rounded-lg text-warm-400 hover:text-danger-600 hover:bg-danger-50 shrink-0">
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-warm-500 mt-1">
            Cambiar la cantidad <b>ajusta el inventario</b> por la diferencia; quitar un producto
            revierte su entrada entera.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 max-w-md">
        <Campo label="Total de la factura">
          <input type="text" inputMode="numeric" value={conMiles(total)}
            onChange={e => setTotal(soloDigitos(e.target.value))}
            aria-label="Total de la factura" className={CLS_INPUT_PLATA} />
        </Campo>
        <Campo label="Ya pagado">
          <input type="text" inputMode="numeric" value={conMiles(pagado)}
            onChange={e => setPagado(soloDigitos(e.target.value))}
            aria-label="Ya pagado" className={CLS_INPUT_PLATA} />
        </Campo>
      </div>
      <p className="text-[11px] text-warm-500">
        Si el pago fue en efectivo, el egreso de caja se ajusta solo por la diferencia.
      </p>

      <ErrorCampo msg={error} />
      <div className="flex gap-2">
        <button onClick={onCancelar} className={CLS_BOTON_SUAVE}>Cancelar</button>
        <button onClick={guardar} disabled={guardando || !listo} className={`${CLS_BOTON_GUARDAR} flex-1`}>
          {guardando ? 'Guardando…' : 'Guardar cambios'}
        </button>
      </div>
    </div>
  )
}
