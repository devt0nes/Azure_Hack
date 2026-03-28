// Tailwind config updated for minimalist, calm theme
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#0077cc',
        secondary: '#333333',
        background: '#ffffff',
      },
      fontFamily: {
        sans: [ 'Inter', 'system-ui', 'Segoe UI', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
