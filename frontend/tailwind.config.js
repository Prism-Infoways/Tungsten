/** @type {import('tailwindcss').Config} */
module.exports = {
  presets: [require("./preset.js")],
  content: ["../src/tungsten/**/*.{html,py,js}"],
  plugins: [require("@tailwindcss/forms"), require("@tailwindcss/typography")],
};
