import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build -> dist/, di-serve oleh FastAPI (offline/LAN).
// base './' agar asset load benar apa pun path mount-nya.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // dev: proxy API/stream/ws ke core FastAPI di :8000
    proxy: {
      "/api": "http://localhost:8000",
      "/video": "http://localhost:8000",
      "/static": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
