// Helper API ke core FastAPI (same-origin di produksi).
//
// CATATAN UNTUK PEMULA:
// File ini adalah "kumpulan tombol jarak jauh" untuk berbicara dengan server
// Python (core/api.py). Semua permintaan ke server dikumpulkan di satu file
// ini agar halaman-halaman React tidak perlu tahu detail alamat URL-nya.
//
// Istilah:
// - fetch()  : perintah bawaan browser untuk meminta data ke server.
// - async/await : cara menunggu balasan server tanpa membuat halaman membeku.
// - export   : menandai sesuatu agar bisa dipakai (di-import) file lain.
// - "same-origin": halaman web dan server berada di alamat yang sama, jadi
//   cukup ditulis "/api/status" tanpa perlu menyebut nama domain lengkap.

// Mengambil kondisi terkini sistem (state, FPS, hitungan hari ini, dll).
export async function getStatus() {
  // await = tunggu balasan server datang dulu.
  const r = await fetch("/api/status");
  // .json() mengubah teks balasan menjadi objek JavaScript yang mudah dipakai.
  return r.json();
}

// Mengambil seluruh isi config.json dari server.
export async function getConfig() {
  const r = await fetch("/api/config");
  return r.json();
}

// Menyimpan config baru ke server.
export async function saveConfig(data) {
  // Objek kedua di dalam fetch berisi pengaturan permintaan:
  const r = await fetch("/api/config", {
    method: "POST",                                        // POST = mengirim data
    headers: { "Content-Type": "application/json" },       // beri tahu server: isinya JSON
    body: JSON.stringify(data),                            // ubah objek jadi teks JSON
  });
  return r.json();
}

// Mengambil daftar nama kelas yang dikenali model AI.
export async function getClasses() {
  const r = await fetch("/api/classes");
  return r.json();
}

// Mengambil riwayat sortir. limit = 50 artinya kalau tidak disebut, ambil 50.
export async function getHistory(limit = 50) {
  // Tanda backtick (`) membuat teks yang bisa disisipi variabel lewat ${...}.
  // Bagian setelah tanda tanya disebut "query parameter".
  const r = await fetch(`/api/history?limit=${limit}`);
  return r.json();
}

// Fungsi umum untuk semua permintaan POST, agar kodenya tidak ditulis
// berulang-ulang di bawah.
export async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Kalau body ada isinya, ubah jadi teks JSON; kalau tidak, kirim tanpa isi.
    // undefined artinya "tidak ada nilai".
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

// Baris-baris berikut memakai "arrow function": bentuk singkat fungsi.
//   () => post(...)  sama artinya dengan  function () { return post(...); }
// Semuanya cuma jalan pintas agar kode di halaman React lebih mudah dibaca.
export const estop = () => post("/api/estop");                         // tombol darurat
export const clearEstop = () => post("/api/estop/clear");              // lepas darurat
export const setMode = (manual) => post("/api/mode", { manual });      // ganti mode auto/manual
export const manualCmd = (cmd) => post("/api/manual", { cmd });        // kirim perintah serial manual
export const calibrateEmpty = () => post("/api/calibrate/empty");      // simpan latar belt kosong

// Fungsi umum untuk permintaan DELETE (menghapus data di server).
// Tanpa kata "export", fungsi ini hanya bisa dipakai di dalam file ini saja.
async function del(path) {
  const r = await fetch(path, { method: "DELETE" });
  return r.json();
}

// riwayat
export const deleteHistory = (id) => del(`/api/history/${id}`);   // hapus satu baris
export const clearHistory = () => del("/api/history");            // hapus semua

// dataset
export async function dsList() {
  const r = await fetch("/api/dataset/list");
  return r.json();
}
export const dsCapture = () => post("/api/dataset/capture");      // ambil foto baru
// encodeURIComponent mengamankan nama file untuk dipakai di dalam URL:
// spasi dan karakter khusus diubah menjadi kode yang aman (spasi -> %20).
// Tanpa ini, nama file bertanda khusus akan membuat alamatnya salah.
export const dsDelete = (name) => del(`/api/dataset/image/${encodeURIComponent(name)}`);
export async function dsGetLabel(name) {
  const r = await fetch(`/api/dataset/label/${encodeURIComponent(name)}`);
  return r.json();
}
export const dsSaveLabel = (name, boxes) =>
  post(`/api/dataset/label/${encodeURIComponent(name)}`, { boxes });

