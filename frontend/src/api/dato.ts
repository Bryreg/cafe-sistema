// ─── Dato<T>: la relación entre la pantalla y un dato del backend ────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// EL PROBLEMA QUE ESTE ARCHIVO EXISTE PARA MATAR
// ═════════════════════════════════════════════════════════════════════════════
// El molde viejo era este, repetido ocho veces en `pages/Plata.tsx`:
//
//     api.get<X>('/ruta').then(r => setX(r.data)).catch(() => setX(null))
//
// Con eso, `null` significaba TRES cosas que el código no podía separar:
//   (a) todavía no llegó        (b) llegó vacío        (c) no volvió
//
// Y como no las podía separar, río abajo cada `?? 0` y cada `?? []` convertía
// «no se pudo preguntar» en «la respuesta es cero». No fue un descuido: fue el
// único camino que el tipo dejaba abierto. `computeOutliers([])` devuelve `[]`
// por construcción, así que «ningún producto está mal» y «no miré ningún
// producto» ERAN EL MISMO VALOR. Cualquiera que editara ese banner iba a caer.
//
// La dirección del error siempre fue la misma, y por eso es cara: la pantalla
// nunca inventó una deuda. Inventó calma. Diez veces.
//
// ═════════════════════════════════════════════════════════════════════════════
// EL CANDADO
// ═════════════════════════════════════════════════════════════════════════════
// `valor` vive SOLO en la rama `listo`. Eso es todo el diseño. `d.valor` no
// compila sin estrechar el estado antes, y sin `.valor` no hay nada a la
// izquierda de un `?? 0`. El compilador —y no la disciplina de quien edite
// dentro de seis meses— es el que impide pintar un número inventado.
//
// No es una idea nueva en este repo: `DiaLibro` en `components/plata/banco.ts`
// ya usa exactamente este truco para que un día sin cadena no pueda dibujar un
// saldo. Esto es lo mismo un nivel más arriba: allá es la fila del libro, acá
// es el sobre entero.

/** Las cuatro relaciones posibles entre la pantalla y un dato del backend. */
export type Dato<T> =
  | { readonly estado: 'cargando' }
  | { readonly estado: 'falla'; readonly mensaje: string }
  /**
   * Llegó un 200, pero no traía sobre qué afirmar.
   *
   * NO lo emite la red: lo emiten las derivaciones de dominio. El caso que lo
   * hizo necesario es `computeOutliers`, que devuelve `[]` tanto cuando no hay
   * ningún producto fuera de rango como cuando ninguna categoría junta los
   * cuatro productos costeados que el algoritmo necesita para comparar. Cien
   * productos en pantalla y cero comparaciones hechas: sin este estado, eso se
   * dibujaba como el verde «todos coherentes con su categoría».
   */
  | { readonly estado: 'sinBase'; readonly porque: string }
  | { readonly estado: 'listo'; readonly valor: T }

// Prefijo `dato*` a propósito. `listo` y `cargando` ya son identificadores
// locales en FormObligacion, FormMovimiento, FormPagoObligacion, BannerFlujo y
// BannerEgresos. El shadowing es legal y compila sin chistar —por eso hay que
// elegir el nombre a mano—, pero deja dos cosas distintas llamadas igual justo
// en los archivos donde más caro sale confundirlas.
export const datoCargando: Dato<never> = { estado: 'cargando' }
export const datoListo = <T,>(valor: T): Dato<T> => ({ estado: 'listo', valor })
export const datoFalla = (mensaje: string): Dato<never> => ({ estado: 'falla', mensaje })
export const datoSinBase = (porque: string): Dato<never> => ({ estado: 'sinBase', porque })

/** Transforma el valor SIN inventar ausencia: las otras tres ramas pasan tal cual. */
export const mapDato = <T, U>(d: Dato<T>, f: (v: T) => U): Dato<U> =>
  d.estado === 'listo' ? datoListo(f(d.valor)) : d

/**
 * Dos datos que solo sirven juntos.
 *
 * El caso real es `pendientesDatos`, que necesita los productos Y el P&L del
 * mes: con el P&L caído, el viejo `plMes && !plMes.resumen.tiene_costos_fijos`
 * cortaba en el `&&` y sumaba 0 pendientes — un P&L muerto se leía igual que un
 * mes con todo cargado.
 *
 * La falla gana sobre el cargando: media tarjeta viva con el otro fetch muerto
 * ya es un fallo, no una carga en curso.
 */
export function ambos<A, B>(a: Dato<A>, b: Dato<B>): Dato<[A, B]> {
  if (a.estado === 'falla') return a
  if (b.estado === 'falla') return b
  if (a.estado === 'sinBase') return a
  if (b.estado === 'sinBase') return b
  if (a.estado === 'cargando' || b.estado === 'cargando') return datoCargando
  return datoListo([a.valor, b.valor])
}
