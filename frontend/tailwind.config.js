/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0d1117',
        surface: '#161b22',
        border: '#21262d',
        'border-hover': '#30363d',
        primary: '#58a6ff',
        'primary-hover': '#79c0ff',
        secondary: '#7ee787',
        danger: '#f85149',
        'danger-hover': '#ff7b72',
        muted: '#7d8590',
        text: '#e6edf3',
        'text-bright': '#f0f6fc',
      },
      fontFamily: {
        mono: ['SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'monospace'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
