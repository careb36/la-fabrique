/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:   '#eef2ff',
          100:  '#e0e7ff',
          300:  '#a5b4fc',
          400:  '#818cf8',
          500:  '#6366f1',
          600:  '#4f46e5',
          700:  '#4338ca',
          800:  '#3730a3',
          900:  '#312e81',
          950:  '#1e1b4b',
        },
        surface: {
          950: '#030712',
          900: '#111827',
          800: '#1f2937',
          750: '#273344',
          700: '#374151',
          600: '#4b5563',
        },
        status: {
          success: '#22c55e',
          online:  '#22c55e',
          warning: '#f59e0b',
          error:   '#ef4444',
          info:    '#3b82f6',
          neutral: '#6b7280',
        },
        priority: {
          critical: '#ef4444',
          high:     '#f97316',
          medium:   '#3b82f6',
          low:      '#6b7280',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        'card':    '0 1px 3px 0 rgb(0 0 0 / 0.4), 0 1px 2px -1px rgb(0 0 0 / 0.4)',
        'card-md': '0 4px 6px -1px rgb(0 0 0 / 0.4), 0 2px 4px -2px rgb(0 0 0 / 0.4)',
        'glow':    '0 0 20px -4px rgb(99 102 241 / 0.4)',
      },
      borderRadius: {
        'card': '0.625rem',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-up':   'slideUp 0.25s ease-out',
        'slide-in':   'slideIn 0.2s ease-out',
      },
      keyframes: {
        fadeIn:  { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(8px)' },  to: { opacity: '1', transform: 'translateY(0)' } },
        slideIn: { from: { opacity: '0', transform: 'translateX(12px)' }, to: { opacity: '1', transform: 'translateX(0)' } },
      },
      screens: {
        'xs': '475px',
      },
    },
  },
  plugins: [],
}

