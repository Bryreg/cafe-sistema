import { useMemo, useState } from 'react'
import {
  AlertCircle, Building2, CalendarClock, ChevronLeft, ChevronRight, History, Inbox,
  Landmark, Receipt, Tag, Truck, Wallet, X,
} from 'lucide-react'
import api from '../../api/client'
import { hoyBogota } from '../../utils/fechaLocal'
import { Agenda, AgendaItem, AgendaSinFecha, Flujo, PuntoFlujo } from '../../pages/Costos'
import { fmt } from '../rentabilidad/helpers'
import ModalRegistrarPago from './ModalRegistrarPago'

// ─── Fechas ───────────────────────────────────────────────────────────────────
// Todo se maneja en ISO 'YYYY-MM-DD' (el mismo formato que devuelve el backend):
// comparar strings ISO es comparar fechas, y así ningún Date con hora se cuela y
// corre un vencimiento un día por el huso.
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const sumarDias = (s: string, n: number) => {
  const d = new Date(s + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return iso(d)
}
const fechaLarga = (s: string) =>
  new Date(s + 'T00:00:00').toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })
const fechaCorta = (s: string) => new Date(s + 'T00:00:00').toLocaleDateString('es-CO')

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
const DIAS_SEMANA = ['L', 'M', 'M', 'J', 'V', 'S', 'D']

// Plata en la celda: solo el orden de magnitud. El monto exacto vive en el detalle
// del día — 42 celdas con 9 dígitos cada una no se leen "de un golpe", que es
// exactamente lo que este calendario tiene que lograr.
const compacto = (v: number) => {
  const a = Math.abs(v)
  const signo = v < 0 ? '−' : ''
  if (a >= 1_000_000) return `${signo}${(a / 1_000_000).toFixed(1).replace('.', ',')}M`
  if (a >= 1_000) return `${signo}${Math.round(a / 1_000)}k`
  return `${signo}${Math.round(a)}`
}

/**
 * Plata · Calendario — «¿qué pago, qué día, y con qué plata lo pago?».
 *
 * Reemplaza la lista por semanas de la agenda vieja por una GRILLA DE MES, que es
 * como el dueño pidió ver el proyectado. Sobre la grilla se superpone el saldo
 * proyectado del flujo: cada día no dice solo cuánto se paga, dice con cuánta
 * plata quedás. Los dos datos ya existían; vivían en pestañas distintas y por eso
 * nunca se leían juntos.
 *
 * UNA SOLA MATEMÁTICA POR CELDA. Dentro del horizonte, el número de arriba es
 * `salidas` de la serie del flujo — literalmente la plata que hace bajar el saldo
 * de abajo—, no una segunda suma hecha acá con otras reglas. Esa segunda suma era
 * el bug: el backend acumula TODO lo que se debe hasta hoy (lo vencido y lo que
 * vence hoy) en hoy+1, porque la serie arranca mañana
 * (services/costos.py::_salidas_por_dia). La celda, en cambio, sumaba solo lo que
 * vencía ese día exacto, así que hoy+1 podía mostrar cero pagos mientras su saldo
 * caía por toda la mora: una celda roja, alarmante y sin nada que abrir.
 *
 * Reglas que NO son cosméticas:
 *  - INVARIANTE: ninguna celda pintada es inerte. Todo lo que se pinta se abre y
 *    se explica —y lo que se pinta sale del flujo, así que el detalle siempre
 *    tiene algo que decir: qué vence, qué arrastra y con cuánto quedás.
 *  - Lo VENCIDO sale arriba y aparte, nunca en una celda del pasado: se debe hoy.
 *    En la grilla reaparece donde la proyección lo cobra (hoy+1), declarado como
 *    arrastre y con el desglose adentro.
 *  - Las obligaciones SIN fecha siguen en su sección propia. No se les inventa un
 *    día — inventarlo sería fabricar un vencimiento que nadie pactó.
 *  - El saldo proyectado solo existe dentro del horizonte del flujo; fuera de él
 *    la celda no muestra saldo en vez de mostrar uno falso.
 */
