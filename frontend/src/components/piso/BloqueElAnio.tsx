import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Dato, datoCargando, datoFalla, datoListo, datoSinBase } from '../../api/dato'
import { SegunDato } from '../ui'
import { MESES_CORTOS, detalleDeError, plata } from '../plata/banco'
import { fmtK } from '../rentabilidad/helpers'
import type { RentabilidadData } from '../rentabilidad/helpers'
import type { Piso } from './tipos'

// ═════════════════════════════════════════════════════════════════════════════
// 8 · EL AÑO, CONTRA EL PISO
// ═════════════════════════════════════════════════════════════════════════════
// La línea del piso se mueve mes a mes con los costos de cada mes: no es una
// meta fija que alguien puso en enero. Por eso cada barra se compara contra SU
// piso y no contra el de hoy — un mes con el arriendo más barato tenía un piso
// más bajo, y medirlo contra el de agosto lo haría parecer mejor de lo que fue.
//
// ── ESTE BLOQUE SE PIDE RECIÉN CUANDO SE ABRE ────────────────────────────
// No hay endpoint anual: son DOS lecturas por mes (la venta y el piso), o sea
// dieciséis pedidos en agosto. Eso no puede salir con la página — la regla del
// pedido es que lo de todos los días cueste cero. Está al final, plegado, y se
// pide la primera vez que alguien lo abre.
//
// ── CADA MES ES INDEPENDIENTE ────────────────────────────────────────────
// Un mes cuya lectura falló dibuja «—» en SU renglón y no apaga los otros once.
// Con un solo `Dato` para todo el año, la caída de un mes borraría el año
// entero — o peor, se contaría como $0 y la caída de la venta se vería más
// dramática de lo que es. Por eso cada renglón lleva sus dos sobres propios.

interface MesDelAnio {
  mes: number
  ventas: Dato<number>
  /** `listo` con `null` = el backend contestó que ese mes no tiene piso (una
   *  puerta). Distinto de `falla`, que es no haber podido preguntar. */
  piso: Dato<number | null>
}

const ultimoDia = (anio: number, mes: number) =>
  new Date(anio, mes, 0).toLocaleDateString('en-CA')

/** Pide los meses UNA vez, la primera que `activo` se pone en true. */
function useElAnio(activo: boolean, anio: number, hastaMes: number) {
  const [meses, setMeses] = useState<MesDelAnio[]>([])
  const [pedido, setPedido] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => { if (activo) setPedido(true) }, [activo])

  useEffect(() => {
    if (!pedido) return
    let vivo = true

    const lista = Array.from({ length: hastaMes }, (_, i) => i + 1)
    setMeses(lista.map(m => ({ mes: m, ventas: datoCargando, piso: datoCargando })))

    const anota = (m: number, parche: Partial<MesDelAnio>) => {
      if (!vivo) return
      setMeses(prev => prev.map(x => (x.mes === m ? { ...x, ...parche } : x)))
    }

    for (const m of lista) {
      const desde = `${anio}-${String(m).padStart(2, '0')}-01`
      api.get<RentabilidadData>('/rentabilidad/', { params: { desde, hasta: ultimoDia(anio, m) } })
        .then(r => anota(m, { ventas: datoListo(r.data.resumen.ventas) }))
        .catch(e => anota(m, {
          ventas: datoFalla(detalleDeError(e, 'No se pudo leer la venta de ese mes.')),
        }))

      api.get<Piso>('/costos/piso', { params: { anio, mes: m } })
        .then(r => anota(m, {
          // `piso_mes` en null es una RESPUESTA del backend (una puerta), no un
          // dato ausente: ese mes no tenía costos fijos, o no tenía con qué
          // medir el margen. Va como `sinBase` con su motivo, para que el
          // renglón pueda decir por qué no hay línea en vez de dibujar un cero.
          piso: r.data.piso_mes === null
            ? datoSinBase(motivoDe(r.data))
            : datoListo(r.data.piso_mes),
        }))
        .catch(e => anota(m, {
          piso: datoFalla(detalleDeError(e, 'No se pudo leer el piso de ese mes.')),
        }))
    }

    return () => { vivo = false }
  }, [pedido, anio, hastaMes, tick])

  return { meses, recargar: () => setTick(n => n + 1) }
}

/** Por qué ese mes no tiene piso, en el idioma del dueño. */
function motivoDe(p: Piso): string {
  switch (p.puerta) {
    case 'sin_costos_fijos': return 'no había costos fijos cargados'
    case 'sin_razones': return 'no había venta con la que medir el margen'
    case 'margen_no_positivo': return 'el margen no daba positivo'
    case 'ok':
    case 'razones_del_mes_anterior': return 'no se pudo calcular'
  }
}

