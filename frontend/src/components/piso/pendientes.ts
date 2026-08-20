// ─── «Las N cosas que hacer» ─────────────────────────────────────────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// POR QUÉ ESTO NO ES UNA LISTA, SINO UNA LISTA DE REVISIONES
// ═════════════════════════════════════════════════════════════════════════════
// La forma obvia sería juntar todo en un `Dato<Pendiente[]>` y dibujarlo. Pero
// las ocho cosas salen de SEIS fetches distintos que se caen por separado, y
// con un solo sobre pasan dos cosas malas:
//
//   · la falla de uno apaga la lista entera, y siete tareas reales desaparecen
//     porque un octavo endpoint no volvió;
//   · o peor, se hace `?? []` y la lista queda corta sin decirlo — «no tenés
//     nada que hacer» dicho sobre una pregunta que nunca se hizo.
//
// Las dos son la misma familia de error de siempre, hacia el lado tranquilizador.
//
// Por eso cada revisión trae SU propio `Dato`: las que llegaron se dibujan, las
// que fallaron dibujan su propio renglón «esto no se pudo mirar» con su
// Reintentar, y el CONTADOR de arriba solo puede decir «hay 8» cuando las ocho
// preguntas se pudieron hacer. Si alguna falló dice «al menos 5», que es lo
// único cierto.
//
// `null` adentro de un `listo` sí significa «por este lado no hay nada que
// hacer»: la pregunta se hizo y la respuesta fue que no. Eso se puede afirmar.

import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import type { Agenda, Bandeja, Flujo, Listado } from '../plata/tipos'
import type { PorProductoData } from '../rentabilidad/helpers'
import { MESES, plata } from '../plata/banco'
import { entraAlPiso } from './calculo'
import type { Impoconsumo } from './tipos'

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

/** El mes por su nombre. Fallback y no `MESES[m - 1]!`: un mes fuera de rango
 *  dibujaría `undefined` en medio de una frase sobre plata. */
const nombreDelMes = (m: number) => MESES[m - 1] ?? `mes ${m}`

/**
 * Las ocho revisiones, cada una con su propio sobre.
 *
 * El orden no es estético: primero lo que ya venció (plata que se está
 * atrasando), después lo que hace que los números de arriba mientan (el extracto
 * viejo, la plata sin fecha), y al final el trabajo de mantenimiento.
 */
