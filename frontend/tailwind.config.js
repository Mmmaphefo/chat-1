/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0b0f14",
          900: "#0f151c",
          850: "#131b24",
          800: "#18222d",
          700: "#243040",
          600: "#33445a",
        },
        accent: {
          DEFAULT: "#38bdf8",
          soft: "#0ea5e9",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
