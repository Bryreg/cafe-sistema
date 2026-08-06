import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { Scale, Download, TrendingUp, TrendingDown, Minus, AlertTriangle, RotateCcw, Cpu, Users, ListChecks, Unlock, DatabaseZap } from 'lucide-react'
import { hoyLocal } from '../utils/fechaLocal'

// ── Doble inventario del día (tabla Detalle) ─────────────────────────────────
interface CeldaConteo { real: number; diferencia: number; sistema: number }
interface FilaDiaria {
  producto_id: number; nombre: string; unidad: string
  sistema: number; apertura: CeldaConteo | null; entradas: number; cierre: CeldaConteo | null
}
interface CierrePrevio {
  fecha: string; barista: string | null; atajo: boolean
  por_producto: Record<number, { real: number; diferencia: number }>
}
interface Reincidente {
  producto_id: number; nombre: string; unidad: string
  dias_con_faltante: number; total_faltante: number; valor_faltante: number
}
interface ConciliacionDiaria {
  tiene_apertura: boolean; tiene_cierre: boolean
  apertura_barista: string | null; cierre_barista: string | null
  apertura_atajo?: boolean; cierre_atajo?: boolean
  items: FilaDiaria[]
  cierres_previos: CierrePrevio[]
  resumen: { faltante_valor: number; faltante_productos: number; sobrante_valor: number; sobrante_productos: number } | null
  reincidentes: Reincidente[]
  cierres_en_ventana: number
  atajos_en_ventana: number
}

interface Item {
  id: number; producto_nombre: string; categoria: string; unidad_medida: string
  cantidad_sistema: number; cantidad_real: number | null
  // Si el número de al lado lo puso una persona o lo rellenó el cierre. El cierre
  // iguala cantidad_real al sistema para todo lo no contado (así la diferencia da
  // 0), y sin esta bandera un mes contado a medias se ve idéntico a uno completo.
  fue_contado: boolean
  diferencia: number; valor_unitario: number; valor_diferencia: number
}
interface Cat { categoria: string; valor_diferencia: number; items: number; con_diferencia: number }
interface Conciliacion {
  id: number; anio: number; mes: number; estado: string
  // Con valor = el mes YA pasó por un cierre, aunque hoy figure "en proceso" por
  // una reabertura. Desde ese momento la foto del período no se re-sincroniza
  // nunca más con el catálogo vivo, y la pantalla no puede prometer lo contrario.
  fecha_primer_cierre: string | null
  fecha_aplicado: string | null
  valor_diferencia_total: number; items: Item[]
  contados: number; total_items: number
  resumen: {
    positivas: number; negativas: number; sin_diferencia: number
    valor_positivo: number; valor_negativo: number; valor_neto: number
    contados: number; no_contados: number
  }
  por_categoria: Cat[]; ranking: Item[]
}
// Qué pasaría al aplicar, ANTES de aplicar. Aplicar es irreversible y usa la
// diferencia congelada en el cierre contra el stock de HOY: sin esta vista, un
// clic podía dejar decenas de productos en 0 sin que nadie viera venir el número.
interface ItemPrevio {
  item_id: number; producto_id: number; producto_nombre: string; unidad_medida: string
  stock_actual: number; diferencia: number
  stock_nuevo: number          // crudo, SIN recortar en 0
  negativo: boolean; fue_contado: boolean; valor_diferencia: number
}
interface PrevioAplicacion {
  inventario_id: number; items: ItemPrevio[]
  ajustados: number; en_cero: number; negativos: number; valor_total: number
  contados: number; total_items: number
  // true = hay negativos. El backend rechaza aplicar TODO; se puede aplicar el
  // resto pidiendo explícitamente excluirlos (omitir_negativos).
  bloqueado: boolean
}
interface Tienda { id: number; nombre: string }

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const CAT_LABEL: Record<string, string> = { pasteleria: 'Pastelería', bebida: 'Bebidas', insumo: 'Insumos' }
const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')
const num = (v: number) => Math.round(v || 0).toLocaleString('es-CO')

