import { ReactNode, useMemo } from 'react'
import { AlertCircle, CheckCircle, CloudOff, Pencil, TrendingDown } from 'lucide-react'
import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { Agenda, Flujo } from './tipos'
import { fechaCorta, plata } from './banco'
import { Banner, ComoSeCalcula } from './campos'
import { hoyBogota } from '../../utils/fechaLocal'

const sumarDias = (iso: string, n: number) => {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return d.toLocaleDateString('en-CA')
}

interface Faltante { titulo: string; detalle: string; banco?: boolean }

/**
 * Lo que le falta a la proyección para significar algo. Se arma en UN solo
 * lugar porque el mismo listado gobierna el COLOR del banner y su TEXTO: sin
 * salidas cargadas, un verde estaría afirmando una seguridad que nadie
 * verificó.
 */
function faltantesDe(flujo: Flujo): Faltante[] {
  const a = flujo.advertencias
  const out: Faltante[] = []
  if (!a) return out
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
}

interface Proyeccion { f: Flujo; faltantes: Faltante[] }
interface Cabecera {
  tono: 'blanco' | 'rojo' | 'ambar'
  titulo: ReactNode
  sub?: ReactNode
  accion?: ReactNode
}

/**
 * El veredicto de arriba, armado en UN solo switch.
 *
 * Título, subtítulo, ícono y color salen del MISMO lugar y del MISMO estado, así
 * que no puede quedar el tilde verde de una rama con el texto de otra. Y las
 * cuatro ramas están escritas: el `Dato` sin `listo` no tiene `valor`, o sea que
 * no hay forma de que un `punto_de_quiebre` inexistente se lea como «no hay
 * quiebre».
 *
 * OJO CON EL BLANCO: en este banner el tono blanco ES el estado bueno («no te
 * quedás sin plata»). Por eso las ramas que no saben van en ÁMBAR y no en
 * blanco: pintar una falla del color del verdicto tranquilizador sería, otra
 * vez, dibujar calma sobre un dato que no volvió.
 */
function cabeceraDe(d: Dato<Proyeccion>): Cabecera {
  switch (d.estado) {
    case 'cargando':
      return { tono: 'blanco', titulo: 'Calculando la proyección…' }
    case 'falla':
      return {
        tono: 'ambar',
        titulo: 'No se pudo calcular la proyección',
        sub: 'No se sabe si te alcanza ni qué día se acaba la plata: el cálculo no volvió.',
        accion: <CloudOff size={20} className="text-gold-700" />,
      }
    case 'sinBase':
      return {
        tono: 'ambar',
        titulo: 'No hay con qué calcular la proyección',
        sub: d.porque,
        accion: <AlertCircle size={20} className="text-gold-700" />,
      }
    case 'listo': {
      const { f, faltantes } = d.valor
      const quiebre = f.punto_de_quiebre
      if (quiebre) return {
        tono: 'rojo',
        titulo: (
          <>Te quedás sin plata el {fechaCorta(quiebre)}
            {f.dias_hasta_quiebre != null && (
              <span className="font-semibold"> — en {f.dias_hasta_quiebre} día
                {f.dias_hasta_quiebre !== 1 ? 's' : ''}</span>
            )}
          </>
        ),
        sub: 'Con lo que hay hoy, lo que se espera vender y lo que hay que pagar, ese día el saldo '
          + 'se va a negativo. Se mueve pagando algo más tarde o consiguiendo plata antes.',
        accion: <TrendingDown size={20} className="text-danger-600" />,
      }
      if (faltantes.length > 0) return {
        tono: 'ambar',
        titulo: 'Falta información para saber si estás bien',
        sub: 'La proyección no encontró ningún día en rojo, pero eso no alcanza para afirmar '
          + 'nada: lo que entra lo calcula sola con tus ventas, lo que sale solo existe si '
          + 'alguien lo cargó.',
        accion: <AlertCircle size={20} className="text-gold-700" />,
      }
      return {
        tono: 'blanco',
        titulo: `No te quedás sin plata en los próximos ${f.dias} días`,
        sub: `El saldo proyectado nunca cruza cero. Terminás el período con ${plata(f.totales.saldo_final)}.`,
        accion: <CheckCircle size={20} className="text-success-600" />,
      }
    }
  }
}

