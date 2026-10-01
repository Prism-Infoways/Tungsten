const shades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const palette = (name) =>
  Object.fromEntries(shades.map((s) => [s, `rgb(var(--tw-c-${name}-${s}) / <alpha-value>)`]));

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["../src/tungsten/**/*.{html,py,js}"],
  theme: {
    extend: {
      colors: {
        primary: palette("primary"),
        success: palette("success"),
        danger: palette("danger"),
        warning: palette("warning"),
        info: palette("info"),
        gray: palette("gray"),
        sidebar: palette("sidebar"),
        purple: palette("purple"),
        teal: palette("teal"),
        pink: palette("pink"),
        indigo: palette("indigo"),
      },
      fontFamily: {
        sans: ["var(--tw-font, Inter)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [require("@tailwindcss/forms"), require("@tailwindcss/typography")],
};
