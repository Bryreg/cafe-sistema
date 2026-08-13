// Tipos compartidos del módulo Horarios & Nómina.
// Espejo de lo que devuelve app/routers/horarios.py: si cambia allá, cambia acá.

export interface TurnoProgramado {
  id: number
  usuario_id: number
  nombre: string
  fecha: string
  hora_inicio: string
  hora_fin: string
  horas: number
  cruza_medianoche: boolean
  estado: 'borrador' | 'publicado' | 'cancelado'
  nota: string | null
}

export interface BaristaSemana {
  usuario_id: number
  nombre: string
  activa: boolean
  turnos: TurnoProgramado[]
  total_horas: number
  excede_jornada: boolean
  horas_sobre_jornada: number
  publicados: number
  borradores: number
}

export interface Tasa {
  id: number
  vigente_desde: string
  jornada_max_semanal: number
  hora_inicio_nocturna: number
  hora_fin_nocturna: number
  recargo_nocturno: number
  recargo_dominical: number
  recargo_dominical_nocturno: number | null
  recargo_dominical_nocturno_efectivo: number
  extra_diurna: number
  extra_nocturna: number
  divisor_hora_mensual: number
  nota: string | null
  confirmar_contador: boolean
}

export interface Semana {
  tienda_id: number
  lunes: string
  domingo: string
  dias: { fecha: string; nombre: string }[]
  jornada_max_semanal: number
  tasa: Tasa
  baristas: BaristaSemana[]
  hay_borradores: boolean
}

export interface TipoNovedad {
  tipo: string
  label: string
  remunerada: boolean
  acredita_horas: boolean
  justifica: boolean
  razon: string
}

export interface Novedad {
  id: number
  usuario_id: number
  nombre: string
  tipo: string
  label: string
  fecha_desde: string
  fecha_hasta: string
  dias: number
  remunerada: boolean
  acredita_horas: boolean
  razon: string
  nota: string | null
  soporte_url: string | null
  created_at: string | null
}

export type EstadoDia =
  | 'ok' | 'no_programado' | 'sin_marcacion' | 'cubrio_otra_sede'
  | 'novedad_remunerada' | 'novedad_no_remunerada' | 'libre'

export interface DiaResumen {
  fecha: string
  horas_planeadas: number
  horas_reales: number
  novedad: Novedad | null
  estado: EstadoDia
}

export interface Estimado {
  valor_hora_ordinaria: number
  detalle: Record<string, number>
  total: number
  es_estimado: boolean
}

export interface BaristaResumen {
  usuario_id: number
  nombre: string
  activa: boolean
  tiene_contrato: boolean
  salario_mensual: number
  horas_planeadas: Record<string, number>
  total_planeado: number
  horas_reales: Record<string, number>
  total_real: number
  horas_acreditadas: Record<string, number>
  total_acreditado: number
  diferencia_horas: number
  tramos_sin_salida: number
  novedades: Novedad[]
  dias_sin_marcacion: string[]
  dias: DiaResumen[]
  estimado: Estimado
}

export interface Resumen {
  tienda_id: number
  anio: number
  mes: number
  desde: string
  hasta: string
  base_liquidacion: string
  base_liquidacion_detalle: string
  advertencias: string[]
  categorias: { clave: string; label: string }[]
  semanas: {
    lunes: string; domingo: string; jornada_max_semanal: number
    vigente_desde: string; confirmar_contador: boolean
  }[]
  baristas: BaristaResumen[]
  totales: {
    total_planeado: number
    total_real: number
    total_acreditado: number
    estimado: number
    dias_sin_marcacion: number
    tramos_sin_salida: number
    sin_contrato: number
  }
}

export interface Contrato {
  usuario_id: number
  nombre: string
  salario_mensual: number
  horas_semana_pactadas: number | null
  fecha_ingreso: string | null
  activo: boolean
  nota: string | null
  tiene_contrato: boolean
}

export interface FestivoRow {
  fecha: string
  nombre: string
  es_festivo: boolean
  origen: string
}

// ─── Helpers de fecha en HORA LOCAL ────────────────────────────────────────
// `new Date('2026-08-10')` se parsea como UTC y en Colombia (UTC-5) retrocede
// un día. Todo el módulo arma las fechas a mano para que el 10 sea el 10.

export function aFecha(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function aISO(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function lunesDe(d: Date): Date {
  const copia = new Date(d)
  const dow = (copia.getDay() + 6) % 7 // 0 = lunes
  copia.setDate(copia.getDate() - dow)
  return copia
}

export function sumarDias(d: Date, n: number): Date {
  const copia = new Date(d)
  copia.setDate(copia.getDate() + n)
  return copia
}

export const fmtHoras = (h: number) =>
  Number.isInteger(h) ? `${h} h` : `${h.toFixed(1)} h`

export const fmtPesos = (v: number) =>
  `$${Math.round(v || 0).toLocaleString('es-CO')}`

export const fmtPct = (v: number) => `${Math.round((v || 0) * 100)}%`

export const fmtDia = (iso: string) => {
  const d = aFecha(iso)
  return `${d.getDate()}/${d.getMonth() + 1}`
}

export const MESES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]
