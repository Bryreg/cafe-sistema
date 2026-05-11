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
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
  // Que Tailwind no purgue las clases de safe-area definidas en index.css
  safelist: ['pt-safe', 'pb-safe', 'header-safe', 'pb-nav'],
}
