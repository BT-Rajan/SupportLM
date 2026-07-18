import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Chat widget build — see vite.admin.config.js for the admin console's
// twin. Kept as two entirely separate single-entry builds (rather than
// one multi-entry config) so Rollup never has to dedupe two same-named
// CSS/JS chunks across bundles — each output name here is fixed and
// unambiguous. Run both via `npm run build`.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: "../static/dist",
    emptyOutDir: false, // admin build runs alongside this one — don't clobber its output
    assetsDir: "assets",
    rollupOptions: {
      input: "src/main.js",
      output: {
        entryFileNames: "chat-widget.js",
        chunkFileNames: "assets/chat-[name].js",
        assetFileNames: (info) =>
          info.name && info.name.endsWith(".css") ? "chat-widget.css" : "assets/[name][extname]",
      },
    },
  },
});