// training
export const trainStart = (params) => post("/api/train/start", params);
export const trainStop = () => post("/api/train/stop");
export async function trainStatus() {
  const r = await fetch("/api/train/status");
  return r.json();
}
export async function listModels() {
  const r = await fetch("/api/models");
  return r.json();
}
export const activateModel = (path) => post("/api/models/activate", { path });

// export model .pt -> onnx/ncnn
export const exportModel = (format, imgsz) => post("/api/model/export", { format, imgsz });
export async function exportStatus() {
  const r = await fetch("/api/model/export/status");
  return r.json();
}

// WebSocket status dengan auto-reconnect + fallback polling.
//
// UNTUK PEMULA: ada dua cara mendapat data terbaru dari server.
//   1. WebSocket — saluran yang tetap terbuka; server MENDORONG data begitu
//      ada perubahan. Cepat dan hemat. Ini cara utama.
//   2. Polling — browser bertanya berulang-ulang "ada data baru?" tiap 1 detik.
//      Lebih boros, tapi tetap jalan saat WebSocket bermasalah. Ini cadangan.
// Fungsi ini otomatis berpindah ke cadangan bila cara utama terputus, lalu
// kembali ke cara utama begitu tersambung lagi.
export function subscribeStatus(onData) {
  // "let" membuat variabel yang isinya boleh diganti (beda dengan const).
  // Ketiga variabel ini dideklarasikan sekaligus dipisah koma.
  let ws,               // objek WebSocket
    alive = true,       // penanda: langganan ini masih aktif?
    poll;               // penanda timer polling

  function connect() {
    // Kalau halaman dibuka lewat HTTPS, WebSocket-nya juga harus versi aman (wss).
    // Bentuk "syarat ? nilaiA : nilaiB" adalah if-else versi singkat.
    const proto = location.protocol === "https:" ? "wss" : "ws";
    // location.host = alamat server yang sedang dibuka, contoh "buahnaga.local:5000".
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    // onmessage dipanggil setiap kali server mengirim data.
    // JSON.parse mengubah teks kiriman menjadi objek JavaScript, lalu
    // diserahkan ke fungsi onData milik pemanggil.
    ws.onmessage = (e) => onData(JSON.parse(e.data));
    // onclose dipanggil saat koneksi terputus.
    ws.onclose = () => {
      // Kalau langganan memang sudah sengaja dihentikan, jangan sambung lagi.
      if (!alive) return;
      startPolling();               // pakai cara cadangan dulu
      setTimeout(connect, 2000);    // coba sambungkan ulang setelah 2 detik
    };
    // onopen dipanggil saat koneksi berhasil -> matikan cara cadangan.
    ws.onopen = () => stopPolling();
  }

  function startPolling() {
    // Pengaman: kalau timer polling sudah jalan, jangan buat lagi
    // (kalau dibiarkan, timernya bisa bertumpuk dan membanjiri server).
    if (poll) return;
    // setInterval menjalankan fungsi berulang tiap 1000 ms (1 detik).
    poll = setInterval(async () => {
      try {
        onData(await getStatus());
      } catch (_) {}
      // Blok catch sengaja dikosongkan: kalau server sedang tidak membalas,
      // itu wajar (memang sedang putus) dan tidak perlu menampilkan error.
      // Garis bawah (_) hanya nama untuk nilai yang tidak dipakai.
    }, 1000);
  }

  function stopPolling() {
    if (poll) {
      clearInterval(poll);   // hentikan timer
      poll = null;           // tandai sudah tidak ada timer
    }
  }

  connect();   // mulai menyambung sekarang

  // Fungsi ini DIKEMBALIKAN ke pemanggil sebagai tombol "berhenti berlangganan".
  // React memanggilnya saat halaman ditutup, agar tidak ada koneksi dan timer
  // yang tertinggal hidup memakan sumber daya (istilahnya "memory leak").
  return () => {
    alive = false;
    stopPolling();
    if (ws) ws.close();
  };
}