export default function ConciliacionInventario() {
  const now = new Date()
  const [anio, setAnio] = useState(now.getFullYear())
  const [mes, setMes] = useState(now.getMonth() + 1)
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [data, setData] = useState<Conciliacion | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas').then(r => { setTiendas(r.data); setTiendaId(p => p ?? (r.data[0]?.id ?? null)) }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!tiendaId) return
    setLoading(true)
    api.get<Conciliacion | null>('/inventario-mensual/conciliacion', { params: { tienda_id: tiendaId, anio, mes } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [tiendaId, anio, mes])

  // ── Doble inventario del día ──────────────────────────────────────────────
  const [dia, setDia] = useState(hoyLocal())
  const [diaria, setDiaria] = useState<ConciliacionDiaria | null>(null)
  const [loadingDia, setLoadingDia] = useState(false)

  useEffect(() => {
    if (!tiendaId) return
    setLoadingDia(true)
    api.get<ConciliacionDiaria>(`/conteos/conciliacion-diaria/${tiendaId}`, { params: { fecha: dia } })
      .then(r => setDiaria(r.data))
      .catch(() => setDiaria(null))
      .finally(() => setLoadingDia(false))
  }, [tiendaId, dia])

  // Cierres previos en orden CRONOLÓGICO (el más viejo primero): van a la
  // izquierda de la apertura, como línea de tiempo que termina en hoy.
  const prevAsc = useMemo(() => [...(diaria?.cierres_previos ?? [])].reverse(), [diaria])

  // GEOMETRÍA EXACTA (table-layout: fixed): el ancho VISIBLE se divide en 7
  // partes IGUALES — las 3 primeras fijas (sticky en 0 / 1w / 2w) y las 4 del
  // día con el mismo ancho. Los cierres previos (140px c/u) viven más allá del
  // borde y solo aparecen deslizando.
  const ANCHO_PREVIO = 140
  const [anchoVisible, setAnchoVisible] = useState(1400)
  const scrollTabla = useRef<HTMLDivElement>(null)
  const colW = Math.max(90, anchoVisible / 7)

  useEffect(() => {
    const medir = () => {
      const el = scrollTabla.current
      if (el) setAnchoVisible(el.clientWidth)
    }
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, [diaria])

  // La tabla arranca desplazada al PRESENTE (extremo derecho): la historia
  // queda detrás, deslizando hacia atrás. Asignación SÍNCRONA en el effect —
  // requestAnimationFrame no corre en pestañas en segundo plano (PWA) y el
  // scroll quedaba en 0 si la pestaña no estaba visible al cargar.
  useEffect(() => {
    const el = scrollTabla.current
    if (!el || !diaria) return
    el.scrollLeft = el.scrollWidth
    const t = setTimeout(() => { el.scrollLeft = el.scrollWidth }, 250)  // respaldo post-layout
    return () => clearTimeout(t)
  }, [diaria, loadingDia, anchoVisible])

  // Arrastrar-para-desplazar: agarrar la tabla con el mouse la mueve en vez de
  // seleccionar texto (que es lo que el dueño notaba al no ver barra). Pointer
  // events cubren mouse y táctil; setPointerCapture no pierde el drag al salir.
  useEffect(() => {
    const el = scrollTabla.current
    if (!el) return
    let dragging = false, startX = 0, startScroll = 0
    const down = (e: PointerEvent) => {
      if (e.button !== 0) return
      dragging = true
      startX = e.clientX
      startScroll = el.scrollLeft
      try { el.setPointerCapture(e.pointerId) } catch { /* noop */ }
      el.style.cursor = 'grabbing'
      el.style.userSelect = 'none'
    }
    const move = (e: PointerEvent) => {
      if (!dragging) return
      el.scrollLeft = startScroll - (e.clientX - startX)
    }
    const up = (e: PointerEvent) => {
      dragging = false
      el.style.cursor = ''
      el.style.userSelect = ''
      try { el.releasePointerCapture(e.pointerId) } catch { /* noop */ }
    }
    el.addEventListener('pointerdown', down)
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
    el.addEventListener('pointercancel', up)
    return () => {
      el.removeEventListener('pointerdown', down)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
      el.removeEventListener('pointercancel', up)
    }
  }, [diaria])

  // Default: la lista COMPLETA del turno (sistema vivo + ultima apertura + cierre
  // cuando exista). El toggle de diferencias es opcional, para revisar dias viejos.
  const [soloDif, setSoloDif] = useState(false)
  const filasDia = useMemo(() => (diaria?.items ?? []).filter(i =>
    !soloDif ||
    (i.apertura !== null && i.apertura.diferencia !== 0) ||
    (i.cierre !== null && i.cierre.diferencia !== 0)
  ), [diaria, soloDif])

  const [reiniciando, setReiniciando] = useState(false)
  const reiniciarMes = async () => {
    if (!tiendaId) return
    if (!window.confirm(`¿Reiniciar el conteo de ${MESES[mes - 1]} de esta sede? Se borra el avance del mes y se vuelve a sembrar con el conteo del sistema ACTUAL (en gramos). Los meses cerrados no se tocan.`)) return
    setReiniciando(true)
    try {
      await api.post('/inventario-mensual/reiniciar', null, { params: { tienda_id: tiendaId, anio, mes } })
      const r = await api.get<Conciliacion | null>('/inventario-mensual/conciliacion', { params: { tienda_id: tiendaId, anio, mes } })
      setData(r.data)
      alert('Mes reiniciado — re-sembrado con el conteo del sistema actual.')
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo reiniciar')
    } finally { setReiniciando(false) }
  }

  const recargarMes = async () => {
    const r = await api.get<Conciliacion | null>('/inventario-mensual/conciliacion', { params: { tienda_id: tiendaId, anio, mes } })
    setData(r.data)
  }

  const [aplicando, setAplicando] = useState(false)
  const [previo, setPrevio] = useState<PrevioAplicacion | null>(null)
  // Renglones que se pueden ajustar sin romper el inventario: el plan completo
  // menos los que quedarían en negativo. Es el número que manda cuando hay
  // trabados, porque es lo que realmente se va a escribir.
  const sanos = previo ? previo.ajustados - previo.negativos : 0

  // Paso 1 de 2: pedir el PLAN. No se puede apretar "aplicar" a ciegas — la
  // operación es irreversible y opera con una diferencia congelada en el cierre
  // contra un stock que pudo moverse desde entonces.
  const previsualizarAplicacion = async () => {
    if (!data) return
    setAplicando(true)
    try {
      const r = await api.get<PrevioAplicacion>(`/inventario-mensual/${data.id}/previsualizar-aplicacion`)
      setPrevio(r.data)
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo calcular la previsualización')
    } finally { setAplicando(false) }
  }

  // Paso 2 de 2: aplicar de verdad, ya con el resumen a la vista.
  //
  // `omitirNegativos` es la salida al bloqueo, y es EXPLÍCITA. Sin ella, un solo
  // renglón trabado frenaba el conteo entero y la única forma de avanzar era
  // corregir ese físico a mano — o sea, escribir un número que nadie contó y que
  // el sistema marca como CONTADO. El admin tiene que poder seguir sin mentir:
  // se aplican los sanos, los trabados quedan afuera y con constancia.
  const aplicarMes = async (omitirNegativos = false) => {
    if (!data || !previo) return
    if (previo.bloqueado && !omitirNegativos) return
    setAplicando(true)
    try {
      const r = await api.post(`/inventario-mensual/${data.id}/aplicar`, null,
        omitirNegativos ? { params: { omitir_negativos: true } } : undefined)
      setPrevio(null)
      await recargarMes()
      alert(`Aplicado: ${r.data.ajustados} productos ajustados`
        + `${r.data.en_cero > 0 ? ` (${r.data.en_cero} quedaron en 0)` : ''}.`
        + `${r.data.excluidos > 0
          ? `\n\nSe EXCLUYERON ${r.data.excluidos} producto(s) que habrían quedado en stock negativo: `
            + `${r.data.items_excluidos.map((i: ItemPrevio) => i.producto_nombre).join(', ')}. `
            + 'Su diferencia no se aplicó (quedó registrada en la auditoría): la foto del cierre ya '
            + 'no calzaba con el stock de hoy.'
          : ''}`)
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo aplicar')
    } finally { setAplicando(false) }
  }

  const corregirItem = async (it: Item) => {
    if (!data || data.estado !== 'cerrado' || data.fecha_aplicado) return
    const resp = window.prompt(`Corregir físico de ${it.producto_nombre} (${it.unidad_medida}):`, String(it.cantidad_real ?? ''))
    if (resp === null) return
    const v = parseFloat(resp.replace(',', '.'))
    if (isNaN(v) || v < 0) { alert('Valor inválido'); return }
    try {
      await api.patch(`/inventario-mensual/items/${it.id}`, { cantidad_real: v })
      await recargarMes()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo corregir')
    }
  }

  const [reabriendo, setReabriendo] = useState(false)
  // Un mismo endpoint, DOS operaciones muy distintas — y la confirmación dice
  // exactamente cuál va a correr, porque tienen consecuencias opuestas:
  //
  //  · mes que YA SE CERRÓ alguna vez → solo se destraba el estado. La foto del
  //    período (existencia teórica, físico contado y diferencias) queda intacta.
  //    Antes esto re-fotografiaba el stock de HOY y ponía las diferencias en 0:
  //    reabrir julio en agosto borraba la fuga de julio para siempre.
  //  · mes que NUNCA se cerró → se sincroniza con el catálogo vivo (productos
  //    nuevos, unidades, sistema). No hay foto que proteger todavía.
  //
  // La distinción es `fecha_primer_cierre` y NO el estado actual: un mes ya
  // reabierto figura "en proceso" pero conserva su medición, así que prometerle
  // al admin una sincronización con el catálogo sería mentirle — el backend no
  // la va a hacer.
  const yaSeCerroAlgunaVez = !!data && (data.estado === 'cerrado' || !!data.fecha_primer_cierre)
  const reabrirMes = async () => {
    if (!tiendaId) return
    const msg = yaSeCerroAlgunaVez
      ? `¿Reabrir el conteo de ${MESES[mes - 1]} para seguir contando?\n\n`
        + 'QUÉ CAMBIA: solo el estado, que vuelve a "en proceso".\n\n'
        + 'QUÉ NO SE TOCA: la existencia teórica del mes, lo que ya se contó y las '
        + 'diferencias que encontró el cierre quedan exactamente como están. La foto '
        + 'del período no se pisa con el stock de hoy.\n\n'
        + 'Al volver a cerrar, las diferencias se recalculan con lo que haya contado.'
      : `¿Sincronizar el conteo de ${MESES[mes - 1]} con el catálogo vivo?\n\n`
        + 'Agrega los productos que falten y refresca unidades, costos y existencia '
        + 'teórica desde el sistema ACTUAL.\n\n'
        + 'OJO: lo contado se conserva, salvo los productos cuya unidad cambió — esos '
        + 'pierden su conteo y hay que recontarlos.'
    if (!window.confirm(msg)) return
    setReabriendo(true)
    try {
      await api.post('/inventario-mensual/reabrir', null, { params: { tienda_id: tiendaId, anio, mes } })
      const r = await api.get<Conciliacion | null>('/inventario-mensual/conciliacion', { params: { tienda_id: tiendaId, anio, mes } })
      setData(r.data)
      alert(yaSeCerroAlgunaVez
        ? 'Listo — el mes quedó en proceso y la medición del período se conservó.'
        : 'Listo — el conteo quedó sincronizado con el catálogo vivo.')
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo completar')
    } finally { setReabriendo(false) }
  }

  // ── Foto mensual: cálculo VIVO renglón por renglón ─────────────────────────
  // La diferencia se calcula acá (real − sistema) y no con la almacenada: en un
  // conteo en proceso la almacenada es 0 hasta el cierre, y así la tabla sirve
  // igual para seguir el conteo en vivo que para revisar un mes cerrado.
  const [soloDifMes, setSoloDifMes] = useState(false)
  const [buscarMes, setBuscarMes] = useState('')
  const mensual = useMemo(() => {
    if (!data) return null
    const items = data.items.map(i => {
      // «Contado» = lo puso una PERSONA, y eso lo dice `fue_contado` y NADA MÁS.
      // Aceptar `cantidad_real` como respaldo era inventar cobertura: el cierre la
      // rellena en TODOS los renglones con el valor del sistema, así que al reabrir
      // un mes cerrado el badge saltaba de «12 de 180» (rojo) a «180 de 180»
      // (verde) sin que nadie hubiera contado un solo producto más.
      const contado = i.fue_contado
      const dif = contado ? (i.cantidad_real as number) - i.cantidad_sistema : 0
      return { ...i, contado, dif, valorDif: dif * (i.valor_unitario || 0) }
    })
    const contados = items.filter(i => i.contado)
    return {
      items,
      nContados: contados.length,
      // Conteos anteriores a la bandera: tienen físico cargado y ni un renglón
      // marcado. No se puede saber qué se contó de verdad, así que se dice que no
      // se sabe — nunca un verde inventado ni un rojo que acusa de no haber contado.
      legacySinBandera: contados.length === 0
        && items.some(i => i.cantidad_real !== null && i.cantidad_real !== undefined),
      positivas: contados.filter(i => i.dif > 0).length,
      negativas: contados.filter(i => i.dif < 0).length,
      exactas: contados.filter(i => i.dif === 0).length,
      valorNeto: contados.reduce((s, i) => s + i.valorDif, 0),
    }
  }, [data])
  const filasMes = useMemo(() => {
    if (!mensual) return []
    const q = buscarMes.trim().toLowerCase()
    return mensual.items
      .filter(i => !q || i.producto_nombre.toLowerCase().includes(q))
      .filter(i => !soloDifMes || (i.contado && i.dif !== 0))
      .sort((a, b) => Math.abs(b.valorDif) - Math.abs(a.valorDif) || Math.abs(b.dif) - Math.abs(a.dif))
  }, [mensual, soloDifMes, buscarMes])

  const exportarCSV = () => {
    if (!data) return
    const head = ['Producto', 'Categoria', 'Unidad', 'Sistema', 'Fisico', 'Diferencia', 'Valor unit', 'Valor diferencia']
    const filas = data.items.map(i => [i.producto_nombre, i.categoria, i.unidad_medida, i.cantidad_sistema, i.cantidad_real ?? 0, i.diferencia, i.valor_unitario, i.valor_diferencia])
    const csv = [head, ...filas].map(r => r.join(';')).join('\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `conciliacion-${anio}-${String(mes).padStart(2, '0')}.csv`
    a.click()
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Scale size={20} className="text-forest" />
          <h1 className="text-lg font-bold text-gray-800">Conciliación de Inventario</h1>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <select value={mes} onChange={e => setMes(Number(e.target.value))} className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            {MESES.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select value={anio} onChange={e => setAnio(Number(e.target.value))} className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            {Array.from({ length: 5 }, (_, i) => now.getFullYear() - i).map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          {data && !data.fecha_aplicado && (
            <button onClick={reabrirMes} disabled={reabriendo || !tiendaId}
              title={yaSeCerroAlgunaVez
                ? "Vuelve el conteo del mes a 'en proceso' conservando intacta la medición del período (no se re-sincroniza con el catálogo)"
                : 'Agrega los productos que falten y refresca unidades y sistema del conteo en proceso'}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-forest hover:bg-forest-700 disabled:opacity-40 text-white">
              {yaSeCerroAlgunaVez
                ? <><Unlock size={14} /> {reabriendo ? 'Reabriendo…' : 'Reabrir mes'}</>
                : <><RotateCcw size={14} /> {reabriendo ? 'Sincronizando…' : 'Sincronizar catálogo'}</>}
            </button>
          )}
          {/* Reiniciar borra el conteo y lo re-siembra con el stock de HOY: contra
              un mes que ya se cerró eso es destruir la medición del período por
              otra puerta (reabrir + reiniciar). El backend lo rechaza; el botón
              no puede invitar a intentarlo. */}
          <button onClick={reiniciarMes} disabled={reiniciando || !tiendaId || yaSeCerroAlgunaVez}
            title="Borra el avance del mes en proceso y re-siembra con el conteo del sistema actual"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-amber-500 hover:bg-amber-600 disabled:opacity-40 text-white">
            <RotateCcw size={14} /> {reiniciando ? 'Reiniciando…' : 'Reiniciar mes'}
          </button>
          <button onClick={exportarCSV} disabled={!data}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white">
            <Download size={14} /> Excel
          </button>
        </div>
      </div>

      {/* Doble inventario: cómo se lee este panel bajo el modelo nuevo */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="bg-white rounded-2xl border border-gray-200 p-4 flex items-start gap-3">
          <span className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center shrink-0"><Cpu size={17} className="text-blue-600" /></span>
          <div>
            <p className="text-sm font-bold text-gray-800">Conteo del sistema</p>
            <p className="text-xs text-gray-500 mt-0.5">Corre solo, por movimientos: ventas del POS (con recetas en gramos), ingresos por factura, mermas y salidas.</p>
          </div>
        </div>
        <div className="bg-white rounded-2xl border border-gray-200 p-4 flex items-start gap-3">
          <span className="w-9 h-9 rounded-xl bg-amber-50 flex items-center justify-center shrink-0"><Users size={17} className="text-amber-600" /></span>
          <div>
            <p className="text-sm font-bold text-gray-800">Conteo de las baristas</p>
            <p className="text-xs text-gray-500 mt-0.5">Físico, en apertura y cierre. No modifica el inventario: se compara contra el sistema y las diferencias quedan registradas.</p>
          </div>
        </div>
        <Link to="/conteos-admin" className="bg-white rounded-2xl border border-gray-200 p-4 flex items-start gap-3 hover:border-forest transition-colors">
          <span className="w-9 h-9 rounded-xl bg-green-50 flex items-center justify-center shrink-0"><ListChecks size={17} className="text-green-700" /></span>
          <div>
            <p className="text-sm font-bold text-gray-800">Diferencias del día →</p>
            <p className="text-xs text-gray-500 mt-0.5">Monitor de Conteos: sistema vs contado por conteo, verificaciones y "Aplicar al inventario". Este panel es la foto MENSUAL.</p>
          </div>
        </Link>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {tiendas.map(t => (
          <button key={t.id} onClick={() => setTiendaId(t.id)}
            className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${tiendaId === t.id ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'}`}>{t.nombre}</button>
        ))}
      </div>

      {/* ── Foto MENSUAL: el conteo de fin de mes, renglón por renglón ── */}
      {loading ? (
        <div className="bg-white rounded-2xl border border-gray-200 p-6 text-center text-sm text-gray-400 animate-pulse">Cargando conteo mensual…</div>
      ) : !data || !mensual ? (
        <div className="bg-white rounded-2xl border border-gray-200 p-6 text-center text-sm text-gray-400">
          Sin conteo mensual para {MESES[mes - 1]} {anio} en esta sede.
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-200">
          <div className={`flex flex-wrap items-center gap-3 px-4 py-3 rounded-t-2xl ${data.estado === 'cerrado' ? 'bg-green-50' : 'bg-amber-50'}`}>
            <p className="text-sm font-bold text-gray-800 m-0">
              Inventario mensual — {MESES[mes - 1]} {anio}
            </p>
            <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${data.estado === 'cerrado' ? 'bg-green-600 text-white' : 'bg-amber-500 text-white'}`}>
              {data.estado === 'cerrado' ? 'Cerrado' : 'En proceso'}
            </span>
            {/* Cobertura del conteo, en grande y al lado del estado: un mes con 12
                de 180 productos contados no puede leerse como uno completo, y su
                diferencia total no significa lo mismo. */}
            {mensual.legacySinBandera ? (
              // Conteo anterior a la bandera: decir "0 de 180" sería acusar de no
              // haber contado, y decir "180 de 180" sería inventar un verde. No
              // hay dato, y eso es lo que se muestra.
              <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-gray-100 text-gray-500"
                title="Este conteo es anterior a que el sistema registrara quién contó qué: no hay forma de saber cuántos productos se contaron de verdad.">
                sin dato de cobertura
              </span>
            ) : (
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                mensual.items.length === 0 ? 'bg-gray-100 text-gray-500'
                  : mensual.nContados === mensual.items.length ? 'bg-green-100 text-green-700'
                  : mensual.nContados * 2 >= mensual.items.length ? 'bg-amber-100 text-amber-700'
                  : 'bg-red-100 text-red-700'
              }`} title="Productos que contó una persona. El resto lo rellenó el cierre con el valor del sistema (diferencia 0), así que no aporta información.">
                {mensual.nContados} de {mensual.items.length} productos contados
              </span>
            )}
            <span className="text-xs text-gray-500">
              {mensual.positivas} sobran · {mensual.negativas} faltan · {mensual.exactas} exactos
            </span>
            {data.estado === 'cerrado' && !data.fecha_aplicado && (
              <button onClick={previsualizarAplicacion} disabled={aplicando}
                title="Muestra primero en qué stock queda cada producto; recién después se aplica"
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white">
                <DatabaseZap size={13} /> {aplicando ? 'Calculando…' : 'Aplicar al inventario'}
              </button>
            )}
            {data.fecha_aplicado && (
              <span className="text-[11px] font-bold text-green-700 bg-green-100 px-2 py-0.5 rounded-full"
                title="El stock del sistema ya se ajustó con las diferencias de este conteo — el mes es histórico">
                ✓ Aplicado al inventario el {data.fecha_aplicado.slice(0, 10)}
              </span>
            )}
            <span className={`ml-auto text-sm font-bold font-mono ${mensual.valorNeto < 0 ? 'text-red-600' : mensual.valorNeto > 0 ? 'text-blue-600' : 'text-gray-700'}`}>
              {fmt(mensual.valorNeto)}
            </span>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-100 flex-wrap">
            <input value={buscarMes} onChange={e => setBuscarMes(e.target.value)} placeholder="Buscar producto…"
              className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 w-48 focus:outline-none focus:border-forest" />
            <button onClick={() => setSoloDifMes(v => !v)}
              className={`text-xs px-3 py-1 rounded-lg font-semibold transition-colors ${soloDifMes ? 'bg-gray-700 text-white' : 'bg-gray-100 text-gray-500'}`}>
              {soloDifMes ? '✓ Solo diferencias' : 'Solo diferencias'}
            </button>
            <span className="text-[11px] text-gray-400 ml-auto">ordenado por impacto en $</span>
          </div>
          <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50">
                <tr className="text-[11px] uppercase tracking-wide text-gray-400">
                  <th className="text-left px-3 py-2 font-bold">Producto</th>
                  <th className="text-right px-3 py-2 font-bold">Sistema</th>
                  <th className="text-right px-3 py-2 font-bold">Físico</th>
                  <th className="text-right px-3 py-2 font-bold">Diferencia</th>
                  <th className="text-right px-3 py-2 font-bold">Valor dif.</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filasMes.map(i => (
                  <tr key={i.id} className={`hover:bg-gray-50 ${!i.contado ? 'bg-gray-50/60' : ''}`}>
                    <td className="px-3 py-1.5 font-medium text-gray-700">
                      {i.producto_nombre} <span className="text-xs text-gray-400">{i.unidad_medida}</span>
                      {!i.contado && <span className="text-[10px] font-bold text-amber-600 ml-1.5">sin contar</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-gray-500">{num(i.cantidad_sistema)}</td>
                    <td className="px-3 py-1.5 text-right font-mono font-bold text-gray-800">
                      {data.estado === 'cerrado' && !data.fecha_aplicado ? (
                        <button onClick={() => corregirItem(i)} title="Corregir este físico (dedazo del conteo)"
                          className="underline decoration-dotted decoration-gray-300 underline-offset-2 hover:text-forest">
                          {i.contado ? num(i.cantidad_real as number) : '—'}
                        </button>
                      ) : (i.contado ? num(i.cantidad_real as number) : '—')}
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono font-bold ${!i.contado ? 'text-gray-300' : i.dif === 0 ? 'text-green-600' : i.dif < 0 ? 'text-red-600' : 'text-blue-600'}`}>
                      {!i.contado ? '—' : i.dif === 0 ? '✓ 0' : `${i.dif > 0 ? '+' : ''}${num(i.dif)}`}
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono ${!i.contado || i.dif === 0 ? 'text-gray-300' : i.valorDif < 0 ? 'text-red-600 font-bold' : 'text-blue-600 font-bold'}`}>
                      {!i.contado || i.dif === 0 ? '—' : fmt(i.valorDif)}
                    </td>
                  </tr>
                ))}
                {filasMes.length === 0 && (
                  <tr><td colSpan={5} className="px-3 py-6 text-center text-sm text-gray-400">
                    {soloDifMes ? 'Sin diferencias con este filtro.' : 'Sin productos que coincidan con la búsqueda.'}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
          {mensual.legacySinBandera && (
            <p className="px-3 py-2 text-[11px] text-amber-700 bg-amber-50 border-t border-amber-100 flex items-start gap-1.5">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>Este conteo es anterior a que el sistema registrara <b>quién contó qué</b>. Tiene
                físico cargado, pero no hay forma de saber cuáles renglones se contaron de verdad y
                cuáles los rellenó el cierre: por eso la cobertura figura sin dato en vez de mostrar
                un número que sería inventado. Los meses nuevos sí lo distinguen.</span>
            </p>
          )}
          <p className="px-3 py-2 text-[11px] text-gray-400 border-t border-gray-50">
            La diferencia se calcula en vivo (físico − sistema actual del conteo). "Sin contar" = nadie
            registró ese producto; en un mes cerrado el cierre le puso el valor del sistema, así que su
            diferencia es 0 por construcción y no significa que haya cuadrado. El Excel exporta esta misma foto.
          </p>
        </div>
      )}

      {/* ── Previsualización de "Aplicar al inventario" ─────────────────────── */}
      {previo && data && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setPrevio(null)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="font-bold text-gray-800 flex items-center gap-2">
                <DatabaseZap size={17} className="text-indigo-600" />
                Esto le va a pasar al inventario
              </h2>
              <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                El stock de cada producto se ajusta <b>sumando la diferencia</b> que descubrió el
                conteo de {MESES[mes - 1]} (no se pisa con el físico absoluto, así las ventas
                posteriores al cierre no se pierden). Queda un movimiento de ajuste por producto.
                <b> No se puede repetir ni deshacer.</b>
              </p>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 px-5 py-3 bg-gray-50">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wide text-gray-400">Productos</p>
                <p className="text-lg font-bold font-mono text-gray-800">{previo.ajustados}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wide text-gray-400">Quedan en 0</p>
                <p className={`text-lg font-bold font-mono ${previo.en_cero > 0 ? 'text-amber-600' : 'text-gray-800'}`}>{previo.en_cero}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wide text-gray-400">Negativos</p>
                <p className={`text-lg font-bold font-mono ${previo.negativos > 0 ? 'text-red-600' : 'text-gray-800'}`}>{previo.negativos}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wide text-gray-400">Impacto</p>
                <p className={`text-lg font-bold font-mono ${previo.valor_total < 0 ? 'text-red-600' : 'text-blue-600'}`}>{fmt(previo.valor_total)}</p>
              </div>
            </div>

            {/* De cuánto del inventario habla este ajuste: si el conteo fue parcial,
                el stock se mueve igual y conviene saberlo antes de confirmar. */}
            {previo.contados < previo.total_items && (
              <p className="mx-5 mt-3 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 flex items-start gap-1.5">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span>Este conteo cubrió <b>{previo.contados} de {previo.total_items} productos</b>. El
                  resto no se contó y no se va a mover — pero tampoco quedó verificado.</span>
              </p>
            )}

            {previo.bloqueado && (
              <p className="mx-5 mt-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 flex items-start gap-1.5">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span><b>{previo.negativos} producto(s) quedarían en stock NEGATIVO</b> (marcados en
                  rojo abajo): la diferencia del conteo es más grande que lo que queda hoy, o sea que
                  la foto del cierre ya no calza con el inventario actual. Podés{' '}
                  <b>aplicar el resto y excluirlos</b> —queda registrado cuáles y por qué— o corregir
                  esos renglones en la tabla de arriba (clic sobre el físico) y volver a intentar.
                  {sanos === 0 && ' Acá no queda ningún renglón sano, así que solo sirve corregirlos.'}</span>
              </p>
            )}

            <div className="overflow-y-auto flex-1 px-5 py-3">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white">
                  <tr className="text-[11px] uppercase tracking-wide text-gray-400">
                    <th className="text-left py-1.5 font-bold">Producto</th>
                    <th className="text-right py-1.5 font-bold">Hoy</th>
                    <th className="text-right py-1.5 font-bold">Ajuste</th>
                    <th className="text-right py-1.5 font-bold">Queda en</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {previo.items.map(i => (
                    <tr key={i.item_id} className={i.negativo ? 'bg-red-50' : ''}>
                      <td className="py-1.5 font-medium text-gray-700">
                        {i.producto_nombre} <span className="text-xs text-gray-400">{i.unidad_medida}</span>
                        {!i.fue_contado && <span className="text-[10px] font-bold text-amber-600 ml-1.5">sin contar</span>}
                      </td>
                      <td className="py-1.5 text-right font-mono text-gray-500">{num(i.stock_actual)}</td>
                      <td className={`py-1.5 text-right font-mono ${i.diferencia < 0 ? 'text-red-600' : 'text-blue-600'}`}>
                        {i.diferencia > 0 ? '+' : ''}{num(i.diferencia)}
                      </td>
                      <td className={`py-1.5 text-right font-mono font-bold ${
                        i.negativo ? 'text-red-700' : i.stock_nuevo === 0 ? 'text-amber-600' : 'text-gray-800'
                      }`}>
                        {num(i.stock_nuevo)}
                      </td>
                    </tr>
                  ))}
                  {previo.items.length === 0 && (
                    <tr><td colSpan={4} className="py-6 text-center text-sm text-gray-400">
                      Ningún producto tiene diferencia: aplicar no cambiaría nada.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex items-center gap-2 px-5 py-4 border-t border-gray-100">
              <button onClick={() => setPrevio(null)}
                className="px-4 py-2.5 rounded-xl text-sm font-bold text-gray-600 bg-gray-100 hover:bg-gray-200">
                Cancelar
              </button>
              {/* Con renglones trabados el botón NO es un muro: aplica los sanos y
                  excluye los otros. Lo dice en el propio botón, con los dos números,
                  para que nadie confunda "se aplicó" con "se aplicó todo". */}
              <button onClick={() => aplicarMes(previo.bloqueado)}
                disabled={aplicando || sanos === 0}
                className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-bold text-white disabled:opacity-40 ${
                  previo.bloqueado ? 'bg-amber-600 hover:bg-amber-700' : 'bg-indigo-600 hover:bg-indigo-700'
                }`}>
                {aplicando ? 'Aplicando…'
                  : previo.ajustados === 0 ? 'No hay diferencias que aplicar'
                  : sanos === 0 ? 'Todos quedarían en negativo: hay que corregirlos'
                  : previo.bloqueado
                    ? `Aplicar a ${sanos} producto${sanos === 1 ? '' : 's'} y excluir ${previo.negativos} — no se puede deshacer`
                    : `Aplicar a ${previo.ajustados} producto${previo.ajustados === 1 ? '' : 's'} — no se puede deshacer`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Señales de decisión: ¿a dónde se está yendo el producto? ── */}
      {diaria && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1">
                <TrendingDown size={12} className="text-red-500" /> Faltante del cierre
              </p>
              {diaria.tiene_cierre && diaria.resumen ? (
                <>
                  <p className="text-xl font-bold text-red-600 font-mono">{fmt(diaria.resumen.faltante_valor)}</p>
                  <p className="text-xs text-gray-400">{diaria.resumen.faltante_productos} productos · {dia}</p>
                </>
              ) : (
                <>
                  <p className="text-xl font-bold text-gray-300 font-mono">—</p>
                  <p className="text-xs text-gray-400">sin cierre aún</p>
                </>
              )}
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1">
                <TrendingUp size={12} className="text-blue-500" /> Sobrante del cierre
              </p>
              {diaria.tiene_cierre && diaria.resumen ? (
                <>
                  <p className="text-xl font-bold text-blue-600 font-mono">{fmt(diaria.resumen.sobrante_valor)}</p>
                  <p className="text-xs text-gray-400">{diaria.resumen.sobrante_productos} productos</p>
                </>
              ) : (
                <>
                  <p className="text-xl font-bold text-gray-300 font-mono">—</p>
                  <p className="text-xs text-gray-400">sin cierre aún</p>
                </>
              )}
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Fugas recurrentes</p>
              <p className={`text-xl font-bold font-mono ${diaria.reincidentes.filter(r => r.dias_con_faltante >= 2).length > 0 ? 'text-red-600' : 'text-green-700'}`}>
                {diaria.reincidentes.filter(r => r.dias_con_faltante >= 2).length}
              </p>
              <p className="text-xs text-gray-400">productos con faltante repetido (8 días)</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Calidad de conteos</p>
              <p className={`text-xl font-bold font-mono ${diaria.atajos_en_ventana > 0 ? 'text-amber-600' : 'text-green-700'}`}>
                {diaria.cierres_en_ventana} <span className="text-sm font-medium text-gray-400">reales</span>
              </p>
              <p className="text-xs text-gray-400">
                {diaria.atajos_en_ventana > 0 ? `⚡ ${diaria.atajos_en_ventana} con "Todo coincide"` : 'sin atajos en la ventana'}
              </p>
            </div>
          </div>

          {/* ¿A dónde se va el producto? — reincidencia = señal de fuga */}
          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">¿A dónde se va el producto?</p>
            <p className="text-xs text-gray-400 mb-3">
              Faltantes en los cierres de los últimos 8 días (los conteos con "Todo coincide" no cuentan).
              Un día con faltante es ruido; varios días seguidos es un patrón para investigar.
            </p>
            {diaria.reincidentes.length === 0 ? (
              <p className="text-sm text-green-700 font-medium">✓ Sin faltantes en los cierres de la ventana</p>
            ) : (
              <div className="space-y-1.5">
                {diaria.reincidentes.map(r => (
                  <div key={r.producto_id} className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${r.dias_con_faltante >= 3 ? 'bg-red-500' : r.dias_con_faltante === 2 ? 'bg-amber-400' : 'bg-gray-300'}`} />
                    <span className="flex-1 font-medium text-gray-700 truncate">{r.nombre}</span>
                    <span className="text-xs text-gray-400">
                      faltó en {r.dias_con_faltante} de {diaria.cierres_en_ventana} cierre{diaria.cierres_en_ventana !== 1 ? 's' : ''}
                    </span>
                    <span className="text-xs font-mono text-red-500 w-24 text-right">{num(r.total_faltante)} {r.unidad}</span>
                    <span className="font-mono font-bold w-24 text-right text-red-600">{r.valor_faltante > 0 ? `≈ ${fmt(r.valor_faltante)}` : ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Detalle: doble inventario del día */}
          <div className="flex items-center gap-3 flex-wrap">
            <p className="text-sm font-semibold text-gray-600">Detalle — doble inventario del día</p>
            <input type="date" value={dia} max={hoyLocal()} onChange={e => setDia(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 focus:outline-none focus:border-forest" />
            {diaria && (
              <span className="text-[11px] text-gray-400 flex items-center gap-1.5 flex-wrap">
                <span>{diaria.tiene_apertura ? `Abrió: ${diaria.apertura_barista ?? 's/n'}` : 'Sin conteo de apertura'}</span>
                {diaria.apertura_atajo && (
                  <span className="bg-amber-100 text-amber-700 font-bold px-1.5 py-0.5 rounded-full" title='La apertura se registró con el botón "Todo coincide con sistema" — no es un conteo físico'>
                    ⚡ Todo coincide
                  </span>
                )}
                <span>· {diaria.tiene_cierre ? `Cerró: ${diaria.cierre_barista ?? 's/n'}` : 'Sin conteo de cierre'}</span>
                {diaria.cierre_atajo && (
                  <span className="bg-amber-100 text-amber-700 font-bold px-1.5 py-0.5 rounded-full" title='El cierre se registró con el botón "Todo coincide con sistema" — no es un conteo físico'>
                    ⚡ Todo coincide
                  </span>
                )}
              </span>
            )}
            <span className="ml-auto flex items-center gap-3">
              {(diaria?.cierres_previos?.length ?? 0) > 0 && (
                <span className="text-[11px] text-gray-400 hidden sm:inline">
                  ← Deslizá la tabla hacia atrás para ver los cierres de días anteriores
                </span>
              )}
              <button onClick={() => setSoloDif(v => !v)}
                className={`text-xs px-3 py-1 rounded-lg font-semibold transition-colors ${
                  soloDif ? 'bg-gray-700 text-white' : 'bg-gray-100 text-gray-500'
                }`}>
                {soloDif ? '✓ Solo diferencias' : 'Solo diferencias'}
              </button>
            </span>
          </div>
          <div className="bg-white rounded-2xl border border-gray-200">
            <div className="overflow-x-auto scroll-visible cursor-grab active:cursor-grabbing rounded-2xl" ref={scrollTabla}>
              {/* Línea de tiempo: los cierres de días anteriores van A LA IZQUIERDA de la
                  apertura (el pasado atrás). La tabla arranca desplazada al presente:
                  las 7 columnas principales llenan el ancho visible y se desliza hacia
                  atrás para ver la historia. */}
              {/* table-layout FIXED + colgroup: cada columna mide EXACTO lo declarado.
                  Los offsets sticky (0/180/280) dependen de estos anchos; las 4 columnas
                  del día llenan justo el ancho visible y los cierres previos quedan
                  100% fuera hasta que se desliza. border-separate: sticky + collapse
                  desalinea bordes en Chrome. */}
              <table className="text-sm border-separate"
                style={{ borderSpacing: 0, tableLayout: 'fixed',
                         width: colW * 7 + prevAsc.length * ANCHO_PREVIO }}>
                <colgroup>
                  {[0, 1, 2].map(i => <col key={`fija-${i}`} style={{ width: colW }} />)}
                  {prevAsc.map(cp => <col key={cp.fecha} style={{ width: ANCHO_PREVIO }} />)}
                  {[0, 1, 2, 3].map(i => <col key={`dia-${i}`} style={{ width: colW }} />)}
                </colgroup>
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-gray-400">
                    {/* Columnas 1-3 FIJAS: el scroll horizontal solo mueve el resto */}
                    <th className="text-left px-3 py-2 font-bold sticky left-0 z-10 bg-gray-50 border-b border-gray-200">Producto</th>
                    <th className="text-right px-3 py-2 font-bold sticky z-10 bg-gray-50 border-b border-gray-200" style={{ left: colW }}>Dif. apertura</th>
                    <th className="text-right px-3 py-2 font-bold sticky z-10 bg-gray-50 border-b border-gray-200 border-r-2 border-r-gray-200" style={{ left: colW * 2 }}>Sistema</th>
                    {prevAsc.map((cp, idx) => (
                      <th key={cp.fecha} className={`text-right px-3 py-2 font-bold bg-gray-50 whitespace-nowrap border-b border-gray-200 ${idx === prevAsc.length - 1 ? 'border-r-2 border-r-gray-200' : ''}`}>
                        Cierre {cp.fecha.slice(8, 10)}/{cp.fecha.slice(5, 7)}{cp.atajo ? ' ⚡' : ''}
                      </th>
                    ))}
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 border-b border-gray-200">Conteo apertura</th>
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 border-b border-gray-200">Ingresos del día</th>
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 border-b border-gray-200">Conteo cierre</th>
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 border-b border-gray-200">Dif. apertura → cierre</th>
                  </tr>
                </thead>
                <tbody>
                  {loadingDia ? (
                    <tr><td colSpan={7 + (diaria?.cierres_previos?.length ?? 0)} className="px-3 py-8 text-center text-sm text-gray-400 animate-pulse">Cargando día…</td></tr>
                  ) : filasDia.map(i => {
                    const celda = (c: CeldaConteo | null, conDif: boolean) => c === null
                      ? <span className="text-gray-300">—</span>
                      : (
                        <span className={c.diferencia !== 0 ? (c.diferencia < 0 ? 'text-red-600' : 'text-blue-600') : 'text-gray-800'}>
                          <span className="font-bold">{num(c.real)}</span>
                          {conDif && c.diferencia !== 0 && (
                            <span className="text-[11px] ml-1">({c.diferencia > 0 ? '+' : ''}{num(c.diferencia)})</span>
                          )}
                        </span>
                      )
                    const difAp = i.apertura?.diferencia ?? null
                    const cambioDia = i.apertura !== null && i.cierre !== null
                      ? i.cierre.real - i.apertura.real : null
                    // border-separate no pinta bordes de <tr>: el divisor va en cada celda
                    const b = 'border-b border-gray-50'
                    return (
                      <tr key={i.producto_id} className="hover:bg-gray-50">
                        <td className={`px-3 py-2 font-medium text-gray-700 sticky left-0 z-10 bg-white break-words ${b}`}>{i.nombre}
                          <span className="text-xs text-gray-400 ml-1">{i.unidad}</span></td>
                        <td className={`px-3 py-2 text-right font-mono font-bold sticky z-10 bg-white ${b} ${
                          difAp === null ? 'text-gray-300' : difAp === 0 ? 'text-green-600' : difAp < 0 ? 'text-red-600' : 'text-blue-600'
                        }`} style={{ left: colW }}>
                          {difAp === null ? '—' : difAp === 0 ? '✓ 0' : `${difAp > 0 ? '+' : ''}${num(difAp)}`}
                        </td>
                        <td className={`px-3 py-2 text-right font-mono text-gray-500 sticky z-10 bg-white border-r-2 border-r-gray-200 ${b}`} style={{ left: colW * 2 }}>{num(i.sistema)}</td>
                        {prevAsc.map((cp, idx) => {
                          const d = cp.por_producto[i.producto_id]
                          return (
                            <td key={cp.fecha} className={`px-3 py-2 text-right font-mono ${b} ${idx === prevAsc.length - 1 ? 'border-r-2 border-r-gray-200' : ''}`}>
                              {d === undefined
                                ? <span className="text-gray-300">—</span>
                                : (
                                  <span className={d.diferencia !== 0 ? (d.diferencia < 0 ? 'text-red-600' : 'text-blue-600') : 'text-gray-600'}>
                                    {num(d.real)}
                                    {d.diferencia !== 0 && (
                                      <span className="text-[11px] ml-1">({d.diferencia > 0 ? '+' : ''}{num(d.diferencia)})</span>
                                    )}
                                  </span>
                                )}
                            </td>
                          )
                        })}
                        <td className={`px-3 py-2 text-right font-mono ${b}`}>{celda(i.apertura, false)}</td>
                        <td className={`px-3 py-2 text-right font-mono ${b} ${i.entradas > 0 ? 'text-green-600 font-bold' : 'text-gray-300'}`}>
                          {i.entradas > 0 ? `+${num(i.entradas)}` : '0'}
                        </td>
                        <td className={`px-3 py-2 text-right font-mono ${b}`}>{celda(i.cierre, true)}</td>
                        <td className={`px-3 py-2 text-right font-mono font-bold ${b} ${
                          cambioDia === null ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                          {cambioDia === null ? '—' : `${cambioDia > 0 ? '+' : ''}${num(cambioDia)}`}
                        </td>
                      </tr>
                    )
                  })}
                  {!loadingDia && filasDia.length === 0 && (
                    <tr><td colSpan={7 + (diaria?.cierres_previos?.length ?? 0)} className="px-3 py-8 text-center text-sm text-gray-400">
                      {soloDif
                        ? 'Sin diferencias este día — los conteos clavaron con el sistema. Desactivá "Solo diferencias" para ver la lista completa.'
                        : 'Sin datos para este día.'}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="px-3 py-2 text-[11px] text-gray-400 border-t border-gray-50">
              Sistema = conteo interno (ventas con recetas, facturas, mermas). "Dif. apertura vs sistema" compara contra el sistema al momento de abrir; en el cierre, el paréntesis es su diferencia contra el sistema al cerrar. "Dif. apertura → cierre" es cuánto cambió el producto durante el día según las baristas. Los conteos nunca modifican el inventario.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
