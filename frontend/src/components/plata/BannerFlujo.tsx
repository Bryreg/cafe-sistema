import { useMemo } from 'react'
import { AlertCircle, CheckCircle, Pencil, TrendingDown } from 'lucide-react'
import { Agenda, Flujo } from './tipos'
import { fechaCorta, plata } from './banco'
import { Banner, ComoSeCalcula } from './campos'
import { hoyBogota } from '../../utils/fechaLocal'

const sumarDias = (iso: string, n: number) => {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return d.toLocaleDateString('en-CA')
}

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * ¿ME ALCANZA? — lo que todavía NO pasó
 * ═════════════════════════════════════════════════════════════════════════════
 * Este banner es la ESTIMACIÓN, y por eso está separado del libro aunque los dos
 * hablen de plata: el libro es lo que ya se movió, esto es lo que va a pasar si
 * nada cambia. Cuando el saldo proyectado se pintaba encima de la grilla del
 * libro, dos números que no significan lo mismo se leían como si sí.
 *
 * ── TRES ESTADOS, NO DOS ───────────────────────────────────────────────────
 * Rojo (hay punto de quiebre), ÁMBAR (no hay quiebre pero falta información) y
 * verde (no hay quiebre y los datos están). El ámbar es el que impide que un
 * «no sé» se lea como «estás bien»: las ENTRADAS se derivan solas de cada
 * ticket, pero las SALIDAS existen solo si alguien las tecleó. La presencia de
 * un punto de quiebre significa algo; su ausencia, sola, no significa nada.
 *
 * ── LO VENCIDO NO ES «LO QUE VIENE» ────────────────────────────────────────
 * «Próximos 7 y 30 días» filtra `!vencida` a propósito: mezclar una mora vieja
 * ahí adentro la haría leer como un pago futuro, que es lo contrario de lo que
 * es. Lo vencido tiene su propio banner, arriba y en rojo.
 */
