// ─── «Las N cosas que hacer» ─────────────────────────────────────────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// POR QUÉ ESTO NO ES UNA LISTA, SINO UNA LISTA DE REVISIONES
// ═════════════════════════════════════════════════════════════════════════════
// La forma obvia sería juntar todo en un `Dato<Pendiente[]>` y dibujarlo. Pero
// las siete cosas salen de SEIS fetches distintos que se caen por separado, y
// con un solo sobre pasan dos cosas malas:
//
//   · la falla de uno apaga la lista entera, y seis tareas reales desaparecen
//     porque un séptimo endpoint no volvió;
//   · o peor, se hace `?? []` y la lista queda corta sin decirlo — «no tenés
//     nada que hacer» dicho sobre una pregunta que nunca se hizo.
//
// Las dos son la misma familia de error de siempre, hacia el lado tranquilizador.
//
// Por eso cada revisión trae SU propio `Dato`: las que llegaron se dibujan, las
// que fallaron dibujan su propio renglón «esto no se pudo mirar» con su
// Reintentar, y el CONTADOR de arriba solo puede decir «hay 7» cuando las siete
// preguntas se pudieron hacer. Si alguna falló dice «al menos 5», que es lo
// único cierto.
//
// `null` adentro de un `listo` sí significa «por este lado no hay nada que
// hacer»: la pregunta se hizo y la respuesta fue que no. Eso se puede afirmar.

import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import type { Agenda, Bandeja, Flujo, Listado } from '../plata/tipos'
import type { PorProductoData } from '../rentabilidad/helpers'
import { plata } from '../plata/banco'

export interface Pendiente {
  /** Lo que hay que hacer, en imperativo y con el nombre propio adentro. */
  titulo: string
  /** Una línea que diga por qué importa o desde cuándo está. */
  detalle: string
  /** El texto del botón. */
  cta: string
  /** Rojo: ya venció algo. Lo demás es trabajo, no emergencia. */
  urgente?: boolean
}

export interface Revision {
  clave: string
  /** En el idioma del dueño, para el renglón de «no se pudo mirar». */
  nombre: string
  /** `null` dentro de `listo` = se preguntó y no hay nada que hacer. */
  dato: Dato<Pendiente | null>
  /** Lo que hace el botón. Vive afuera del `Dato` porque no depende de él. */
  hacer: () => void
  recargar: () => void
}

const plural = (n: number, uno: string, varios: string) => (n === 1 ? uno : varios)

/**
 * Las siete revisiones, cada una con su propio sobre.
 *
 * El orden no es estético: primero lo que ya venció (plata que se está
 * atrasando), después lo que hace que los números de arriba mientan (el extracto
 * viejo, la plata sin fecha), y al final el trabajo de mantenimiento.
 */
