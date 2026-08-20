// ─── Las tres cuentas que la PANTALLA hace, y por qué son solo tres ──────────
//
// El piso lo calcula el backend entero (`services/costos.get_piso`). Esta
// pantalla NO recalcula nada de eso: `piso_mes`, `piso_hoy`, `falta` y el piso
// de caja llegan hechos, y volver a dividirlos acá sería tener dos matemáticas
// para el mismo número — el error que este módulo viene arrastrando.
//
// Lo que sí se hace acá es ARITMÉTICA SOBRE DATOS QUE YA VINIERON, para
// contestar preguntas que el endpoint no contesta:
//
//   1. cuántos días ABRE un rango, según el `dias_semana` que mandó el backend
//   2. el piso del mes repartido en partes IGUALES (≠ el piso de hoy)
//   3. cuántos de los días ya corridos pasaron ese piso parejo
//
// Ninguna inventa un dato ausente: las tres toman `Piso` ya `listo` y devuelven
// `null` en cuanto les falta un ingrediente. Un `null` acá se dibuja «—», nunca 0.

import type { Piso } from './tipos'

/** Fecha ISO → 0=lunes … 6=domingo, sin pasar por UTC (mismo criterio que banco.ts). */
export function indiceDeSemana(iso: string): number {
  const d = new Date(iso + 'T00:00:00').getDay()   // 0=domingo
  return (d + 6) % 7                                // 0=lunes
}

/** Suma días a una fecha ISO y devuelve ISO. Aritmética, no una afirmación. */
export function sumarDias(iso: string, n: number): string {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return d.toLocaleDateString('en-CA')
}

/**
 * Cuántos días del rango [desde, hasta] el negocio ABRE.
 *
 * `diasSemana` es el `dias.dias_semana` del backend, que salió de la HISTORIA de
 * ventas (o del calendario pelado si no había historia, y entonces
 * `dias.derivados` viene en false y la pantalla lo dice). No se asume «de lunes
 * a sábado»: una semana que el backend no vio no se puede inventar acá.
 *
 * Devuelve `null` con la lista vacía. Cero días abiertos no es una respuesta —
 * es un divisor que haría infinito el piso parejo de más abajo.
 */
export function diasQueAbre(desde: string, hasta: string, diasSemana: number[]): number | null {
  if (diasSemana.length === 0) return null
  const set = new Set(diasSemana)
  let n = 0
  for (let f = desde; f <= hasta; f = sumarDias(f, 1)) {
    if (set.has(indiceDeSemana(f))) n++
    // Cinturón contra un rango mal formado (hasta < desde nunca entra al bucle;
    // un rango absurdo sí podría). 400 vueltas cubre cualquier mes real.
    if (n > 400) return null
  }
  return n > 0 ? n : null
}

/**
 * EL PISO DEL MES REPARTIDO EN PARTES IGUALES. NO es el piso de hoy.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * POR QUÉ EXISTEN DOS PISOS POR DÍA, Y POR QUÉ NO SE PUEDEN CONFUNDIR
 * ═════════════════════════════════════════════════════════════════════════════
 * `piso_hoy` (del backend) es `falta / días que quedan`: SUBE si se viene
 * atrasado, porque lo que no se vendió hay que repartirlo en menos días. Es el
 * número con el que se decide hoy.
 *
 * Este otro es `piso_mes / días que abre el mes entero`: la vara PAREJA, la
 * misma para todos los días del mes. Sirve para una sola cosa —mirar hacia
 * atrás y contar cuántos días se pasó— y para nada más. Mezclarlos daría un
 * conteo de días buenos calculado contra una vara que se mueve, o sea un
 * porcentaje que sube solo cuando el mes va mal.
 *
 * Por eso tiene su propio nombre en el código y su propia frase en pantalla.
 */
export function pisoParejoDelMes(p: Piso): number | null {
  if (p.piso_mes === null) return null
  const abre = diasQueAbre(p.desde, p.hasta, p.dias.dias_semana)
  if (abre === null) return null
  return p.piso_mes / abre
}

export interface DiasContraElPiso {
  /** Días ya corridos en los que el negocio abre (hoy NO se cuenta: va en curso). */
  corridos: number
  /** De esos, cuántos vendieron al menos el piso parejo. */
  pasados: number
  piso_parejo: number
}