export default function BannerFlujo({ agenda, flujo, cargando, onActualizarExtracto }: {
  agenda: Agenda | null
  flujo: Flujo | null
  cargando: boolean
  /** Sube hasta el editor del extracto: es el ÚNICO editor del ancla que queda. */
  onActualizarExtracto: () => void
}) {
  const items = agenda?.items ?? []
  // EL RELOJ NO ES EL FLUJO. «Se paga en 7 días» y «en 30» salen de la AGENDA;
  // del flujo solo se necesitaba saber qué día es hoy. Cortando cuando `flujo`
  // viene null, los dos montos se imprimían en $0 —plata exacta, sin «—»— aunque
  // la agenda hubiera cargado bien: el banner decía arriba «no se pudo calcular
  // la proyección» y abajo afirmaba que esta semana no hay que pagarle nada a
  // nadie. Los dos fetch son independientes y ese estado es alcanzable.
  const hoy = flujo?.hoy ?? hoyBogota()

  const { prox7, prox30 } = useMemo(() => {
    const t7 = sumarDias(hoy, 7)
    const t30 = sumarDias(hoy, 30)
    const porVencer = items.filter(i => !i.vencida)
    return {
      prox7: porVencer.filter(i => i.fecha <= t7).reduce((s, i) => s + i.monto, 0),
      prox30: porVencer.filter(i => i.fecha <= t30).reduce((s, i) => s + i.monto, 0),
    }
  }, [items, hoy])

  /**
   * Lo que le falta a la proyección para significar algo. Se arma en UN solo
   * lugar porque el mismo listado gobierna el COLOR del banner y su TEXTO: sin
   * salidas cargadas, un verde estaría afirmando una seguridad que nadie
   * verificó.
   */
  const faltantes = useMemo(() => {
    const a = flujo?.advertencias
    if (!flujo || !a) return [] as { titulo: string; detalle: string; banco?: boolean }[]
    const out: { titulo: string; detalle: string; banco?: boolean }[] = []
    if (a.sin_salidas_cargadas) out.push({
      titulo: `No hay pagos cargados en los próximos ${flujo.dias} días`,
      detalle: 'Si tenés cuentas por pagar —arriendo, nómina, proveedores—, cargalas para que '
        + 'esta proyección signifique algo. Como está, solo sabe de la plata que entra.',
    })
    if (a.sin_historia_ventas) out.push({
      titulo: 'No hay ventas de las últimas 8 semanas para estimar lo que entra',
      detalle: 'La proyección está asumiendo que no entra un peso. Con ventas registradas, cada '
        + 'día toma la mediana de su mismo día de la semana.',
    })
    if (a.excluye_corporativas) out.push({
      titulo: `Esta vista no incluye ${plata(a.corporativas_fuera)} de gastos corporativos`,
      detalle: 'El arriendo y la nómina no pertenecen a ninguna sede, así que quedan afuera — y '
        + 'el saldo del banco tampoco suma, porque la cuenta es de la empresa.',
    })
    if (a.saldo_banco_desactualizado) out.push({
      titulo: flujo.caja_hoy.saldo_banco_fecha
        ? `El último extracto que cargaste es del ${fechaCorta(flujo.caja_hoy.saldo_banco_fecha)}`
        : 'Todavía no cargaste el saldo del banco',
      detalle: 'El sistema registra las consignaciones pero nunca el saldo de la cuenta: ese '
        + 'número lo tenés que mirar vos. El libro le suma los movimientos que vas tecleando, '
        + 'pero eso no es haberlo comparado contra el banco: lo que no tecleaste —un débito '
        + 'automático, una comisión— no está en ninguna parte.',
      banco: true,
    })
    return out
  }, [flujo])

  const quiebre = flujo?.punto_de_quiebre ?? null
  const tono = quiebre ? 'rojo' : faltantes.length > 0 ? 'ambar' : 'blanco'

  // Escala del gráfico: el mayor valor ABSOLUTO de la serie. Con una escala solo
  // sobre los positivos, un saldo muy negativo se sale del cajón y el día del
  // quiebre —lo único que importa acá— se ve como una barrita cualquiera.
  const escala = useMemo(
    () => Math.max(1, ...(flujo?.serie ?? []).map(p => Math.abs(p.saldo))), [flujo])
  // Solo los días con movimiento: 30 filas de ceros esconden las 4 que importan.
  const diasConMovimiento = useMemo(
    () => (flujo?.serie ?? []).filter(p => p.entradas > 0 || p.salidas > 0), [flujo])

  const porCategoria = agenda?.por_categoria ?? []
  const totalAgendado = agenda?.totales.monto ?? 0

  return (
    <Banner
      tono={tono}
      titulo={
        cargando ? 'Calculando la proyección…'
        : !flujo ? 'No se pudo calcular la proyección'
        : quiebre ? (
          <>Te quedás sin plata el {fechaCorta(quiebre)}
            {flujo.dias_hasta_quiebre != null && (
              <span className="font-semibold"> — en {flujo.dias_hasta_quiebre} día
                {flujo.dias_hasta_quiebre !== 1 ? 's' : ''}</span>
            )}
          </>
        ) : faltantes.length > 0
          ? 'Falta información para saber si estás bien'
          : `No te quedás sin plata en los próximos ${flujo.dias} días`
      }
      sub={
        !flujo ? undefined
        : quiebre
          ? 'Con lo que hay hoy, lo que se espera vender y lo que hay que pagar, ese día el saldo '
            + 'se va a negativo. Se mueve pagando algo más tarde o consiguiendo plata antes.'
          : faltantes.length > 0
            ? 'La proyección no encontró ningún día en rojo, pero eso no alcanza para afirmar '
              + 'nada: lo que entra lo calcula sola con tus ventas, lo que sale solo existe si '
              + 'alguien lo cargó.'
            : `El saldo proyectado nunca cruza cero. Terminás el período con ${plata(flujo.totales.saldo_final)}.`
      }
      accion={
        flujo && (quiebre
          ? <TrendingDown size={20} className="text-danger-600" />
          : faltantes.length > 0
            ? <AlertCircle size={20} className="text-gold-700" />
            : <CheckCircle size={20} className="text-success-600" />)
      }
    >
      {/* Lo que falta va ACÁ ARRIBA y no al pie: enterrarlo es exactamente lo que
          convierte un «no sé» en un «estás bien». */}
      {faltantes.length > 0 && (
        <div className="divide-y divide-gold-200/50 bg-gold-50/60">
          {faltantes.map((f, i) => (
            <div key={i} className="flex items-start gap-2 px-4 py-2.5">
              <AlertCircle size={14} className="text-gold-700 mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-bold text-gold-700">{f.titulo}</p>
                <p className="text-[11px] text-gold-700/90 leading-relaxed mt-0.5">{f.detalle}</p>
              </div>
              {/* NO abre otro editor: sube al único que hay. El modal viejo del
                  cajón escribía las MISMAS dos claves (`saldo_banco`,
                  `saldo_banco_fecha`) llamando al MISMO servicio que el editor
                  del extracto — dos formularios para una sola fila. */}
              {f.banco && (
                <button onClick={onActualizarExtracto}
                  className="shrink-0 flex items-center gap-1.5 text-[11px] font-bold text-white bg-gold-600 hover:bg-gold-500 px-3 min-h-[38px] rounded-lg">
                  <Pencil size={12} /> Actualizar
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Los cuatro números que explican el veredicto de arriba. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-warm-100 bg-white">
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Se paga en 7 días</p>
          <p className="text-lg font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {plata(prox7)}
          </p>
        </div>
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Se paga en 30 días</p>
          <p className="text-lg font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {plata(prox30)}
          </p>
        </div>
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
            Entra en {flujo?.dias ?? 30} días
          </p>
          <p className="text-lg font-bold font-mono tabular-nums text-success-600 leading-tight mt-0.5">
            {flujo ? `+ ${plata(flujo.totales.entradas)}` : '—'}
          </p>
          <p className="text-[10px] text-warm-400">venta esperada</p>
        </div>
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
            Sale en {flujo?.dias ?? 30} días
          </p>
          <p className="text-lg font-bold font-mono tabular-nums text-danger-600 leading-tight mt-0.5">
            {flujo ? `− ${plata(flujo.totales.salidas)}` : '—'}
          </p>
          <p className="text-[10px] text-warm-400">lo agendado</p>
        </div>
      </div>

      {/* ── En qué se va la plata que se debe ────────────────────────────────
          `agenda.por_categoria` lo manda el backend YA RESUELTO y nadie lo
          pintaba: hasta ahora la pantalla sabía CUÁNTO se debe pero no de qué,
          y las palabras que el dueño busca («la nómina», «el arriendo») no
          aparecían en ninguna parte.

          EL RÓTULO DICE «TODO LO AGENDADO» PORQUE ESO ES: el backend lo calcula
          sobre `items`, o sea con lo VENCIDO adentro. Llamarlo «lo que viene»
          escondería la mora dentro de un número que se lee como futuro. */}
      {porCategoria.length > 0 && (
        <div className="border-t border-warm-100 bg-white px-4 py-3">
          <div className="flex items-baseline justify-between gap-2 mb-1.5">
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
              Todo lo agendado, por categoría
            </p>
            <p className="text-xs font-mono font-bold tabular-nums text-warm-700">
              {plata(totalAgendado)}
              <span className="text-warm-400 font-normal"> · {agenda?.totales.n ?? 0} pagos</span>
            </p>
          </div>
          <div className="space-y-1">
            {porCategoria.map(g => {
              const pct = totalAgendado > 0 ? (g.monto / totalAgendado) * 100 : 0
              return (
                <div key={g.clave}>
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="min-w-0 truncate text-warm-700 font-semibold">{g.nombre}</span>
                    <span className="font-mono tabular-nums text-warm-600 shrink-0">
                      {plata(g.monto)} <span className="text-warm-400">({g.n})</span>
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-warm-100 overflow-hidden mt-0.5">
                    <div className="h-full rounded-full bg-forest-400"
                      style={{ width: `${Math.max(2, pct)}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
          <p className="text-[11px] text-warm-400 mt-1.5 leading-snug">
            Es todo lo que tiene fecha de pago, con <b>lo vencido adentro</b>. Lo que se cargó sin
            fecha no está acá: va en su propio bloque, más abajo.
          </p>
        </div>
      )}

      {/* El gráfico y el detalle día por día van plegados: el veredicto y los
          cuatro números de arriba ya contestan la pregunta. Esto es para el
          martes en que la respuesta no alcanza. */}
      {flujo && flujo.serie.length > 0 && (
        <ComoSeCalcula titulo="Ver el saldo día por día y de dónde sale la venta esperada">
          <div className="flex items-stretch gap-[3px] overflow-x-auto pb-1" style={{ minHeight: 132 }}>
            {flujo.serie.map(p => {
              const alto = Math.round((Math.abs(p.saldo) / escala) * 56)
              const neg = p.saldo < 0
              const esQuiebre = p.fecha === flujo.punto_de_quiebre
              return (
                <div key={p.fecha} className="flex flex-col items-center justify-center flex-1 min-w-[13px]"
                  title={`${fechaCorta(p.fecha)}\nSaldo: ${plata(p.saldo)}\nEntra: ${plata(p.entradas)}\nSale: ${plata(p.salidas)}`}>
                  <div className="flex flex-col justify-end" style={{ height: 60 }}>
                    {!neg && <div className="w-full rounded-t"
                      style={{ height: alto, minHeight: 2, background: esQuiebre ? '#c64a3a' : '#5c7a4e' }} />}
                  </div>
                  <div className="w-full border-t border-warm-200" />
                  <div className="flex flex-col justify-start" style={{ height: 60 }}>
                    {neg && <div className="w-full rounded-b"
                      style={{ height: alto, minHeight: 2, background: esQuiebre ? '#c64a3a' : '#e6a08f' }} />}
                  </div>
                </div>
              )
            })}
          </div>
          <div className="flex items-center justify-between text-[10px] text-warm-400">
            <span>{fechaCorta(flujo.serie[0].fecha)}</span>
            <span>{fechaCorta(flujo.serie[flujo.serie.length - 1].fecha)}</span>
          </div>
          <p>
            La venta esperada de cada día es la <b>mediana</b> del mismo día de la semana en las
            últimas 8 semanas — no el promedio, para que un solo día raro no infle la proyección.
            Todo lo que ya está vencido se carga entero a mañana: se debe ahora.
          </p>

          {diasConMovimiento.length > 0 && (
            <div className="rounded-xl border border-warm-200 overflow-hidden">
              <p className="px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-warm-500 bg-warm-50 border-b border-warm-100">
                Días con movimiento — proyectados, no reales
              </p>
              <div className="divide-y divide-warm-100">
                {diasConMovimiento.map(p => (
                  <div key={p.fecha}
                    className={`flex items-center gap-2 px-3 py-2 ${p.fecha === flujo.punto_de_quiebre ? 'bg-danger-50/60' : ''}`}>
                    <span className="text-[11px] text-warm-500 w-20 shrink-0">{fechaCorta(p.fecha)}</span>
                    <span className="font-mono text-[11px] tabular-nums text-success-600 w-24 shrink-0 text-right">
                      {p.entradas > 0 ? `+ ${plata(p.entradas)}` : ''}
                    </span>
                    <span className="font-mono text-[11px] tabular-nums text-danger-600 w-24 shrink-0 text-right">
                      {p.salidas > 0 ? `− ${plata(p.salidas)}` : ''}
                    </span>
                    <span className={`font-mono text-xs font-bold tabular-nums ml-auto ${
                      p.saldo < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                      {plata(p.saldo)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <p>
            Estos días son <b>estimaciones</b>: no son las filas del libro de abajo, que es plata
            que ya se movió. Se filtran los días sin nada que mostrar — treinta filas de ceros
            esconderían las cuatro que importan.
          </p>
        </ComoSeCalcula>
      )}
    </Banner>
  )
}
