import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        night: { 950: "#060b16", 900: "#0a1222", 800: "#101a2e", 700: "#18253d", 600: "#22324f" },
        neon: { green: "#4dff7c", lime: "#9bff3a", orange: "#ff8a2a", red: "#ff4d5e", cyan: "#5fe6ff" },
      },
      fontFamily: {
        pixel: ['"Press Start 2P"', "monospace"],
        term: ['"VT323"', "monospace"],
      },
      boxShadow: {
        neon: "0 0 0 1px rgba(77,255,124,.55), 0 0 18px rgba(77,255,124,.25)",
        "neon-orange": "0 0 0 1px rgba(255,138,42,.6), 0 0 18px rgba(255,138,42,.25)",
        "neon-red": "0 0 0 1px rgba(255,77,94,.6), 0 0 18px rgba(255,77,94,.25)",
      },
    },
  },
  plugins: [],
} satisfies Config;