export function armarRevisiones({
  agenda, flujo, obligaciones, egresos, productos, impoconsumo,
  hoy, anioSiguiente, mesSiguiente,
  irAlExtracto, irAPagar, irASinFecha, irAlDetalleDelMes, irAEgresos,
  irANomina, irAArmarElMes, irAlImpoconsumo,
}: {
  agenda: Fuente<Agenda>
  flujo: Fuente<Flujo>
  /** Del mes actual Y del que viene, en una sola lectura. */
  obligaciones: Fuente<Listado>
  egresos: Fuente<Bandeja>
  productos: Fuente<PorProductoData>
  impoconsumo: Fuente<Impoconsumo>
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
  irAlImpoconsumo: () => void
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

    // ── 2 · La declaración del impoconsumo ─────────────────────────────────
    // EL ÚNICO GASTO GRANDE QUE NO SE VEÍA COMO GASTO. 7,41% de cada peso
    // facturado es de la DIAN: el sistema ya lo descuenta del margen y del piso,
    // pero como plata a pagar en una fecha no aparecía en ninguna parte. Se ve
    // como menos venta todos los días y después aparece de golpe cada dos meses.
    //
    // EL MONTO NO SE INVENTA. Viene MEDIDO del backend, o viene `null` con el
    // porqué escrito —y entonces acá se dice «hay que declararlo» sin cifra. Un
    // monto inventado en una pantalla de plata es peor que un recordatorio sin
    // monto, así que no hay un solo `?? 0` en esta rama.
    //
    // MANDA AL PLIEGUE DE «UNA VEZ AL MES», QUE ES DONDE ESTÁN LOS DOS BOTONES.
    // Este comentario decía lo contrario —«no manda a crear una obligación:
    // contaría la misma plata dos veces»— y dejó de ser cierto: la declaración
    // SÍ se agenda ahora, en una categoría dedicada que el P&L excluye POR
    // CLAVE, y está medido que no mueve el piso ni el margen ni un centavo
    // (delta $0,00 exacto) mientras la agenda y la proyección de caja sí la ven.
    // Lo que contaba dos veces era cargarla como costo de 'impuestos', que es
    // grupo fijo y entra al numerador del piso; eso sigue prohibido y ahora lo
    // rechaza el server.
    //
    // Y SON DOS BOTONES DISTINTOS, que es la razón por la que este renglón manda
    // al pliegue y no dispara nada solo: «ya la declaré» apaga el recordatorio
    // del TRÁMITE, y «meterla en lo que hay que pagar» reserva la PLATA. Se
    // puede declarar sin haber pagado, así que el primero no puede hacer el
    // trabajo del segundo — y este renglón, que sale de `hay_que_declarar`,
    // habla del trámite. El de la plata lo levanta el flujo con
    // `conceptos_sin_cargar`, que mira una sola cosa: si la obligación existe.
    {
      clave: 'impoconsumo',
      nombre: 'la declaración del impoconsumo',
      hacer: irAlImpoconsumo,
      recargar: impoconsumo.recargar,
      dato: mapDato(impoconsumo.dato, i => {
        if (!i.hay_que_declarar) return null
        const cuanto = i.monto_medido === null
          ? `el sistema no puede decir cuánto: ${i.sin_monto_porque}`
          : `${plata(i.monto_medido)} que cobraste y son de la DIAN`
        return {
          titulo: `Declarar el impoconsumo de ${i.bimestre.nombre}`,
          detalle: i.vencido
            ? `${cuanto} · el plazo era en ${i.declara_en.nombre} y ya pasó`
            : `${cuanto} · se declara en ${i.declara_en.nombre}`,
          cta: 'Ver',
          // Rojo solo cuando pasó el MES ENTERO del plazo: el día exacto lo fija
          // la DIAN según el NIT y el sistema no lo conoce, así que antes de eso
          // no se puede afirmar que esté tarde.
          urgente: i.vencido,
        }
      }),
    },

    // ── 3 · El extracto atrasado ───────────────────────────────────────────
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

    // ── 4 · La plata que se debe y no proyecta ─────────────────────────────
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

    // ── 5 · Las facturas sin precio ────────────────────────────────────────
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

    // ── 6 · Los egresos sin categorizar ────────────────────────────────────
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

    // ── 7 · La nómina sin agendar ──────────────────────────────────────────
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

    // ── 8 · El mes que viene sin sus costos ────────────────────────────────
    // Se mira sobre las obligaciones del mes actual Y el siguiente, que vienen
    // en la MISMA lectura.
    //
    // ═══════════════════════════════════════════════════════════════════════
    // LA FRASE QUE ESTE RENGLÓN LLEGÓ A DECIR, Y QUE COSTÓ $27.620.000
    // ═══════════════════════════════════════════════════════════════════════
    // «ninguna de las 5 cuentas está marcada para repetirse: el mes que viene
    // arrancaría sin costos fijos y el piso en cero» — dicho con el mes que
    // viene YA CARGADO A MANO, con sus $27.620.000 adentro, y saliendo del
    // MISMO array del que salió la frase. Era una afirmación sobre algo que no
    // se miró, y sobre lo único que al dueño le da miedo. Tocaba «Elegir
    // cuáles», tildaba los cinco, y el mes destino pasaba a $55.240.000 con el
    // piso en $59.659.195,23 contra los $29.829.597,61 que necesita.
    //
    // Ahora `enElMesQueViene` se cuenta ANTES de cualquier frase, y ninguna
    // rama habla del mes destino sin haberlo abierto.
    //
    // ═══════════════════════════════════════════════════════════════════════
    // LOS ESTADOS, TODOS, Y QUÉ DICE CADA UNO
    // ═══════════════════════════════════════════════════════════════════════
    //  E0 · la lectura no volvió → no se dibuja acá: el `Dato` de esta revisión
    //       pinta su propio renglón «esto no se pudo mirar» con su Reintentar.
    //       Ninguna de las ramas de abajo corre fuera de `listo`.
    //  E1 · faltan copias de SERIE → «Armar los costos», con lo que el mes
    //       destino ya tiene dicho al lado para que el número no se lea como
    //       «el mes está en cero».
    //  E2 · destino VACÍO, nada marcado, hay cuentas para llevar → EL AVISO
    //       FUERTE. Es el único estado en el que la frase de arriba es cierta,
    //       y ahora está condicionada a haberlo contado.
    //  E3 · destino CON PLATA y nada marcado → SUAVE. El mes está cubierto: no
    //       urge nada. Pero marcarlas es lo que corta las siete cargas a mano,
    //       así que se dice sin alarma y sin rojo.
    //  E4 · destino vacío y no hay NADA que llevar (base sin costos) → `null`.
    //       No es un «al día» escondido: el bloque del piso ya dice el hueco
    //       con nombre (`PUERTA_SIN_COSTOS_FIJOS`) y repetirlo acá sería una
    //       segunda alarma sobre lo mismo.
    //  E5 · todo marcado y copiado → `null`. Se preguntó y no hay nada que
    //       hacer, que es lo único que `null` puede significar.
    //
    // NUNCA va `urgente`: el rojo está reservado para plata ya vencida, y esto
    // es trabajo que hay que hacer, no un pago atrasado.
    {
      clave: 'mes_que_viene',
      nombre: 'los costos fijos',
      hacer: irAArmarElMes,
      recargar: obligaciones.recargar,
      dato: mapDato(obligaciones.dato, l => {
        const vivas = l.obligaciones.filter(o => o.estado !== 'anulada')
        // LO QUE EL MES QUE VIENE YA TIENE. Se cuenta primero, y todo lo de
        // abajo lo usa: es el dato que faltaba mirar.
        //
        // SE CUENTAN LOS QUE ENTRAN AL PISO, no todas las obligaciones vivas.
        // Contar todas daba un número CERCA del correcto y del lado
        // tranquilizador: una declaración del impoconsumo sola en el mes hacía
        // que un mes sin un peso de costos fijos se leyera como cubierto, y
        // apagaba justo el aviso que existe para eso. `entraAlPiso` usa el mismo
        // filtro que el numerador del backend.
        const enElMesQueViene = vivas
          .filter(o => o.fecha_devengo.slice(0, 7) === mesQueViene && entraAlPiso(o))
        const platEnElMesQueViene = enElMesQueViene.reduce((s, o) => s + o.monto, 0)
        // Para «¿falta la copia?» se miran TODAS las vivas del mes y no solo las
        // del piso: una copia ya hecha en una categoría variable igual existe, y
        // volver a crearla sería duplicarla.
        const yaCopiadas = new Set(
          vivas.filter(o => o.fecha_devengo.slice(0, 7) === mesQueViene)
            .map(o => o.plantilla_id).filter((x): x is number => x !== null))
        const fuera = vivas.filter(o => o.fecha_devengo.slice(0, 7) !== mesQueViene)
        const faltan = fuera.filter(o =>
          o.plantilla_id !== null && !yaCopiadas.has(o.plantilla_id))
        const sueltas = fuera.filter(o => o.plantilla_id === null)
        const yaTiene = `${nombreDelMes(mesSiguiente)} ya tiene ${enElMesQueViene.length} `
          + `${plural(enElMesQueViene.length, 'costo fijo', 'costos fijos')} por `
          + `${plata(platEnElMesQueViene)}`

        // E1 · Faltan copias de serie.
        if (faltan.length > 0) {
          return {
            titulo: 'Armar los costos del mes que viene',
            detalle: `${faltan.length} ${plural(faltan.length, 'cuenta', 'cuentas')} de la serie `
              + 'mensual todavía sin copia'
              // El conteo del destino va PEGADO al número que falta: «3 sin
              // copia» a secas se lee como un mes en cero.
              + (enElMesQueViene.length > 0 ? ` · ${yaTiene}` : ''),
            cta: 'Armar el mes',
          }
        }

        const nadaMarcado = !vivas.some(o => o.plantilla_id !== null)

        // E2 · El destino está VACÍO y no hay nada marcado: el aviso fuerte, y
        // recién ahora se puede decir.
        if (nadaMarcado && sueltas.length > 0 && enElMesQueViene.length === 0) {
          return {
            titulo: 'Elegir qué costos van al mes que viene',
            detalle: (sueltas.length === 1
              ? 'la única cuenta cargada no está marcada para repetirse'
              : `ninguna de las ${sueltas.length} cuentas está marcada para repetirse`)
              + ` y ${nombreDelMes(mesSiguiente)} no tiene todavía un peso de costos fijos: `
              + 'arrancaría con el piso en cero',
            cta: 'Elegir cuáles',
          }
        }

        // E3 · El destino YA tiene sus costos y nada está marcado. No urge —el
        // mes está cubierto— pero el dueño los está cargando a mano todos los
        // meses y nadie se lo dijo nunca. Suave, sin alarma y sin cifra de
        // miedo: la plata que se nombra es la que YA está, no una que falte.
        if (nadaMarcado && sueltas.length > 0 && enElMesQueViene.length > 0) {
          return {
            titulo: 'Marcar los costos que se repiten todos los meses',
            detalle: `${yaTiene}, así que esto no urge. Marcarlos una vez es lo que evita `
              + 'volver a cargarlos a mano el mes que viene',
            cta: 'Marcarlos',
          }
        }

        // E4 y E5 · Se preguntó y no hay nada que hacer por este lado.
        return null
      }),
    },
  ]
}
