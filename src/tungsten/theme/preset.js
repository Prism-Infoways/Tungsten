// Tungsten's Tailwind preset: the color palettes (CSS variables set by Panel(colors=...)),
// dark mode and font. Shared by Tungsten's own build and by custom themes made with
// `tungsten make:theme` (build.mjs copies it into the package as tungsten/theme/preset.js).
// Keep it free of require() calls: in a theme it is loaded from inside the Python package,
// where there is no node_modules folder.
const shades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const palette = (name) =>
  Object.fromEntries(shades.map((s) => [s, `rgb(var(--tw-c-${name}-${s}) / <alpha-value>)`]));

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
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
};
