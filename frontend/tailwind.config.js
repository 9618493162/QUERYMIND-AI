/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef4ff',
          100: '#dce6ff',
          200: '#bcd0ff',
          300: '#8fb0ff',
          400: '#5b85fb',
          500: '#365ef5',
          600: '#2142e6',
          700: '#1b33c0',
          800: '#1c2e99',
          900: '#1d2c79',
          950: '#141c4b',
        },
        surface: {
          light: '#ffffff',
          dark: '#0f1420',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.06), 0 1px 3px rgba(16, 24, 40, 0.1)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
};
