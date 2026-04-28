# Prompt para Claude Code — Exportar archivos para rediseño de interfaz

## OBJETIVO

Generar un conjunto de archivos que documenten la interfaz actual del sistema
y sirvan de base para rediseñar la UI con una herramienta de diseño.
NO modificar ningún componente funcional existente.

---

## ARCHIVO 1 — design-tokens.json

Crear en `frontend-react/src/design/design-tokens.json` con todos los valores
actuales de colores, tipografía y espaciado que usa la app:

```json
{
  "colors": {
    "primary": "",
    "secondary": "",
    "success": "",
    "warning": "",
    "danger": "",
    "background": "",
    "surface": "",
    "text": "",
    "textMuted": "",
    "border": ""
  },
  "typography": {
    "fontFamily": "",
    "sizes": {}
  },
  "spacing": {},
  "borderRadius": {},
  "shadows": {}
}
```

Revisar `tailwind.config.js` y los componentes existentes para extraer los valores reales.

---

## ARCHIVO 2 — page-inventory.md

Crear en `frontend-react/src/design/page-inventory.md` con el inventario
completo de páginas y componentes actuales:

Para cada página documentar:
- Ruta y nombre
- Rol que puede acceder (admin / barista / ambos)
- Propósito en una línea
- Lista de elementos UI principales (forms, tables, cards, buttons)
- Datos que muestra (qué campos del API consume)
- Acciones que permite (qué endpoints llama)

Páginas a documentar (16 en total):
```
/login              Login con selección de usuario + numpad PIN
/hub                Hub principal del barista
/apertura           Apertura de caja con contador de denominaciones
/conteo-apertura    Conteo físico de apertura
/ventas             Registro de ventas del turno
/conteo-cierre      Conteo físico de cierre
/cierre             Cierre de caja con cuadre
/entrega            Cuadre de llegada mid-turno
/inventario         Stock y movimientos
/mermas             Registro de mermas
/pasteleria         Control de lotes de panadería
/consignaciones     Registro de consignaciones
/pedido             Solicitud de pedido al admin
/sencilla           Solicitud de cambio de sencilla
/conteos            Historial de conteos del turno
/dashboard          Dashboard admin
/bandeja            Bandeja de aprobación admin
/informes           Informes y exportación CSV
```

---

## ARCHIVO 3 — component-map.md

Crear en `frontend-react/src/design/component-map.md` con el mapa de componentes
reutilizables actuales:

Para cada componente en `frontend-react/src/components/`:
- Nombre del archivo
- Props que recibe
- Dónde se usa (páginas)
- Descripción visual de qué renderiza

---

## ARCHIVO 4 — ui-screenshots.html

Crear en `frontend-react/src/design/ui-screenshots.html` como documento HTML
estático que muestre mockups en HTML/CSS de las 5 pantallas más importantes:

1. **Hub del barista** — con todas las secciones: pastelería activa, stock crítico,
   flujo del turno, grid de acciones 4x2
2. **Apertura de caja** — con el contador de denominaciones y el campo de diferencia
3. **Conteo de apertura** — con la lista de productos agrupados por categoría
4. **Dashboard admin** — con KPIs, checklist, alertas y cuadres de llegada
5. **Login** — con la lista de usuarios y el numpad PIN

Usar HTML + Tailwind CDN para que se vea igual a la app real.
Incluir datos de ejemplo realistas (nombres colombianos, valores en COP).
No necesita ser funcional — solo visual.

```html
<!DOCTYPE html>
<html>
<head>
  <script src="https://cdn.tailwindcss.com"></script>
  <title>UI Screenshots — Medium Café</title>
</head>
<body>
  <!-- Cada pantalla en una sección separada con su título -->
  <section id="hub">...</section>
  <section id="apertura">...</section>
  <section id="conteo">...</section>
  <section id="dashboard">...</section>
  <section id="login">...</section>
</body>
</html>
```

---

## ARCHIVO 5 — design-brief.md

Crear en `frontend-react/src/design/design-brief.md` con el brief completo
para el rediseño:

Incluir:
1. Descripción del negocio y usuarios (barista vs admin)
2. Flujo crítico del barista (5 pasos secuenciales)
3. Flujo del admin (dashboard + bandeja + informes)
4. Restricciones de diseño:
   - Barista usa celular en mano, posiblemente con guantes
   - Admin usa tablet o desktop
   - Operación en ambiente con poca luz (cafetería temprano en la mañana)
   - Barista no puede cometer errores en el cuadre — los campos críticos deben ser imposibles de ignorar
5. Pantallas prioritarias para rediseño (en orden de impacto operativo)
6. Elementos de identidad visual actual (si existen colores o logos de marca)

---

## INSTRUCCIONES

1. Leer todos los archivos de `frontend-react/src/pages/` y `frontend-react/src/components/`
2. Leer `frontend-react/tailwind.config.js` y `frontend-react/src/index.css`
3. Generar los 5 archivos descritos arriba
4. NO modificar ningún archivo existente del proyecto
5. Confirmar qué archivos se crearon y su ubicación exacta
