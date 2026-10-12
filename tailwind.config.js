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
        marca: {
          50: "#f0fdfa", 100: "#ccfbf1", 200: "#99f6e4", 500: "#14b8a6",
          600: "#0d9488", 700: "#0f766e", 800: "#115e59", 900: "#134e4a",
        },
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