export default function CalendarioView({
  agenda, flujo, loading, onRefresh, onAbrirObligaciones, onAbrirProveedores, onAbrirFlujo,
}: {
  agenda: Agenda | null
  flujo: Flujo | null
  loading: boolean
  onRefresh: () => void
  onAbrirObligaciones: () => void
  onAbrirProveedores: () => void
  onAbrirFlujo: () => void
}) {
  const hoy = flujo?.hoy ?? hoyBogota()
  // El día donde el flujo cobra todo lo atrasado. No es un detalle de UI: es la
  // definición del backend, y la grilla la espeja en vez de inventar la propia.
  const manana = sumarDias(hoy, 1)
  const [ancla, setAncla] = useState(() => {
    const [y, m] = hoy.split('-').map(Number)
    return new Date(y, m - 1, 1)
  })
  const [diaAbierto, setDiaAbierto] = useState<string | null>(null)

  // registrar pago de una obligación (el modal es compartido con Costos)
  const [pagoDe, setPagoDe] = useState<AgendaItem | null>(null)

  // ponerle fecha a una obligación cargada sin «Vence»
  const [fechando, setFechando] = useState<AgendaSinFecha | null>(null)
  const [fVence, setFVence] = useState('')
  const [fError, setFError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const items = agenda?.items ?? []
  const vencidos = useMemo(
    () => items.filter(i => i.vencida).sort((a, b) => a.fecha.localeCompare(b.fecha)),
    [items])

  // Lo que ya se debe: lo vencido MÁS lo que vence hoy. Es exactamente el conjunto
  // que `_salidas_por_dia` vuelca en hoy+1, así que acá se filtra con la misma
  // condición (`fecha <= hoy`) y no con `vencida` — `vencida` es `fecha < hoy` y
  // dejaría lo de hoy afuera del desglose de una celda que sí lo está cobrando.
  //
  // Sin flujo no hay arrastre que explicar: el arrastre es un efecto de la
  // proyección, y anunciarlo cuando no hay proyección sería hablar de una cuenta
  // que la pantalla no está haciendo.
  const arrastre = useMemo(
    () => (flujo ? items.filter(i => i.fecha <= hoy).sort((a, b) => a.fecha.localeCompare(b.fecha)) : []),
    [items, hoy, flujo])
  const totalArrastre = useMemo(
    () => arrastre.reduce((s, i) => s + i.monto, 0), [arrastre])

  // Lo vencido queda FUERA de las celdas por su fecha real: ya se mostró arriba, y
  // repetirlo en una casilla de la semana pasada lo vuelve a esconder. Lo que vence
  // hoy sí conserva su celda: hoy todavía es un día para pagar.
  const porDia = useMemo(() => {
    const m = new Map<string, AgendaItem[]>()
    for (const i of items) {
      if (i.vencida) continue
      const arr = m.get(i.fecha)
      if (arr) arr.push(i); else m.set(i.fecha, [i])
    }
    return m
  }, [items])

  // La serie del flujo, indexada. Es la fuente del número de arriba y del de abajo
  // de cada celda dentro del horizonte: un solo origen, imposible de desincronizar.
  const flujoPorDia = useMemo(() => {
    const m = new Map<string, PuntoFlujo>()
    for (const p of flujo?.serie ?? []) m.set(p.fecha, p)
    return m
  }, [flujo])

  // Grilla lunes→domingo, con los días de relleno del mes vecino en gris.
  const celdas = useMemo(() => {
    const y = ancla.getFullYear(), mes = ancla.getMonth()
    const primero = new Date(y, mes, 1)
    const arranque = new Date(primero)
    arranque.setDate(1 - ((primero.getDay() + 6) % 7))   // getDay(): 0 = domingo
    return Array.from({ length: 42 }, (_, n) => {
      const d = new Date(arranque)
      d.setDate(arranque.getDate() + n)
      return { fecha: iso(d), dia: d.getDate(), delMes: d.getMonth() === mes }
    })
  }, [ancla])

  // Cuánto VENCE en el mes que se está mirando. Se cuenta por la fecha real de cada
  // obligación y no por lo que sale de las celdas: el arrastre de hoy+1 es la misma
  // plata que ya está contada en su propio día, y sumarla otra vez inflaría el mes.
  const totalMes = useMemo(() => celdas
    .filter(c => c.delMes)
    .reduce((s, c) => s + (porDia.get(c.fecha) ?? []).reduce((t, i) => t + i.monto, 0), 0),
    [celdas, porDia])

  const moverMes = (n: number) => {
    setDiaAbierto(null)
    setAncla(a => new Date(a.getFullYear(), a.getMonth() + n, 1))
  }
  const irAHoy = () => {
    const [y, m] = hoy.split('-').map(Number)
    setDiaAbierto(null)
    setAncla(new Date(y, m - 1, 1))
  }

  const fecharObligacion = async () => {
    if (!fechando) return
    if (!fVence) { setFError('Elegí para cuándo hay que pagarlo'); return }
    setGuardando(true); setFError('')
    try {
      await api.patch(`/costos/obligaciones/${fechando.id}`, { fecha_vencimiento: fVence })
      setFechando(null); onRefresh()
    } catch (e: any) {
      setFError(e.response?.data?.detail || 'No se pudo guardar la fecha. Reintentá.')
    } finally { setGuardando(false) }
  }

  /** Lo que SALE ese día. Dentro del horizonte manda el flujo (es el número que
   *  mueve el saldo); fuera, la única fuente posible es la agenda. */
  const salidasDe = (fecha: string) => {
    const p = flujoPorDia.get(fecha)
    if (p) return p.salidas
    return (porDia.get(fecha) ?? []).reduce((s, i) => s + i.monto, 0)
  }

  const itemsDelDia = diaAbierto ? (porDia.get(diaAbierto) ?? []) : []
  const arrastreDelDia = diaAbierto === manana ? arrastre : []
  const puntoDelDia = diaAbierto ? flujoPorDia.get(diaAbierto) : undefined
  const a = flujo?.advertencias

  return (
    <div className="space-y-3">
      {/* Lo vencido: arriba, aparte y primero. No es "el pasado", es lo que se debe hoy. */}
      {vencidos.length > 0 && (
        <div className="rounded-2xl border border-danger-200 bg-danger-50 overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-danger-200/60">
            <p className="text-sm font-bold text-danger-700">Vencido — pagalo ya</p>
            <span className="font-mono font-bold text-sm text-danger-700 tabular-nums">
              {fmt(agenda?.totales.vencido ?? 0)}
            </span>
          </div>
          <div className="divide-y divide-danger-200/40">
            {vencidos.map(i => (
              <FilaItem key={`v-${i.tipo}-${i.id}`} item={i}
                onPagar={() => setPagoDe(i)} onProveedores={onAbrirProveedores} />
            ))}
          </div>
        </div>
      )}

      {/* Cabecera del mes */}
      <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-warm-100">
          <button onClick={() => moverMes(-1)} aria-label="Mes anterior"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronLeft size={17} /></button>
          <div className="min-w-0 flex-1 text-center">
            <p className="text-sm font-bold text-warm-700 capitalize">
              {MESES[ancla.getMonth()]} {ancla.getFullYear()}
            </p>
            <p className="text-[11px] text-warm-500">{fmt(totalMes)} vence este mes</p>
          </div>
          <button onClick={() => moverMes(1)} aria-label="Mes siguiente"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronRight size={17} /></button>
        </div>

        <div className="grid grid-cols-7 px-2 pt-2">
          {DIAS_SEMANA.map((d, n) => (
            <div key={n} className="text-center text-[10px] font-bold uppercase text-warm-400 pb-1">{d}</div>
          ))}
        </div>

        <div className="grid grid-cols-7 gap-1 px-2 pb-2">
          {celdas.map(c => {
            const punto = flujoPorDia.get(c.fecha)
            const sale = salidasDe(c.fecha)
            const saldo = punto?.saldo
            const enRojo = saldo != null && saldo < 0
            const esHoy = c.fecha === hoy
            const esQuiebre = c.fecha === flujo?.punto_de_quiebre
            const conArrastre = c.fecha === manana && totalArrastre > 0
            // Se abre si hay ALGO que contar: lo que vence, lo que arrastra, o la
            // proyección del día. Fuera del horizonte y sin pagos no hay detalle
            // posible — y tampoco hay pintura, así que el invariante se sostiene.
            const abrible = (porDia.get(c.fecha)?.length ?? 0) > 0 || conArrastre || punto != null
            return (
              <button key={c.fecha}
                onClick={() => setDiaAbierto(d => (d === c.fecha ? null : c.fecha))}
                disabled={!abrible}
                aria-label={`${fechaLarga(c.fecha)}${sale > 0 ? `, ${fmt(sale)} a pagar` : ', sin pagos'}${
                  conArrastre ? ', incluye lo vencido' : ''}${
                  saldo != null ? `, quedás con ${fmt(saldo)}` : ''}`}
                className={`min-h-[58px] rounded-xl border px-1 pt-1 pb-0.5 flex flex-col items-center text-center transition-colors ${
                  !c.delMes ? 'opacity-35 ' : ''
                }${
                  esQuiebre ? 'border-danger-500 bg-danger-50'
                    : enRojo ? 'border-danger-200 bg-danger-50/60'
                    : diaAbierto === c.fecha ? 'border-forest bg-forest-50'
                    : sale > 0 ? 'border-warm-200 bg-warm-50 hover:border-forest'
                    : 'border-transparent'
                }`}>
                <span className={`text-[11px] leading-none ${
                  esHoy ? 'font-extrabold text-forest bg-forest-100 rounded-full px-1.5 py-0.5'
                    : 'font-bold text-warm-600'}`}>
                  {c.dia}
                </span>
                {sale > 0 && (
                  <span className="text-[10px] font-bold font-mono tabular-nums text-warm-700 mt-0.5 leading-none flex items-center gap-0.5">
                    {/* El reloj dice "acá adentro hay plata de otros días": sin esta
                        marca, el salto de monto de hoy+1 no se explica solo. */}
                    {conArrastre && <History size={8} className="text-danger-600 shrink-0" aria-hidden="true" />}
                    {compacto(sale)}
                  </span>
                )}
                {saldo != null && (
                  <span className={`text-[9px] font-mono tabular-nums mt-auto leading-none ${
                    saldo < 0 ? 'text-danger-600 font-bold' : 'text-warm-400'}`}>
                    {compacto(saldo)}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 border-t border-warm-100 text-[10px] text-warm-500">
          <span className="font-bold text-warm-600">Arriba</span> lo que sale ese día ·
          <span className="font-bold text-warm-600">abajo</span> con cuánta plata quedás
          <button onClick={irAHoy} className="ml-auto font-bold text-forest">Hoy</button>
        </div>
        {totalArrastre > 0 && (
          <button onClick={() => setDiaAbierto(manana)}
            className="w-full flex items-center gap-1.5 px-3 py-2 border-t border-warm-100 text-left">
            <History size={12} className="text-danger-600 shrink-0" />
            <span className="text-[10px] text-warm-500 leading-snug">
              El <b className="text-warm-600">{fechaCorta(manana)}</b> carga además {fmt(totalArrastre)} de
              lo vencido y lo que vence hoy: la proyección arranca mañana, así que todo lo que
              se debe hasta hoy pesa sobre ese día. <b className="text-forest">Ver el desglose</b>
            </span>
          </button>
        )}
      </div>

      {/* Honestidad del overlay: fuera del horizonte del flujo NO hay saldo, y el
          silencio tiene que estar dicho o se lee como "no pasa nada ese mes". */}
      {flujo && (
        <p className="text-[11px] text-warm-500 px-1 leading-relaxed">
          El saldo proyectado solo existe para los próximos {flujo.dias} días (hasta el{' '}
          {fechaCorta(flujo.serie[flujo.serie.length - 1]?.fecha ?? hoy)}). Más allá el calendario
          muestra los pagos, pero no inventa un saldo.{' '}
          <button onClick={onAbrirFlujo} className="font-bold text-forest underline decoration-dotted">
            Ver el flujo completo
          </button>
        </p>
      )}

      {/* Lo que le falta a la proyección para significar algo. */}
      {a && (a.sin_salidas_cargadas || a.sin_historia_ventas || a.saldo_banco_desactualizado) && (
        <button onClick={onAbrirFlujo}
          className="w-full flex items-start gap-2 rounded-2xl border border-gold-200 bg-gold-50 px-4 py-3 text-left">
          <AlertCircle size={15} className="text-gold-700 mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-bold text-gold-700">Falta información para el saldo proyectado</span>
            <span className="block text-[11px] text-gold-700/90 leading-relaxed mt-0.5">
              {a.sin_salidas_cargadas && 'No hay ni un pago cargado en el horizonte. '}
              {a.sin_historia_ventas && 'No hay ventas de las últimas 8 semanas para estimar lo que entra. '}
              {a.saldo_banco_desactualizado && 'El saldo del banco está viejo: la proyección arranca de una plata que puede no ser la que hay. '}
            </span>
          </span>
          <Landmark size={15} className="text-gold-700 shrink-0 mt-0.5" />
        </button>
      )}

      {/* Detalle del día. Tiene que poder explicar TRES cosas, porque las tres
          mueven el saldo que la celda pinta: lo que vence ese día, lo que arrastra
          de días anteriores y la venta esperada. */}
      {diaAbierto && (
        <div className="bg-white rounded-2xl border border-forest overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-warm-100">
            <p className="text-sm font-bold text-warm-700 capitalize min-w-0 flex-1 truncate">
              {fechaLarga(diaAbierto)}
            </p>
            <span className="font-mono font-bold text-sm text-warm-700 tabular-nums shrink-0">
              {fmt(salidasDe(diaAbierto))}
            </span>
            <button onClick={() => setDiaAbierto(null)} aria-label="Cerrar el día"
              className="shrink-0 p-1 -mr-1 rounded-lg text-warm-400 hover:bg-warm-100"><X size={15} /></button>
          </div>

          {/* El arrastre va PRIMERO: es lo que hace que el número de arriba no
              coincida con "lo que vence hoy", y leerlo después sería leerlo tarde. */}
          {arrastreDelDia.length > 0 && (
            <div className="border-b border-warm-100 bg-danger-50/40">
              <div className="flex items-start gap-2 px-4 py-2.5">
                <History size={14} className="text-danger-600 mt-0.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold text-danger-700">
                    Arrastre — vencido y lo que vence hoy
                  </p>
                  <p className="text-[11px] text-warm-500 leading-relaxed">
                    La proyección arranca mañana, así que todo lo que se debe hasta hoy pesa sobre
                    este día. Si sale hoy, el saldo mejora en la próxima carga.
                  </p>
                </div>
                <span className="font-mono font-bold text-sm text-danger-700 shrink-0 tabular-nums">
                  {fmt(arrastreDelDia.reduce((s, i) => s + i.monto, 0))}
                </span>
              </div>
              <div className="divide-y divide-danger-200/30">
                {arrastreDelDia.map(i => (
                  <FilaItem key={`a-${i.tipo}-${i.id}`} item={i}
                    onPagar={() => setPagoDe(i)} onProveedores={onAbrirProveedores} />
                ))}
              </div>
            </div>
          )}

          {itemsDelDia.length > 0 && (
            <div className="divide-y divide-warm-100">
              {arrastreDelDia.length > 0 && (
                <p className="px-4 py-2 text-xs font-bold text-warm-600">Vence este día</p>
              )}
              {itemsDelDia.map(i => (
                <FilaItem key={`d-${i.tipo}-${i.id}`} item={i}
                  onPagar={() => setPagoDe(i)} onProveedores={onAbrirProveedores} />
              ))}
            </div>
          )}

          {itemsDelDia.length === 0 && arrastreDelDia.length === 0 && (
            <p className="px-4 py-3 text-xs text-warm-500 leading-relaxed">
              No vence nada este día. El saldo se mueve solo por la venta esperada.
            </p>
          )}

          {/* Los tres números de la proyección para ese día, tal cual los da el
              backend: es la cuenta completa detrás del color de la celda. */}
          {puntoDelDia && (
            <div className="border-t border-warm-100 bg-warm-50/60 px-4 py-2.5">
              <div className="flex items-center justify-between gap-2 text-[11px]">
                <span className="text-warm-500">Venta esperada</span>
                <span className="font-mono tabular-nums text-success-600">+ {fmt(puntoDelDia.entradas)}</span>
              </div>
              <div className="flex items-center justify-between gap-2 text-[11px] mt-0.5">
                <span className="text-warm-500">Sale</span>
                <span className="font-mono tabular-nums text-danger-600">− {fmt(puntoDelDia.salidas)}</span>
              </div>
              <div className="flex items-center justify-between gap-2 text-xs mt-1 pt-1 border-t border-warm-200/70">
                <span className="font-bold text-warm-600">Quedás con</span>
                <span className={`font-mono font-bold tabular-nums ${
                  puntoDelDia.saldo < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                  {fmt(puntoDelDia.saldo)}
                </span>
              </div>
              {diaAbierto === flujo?.punto_de_quiebre && (
                <p className="text-[11px] font-bold text-danger-700 mt-1.5 leading-relaxed">
                  Acá te quedás sin plata. Movés la fecha pagando algo más tarde o consiguiendo
                  plata antes.
                </p>
              )}
            </div>
          )}

          {/* Hoy no tiene punto en la serie (la proyección arranca mañana): decirlo
              es lo que conecta esta celda con el arrastre de la de al lado. */}
          {diaAbierto === hoy && (
            <p className="border-t border-warm-100 px-4 py-2.5 text-[11px] text-warm-500 leading-relaxed">
              La proyección arranca mañana: lo que no salga hoy pesa sobre el saldo del{' '}
              {fechaCorta(manana)}.
            </p>
          )}
        </div>
      )}

      {/* Obligaciones cargadas SIN fecha de pago: no se agendan (no hay para cuándo)
          pero tampoco pueden ser invisibles — sí cuentan en el resultado del mes. */}
      {(agenda?.sin_fecha.length ?? 0) > 0 && (
        <div className="rounded-2xl border border-gold-200 bg-gold-50 overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-gold-200/60">
            <div className="min-w-0">
              <p className="text-sm font-bold text-gold-700">Sin fecha de pago</p>
              <p className="text-[11px] text-gold-700/90 leading-snug">
                Cuentan en el resultado del mes, pero no se pueden agendar ni proyectar hasta
                que tengan una fecha. Ponésela y entran solas al calendario.
              </p>
            </div>
            <span className="font-mono font-bold text-sm text-gold-700 shrink-0 tabular-nums">
              {fmt(agenda?.totales.sin_fecha ?? 0)}
            </span>
          </div>
          <div className="divide-y divide-gold-200/40">
            {(agenda?.sin_fecha ?? []).map(i => (
              <div key={`sf-${i.id}`} className="flex items-center gap-3 px-4 py-2.5">
                <span className="shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg bg-white text-gold-700 border border-gold-200">
                  <Tag size={11} /> {i.categoria_nombre || 'Sin categoría'}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-warm-700 truncate">{i.concepto}</p>
                  <p className="text-[11px] text-warm-500 truncate">
                    {i.tienda_nombre || 'Corporativo'} · devengo {fechaCorta(i.fecha_devengo)}
                  </p>
                </div>
                <span className="font-mono font-bold text-sm text-warm-700 shrink-0 tabular-nums">{fmt(i.monto)}</span>
                <button onClick={() => { setFechando(i); setFVence(i.fecha_devengo || hoy); setFError('') }}
                  className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-white bg-gold-600 hover:bg-gold-500 px-3 py-1.5 rounded-lg">
                  <CalendarClock size={13} /> Poner fecha
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {!loading && items.length === 0 && (agenda?.sin_fecha.length ?? 0) === 0 && (
        <div className="bg-white border border-warm-200 rounded-2xl px-4 py-10 text-center">
          <CalendarClock size={26} className="text-warm-300 mx-auto mb-2" />
          <p className="text-sm text-warm-600">No hay nada agendado</p>
          <p className="text-xs text-warm-400 mt-1">
            Cargá el arriendo, la nómina y los servicios en Obligaciones. Las facturas viejas sin
            plazo tampoco se agendan solas: el plazo se pone en Pagos a proveedores.
          </p>
        </div>
      )}

      {/* Las herramientas que NO son una de las tres pantallas: siguen enteras,
          como cajón, en vez de volver a ser pestañas de primer nivel. */}
      <div className="grid grid-cols-2 gap-2">
        <button onClick={onAbrirObligaciones}
          className="flex items-center gap-2 bg-white rounded-2xl border border-warm-200 px-3 py-3 text-left">
          <Receipt size={16} className="text-forest shrink-0" />
          <span className="min-w-0">
            <span className="block text-sm font-bold text-warm-700">Obligaciones</span>
            <span className="block text-[11px] text-warm-500 leading-snug">Cargar, repetir y anular costos fijos</span>
          </span>
        </button>
        <button onClick={onAbrirProveedores}
          className="flex items-center gap-2 bg-white rounded-2xl border border-warm-200 px-3 py-3 text-left">
          <Truck size={16} className="text-forest shrink-0" />
          <span className="min-w-0">
            <span className="block text-sm font-bold text-warm-700">Pagos a proveedores</span>
            <span className="block text-[11px] text-warm-500 leading-snug">Registrar el pago de una factura</span>
          </span>
        </button>
      </div>

      {/* El modal es el MISMO que usa Costos: `key` fuerza el montaje limpio que su
          estado inicial-desde-props necesita. */}
      {pagoDe && (
        <ModalRegistrarPago key={pagoDe.id}
          obligacion={{
            id: pagoDe.id,
            concepto: pagoDe.concepto,
            saldo: pagoDe.monto,
            detalle: [pagoDe.categoria_nombre || 'Costo fijo',
              pagoDe.tienda_nombre || 'Corporativo',
              pagoDe.beneficiario || ''].filter(Boolean).join(' · '),
          }}
          onCerrar={() => setPagoDe(null)}
          onPagado={() => { setPagoDe(null); onRefresh() }} />
      )}

      {/* Modal: ponerle fecha a una obligación cargada sin «Vence» */}
      {fechando && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setFechando(null)}>
          <div className="bg-white rounded-2xl w-full max-w-sm p-5 space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-warm-700">¿Para cuándo hay que pagarlo?</h2>
              <button onClick={() => setFechando(null)} aria-label="Cerrar" className="text-warm-400"><X size={18} /></button>
            </div>
            <div className="text-sm text-warm-500">
              <p className="font-semibold text-warm-700">{fechando.concepto}</p>
              <p>{fechando.categoria_nombre || 'Sin categoría'} · {fechando.tienda_nombre || 'Corporativo'}
                {' · '}<span className="font-mono font-bold text-warm-700">{fmt(fechando.monto)}</span></p>
            </div>
            <div>
              <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Fecha de pago</label>
              <input type="date" value={fVence} onChange={e => setFVence(e.target.value)}
                className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
              <p className="text-[11px] text-warm-400 mt-1">
                Con esta fecha el costo entra al calendario y a la proyección. El mes al que
                pertenece (el devengo) no cambia.
              </p>
            </div>
            {fError && <p className="text-sm text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-3 py-2">{fError}</p>}
            <button onClick={fecharObligacion} disabled={guardando || !fVence}
              className="w-full bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm">
              {guardando ? 'Guardando...' : 'Guardar fecha'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Fila de un pago, con la CATEGORÍA y el beneficiario adelante — que es como el
 * dueño los nombra («la nómina», «el arriendo»), no «costo fijo».
 *
 * La acción depende del tipo, y no por estética: `POST /costos/pagos` con
 * `factura_id` guarda el pago pero NO mueve `FacturaCompra.valor_pagado`, o sea
 * que el saldo de la factura quedaría igual y el pago se vería como si no hubiera
 * pasado. El camino real de una factura es `PATCH /facturas/{id}/pago`, que vive
 * en Pagos a proveedores: se manda ahí en vez de fingir que se pagó.
 */
function FilaItem({ item, onPagar, onProveedores }: {
  item: AgendaItem
  onPagar: () => void
  onProveedores: () => void
}) {
  const esFactura = item.tipo === 'factura'
  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      <span className={`shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg ${
        esFactura ? 'bg-white text-forest border border-warm-200' : 'bg-gold-50 text-gold-700 border border-gold-200'
      }`}>
        {esFactura ? <Truck size={11} /> : <Building2 size={11} />}
        {esFactura ? 'Proveedor' : (item.categoria_nombre || 'Costo fijo')}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-warm-700 truncate">{item.concepto}</p>
        <p className="text-[11px] text-warm-500 truncate">
          {item.beneficiario && item.beneficiario !== item.concepto ? `${item.beneficiario} · ` : ''}
          {item.tienda_nombre || 'Corporativo'}
          {item.referencia ? ` · Fact. ${item.referencia}` : ''}
          {` · ${fechaCorta(item.fecha)}`}
          {item.origen_fecha === 'programada' ? ' (programado)' : ''}
          {item.origen_fecha === 'plazo' ? ' (por plazo del proveedor)' : ''}
        </p>
      </div>
      <span className={`font-mono font-bold text-sm shrink-0 tabular-nums ${
        item.vencida ? 'text-danger-600' : 'text-warm-700'}`}>
        {fmt(item.monto)}
      </span>
      {esFactura ? (
        <button onClick={onProveedores} title="El pago de una factura se registra en Pagos a proveedores"
          className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-forest bg-forest-50 hover:bg-forest-100 px-3 py-1.5 rounded-lg">
          <Inbox size={13} /> Pagar
        </button>
      ) : (
        <button onClick={onPagar}
          className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-white bg-forest hover:bg-forest-700 px-3 py-1.5 rounded-lg">
          <Wallet size={13} /> Pagar
        </button>
      )}
    </div>
  )
}
