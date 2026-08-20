import { useMemo, useState } from 'react'
import { Building2, CalendarPlus, Settings2, Truck } from 'lucide-react'
import api from '../../api/client'
import { mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { CuentaBanco, detalleDeError, fechaCorta, plata } from '../plata/banco'
import { Agenda, AgendaItem, AgendaSinFecha } from '../plata/tipos'
import { CLS_INPUT, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE, ErrorCampo, teclas } from '../plata/campos'
import FormPagoObligacion from '../plata/FormPagoObligacion'
import { sumarDias } from './calculo'

// ═════════════════════════════════════════════════════════════════════════════
// 4 · LO QUE HAY QUE PAGAR — UNA SOLA LISTA
// ═════════════════════════════════════════════════════════════════════════════
// Antes esto vivía en tres lugares: el banner rojo de vencidos, las celdas «se
// paga en 7 / en 30 días» del flujo, y el bloque «sin fecha» de obligaciones.
// Las tres decían CUÁNTO y solo una decía CUÁNDO. Acá es una lista sola,
// ordenada por fecha, con el botón de pagar en cada renglón.
//
// ── ESTA LISTA ES DEL NEGOCIO ENTERO, Y NO TIENE FILTRO POR SEDE ──────────
// A propósito. El arriendo y la nómina son CORPORATIVOS: filtrando por sede
// desaparecen de la lista y todo se ve más tranquilo en las dos sedes a la vez.
// Un filtro que apaga los dos gastos más grandes no es una vista, es un sesgo.
//
// ── EL MONTO DE CADA RENGLÓN ES EL SALDO, NO EL TOTAL ────────────────────
// Lo decide el backend (`AgendaItem.monto` ya viene neteado de pagos). Mostrar
// el total de la factura al lado de un botón «Pagar» precargado con el saldo
// son dos números para la misma pregunta.
//
// ── «SIN FECHA» NO SE SUMA A NINGÚN TOTAL DE ARRIBA ──────────────────────
// Y se dice por qué: sin fecha de pago no entran a la proyección, así que
// mientras estén ahí la caja se ve mejor de lo que está. Sumarlos a los otros
// buckets los haría parecer agendados; esconderlos los haría desaparecer.

interface Grupo {
  clave: string
  titulo: string
  items: AgendaItem[]
  total: number
  tono: 'rojo' | 'ambar' | 'normal'
}

/** Los tres buckets con fecha, armados en un solo lugar sobre la agenda `listo`. */
function agrupar(a: Agenda, hoy: string, finDeMes: string): Grupo[] {
  const enUnaSemana = sumarDias(hoy, 7)
  const orden = (x: AgendaItem, y: AgendaItem) => x.fecha.localeCompare(y.fecha)

  const vencido = a.items.filter(i => i.vencida).sort(orden)
  // `!vencida` en los otros dos a propósito: mezclar una mora vieja adentro de
  // «esta semana» la haría leer como un pago futuro, que es lo contrario de lo
  // que es. Lo decide el BACKEND (`vencida`), no una comparación de fechas acá.
  const porVencer = a.items.filter(i => !i.vencida)
  const semana = porVencer.filter(i => i.fecha <= enUnaSemana).sort(orden)
  const resto = porVencer.filter(i => i.fecha > enUnaSemana && i.fecha <= finDeMes).sort(orden)
  const despues = porVencer.filter(i => i.fecha > finDeMes).sort(orden)

  const suma = (xs: AgendaItem[]) => xs.reduce((s, i) => s + i.monto, 0)
  const gs: Grupo[] = [
    { clave: 'vencido', titulo: 'Vencido', items: vencido, total: suma(vencido), tono: 'rojo' },
    { clave: 'semana', titulo: 'Esta semana', items: semana, total: suma(semana), tono: 'ambar' },
    { clave: 'resto', titulo: 'Resto del mes', items: resto, total: suma(resto), tono: 'normal' },
    { clave: 'despues', titulo: 'Después de fin de mes', items: despues, total: suma(despues), tono: 'normal' },
  ]
  return gs.filter(g => g.items.length > 0)
}

/** Un renglón con fecha. El monto es el SALDO que falta. */
function Fila({ item, onPagar, activo, onVerNomina }: {
  item: AgendaItem
  onPagar: (i: AgendaItem) => void
  activo: boolean
  onVerNomina: () => void
}) {
  const esFactura = item.tipo === 'factura'
  const esNomina = item.categoria === 'nomina'
  return (
    <div className={`flex items-center gap-2 px-3 py-2.5 ${activo ? 'bg-forest-50' : ''}`}>
      <span className={`shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase
        tracking-wide px-2 py-1 rounded-lg ${esFactura
          ? 'bg-white text-forest border border-warm-200'
          : 'bg-gold-50 text-gold-700 border border-gold-200'}`}>
        {esFactura ? <Truck size={11} /> : <Building2 size={11} />}
        {esFactura ? 'Proveedor' : (item.categoria_nombre || 'Costo fijo')}
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-warm-700 truncate">{item.concepto}</p>
        {/* `origen_fecha` viene resuelto por el backend y explica POR QUÉ cae ese
            día: sin eso, una factura con plazo de 30 días parece agendada a dedo. */}
        <p className="text-[11px] text-warm-500 truncate">
          {item.beneficiario && item.beneficiario !== item.concepto ? `${item.beneficiario} · ` : ''}
          {item.tienda_nombre || 'Corporativo'}
          {item.referencia ? ` · Fact. ${item.referencia}` : ''}
          {` · ${fechaCorta(item.fecha)}`}
          {item.origen_fecha === 'programada' ? ' (programado)' : ''}
          {item.origen_fecha === 'plazo' ? ' (por plazo del proveedor)' : ''}
        </p>
        {/* NO dice «este número lo calculó el sistema»: `agendar_nomina` acepta
            un monto tecleado por el dueño y la agenda no distingue los dos
            casos. Afirmarlo sería exactamente un dato «cerca del correcto».
            Lo que sí se puede ofrecer es el camino a verlo persona por persona. */}
        {esNomina && (
          <button onClick={onVerNomina}
            className="mt-0.5 inline-flex items-center gap-1 text-[11px] font-bold text-forest
                       underline decoration-dotted">
            <Settings2 size={11} /> ver la nómina persona por persona
          </button>
        )}
      </div>

      <span className={`font-mono font-bold text-sm shrink-0 tabular-nums ${
        item.vencida ? 'text-danger-700' : 'text-warm-700'}`}>
        {plata(item.monto)}
      </span>

      <button onClick={() => onPagar(item)}
        className={`shrink-0 min-h-[46px] px-3 rounded-xl text-[11px] font-bold ${
          activo ? 'bg-forest text-white' : 'text-forest hover:bg-warm-100'}`}>
        Pagar
      </button>
    </div>
  )
}

/** El renglón de una cuenta SIN fecha, con el campo que se la pone. */
function FilaSinFecha({ item, hoy, onListo }: {
  item: AgendaSinFecha; hoy: string; onListo: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [fecha, setFecha] = useState('')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const guardar = async () => {
    if (guardando || !fecha) return
    setGuardando(true); setError('')
    try {
      await api.patch(`/costos/obligaciones/${item.id}`, { fecha_vencimiento: fecha })
      setAbierto(false)
      onListo()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar la fecha. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div>
      <div className="flex items-center gap-2 px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-warm-700 truncate">{item.concepto}</p>
          <p className="text-[11px] text-warm-500 truncate">
            {item.categoria_nombre || 'Costo fijo'} · {item.tienda_nombre || 'Corporativo'}
            {` · devengado el ${fechaCorta(item.fecha_devengo)}`}
          </p>
        </div>
        <span className="font-mono font-bold text-sm text-warm-700 shrink-0 tabular-nums">
          {plata(item.monto)}
        </span>
        <button onClick={() => { setAbierto(v => !v); setFecha(f => f || hoy) }}
          className={`shrink-0 flex items-center gap-1 min-h-[46px] px-3 rounded-xl text-[11px]
            font-bold ${abierto ? 'bg-forest text-white' : 'text-forest hover:bg-warm-100'}`}>
          <CalendarPlus size={13} /> Ponerle fecha
        </button>
      </div>
      {abierto && (
        <div className="px-3 pb-3 space-y-2 bg-warm-50"
          onKeyDown={teclas({ listo: !!fecha, guardar, cancelar: () => setAbierto(false) })}>
          <p className="text-[11px] text-warm-500 leading-relaxed pt-2">
            En cuanto tenga fecha entra a la proyección de caja y a los buckets de arriba.
          </p>
          <div className="flex gap-2">
            <input type="date" value={fecha} onChange={e => setFecha(e.target.value)}
              aria-label="Fecha de pago" className={`${CLS_INPUT} max-w-[180px]`} />
            <button onClick={guardar} disabled={guardando || !fecha} className={CLS_BOTON_GUARDAR}>
              {guardando ? 'Guardando…' : 'Guardar'}
            </button>
            <button onClick={() => setAbierto(false)} className={CLS_BOTON_SUAVE}>Cancelar</button>
          </div>
          <ErrorCampo msg={error} />
        </div>
      )}
    </div>
  )
}

const Cabecera = ({ titulo, total, n, tono }: {
  titulo: string; total: number; n: number; tono: Grupo['tono']
}) => {
  const c = tono === 'rojo' ? 'text-danger-700 bg-danger-50 border-danger-200'
    : tono === 'ambar' ? 'text-gold-700 bg-gold-50 border-gold-200'
    : 'text-warm-600 bg-warm-50 border-warm-200'
  return (
    <div className={`flex items-baseline gap-2 px-3 py-2 border-y ${c}`}>
      <p className="text-[11px] font-bold uppercase tracking-wide flex-1 min-w-0">
        {titulo} <span className="opacity-60">({n})</span>
      </p>
      <p className="font-mono font-bold text-sm tabular-nums shrink-0">{plata(total)}</p>
    </div>
  )
}

export default function BloqueLoQueHayQuePagar({
  agenda, cuentas, hoy, finDeMes, onCambio, onPagarFactura, onVerNomina,
}: {
  agenda: Fuente<Agenda>
  cuentas: Fuente<CuentaBanco[]>
  hoy: string
  /** Último día del mes, para partir «resto del mes» de «después». */
  finDeMes: string
  onCambio: () => void
  /**
   * Las FACTURAS no se pagan acá.
   *
   * `POST /costos/pagos` con `factura_id` guarda el pago pero NO mueve
   * `FacturaCompra.valor_pagado`, así que el saldo quedaría igual y la factura
   * seguiría en esta lista debiendo lo mismo. El único camino real es
   * `PATCH /facturas/{id}/pago`, que vive en el bloque de proveedores: se baja
   * hasta su fila y se abre ahí.
   */
  onPagarFactura: (id: number) => void
  onVerNomina: () => void
}) {
  const [pagando, setPagando] = useState<AgendaItem | null>(null)
  /** El pago quedó, pero la salida del banco falló. Sube desde el formulario,
   *  que se desmonta en ese mismo render y no puede mostrarlo él. */
  const [avisoPago, setAvisoPago] = useState('')

  const grupos = useMemo(
    () => mapDato(agenda.dato, a => ({ grupos: agrupar(a, hoy, finDeMes), agenda: a })),
    [agenda.dato, hoy, finDeMes])

  const clave = pagando ? `${pagando.tipo}-${pagando.id}` : null

  const pedirPago = (i: AgendaItem) => {
    if (i.tipo === 'factura') { setPagando(null); onPagarFactura(i.id); return }
    setPagando(p => (p && p.id === i.id && p.tipo === i.tipo ? null : i))
  }

  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="flex items-baseline gap-2 px-4 py-3 border-b border-warm-100">
        <h2 className="text-sm font-bold text-warm-700 flex-1 min-w-0">
          Lo que hay que pagar — una sola lista
        </h2>
        <SegunDato
          dato={agenda.dato}
          cargando={<span className="text-sm font-bold font-mono text-warm-400">…</span>}
          falla={() => <span className="text-sm font-bold font-mono text-warm-400">—</span>}
          listo={a => (
            <span className="text-sm font-bold font-mono tabular-nums text-warm-700 shrink-0">
              {plata(a.totales.monto)}
            </span>
          )} />
      </div>

      {avisoPago && (
        <div className="flex items-start gap-2 border-b border-gold-200 bg-gold-50 px-3 py-2.5">
          <p className="flex-1 text-xs text-gold-700 leading-relaxed">{avisoPago}</p>
          <button onClick={() => setAvisoPago('')}
            className="shrink-0 text-[11px] font-bold text-gold-700 underline decoration-dotted">
            Entendido
          </button>
        </div>
      )}

      <SegunDato
        dato={grupos}
        cargando={<p className="px-4 py-8 text-center text-sm text-warm-400">Leyendo la agenda…</p>}
        falla={m => (
          <div className="p-3">
            {/* EL HUECO OCUPA LUGAR A PROPÓSITO. Esta sección estaba condicionada
                a `items.length > 0` con `items` saliendo de `agenda?.items ?? []`:
                con la agenda caída el bloque rojo NO APARECÍA, y una pantalla sin
                bloque rojo dice «no hay nada atrasado» tan claro como si lo
                escribiera. Es la mentira más cara de la página. */}
            <NoSeSabe bloque onReintentar={agenda.recargar}
              mensaje={`${m} — no se sabe qué hay que pagar ni si algo está vencido. Que no `
                + 'aparezca la lista de siempre no quiere decir que estés al día.'} />
          </div>
        )}
        listo={({ grupos: gs, agenda: a }) => (<>
          {gs.length === 0 && a.sin_fecha.length === 0 ? (
            <p className="px-4 py-6 text-sm text-warm-500 leading-relaxed">
              No hay nada agendado. El arriendo, la nómina y los servicios se cargan más abajo,
              en <b>lo que sube el piso</b>; las facturas de proveedor traen su plazo desde el
              bloque de proveedores. Sin nada agendado, la proyección solo sabe de la plata que
              entra — y se ve mejor de lo que está.
            </p>
          ) : gs.map(g => (
            <div key={g.clave}>
              <Cabecera titulo={g.titulo} total={g.total} n={g.items.length} tono={g.tono} />
              <div className="divide-y divide-warm-100">
                {g.items.map(i => (
                  <div key={`${i.tipo}-${i.id}`}>
                    <Fila item={i} onPagar={pedirPago}
                      activo={clave === `${i.tipo}-${i.id}`}
                      onVerNomina={onVerNomina} />
                    {clave === `${i.tipo}-${i.id}` && i.tipo === 'obligacion' && (
                      <FormPagoObligacion key={`pg-${i.id}`}
                        obligacionId={i.id}
                        concepto={i.concepto}
                        detalle={[i.categoria_nombre || 'Costo fijo',
                          i.tienda_nombre || 'Corporativo',
                          i.beneficiario || ''].filter(Boolean).join(' · ')}
                        saldo={i.monto}
                        cuentas={cuentas}
                        onCancelar={() => setPagando(null)}
                        onPagado={av => { setPagando(null); onCambio(); setAvisoPago(av || '') }} />
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* ── Sin fecha ─────────────────────────────────────────────────── */}
          {a.sin_fecha.length > 0 && (<>
            <div className="flex items-baseline gap-2 px-3 py-2 border-y border-warm-200 bg-warm-50">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-600 flex-1 min-w-0">
                Sin fecha — no se suman a ningún total de arriba{' '}
                <span className="opacity-60">({a.sin_fecha.length})</span>
              </p>
              <p className="font-mono font-bold text-sm tabular-nums text-warm-600 shrink-0">
                {plata(a.totales.sin_fecha)}
              </p>
            </div>
            <p className="px-3 py-2 text-[11px] text-warm-500 leading-relaxed border-b border-warm-100">
              Sin fecha de pago no entran a la proyección: mientras estén acá, la caja se ve mejor
              de lo que está.
            </p>
            <div className="divide-y divide-warm-100">
              {a.sin_fecha.map(i => (
                <FilaSinFecha key={`sf-${i.tipo}-${i.id}`} item={i} hoy={hoy} onListo={onCambio} />
              ))}
            </div>
          </>)}
        </>)} />

      <p className="px-4 py-2.5 text-[11px] text-warm-400 leading-relaxed border-t border-warm-100">
        Esta lista es del <b>negocio entero</b> y no tiene filtro por sede a propósito: el arriendo
        y la nómina son corporativos, así que filtrando por sede desaparecen de la lista y todo se
        ve más tranquilo en las dos sedes a la vez. El monto de cada renglón es el <b>saldo</b> que
        falta, no el total.
      </p>
    </section>
  )
}

