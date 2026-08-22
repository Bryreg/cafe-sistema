import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { Dato } from '../api/dato'
import { useDato } from '../api/useDato'
import { FranjaDeConfianza } from '../components/ui'
import { hoyBogota } from '../utils/fechaLocal'
import { CuentaBanco, Sede } from '../components/plata/banco'
import { Agenda, Categoria } from '../components/plata/tipos'
import { useLibro } from '../components/plata/useLibro'
import LibroDiario from '../components/plata/LibroDiario'
import FormRecogida from '../components/plata/FormRecogida'
import LoQueViene from '../components/plata/LoQueViene'
import type { Piso } from '../components/piso/tipos'
import BloqueEquilibrio from '../components/piso/BloqueEquilibrio'
import ExtractoDelBanco from '../components/piso/ExtractoDelBanco'

// ═════════════════════════════════════════════════════════════════════════════
// LA PLATA — el libro diario, y alrededor lo que lo explica
// ═════════════════════════════════════════════════════════════════════════════
// El dueño abre esto temprano, antes de abrir el local. El protagonista es EL
// LIBRO —la hoja de su Excel, día por día: arranca + entra − sale = queda— con
// sus movimientos al lado (todos con scroll, o solo los del día que señala).
// Alrededor, en orden:
//
//   1 · el libro y sus movimientos (hero con el resultado del mes arriba)
//   2 · agregar un movimiento (dentro del bloque del libro, siempre montado)
//   3 · el saldo del extracto (el ancla: de ahí arranca la cadena del libro)
//   4 · el punto de equilibrio por sede
//   5 · lo que viene: el cierre estimado de los próximos meses
//
// ── LO QUE VIVE EN «EL MES EN DETALLE» (`/plata/mes`) ─────────────────────
// El margen por producto, sede contra sede y el pulso de comportamiento son
// para ENTENDER, no para decidir a las 7am: viven en la pantalla de detalle,
// a un toque del pie.

