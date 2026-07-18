import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Admin console build — see vite.chat.config.js for why this is a
// separate config rather than a second entry in the same build.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: "../static/dist",
    emptyOutDir: false,
    assetsDir: "assets",
    rollupOptions: {
      input: "src/admin-main.js",
      output: {
        entryFileNames: "admin-widget.js",
        chunkFileNames: "assets/admin-[name].js",
        assetFileNames: (info) =>
          info.name && info.name.endsWith(".css") ? "admin-widget.css" : "assets/[name][extname]",
      },
    },
  },
});
