/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}'
  ],
  theme: {
    extend: {
      colors: {
        primary: '#1E90FF',
        secondary: '#43A047',
        accent: '#FBC02D',
        neutral: '#23272F',
        background: '#F5FAFE',
        'high-contrast': '#000',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui'],
        heading: ['Montserrat', 'sans-serif']
      }
    }
  },
  plugins: [],
};