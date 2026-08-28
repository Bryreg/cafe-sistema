// Fechas "de hoy" en hora LOCAL del dispositivo (Colombia), formato YYYY-MM-DD.
//
// NUNCA usar new Date().toISOString().slice(0, 10) para "hoy": toISOString es UTC,
// y despues de las 19:00 de Colombia (UTC-5) devuelve la fecha de MANANA. Todo
// filtro "hoy" que viaje al backend con esa fecha consulta un dia futuro y da cero.
// El backend interpreta fecha_desde/fecha_hasta como dias de Colombia (rango_col_utc).

const pad = (n: number) => String(n).padStart(2, '0')

/** YYYY-MM-DD de un Date usando sus componentes LOCALES (sin pasar por UTC). */
export function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Fecha de hoy en hora local del dispositivo. */
export function hoyLocal(): string {
  return isoLocal(new Date())
}

/**
 * "Hoy" segun el reloj de COLOMBIA (el negocio), no el del dispositivo.
 *
 * El modulo Plata lo necesita en varios lugares y cada uno tenia su propia copia:
 * con un admin viajando (o un navegador mal configurado) esas copias se separan y
 * "vencido" empieza a significar cosas distintas en dos tarjetas de la misma
 * pantalla. Igual que en el backend, la fecha del negocio es una sola.
 */
export function hoyBogota(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' })
}

/** Fecha de hace `n` dias en hora local. */
export function haceDiasLocal(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoLocal(d)
}

/** Primer dia del mes actual en hora local. */
export function inicioMesLocal(): string {
  const d = new Date()
  return isoLocal(new Date(d.getFullYear(), d.getMonth(), 1))
}

/** Lunes de la semana actual en hora local. */
export function inicioSemanaLocal(): string {
  const d = new Date()
  const day = d.getDay() || 7 // domingo=0 -> 7
  d.setDate(d.getDate() - (day - 1))
  return isoLocal(d)
}

/**
 * Un instante que vino del backend, en hora de COLOMBIA.
 *
 * El backend guarda y serializa en UTC con `datetime.isoformat()`, que NO lleva
 * marca de zona. Eso rompe de dos formas y las dos se vieron en producción:
 *
 *  · `new Date("2026-08-01T05:00:00")` lo interpreta como hora LOCAL, no UTC.
 *    En la tablet (UTC−5) eso corre el instante cinco horas: un conteo de
 *    cierre hecho a las 8:07 de la noche se mostraba como «1:07 a. m.», una
 *    hora a la que el local no tiene servicio. El dueño lo cazó mirando el
 *    globo de una barra.
 *
 *  · Cortar el texto ISO (`s.slice(0, 10)`) muestra el día UTC. Todo lo que
 *    pasa entre las 7 de la tarde y la medianoche en Colombia ya es del día
 *    siguiente en UTC, o sea que los movimientos del cierre —justo los del
 *    turno que se está revisando— se fechaban un día tarde.
 *
 * La zona se fija a Bogotá y no se hereda del dispositivo, por lo mismo que
 * `hoyBogota`: la hora del negocio es una sola, viaje quien viaje.
 */
export function instanteCol(s: string): Date {
  const conZona = /[Zz]$/.test(s) || /[+-]\d\d:?\d\d$/.test(s)
  return new Date(conZona ? s : s + 'Z')
}

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

/** «13 ago» en hora de Colombia. */
export function diaCol(s: string | null): string {
  if (!s) return '—'
  const d = instanteCol(s)
  if (Number.isNaN(d.getTime())) return s.slice(0, 10)
  const [, m, dd] = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Bogota', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(d).split('-')
  return `${dd} ${MESES[Number(m) - 1] ?? m}`
}

/** «13 de ago, 8:07 p. m.» en hora de Colombia. */
export function fechaHoraCol(d: Date): string {
  return d.toLocaleString('es-CO', {
    timeZone: 'America/Bogota',
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
  })
}
