/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        midnight: '#0b0b0f',
        ember: '#f26a2e',
        sand: '#f7f1ea',
        ink: '#1c1c24',
        haze: '#f1e7d9',
      },
      boxShadow: {
        glow: '0 0 40px rgba(242, 106, 46, 0.25)',
      },
    },
  },
  plugins: [],
}
