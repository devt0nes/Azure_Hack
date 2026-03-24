/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: ['class'],
  theme: {
    extend: {
      fontFamily: {
        body: ['Inter', 'sans-serif'],
        mono: ['Space Mono', 'monospace'],
        display: ['Rajdhani', 'sans-serif'],
      },
      colors: {
        border: 'hsl(var(--border) / <alpha-value>)',
        input: 'hsl(var(--input) / <alpha-value>)',
        ring: 'hsl(var(--ring) / <alpha-value>)',
        background: 'hsl(var(--background) / <alpha-value>)',
        foreground: 'hsl(var(--foreground) / <alpha-value>)',
        primary: {
          DEFAULT: 'hsl(var(--primary) / <alpha-value>)',
          foreground: 'hsl(var(--primary-foreground) / <alpha-value>)',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary) / <alpha-value>)',
          foreground: 'hsl(var(--secondary-foreground) / <alpha-value>)',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted) / <alpha-value>)',
          foreground: 'hsl(var(--muted-foreground) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent) / <alpha-value>)',
          foreground: 'hsl(var(--accent-foreground) / <alpha-value>)',
        },
        card: {
          DEFAULT: 'hsl(var(--card) / <alpha-value>)',
          foreground: 'hsl(var(--card-foreground) / <alpha-value>)',
        },
        ember: 'hsl(var(--ember) / <alpha-value>)',
        glow: 'hsl(var(--glow) / <alpha-value>)',
        terminal: 'hsl(var(--terminal) / <alpha-value>)',
        surface: 'hsl(var(--surface) / <alpha-value>)',
        'surface-raised': 'hsl(var(--surface-raised) / <alpha-value>)',
        wire: 'hsl(var(--wire) / <alpha-value>)',
        midnight: 'hsl(var(--background) / <alpha-value>)',
        sand: 'hsl(var(--card) / <alpha-value>)',
        ink: 'hsl(var(--foreground) / <alpha-value>)',
        haze: 'hsl(var(--surface-raised) / <alpha-value>)',
      },
      boxShadow: {
        glow: '0 0 40px rgba(242, 106, 46, 0.25)',
        'glow-sm': '0 0 20px rgba(242, 106, 46, 0.15)',
        'glass': '0 8px 32px rgba(0, 0, 0, 0.08)',
      },
      backdropBlur: {
        'xs': '2px',
      },
      animation: {
        'fade-in': 'fadeIn 0.6s ease-out',
        'fade-in-up': 'fadeInUp 0.8s ease-out',
        'slide-in-right': 'slideInRight 0.8s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow-pulse': 'glowPulse 3s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
        'shimmer': 'shimmer 2s infinite',
        'grain': 'grain 8s steps(10) infinite',
        'scan': 'scan 6s linear infinite',
        'pulse-glow': 'pulse-glow 3s ease-in-out infinite',
        'drift': 'drift 20s ease-in-out infinite',
        'drift-reverse': 'drift-reverse 25s ease-in-out infinite',
        'ticker': 'ticker 40s linear infinite',
        'blink': 'blink 1s step-end infinite',
        'float-particle': 'float-particle 12s linear infinite',
        'progress-fill': 'progress-fill 1s ease-out forwards',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        glowPulse: {
          '0%, 100%': { boxShadow: '0 0 20px rgba(242, 106, 46, 0.2)' },
          '50%': { boxShadow: '0 0 40px rgba(242, 106, 46, 0.4)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-20px)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-1000px 0' },
          '100%': { backgroundPosition: '1000px 0' },
        },
        grain: {
          '0%, 100%': { transform: 'translate(0, 0)' },
          '10%': { transform: 'translate(-5%, -10%)' },
          '30%': { transform: 'translate(3%, -15%)' },
          '50%': { transform: 'translate(-10%, 5%)' },
          '70%': { transform: 'translate(7%, -5%)' },
          '90%': { transform: 'translate(-3%, 10%)' },
        },
        scan: {
          '0%': { transform: 'translateY(-100%)', opacity: '0' },
          '10%': { opacity: '1' },
          '90%': { opacity: '1' },
          '100%': { transform: 'translateY(100vh)', opacity: '0' },
        },
        'pulse-glow': {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '0.8' },
        },
        drift: {
          '0%, 100%': { transform: 'translate(0, 0)' },
          '25%': { transform: 'translate(30px, -20px)' },
          '50%': { transform: 'translate(-10px, 15px)' },
          '75%': { transform: 'translate(20px, 10px)' },
        },
        'drift-reverse': {
          '0%, 100%': { transform: 'translate(0, 0)' },
          '25%': { transform: 'translate(-20px, 15px)' },
          '50%': { transform: 'translate(15px, -25px)' },
          '75%': { transform: 'translate(-30px, -5px)' },
        },
        ticker: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'float-particle': {
          '0%': { transform: 'translateY(100vh) scale(0)', opacity: '0' },
          '10%': { opacity: '1' },
          '90%': { opacity: '1' },
          '100%': { transform: 'translateY(-10vh) scale(1)', opacity: '0' },
        },
        'progress-fill': {
          '0%': { width: '0%' },
          '100%': { width: '100%' },
        },
      },
    },
  },
  plugins: [],
}
