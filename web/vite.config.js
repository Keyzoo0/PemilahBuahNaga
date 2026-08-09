// CATATAN UNTUK PEMULA:
// Vite adalah alat bantu (build tool) yang mengubah kode React kita menjadi
// file HTML/CSS/JS biasa yang bisa dibaca browser. File ini mengatur caranya.
//
// Dua peran Vite:
//   1. Saat MENGEMBANGKAN (npm run dev) — server sementara di laptop dengan
//      fitur "perubahan kode langsung terlihat" tanpa refresh manual.
//   2. Saat MEMBANGUN (npm run build) — semua kode dipadatkan ke folder dist/,
//      lalu folder itulah yang disajikan oleh FastAPI di Raspberry Pi.

import { defineConfig } from "vite";
// Plugin agar Vite mengerti sintaks JSX milik React.
import react from "@vitejs/plugin-react";

// Build -> dist/, di-serve oleh FastAPI (offline/LAN).
// base './' agar asset load benar apa pun path mount-nya.
export default defineConfig({
  plugins: [react()],
  // base "./" = alamat file pendukung ditulis relatif, bukan mutlak. Ini penting
  // karena halaman disajikan FastAPI, dan alamat mutlak bisa salah arah.
  base: "./",
  // outDir  : folder tempat hasil build ditaruh.
  // emptyOutDir: kosongkan folder itu dulu tiap build, agar tidak ada sisa
  //              file lama yang membingungkan.
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // dev: proxy API/stream/ws ke core FastAPI di :8000
    // Masalahnya begini: saat mengembangkan, React jalan di port 5173 sedangkan
    // server Python di port 8000. Browser MELARANG halaman meminta data ke port
    // berbeda (aturan keamanan bernama CORS).
    // Proxy memecahkannya: permintaan ke /api dari halaman React diteruskan
    // diam-diam oleh Vite ke port 8000, seolah-olah datang dari alamat yang sama.
    proxy: {
      "/api": "http://localhost:8000",       // semua endpoint data
      "/video": "http://localhost:8000",     // siaran kamera MJPEG
      "/static": "http://localhost:8000",    // foto snapshot
      // WebSocket perlu ditulis lebih rinci: ws: true memberi tahu Vite bahwa
      // ini koneksi menetap, bukan permintaan HTTP biasa.
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
