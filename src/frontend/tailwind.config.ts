import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'bg-primary': '#0A0B0D',
        'bg-card': '#16181C',
        'bg-hover': '#1E2128',
        'border': '#2B2F36',
        'neon-cyan': '#00F0FF',
        'neon-magenta': '#FF00AA',
        'up-green': '#00FF9D',
        'down-red': '#FF0055',
        'warn-gold': '#FFD700',
        'info-gray': '#888E9B',
      },
      fontFamily: {
        orbitron: ['Orbitron', 'sans-serif'],
        inter: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'scanline': 'scanline 10s linear infinite',
        'flicker': 'flicker 0.15s infinite',
        'pulse-neon': 'pulse-neon 2s infinite',
      },
      keyframes: {
        scanline: {
          '0%': { bottom: '100%' },
          '100%': { bottom: '-100px' },
        },
        flicker: {
          '0%': { opacity: '0.1' },
          '50%': { opacity: '0.05' },
          '100%': { opacity: '0.1' },
        },
        'pulse-neon': {
          '0%': { boxShadow: '0 0 5px var(--neon-cyan)', textShadow: '0 0 5px var(--neon-cyan)' },
          '50%': { boxShadow: '0 0 15px var(--neon-cyan)', textShadow: '0 0 15px var(--neon-cyan)' },
          '100%': { boxShadow: '0 0 5px var(--neon-cyan)', textShadow: '0 0 5px var(--neon-cyan)' },
        }
      }
    },
  },
  plugins: [],
};

export default config;
