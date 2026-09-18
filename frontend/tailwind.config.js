/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['DM Sans', 'system-ui', 'sans-serif'],
        display: ['Space Grotesk', 'system-ui', 'sans-serif'],
      },
      colors: {
        ink: {
          50: '#f3efe7',
          100: '#e5e0d6',
          200: '#c9c3b5',
          300: '#a8a193',
          400: '#7d7666',
          500: '#5c5648',
          600: '#423d33',
          700: '#2e2a23',
          800: '#1f1c17',
          900: '#15130f',
          950: '#0c0b09',
        },
        brand: {
          50: '#fff2ed',
          100: '#ffe0d4',
          200: '#ffc1a9',
          300: '#ff9a78',
          400: '#ef806c',
          500: '#e05a3f',
          600: '#c84327',
          700: '#a3351d',
          800: '#7a2818',
          900: '#5c1f14',
          950: '#351c1b',
        },
        gold: {
          400: '#e8b96a',
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.45s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '200% 0' },
          '100%': { backgroundPosition: '-200% 0' },
        },
      },
    },
  },
  plugins: [],
};