/** Una de las cuatro celdas de plata. `apagado` = no hay cifra, hay un hueco. */
function Celda({ label, valor, pie, color = 'text-warm-700', apagado = false }: {
  label: ReactNode; valor: ReactNode; pie?: ReactNode; color?: string; apagado?: boolean
}) {
  return (
    <div className="px-4 py-3">
      <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">{label}</p>
      <p className={`text-lg font-bold font-mono tabular-nums leading-tight mt-0.5 ${
        apagado ? 'text-warm-400' : color}`}>
        {valor}
      </p>
      {pie && <p className="text-[10px] text-warm-400">{pie}</p>}
    </div>
  )
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
 * blanco (no hay quiebre y los datos están). El ámbar es el que impide que un
 * «no sé» se lea como «estás bien»: las ENTRADAS se derivan solas de cada
 * ticket, pero las SALIDAS existen solo si alguien las tecleó. La presencia de
 * un punto de quiebre significa algo; su ausencia, sola, no significa nada.
 *
 * ── LO VENCIDO NO ES «LO QUE VIENE» ────────────────────────────────────────
 * «Próximos 7 y 30 días» filtra `!vencida` a propósito: mezclar una mora vieja
 * ahí adentro la haría leer como un pago futuro, que es lo contrario de lo que
 * es. Lo vencido tiene su propio banner, arriba y en rojo.
 *
 * ── DOS FUENTES QUE SE CAEN POR SEPARADO ───────────────────────────────────
 * `agenda` y `flujo` son DOS fetch independientes, y este banner tiene que poder
 * mostrar el bueno cuando el otro se cayó. Es una historia con cadáver: los dos
 * montos de «se paga en 7 / en 30 días» salen de la AGENDA y se imprimían en $0
 * —plata exacta, sin «—»— cuando la que fallaba era ELLA. El banner decía arriba
 * «no se pudo calcular la proyección» y abajo afirmaba, con dos cifras, que esta
 * semana no había que pagarle nada a nadie.
 */
export default function BannerFlujo({ agenda, flujo, onActualizarExtracto }: {
  agenda: Fuente<Agenda>
  flujo: Fuente<Flujo>
  /** Sube hasta el editor del extracto: es el ÚNICO editor del ancla que queda. */
  onActualizarExtracto: () => void
}) {
  const proyeccion = useMemo<Dato<Proyeccion>>(
    () => mapDato(flujo.dato, f => ({ f, faltantes: faltantesDe(f) })), [flujo.dato])

  // EL RELOJ NO ES EL FLUJO. «Se paga en 7 días» y «en 30» salen de la AGENDA;
  // del flujo solo se necesitaba saber qué día es hoy, y eso el navegador lo
  // sabe solo (hoyBogota lee el reloj de Colombia, no el del aparato). Que la
  // proyección no vuelva no puede apagar dos montos que no dependen de ella.
  const hoy = flujo.dato.estado === 'listo' ? flujo.dato.valor.hoy : hoyBogota()

  const proximos = useMemo(() => mapDato(agenda.dato, a => {
    const t7 = sumarDias(hoy, 7)
    const t30 = sumarDias(hoy, 30)
    const porVencer = a.items.filter(i => !i.vencida)
    return {
      prox7: porVencer.filter(i => i.fecha <= t7).reduce((s, i) => s + i.monto, 0),
      prox30: porVencer.filter(i => i.fecha <= t30).reduce((s, i) => s + i.monto, 0),
    }
  }), [agenda.dato, hoy])

  const cab = cabeceraDe(proyeccion)

  return (
    <Banner tono={cab.tono} titulo={cab.titulo} sub={cab.sub} accion={cab.accion}>
      {/* Lo que falta va ACÁ ARRIBA y no al pie: enterrarlo es exactamente lo que
          convierte un «no sé» en un «estás bien». Y cuando la que no volvió es la
          proyección entera, el hueco ocupa este mismo lugar con el mismo peso. */}
      <SegunDato
        dato={proyeccion}
        cargando={
          <p className="px-4 py-3 text-[11px] text-warm-400 animate-pulse">
            Calculando el saldo día por día…
          </p>
        }
        falla={m => (
          <div className="px-4 py-3 bg-white">
            <NoSeSabe bloque onReintentar={flujo.recargar}
              mensaje={`${m} — no se sabe si el saldo se va a negativo ni qué día. Que no aparezca `
                + 'un día en rojo acá abajo no significa que no lo haya.'} />
          </div>
        )}
        listo={({ faltantes }) => faltantes.length === 0 ? null : (
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
      />

      {/* Los cuatro números que explican el veredicto de arriba. Las dos primeras
          celdas son de la AGENDA y las dos últimas del FLUJO: cada par se apaga
          por su cuenta, porque cada par se cae por su cuenta. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-warm-100 bg-white">
        <SegunDato
          dato={proximos}
          cargando={<>
            <Celda label="Se paga en 7 días" valor="…" apagado />
            <Celda label="Se paga en 30 días" valor="…" apagado />
          </>}
          falla={() => (<>
            <Celda label="Se paga en 7 días" valor="—" apagado pie="no se pudo leer la agenda" />
            <Celda label="Se paga en 30 días" valor="—" apagado pie="no se pudo leer la agenda" />
          </>)}
          listo={p => (<>
            <Celda label="Se paga en 7 días" valor={plata(p.prox7)} />
            <Celda label="Se paga en 30 días" valor={plata(p.prox30)} />
          </>)}
        />

        <SegunDato
          dato={flujo.dato}
          cargando={<>
            <Celda label="Lo que entra" valor="…" apagado />
            <Celda label="Lo que sale" valor="…" apagado />
          </>}
          falla={() => (<>
            {/* El rótulo pierde el «en 30 días» a propósito: el horizonte lo dice
                la respuesta (`flujo.dias`), y sin respuesta escribirlo sería
                afirmar de qué período es el hueco que se está mostrando. */}
            <Celda label="Lo que entra" valor="—" apagado pie="no se pudo proyectar" />
            <Celda label="Lo que sale" valor="—" apagado pie="no se pudo proyectar" />
          </>)}
          listo={f => (<>
            <Celda label={`Entra en ${f.dias} días`} pie="venta esperada"
              color="text-success-600" valor={`+ ${plata(f.totales.entradas)}`} />
            <Celda label={`Sale en ${f.dias} días`} pie="lo agendado"
              color="text-danger-600" valor={`− ${plata(f.totales.salidas)}`} />
          </>)}
        />
      </div>

      {/* ── En qué se va la plata que se debe ────────────────────────────────
          `agenda.por_categoria` lo manda el backend YA RESUELTO y nadie lo
          pintaba: hasta ahora la pantalla sabía CUÁNTO se debe pero no de qué,
          y las palabras que el dueño busca («la nómina», «el arriendo») no
          aparecían en ninguna parte.

          EL RÓTULO DICE «TODO LO AGENDADO» PORQUE ESO ES: el backend lo calcula
          sobre `items`, o sea con lo VENCIDO adentro. Llamarlo «lo que viene»
          escondería la mora dentro de un número que se lee como futuro. */}
      <SegunDato
        dato={agenda.dato}
        cargando={null}
        falla={m => (
          <div className="border-t border-warm-100 bg-white px-4 py-3">
            <NoSeSabe onReintentar={agenda.recargar}
              mensaje={`${m} — no se sabe cuánto hay que pagar en los próximos días ni en qué `
                + 'se va (nómina, arriendo, proveedores).'} />
          </div>
        )}
        listo={a => {
          // Condicionado por CONTENIDO, no por la forma: sin categorías no hay
          // torta que dibujar, y eso ya lo dice el «$0 · 0 pagos» de arriba.
          if (a.por_categoria.length === 0) return null
          const total = a.totales.monto
          return (
            <div className="border-t border-warm-100 bg-white px-4 py-3">
              <div className="flex items-baseline justify-between gap-2 mb-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
                  Todo lo agendado, por categoría
                </p>
                <p className="text-xs font-mono font-bold tabular-nums text-warm-700">
                  {plata(total)}
                  <span className="text-warm-400 font-normal"> · {a.totales.n} pagos</span>
                </p>
              </div>
              <div className="space-y-1">
                {a.por_categoria.map(g => {
                  const pct = total > 0 ? (g.monto / total) * 100 : 0
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
          )
        }}
      />

      {/* El gráfico y el detalle día por día van plegados: el veredicto y los
          cuatro números de arriba ya contestan la pregunta. Esto es para el
          martes en que la respuesta no alcanza. Solo existe con la proyección
          en la mano — que no esté ya lo explicó el hueco de arriba. */}
      {flujo.dato.estado === 'listo' && flujo.dato.valor.serie.length > 0 && (
        <DiaPorDia flujo={flujo.dato.valor} />
      )}
    </Banner>
  )
}

/** El saldo proyectado día por día. Recibe el flujo YA resuelto: acá no hay
 *  ninguna decisión sobre datos ausentes, solo dibujo. */
function DiaPorDia({ flujo }: { flujo: Flujo }) {
  // Escala del gráfico: el mayor valor ABSOLUTO de la serie. Con una escala solo
  // sobre los positivos, un saldo muy negativo se sale del cajón y el día del
  // quiebre —lo único que importa acá— se ve como una barrita cualquiera.
  const escala = Math.max(1, ...flujo.serie.map(p => Math.abs(p.saldo)))
  // Solo los días con movimiento: 30 filas de ceros esconden las 4 que importan.
  const diasConMovimiento = flujo.serie.filter(p => p.entradas > 0 || p.salidas > 0)

  return (
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
  )
}