export default function Plata() {
  const navigate = useNavigate()
  const hoy = hoyBogota()
  const anio = Number(hoy.slice(0, 4))
  const mes = Number(hoy.slice(5, 7))

  /** Sube con cada mutación de plata: es la dependencia de lo que cambia. */
  const [refresco, setRefresco] = useState(0)
  const refrescarTodo = useCallback(() => setRefresco(n => n + 1), [])

  // ── LA SEDE que se está mirando: null = «Ambas» (las dos sumadas). Desde
  // agosto cada sede lleva su libro; antes, y en Ambas, es el combinado. ────────
  const [sede, setSede] = useState<number | null>(null)
  const tiendas = useDato<Sede[]>(
    () => api.get('/auth/tiendas'), 'las sedes',
    'No se pudieron leer las sedes.')

  // ── Los datos de la página, cada uno un `Dato<T>` (ver src/api/dato.ts) ────
  const piso = useDato<Piso>(
    () => api.get('/costos/piso', { params: { anio, mes } }), 'el piso de venta',
    'No se pudo calcular el piso de venta.', [refresco, anio, mes])

  const agenda = useDato<Agenda>(
    () => api.get('/costos/agenda'), 'la agenda de pagos',
    'No se pudo leer la agenda de pagos.', [refresco])

  const cuentas = useDato<CuentaBanco[]>(
    () => api.get('/banco/cuentas'), 'las cuentas del banco',
    'No se pudieron leer las cuentas del banco.')

  /**
   * El catálogo COMPLETO para el libro: café + personales + banco. Un servidor
   * viejo ignora `ambito` y devuelve solo café: el select del libro ofrece menos
   * opciones un rato, sin mentir.
   */
  const categoriasLibro = useDato<Categoria[]>(
    () => api.get('/costos/categorias', { params: { ambito: 'todas' } }),
    'las categorías del libro',
    'No se pudieron leer las categorías del libro.', [refresco])

  // El libro tiene su propia llave: teclear un movimiento no repide la página
  // entera ni hace parpadear los bloques que nadie tocó.
  const [llaveLibro, setLlaveLibro] = useState(0)
  const libro = useLibro(llaveLibro, sede)

  /** Cambió plata: se repide la página Y el libro. */
  const refrescarPlata = useCallback(() => {
    setLlaveLibro(n => n + 1)
    refrescarTodo()
  }, [refrescarTodo])

  /** Lo que mira la franja de confianza. */
  const fuentes = useMemo(
    () => [piso, agenda, cuentas, categoriasLibro],
    [piso, agenda, cuentas, categoriasLibro])

  // ── El ancla del extracto: la hero manda el foco acá cuando falta el cierre ──
  const refExtracto = useRef<HTMLDivElement>(null)
  const [pedidoFocoExtracto, setPedidoFocoExtracto] = useState(0)
  const irAlExtracto = useCallback(() => {
    refExtracto.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setPedidoFocoExtracto(n => n + 1)
  }, [])

  const irAlDetalleDelMes = useCallback(() => navigate('/plata/mes'), [navigate])

  /** El nombre de la sede elegida (para el título del extracto). */
  const sedeNombre = sede != null && tiendas.dato.estado === 'listo'
    ? tiendas.dato.valor.find(t => t.id === sede)?.nombre
    : undefined

  return (
    <div className="space-y-3 pb-8">
      {/* «¿Le puedo creer a esta pantalla?» en un renglón. Invisible si nada se rompió. */}
      <FranjaDeConfianza fuentes={fuentes} />

      {/* El selector de sede: cada una su libro, o «Ambas» sumadas. */}
      <SelectorSede tiendas={tiendas.dato} sede={sede} onCambiar={setSede} />

      {/* 1 · El libro y sus movimientos + 2 · agregar (adentro, siempre montado). */}
      <LibroDiario
        libro={libro.libro} anio={libro.anio} mes={libro.mes}
        hoy={libro.hoy} viendoElMesDeHoy={libro.viendoElMesDeHoy}
        cuentas={cuentas} agenda={agenda} categorias={categoriasLibro}
        sede={sede} tiendas={tiendas}
        onIrAlMes={libro.irAlMes} onIrAHoy={libro.irAHoy}
        onGuardado={fecha => { libro.irALaFechaDe(fecha); refrescarPlata() }}
        onIrAlAncla={irAlExtracto} />

      {/* 2.5 · Recogí efectivo: la pasada del dueño. Entra a «la mano» del libro
          y descuenta solo el día de esa sede en Consignaciones. Es lo que el
          candado de Consignaciones («Registrá la pasada en La Plata → Recogí
          efectivo») manda a hacer acá. */}
      <div className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-warm-100">
          <p className="text-sm font-bold text-warm-700">Recogí efectivo</p>
          <p className="text-[11px] text-warm-500 mt-0.5">
            Cuando te llevás el efectivo de una sede, registralo acá: entra a <b>la mano</b> y el
            día de esa sede se descuenta solo en Consignaciones — sin marcar nada allá.
          </p>
        </div>
        <FormRecogida tiendas={tiendas} hoy={hoy} pedidoFoco={0} onGuardado={refrescarPlata} />
      </div>

      {/* 3 · El saldo del extracto: el ancla de la cadena del libro. */}
      <div ref={refExtracto}>
        <ExtractoDelBanco
          libro={libro.libroConHoy} hoy={libro.hoy}
          pedidoFoco={pedidoFocoExtracto} sedeNombre={sedeNombre}
          onGuardado={refrescarPlata} onRecargarLibro={libro.recargar} />
      </div>

      {/* 4 · El punto de equilibrio por sede. */}
      <BloqueEquilibrio piso={piso} onCargarCosto={irAlDetalleDelMes} />

      {/* 5 · Lo que viene: el cierre estimado de los próximos meses. */}
      <LoQueViene refreshKey={refresco} />

      {/* La página no navega a ninguna parte, salvo acá. */}
      <button onClick={irAlDetalleDelMes}
        className="w-full min-h-[46px] text-xs font-bold text-forest hover:underline text-left px-1">
        → El mes en detalle: margen por producto, sede contra sede, lo que sube y baja
      </button>

      <p className="text-[11px] text-warm-400 px-1 leading-relaxed">
        El equilibrio se muestra en <b>tres números</b> — lo de Vida, lo de Palmetto y lo
        corporativo que las dos cubren entre las dos — y nunca se prorratea.
      </p>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// El selector de sede: «Ambas» + cada sede. Desde agosto cada una lleva su libro.
// ═════════════════════════════════════════════════════════════════════════════
function SelectorSede({ tiendas, sede, onCambiar }: {
  tiendas: Dato<Sede[]>
  sede: number | null
  onCambiar: (s: number | null) => void
}) {
  // Sin las sedes (cargando o caído) el selector no aparece: el libro se ve
  // igual como «Ambas». No es un gate del libro —es una comodidad de navegación—.
  if (tiendas.estado !== 'listo' || tiendas.valor.length < 2) return null
  const opciones: { id: number | null; nombre: string }[] = [
    { id: null, nombre: 'Ambas' },
    ...tiendas.valor.map(t => ({ id: t.id, nombre: t.nombre })),
  ]
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-[11px] font-bold uppercase tracking-wide text-warm-400 mr-1">Sede</span>
      {opciones.map(o => {
        const activo = sede === o.id
        return (
          <button key={o.id ?? 'ambas'} onClick={() => onCambiar(o.id)}
            aria-pressed={activo}
            className={`min-h-[40px] px-4 rounded-xl text-sm font-bold border-2 transition-colors ${
              activo
                ? 'border-forest bg-forest text-white'
                : 'border-warm-200 bg-white text-warm-600 hover:border-forest-300'}`}>
            {o.nombre}
          </button>
        )
      })}
    </div>
  )
}
