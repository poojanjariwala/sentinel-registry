/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#f6f7f9',
        ink: {
          DEFAULT: '#1b2430',
          muted: '#5b6472',
          faint: '#8a93a1',
        },
        line: '#dde1e7',
        accent: {
          DEFAULT: '#1e4bd8',
          soft: '#e8edfb',
        },
        ok: '#15803d',
        warn: '#b45309',
        crit: '#b91c1c',
        info: '#1d4ed8',
      },
      fontFamily: {
        sans: ['"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
    },
    keyframes: {
      fadeIn: {
        from: { opacity: '0', transform: 'translateY(4px)' },
        to: { opacity: '1', transform: 'translateY(0)' },
      },
    },
    animation: {
      fadeIn: 'fadeIn 160ms ease-out',
    },
  },
  plugins: [],
}
