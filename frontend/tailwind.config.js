module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}" // Added for safety
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0a"
      }
    }
  },
  plugins: []
};
