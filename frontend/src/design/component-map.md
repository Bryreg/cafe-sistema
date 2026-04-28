# Mapa de componentes — Sistema Café

> Componentes en `frontend/src/components/`. Generado desde el código real.

---

## BaristaLayout

**Archivo:** `BaristaLayout.tsx`

**Props:**
```ts
children: ReactNode
title?: string         // Si se omite muestra "Sistema Café" con ícono Coffee
backTo?: string        // Ruta del botón back — default: '/hub'
```

**Renderiza:**
- `div.min-h-screen.bg-gray-50.flex.flex-col`
- Header sticky `bg-white border-b`:
  - Botón back (ArrowLeft) → navega a `backTo`
  - Si `title` prop: texto bold. Si no: ícono Coffee amber + "Sistema Café"
  - Nombre del usuario (texto xs gris)
  - Botón logout (LogOut icon) → logout + navigate('/login')
- `main.flex-1.p-4.max-w-lg.mx-auto.w-full` → `{children}`

**Usado en:** ConteoApertura, ConteoCierre, Inventario, Mermas, Consignaciones, Pasteleria, SolicitudPedido, SolicitudSencilla, ConteoFisico, VentasDia

---

## Layout

**Archivo:** `Layout.tsx`

**Props:**
```ts
children: React.ReactNode
```

**Renderiza:**
- `div.min-h-screen.bg-gray-50.flex.flex-col`
- Header: logo + nombre usuario + badge rol (purple=admin, amber=barista) + botón logout
- Nav horizontal con NavLinks activos (amber): Dashboard, Inventario, Consignaciones, Bandeja, Informes
- `main.flex-1.p-4.max-w-5xl.mx-auto.w-full` → `{children}`

**Usado en:** Dashboard (admin), Informes, Bandeja

---

## ProtectedRoute

**Archivo:** `ProtectedRoute.tsx`

**Props:**
```ts
children: React.ReactNode
role?: string   // Si se pasa, verifica que user.rol === role
```

**Renderiza:**
- Si `!user` → `<Navigate to="/login" replace />`
- Si `role && user.rol !== role` → `<Navigate to="/" replace />`
- De lo contrario: `<>{children}</>`

**Usado en:** `App.tsx` para proteger todas las rutas

---

## MoneyInput

**Archivo:** `MoneyInput.tsx`

**Props:**
```ts
label: string
value: string
onChange: (v: string) => void
placeholder?: string       // default: '0'
hint?: string              // Texto de ayuda bajo el label
dark?: boolean             // default: false — modo claro/oscuro
size?: 'sm' | 'lg'         // default: 'lg' — controla font size y padding
```

**Renderiza:**
- `div` con label, hint opcional
- Input numérico con `$` absoluto a la izquierda
- Modo claro: `bg-white border-gray-200 text-gray-900`
- Modo oscuro: `bg-gray-800 border-gray-700 text-white`
- Tamaño lg: `text-3xl py-4` / sm: `text-xl py-3`
- Focus: `border-amber-400`

**Usado en:** Entrega.tsx (×3 inputs de montos)

---

## DifferenceBadge

**Archivo:** `DifferenceBadge.tsx`

**Props:**
```ts
diferencia: number
dark?: boolean       // default: false — modo claro/oscuro
showZero?: boolean   // default: true — si false, no renderiza nada si diff === 0
```

**Renderiza:**
- Si `diferencia === 0`: pill verde con `CheckCircle2` + "Cuadra"
  - Claro: `bg-green-100 text-green-700`
  - Oscuro: `bg-green-900/40 text-green-400`
- Si `diferencia !== 0`: pill rojo con `XCircle` + valor (con signo + si positivo)
  - Claro: `bg-red-100 text-red-700`
  - Oscuro: `bg-red-900/40 text-red-400`
- `showZero: false` → retorna `null` si diferencia = 0

**Usado en:** Entrega.tsx, Informes.tsx (TabCuadres)

---

## ImageUploader

**Archivo:** `ImageUploader.tsx`

**Props:**
```ts
onFileChange: (file: File | null) => void
dark?: boolean   // default: false
```

**Renderiza:**
- Label "Foto de evidencia" + hint "Incluye Siigo y el cuadre físico en la foto"
- Sin imagen: botón dashed con íconos `Camera` + `ImageIcon`, texto "Tomar foto o subir imagen"
- Con imagen: `<img>` preview h-48 con botón X para limpiar
- `<input type="file" accept="image/*" capture="environment" hidden />` — activa cámara en móvil

**Usado en:** Entrega.tsx

---

## Componentes inline (no separados en archivos)

Algunos componentes están definidos directamente en los archivos de página:

### `FilaDenom` (en Apertura.tsx y Cierre.tsx)
- **Props:** `{ item: { valor, label, tipo }, cantidad, onChange }`
- Fila de denominación con badge denominación + botón − + input + botón + + subtotal
- Dark theme en Cierre.tsx

### `PanelCuadre` (en Cierre.tsx)
- **Props:** `{ label, contado, sistema, color: 'green' | 'blue' }`
- Panel que muestra sistema vs contado + diferencia con `CheckCircle2` o `XCircle`

### `SectionCard` (en Entrega.tsx)
- **Props:** `{ title, children, accent?: 'amber' | 'green' | 'blue' }`
- Contenedor con borde de color según accent, fondo tenue

### `FilaDenom` (en SolicitudSencilla.tsx y Bandeja.tsx)
- Versión similar a Apertura pero con input en pesos → calcula cantidad de billetes/monedas

### `EditorSencilla` (en Bandeja.tsx)
- Editor inline de denominaciones para que el admin ajuste al aprobar sencilla

### `TabVentas`, `TabMermas`, `TabInventario`, `TabCuadres`, `TabTurnos` (en Informes.tsx)
- Sub-componentes con filtros de fecha + tabla de cada reporte

---

## Contextos

### AuthContext (`contexts/AuthContext.tsx`)
- Provee: `user: { id, nombre, rol, tienda_id, token }`, `login()`, `logout()`
- Almacena JWT en `localStorage`

### TurnoContext (`contexts/TurnoContext.tsx`)
- Provee: `turno: CajaTurno | null`, `refresh()`
- Hace polling / actualización del turno activo

---

## Utilidades (no son componentes pero son reutilizadas)

### `parseUTC(s: string): Date`
Definida en `Hub.tsx` y `Pasteleria.tsx`:
```ts
const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
return new Date(t.endsWith('Z') ? t : t + 'Z')
```
Normaliza fechas SQLite UTC → objeto Date JS.

### `fmt(v: number) => string`
```ts
const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
```
Formatea montos en pesos colombianos. Definida en múltiples archivos.