export function armarRevisiones({
  agenda, flujo, obligaciones, egresos, productos,
  hoy, anioSiguiente, mesSiguiente,
  irAlExtracto, irAPagar, irASinFecha, irAlDetalleDelMes, irAEgresos,
  irANomina, irAArmarElMes,
}: {
  agenda: Fuente<Agenda>
  flujo: Fuente<Flujo>
  /** Del mes actual Y del que viene, en una sola lectura. */
  obligaciones: Fuente<Listado>
  egresos: Fuente<Bandeja>
  productos: Fuente<PorProductoData>
  hoy: string
  anioSiguiente: number
  mesSiguiente: number
  irAlExtracto: () => void
  irAPagar: () => void
  irASinFecha: () => void
  irAlDetalleDelMes: () => void
  irAEgresos: () => void
  irANomina: () => void
  irAArmarElMes: () => void
}): Revision[] {
  const mesQueViene = `${anioSiguiente}-${String(mesSiguiente).padStart(2, '0')}`

  return [
    // ── 1 · Lo vencido ─────────────────────────────────────────────────────
    {
      clave: 'vencido',
      nombre: 'la agenda de pagos',
      hacer: irAPagar,
      recargar: agenda.recargar,
      dato: mapDato(agenda.dato, a => {
        const v = a.items.filter(i => i.vencida)
        if (v.length === 0) return null
        // El más viejo primero: es el que más días lleva sin pagarse.
        const peor = v.slice().sort((x, y) => x.fecha.localeCompare(y.fecha))[0]
        const dias = Math.round(
          (new Date(hoy + 'T00:00:00').getTime()
            - new Date(peor.fecha + 'T00:00:00').getTime()) / 86_400_000)
        return {
          titulo: `Pagar ${peor.beneficiario || peor.concepto}`,
          detalle: `${plata(peor.monto)} · venció hace ${dias} ${plural(dias, 'día', 'días')}`
            + (v.length > 1 ? ` · hay ${v.length - 1} ${plural(v.length - 1, 'pago más vencido', 'pagos más vencidos')}` : ''),
          cta: 'Pagar',
          urgente: true,
        }
      }),
    },

    // ── 2 · El extracto atrasado ───────────────────────────────────────────
    // `saldo_banco_desactualizado` lo decide el BACKEND (y solo lo prende cuando
    // el banco de verdad entra al total). No se recalcula acá comparando fechas:
    // dos reglas para «¿está viejo?» son dos pantallas que se contradicen.
    {
      clave: 'extracto',
      nombre: 'la caja de hoy',
      hacer: irAlExtracto,
      recargar: flujo.recargar,
      dato: mapDato(flujo.dato, f => {
        const c = f.caja_hoy
        if (!c.saldo_banco_desactualizado) return null
        return {
          titulo: 'Copiar el saldo del extracto',
          detalle: c.saldo_banco_fecha
            ? `El último que cargaste es del ${c.saldo_banco_fecha}: de ahí para acá el libro `
              + 'solo sabe lo que tecleaste'
            : 'Todavía no cargaste ningún saldo del banco, así que la proyección arranca sin él',
          cta: 'Ir',
        }
      }),
    },

    // ── 3 · La plata que se debe y no proyecta ─────────────────────────────
    {
      clave: 'sin_fecha',
      nombre: 'la agenda de pagos',
      hacer: irASinFecha,
      recargar: agenda.recargar,
      dato: mapDato(agenda.dato, a => {
        if (a.sin_fecha.length === 0) return null
        return {
          titulo: `Ponerle fecha a ${a.sin_fecha.length} ${plural(a.sin_fecha.length, 'cuenta', 'cuentas')}`,
          detalle: `${plata(a.totales.sin_fecha)} que se deben y no entran a ninguna proyección: `
            + 'mientras estén así, la caja se ve mejor de lo que está',
          cta: 'Ponerle fecha',
        }
      }),
    },

    // ── 4 · Las facturas sin precio ────────────────────────────────────────
    {
      clave: 'facturas_sin_costo',
      nombre: 'los productos',
      hacer: irAlDetalleDelMes,
      recargar: productos.recargar,
      dato: mapDato(productos.dato, p => {
        const n = p.facturas_pendientes_de_costos
        if (n <= 0) return null
        return {
          titulo: `Ponerle precio a ${n} ${plural(n, 'factura', 'facturas')}`,
          detalle: 'Sin el precio de compra, esos productos entran al piso valiendo $0 y el '
            + 'piso sale más bajo que el real',
          cta: 'Ver',
        }
      }),
    },

    // ── 5 · Los egresos sin categorizar ────────────────────────────────────
    {
      clave: 'egresos',
      nombre: 'los egresos sin categorizar',
      hacer: irAEgresos,
      recargar: egresos.recargar,
      dato: mapDato(egresos.dato, b => {
        if (b.totales.n === 0) return null
        return {
          titulo: `Clasificar ${b.totales.n} ${plural(b.totales.n, 'egreso', 'egresos')} de caja`,
          detalle: `${plata(b.totales.monto)} que salieron y todavía no entran a ninguna `
            + 'categoría, así que no suben el piso',
          cta: 'Clasificar',
        }
      }),
    },

    // ── 6 · La nómina sin agendar ──────────────────────────────────────────
    // Se pregunta a la AGENDA, no a la nómina: la pregunta no es «cuánto cuesta»
    // sino «¿está adentro de lo que hay que pagar?». La nómina puede estar
    // perfectamente calculada y aun así no existir como obligación — que es
    // exactamente el agujero que la fase 1 cerró.
    {
      clave: 'nomina',
      nombre: 'la agenda de pagos',
      hacer: irANomina,
      recargar: agenda.recargar,
      dato: mapDato(agenda.dato, a => {
        const hay = a.items.some(i => i.categoria === 'nomina')
          || a.sin_fecha.some(i => i.categoria === 'nomina')
        if (hay) return null
        return {
          titulo: 'Agendar la nómina del mes',
          detalle: 'Es el gasto más grande del negocio y hoy no está en lo que hay que pagar: '
            + 'sin ella, la proyección de caja se ve mejor de lo que está',
          cta: 'Agendarla',
        }
      }),
    },

    // ── 7 · El mes que viene sin sus costos ────────────────────────────────
    // Se mira sobre las obligaciones del mes actual Y el siguiente, que vienen
    // en la MISMA lectura: las que se repiten (tienen `plantilla_id`) y todavía
    // no tienen copia con devengo del mes que viene.
    {
      clave: 'mes_que_viene',
      nombre: 'los costos fijos',
      hacer: irAArmarElMes,
      recargar: obligaciones.recargar,
      dato: mapDato(obligaciones.dato, l => {
        const vivas = l.obligaciones.filter(o => o.estado !== 'anulada')
        const yaEnElMesQueViene = new Set(
          vivas.filter(o => o.fecha_devengo.slice(0, 7) === mesQueViene)
            .map(o => o.plantilla_id)
            .filter((x): x is number => x !== null))
        const faltan = vivas.filter(o =>
          o.fecha_devengo.slice(0, 7) !== mesQueViene
          && o.plantilla_id !== null
          && !yaEnElMesQueViene.has(o.plantilla_id))
        if (faltan.length === 0) return null
        return {
          titulo: `Armar los costos del mes que viene`,
          detalle: `${faltan.length} ${plural(faltan.length, 'cuenta', 'cuentas')} de la serie `
            + 'mensual todavía sin copia',
          cta: 'Armar el mes',
        }
      }),
    },
  ]
}