export default function BloqueElAnio({ anio, hastaMes }: { anio: number; hastaMes: number }) {
  const [abierto, setAbierto] = useState(false)
  const { meses, recargar } = useElAnio(abierto, anio, hastaMes)

  // La escala la fija el mes MÁS ALTO que se pudo leer, ventas y pisos
  // incluidos. Si no se leyó ninguno, no hay barras que dibujar y tampoco hay
  // una escala inventada de por medio.
  const valores = meses.flatMap(m => [
    m.ventas.estado === 'listo' ? m.ventas.valor : 0,
    m.piso.estado === 'listo' && m.piso.valor !== null ? m.piso.valor : 0,
  ])
  const max = Math.max(...valores, 1)

  const leidos = meses.filter(m => m.ventas.estado === 'listo')
  const primero = leidos[0]
  const ultimo = leidos[leidos.length - 1]
  const caida = primero && ultimo
    && primero.ventas.estado === 'listo' && ultimo.ventas.estado === 'listo'
    && primero.ventas.valor > 0
    ? Math.round(((ultimo.ventas.valor - primero.ventas.valor) / primero.ventas.valor) * 100)
    : null

  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <details className="group"
        onToggle={e => setAbierto(e.currentTarget.open)}>
        <summary className="cursor-pointer select-none list-none px-4 py-3 min-h-[46px]
                            flex items-center hover:bg-warm-50">
          <span className="text-sm font-bold text-warm-700 flex-1">
            <span className="group-open:hidden">▸ </span>
            <span className="hidden group-open:inline">▾ </span>
            El año {anio}, contra el piso
          </span>
        </summary>

        <div className="px-4 pb-3 border-t border-warm-100 pt-3">
          {meses.length === 0 ? (
            <p className="text-sm text-warm-400 py-4">Leyendo los meses…</p>
          ) : (<>
            <div className="space-y-1.5">
              {meses.map(m => (
                <Fila key={m.mes} m={m} max={max} />
              ))}
            </div>

            <p className="text-[11px] text-warm-400 leading-relaxed mt-3">
              La línea del piso se mueve mes a mes con los costos de <b>cada</b> mes: no es una meta
              fija. Un mes con el arriendo más barato tenía un piso más bajo, y medirlo contra el de
              hoy lo haría parecer mejor de lo que fue.
            </p>

            {caida !== null && (
              <p className="text-xs text-warm-600 leading-relaxed mt-1">
                La venta {caida < 0 ? 'cayó' : 'subió'} <b>{Math.abs(caida)}%</b> entre{' '}
                {MESES_CORTOS[primero.mes - 1]} y {MESES_CORTOS[ultimo.mes - 1]}
                {leidos.length < meses.length && <> (comparando solo los meses que se pudieron leer)</>}.
              </p>
            )}

            <button onClick={recargar}
              className="mt-2 min-h-[44px] text-[11px] font-bold text-forest underline decoration-dotted">
              volver a leer el año
            </button>
          </>)}
        </div>
      </details>
    </section>
  )
}

function Fila({ m, max }: { m: MesDelAnio; max: number }) {
  const nombre = MESES_CORTOS[m.mes - 1]?.toUpperCase() ?? String(m.mes)

  return (
    <div className="flex items-center gap-2">
      <span className="w-8 shrink-0 text-[10px] font-bold text-warm-500">{nombre}</span>

      {/* La barra: solo se dibuja con la venta en la mano. Una barra vacía sobre
          un fetch caído se lee como un mes sin ventas. */}
      <div className="flex-1 min-w-0 h-5 relative rounded bg-warm-50 overflow-hidden">
        <SegunDato
          dato={m.ventas}
          cargando={null}
          falla={() => null}
          listo={v => (
            <div className="h-full bg-forest/70 rounded"
              style={{ width: `${Math.max(1, Math.min(100, (v / max) * 100))}%` }} />
          )} />
        {/* La marca del piso de ESE mes, encima de la barra. */}
        <SegunDato
          dato={m.piso}
          cargando={null}
          falla={() => null}
          sinBase={() => null}
          listo={p => p === null ? null : (
            <div className="absolute inset-y-0 w-[2px] bg-danger-500"
              style={{ left: `${Math.max(0, Math.min(100, (p / max) * 100))}%` }} />
          )} />
      </div>

      <span className="w-16 shrink-0 text-right text-[11px] font-mono tabular-nums text-warm-700">
        <SegunDato dato={m.ventas}
          cargando={<span className="text-warm-400">…</span>}
          falla={() => <span className="text-warm-400" title="no se pudo leer">—</span>}
          listo={v => <>{fmtK(v)}</>} />
      </span>

      <span className="w-20 shrink-0 text-right text-[11px] font-mono tabular-nums text-warm-500">
        <SegunDato dato={m.piso}
          cargando={<span className="text-warm-400">…</span>}
          falla={() => <span className="text-warm-400" title="no se pudo leer">—</span>}
          sinBase={porque => <span className="text-warm-400" title={porque}>sin piso</span>}
          listo={p => p === null ? <span className="text-warm-400">—</span> : <>piso {fmtK(p)}</>} />
      </span>

      {/* El veredicto SOLO con los dos números. Un tilde verde con el piso
          caído afirmaría que el mes alcanzó una vara que nunca se leyó. */}
      <span className="w-4 shrink-0 text-center text-xs font-bold">
        {m.ventas.estado === 'listo' && m.piso.estado === 'listo' && m.piso.valor !== null
          ? (m.ventas.valor >= m.piso.valor
            ? <span className="text-success-600" title={`${plata(m.ventas.valor)} contra un piso de ${plata(m.piso.valor)}`}>✓</span>
            : <span className="text-danger-600" title={`${plata(m.ventas.valor)} contra un piso de ${plata(m.piso.valor)}`}>✗</span>)
          : <span className="text-warm-300">·</span>}
      </span>
    </div>
  )
}
