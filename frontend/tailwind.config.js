export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        forest: {
          50:  'oklch(95% 0.015 155)',
          100: 'oklch(90% 0.025 155)',
          400: 'oklch(55% 0.12 155)',
          500: 'oklch(48% 0.12 155)',
          DEFAULT: 'oklch(35% 0.05 155)',
          700: 'oklch(30% 0.05 155)',
        },
        warm: {
          50:  'oklch(98% 0.006 75)',
          100: 'oklch(96% 0.008 75)',
          200: 'oklch(92% 0.006 75)',
          300: 'oklch(85% 0.08 75)',
          400: 'oklch(72% 0.008 60)',
          500: 'oklch(58% 0.01 60)',
          600: 'oklch(40% 0.01 60)',
          700: 'oklch(22% 0.01 60)',
        },
        bark: {
          700: 'oklch(32% 0.014 55)',
          800: 'oklch(23% 0.012 55)',
          900: 'oklch(18% 0.01 55)',
        },

        // ─── Tokens semánticos (sistema de diseño) ──────────────────────────
        // Formalizan los oklch() inline repetidos en Hub/AdminHub/POS/Checkout.
        // Consumir SIEMPRE estos en componentes nuevos; nunca oklch() inline.

        // clay — naranja CTA / acción primaria cálida (botón "siguiente paso")
        clay: {
          50:  'oklch(97% 0.02 50)',
          100: 'oklch(94% 0.04 50)',
          200: 'oklch(88% 0.07 50)',
          400: 'oklch(68% 0.15 65)',   // inicio de gradiente CTA
          500: 'oklch(60% 0.16 50)',   // fin de gradiente CTA / DEFAULT
          600: 'oklch(54% 0.16 45)',
          DEFAULT: 'oklch(60% 0.16 50)',
        },

        // danger — rojo error / stock crítico
        danger: {
          50:  'oklch(97% 0.02 30)',
          100: 'oklch(94% 0.04 30)',
          200: 'oklch(88% 0.06 30)',
          400: 'oklch(60% 0.16 25)',
          500: '#c64a3a',             // rojo principal (usado literal en Hub)
          600: 'oklch(45% 0.16 25)',
          700: '#8a3325',             // texto fuerte sobre fondo danger
          DEFAULT: '#c64a3a',
        },

        // success — verde ok / confirmación
        success: {
          50:  'oklch(96% 0.018 145)',
          100: 'oklch(94% 0.04 145)',
          200: 'oklch(85% 0.10 145)',
          400: 'oklch(72% 0.16 145)',
          500: 'oklch(48% 0.16 145)', // verde principal
          600: 'oklch(40% 0.14 145)',
          700: 'oklch(30% 0.10 145)',
          DEFAULT: 'oklch(48% 0.16 145)',
        },

        // gold — dorado destaque / consignaciones / pastelería por impulsar
        gold: {
          50:  'oklch(97% 0.025 65)',
          100: 'oklch(94% 0.06 65)',
          200: 'oklch(88% 0.09 65)',
          400: 'oklch(72% 0.14 65)',
          500: 'oklch(60% 0.16 65)',
          600: 'oklch(52% 0.15 65)',
          700: 'oklch(38% 0.12 65)',  // texto fuerte
          DEFAULT: 'oklch(72% 0.14 65)',
        },
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontVariantNumeric: {
        // Permite `tabular-nums` como utilidad para alinear cifras de dinero.
        tabular: 'tabular-nums',
      },
    },
  },
  plugins: [],
  // Que Tailwind no purgue las clases de safe-area definidas en index.css
  safelist: ['pt-safe', 'pb-safe', 'header-safe', 'pb-nav'],
}
