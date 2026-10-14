/** Tailwind v3 (CLI standalone): `make css` compila static/src/app.css → static/css/app.css */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./apps/**/*.py",
    "./static/js/**/*.js",
  ],
  // Clases que las plantillas arman con variables (p. ej. badge-{{ estado }}).
  safelist: [
    "badge-viable", "badge-ajustado", "badge-no_viable",
    "badge-info", "badge-media", "badge-alta",
  ],
  theme: {
    extend: {
      colors: {
        // Azul marino: color principal (botones, enlaces, tarjeta destacada).
        marca: {
          50: "#eef3fb", 100: "#dbe6f7", 200: "#b9cdee", 500: "#3f66b0",
          600: "#27478a", 700: "#17305f", 800: "#10224a", 900: "#0c1b3d",
        },
        // Turquesa: acento (logo, avisos suaves, barras de avance).
        turquesa: {
          50: "#ecfaf7", 100: "#d5f3f0", 200: "#b0eadf", 400: "#3bb8a7",
          500: "#1a9c8f", 600: "#14857a", 700: "#0f6b63", 800: "#0b4a4d",
        },
        fondo: "#f8fafb",
        tinta: "#131d33",
        // Barra lateral (escritorio) y panel de la pantalla de acceso.
        lateral: { DEFAULT: "#10224a", claro: "#1d2f57", borde: "#24365d", texto: "#dbe3ef" },
      },
      fontFamily: {
        sans: ["Manrope", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        display: ["Sora", "Manrope", "system-ui", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgb(20 33 61 / 0.06), 0 8px 24px -12px rgb(20 33 61 / 0.12)",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