/**
 * Cuántos días de los que ya pasaron llegaron al piso parejo.
 *
 * ── HOY NO SE CUENTA ───────────────────────────────────────────────────────
 * El día está a medio hacer: contarlo como «no llegó» a las 8 de la mañana
 * arruinaría el conteo todos los días, y contarlo como «llegó» sería peor.
 *
 * ── UN DÍA SIN FILA ES UN DÍA SIN VENTA, Y ESO SE PUEDE AFIRMAR ────────────
 * `ventas_diarias` sale de agrupar los tickets del mes: un día que abre y no
 * aparece es un día que no facturó. No es un dato ausente —los tickets del mes
 * llegaron enteros— sino un cero medido. Los días que el negocio NO abre ya
 * quedaron afuera por `dias_semana`, así que no ensucian el denominador.
 *
 * Devuelve `null` si no hay piso parejo o si todavía no corrió ningún día:
 * «pasó el piso 0 de 0 días» es una frase sin contenido.
 */
export function diasContraElPiso(
  p: Piso,
  ventasDiarias: { dia: string; ventas: number }[],
): DiasContraElPiso | null {
  const parejo = pisoParejoDelMes(p)
  if (parejo === null || parejo <= 0) return null

  const ayer = sumarDias(p.hoy, -1)
  if (ayer < p.desde) return null

  const set = new Set(p.dias.dias_semana)
  const porDia = new Map(ventasDiarias.map(v => [v.dia, v.ventas]))

  let corridos = 0
  let pasados = 0
  for (let f = p.desde; f <= ayer; f = sumarDias(f, 1)) {
    if (!set.has(indiceDeSemana(f))) continue
    corridos++
    if ((porDia.get(f) ?? 0) >= parejo) pasados++
  }
  return corridos > 0 ? { corridos, pasados, piso_parejo: parejo } : null
}

/**
 * Los sesgos ACTIVOS, en el orden en que el backend los mandó.
 *
 * `sesgos` viene `[]` con la puerta `sin_razones`, y eso NO es «no hay sesgos»:
 * es que sin razones no se midió ninguno. Quien llama a esto está adentro de una
 * rama donde el piso existe, así que la lista vacía sí significa «ninguno vivo».
 */
export const sesgosActivos = (p: Piso) => p.sesgos.filter(s => s.activo)

/** Un número del `detalle` de un sesgo, o `null`. Nunca `undefined` impreso. */
export function detalleNum(d: Record<string, number | null>, clave: string): number | null {
  const v = d[clave]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

// ─── Lo que el PISO cuenta de un mes, y por qué se filtra dos veces ──────────
//
// Esto NO recalcula el piso: el piso viene hecho del backend y volver a
// dividirlo acá sería tener dos matemáticas para el mismo número. Lo que
// contesta es otra pregunta, la que el endpoint del piso no contesta: «¿el mes
// que viene ya tiene costos fijos cargados, o arranca en cero?» — y esa
// pregunta se hace sobre el LISTADO de obligaciones, que es lo único que la
// pantalla trae de los dos meses.
//
// TIENE QUE FILTRAR IGUAL QUE EL NUMERADOR DEL PISO, y por eso son dos filtros
// y no uno. Contar TODAS las obligaciones vivas del mes daba un número CERCA
// del correcto y siempre para el lado tranquilizador: una declaración del
// impoconsumo de $12M o una fila legacy de proveedores hacían que un mes sin un
// peso de costos fijos se leyera como un mes cubierto, y el aviso fuerte —el
// único que le dice al dueño que el mes que viene arranca con el piso en cero—
// se apagaba solo.
//
//   · grupo 'fijo'  → es lo que `rentabilidad._cuenta_costos_fijos` mira;
//   · y NO las dos claves excluidas del gasto, que el backend saca antes en
//     `_obligaciones_del_periodo` (proveedores ya entra por su factura de
//     Compras; el impoconsumo ya está restado de la venta neta).
//
// SYNC: si cambia `rentabilidad.CLAVES_FUERA_DEL_GASTO`, cambia acá en el mismo
// commit. Son dos copias porque son dos lados de la red, no porque sea gratis.
const CLAVES_FUERA_DEL_PISO = ['proveedores', 'impoconsumo']

/** ¿Esta obligación entra al numerador del piso? Anuladas afuera, siempre. */
export function entraAlPiso(o: {
  estado: string; categoria_grupo: string; categoria_clave: string
}): boolean {
  return o.estado !== 'anulada'
    && o.categoria_grupo === 'fijo'
    && !CLAVES_FUERA_DEL_PISO.includes(o.categoria_clave)
}
