/* ========================================
   PemilahBuahNaga — Camera Monitor JS
   ========================================

   CATATAN UNTUK PEMULA:
   File ini ditulis dalam bahasa JavaScript dan dijalankan di BROWSER
   (Chrome/Firefox di HP atau laptop), bukan di Raspberry Pi.

   Pembagian tugasnya:
     - main.py (Python)  -> jalan di Raspberry Pi, menyediakan gambar & data.
     - main.js (file ini) -> jalan di browser, mengambil data itu lalu
                             menampilkannya di layar.

   Tugas file ini hanya dua:
     1. Menanyakan status kamera ke server tiap 2 detik, lalu memperbarui
        tulisan FPS di halaman.
     2. Memuat ulang gambar secara otomatis kalau siarannya terputus.
*/

// Bentuk (function () { ... })(); disebut IIFE — fungsi yang langsung
// dijalankan saat itu juga. Gunanya: semua variabel di dalamnya terkurung
// rapat dan tidak bocor mencemari halaman web secara keseluruhan.
(function () {
    // "use strict" menyalakan mode ketat JavaScript: kesalahan umum
    // (misalnya memakai variabel yang lupa dideklarasikan) langsung dilaporkan
    // sebagai error, bukan didiamkan.
    "use strict";

    // "const" membuat variabel yang isinya tidak akan diganti.
    // document = seluruh halaman web yang sedang tampil.
    // getElementById mencari satu elemen HTML berdasarkan atribut id-nya.
    const statusText = document.getElementById("status-text");
    // querySelector mencari dengan pola CSS. Titik (.dot) berarti "cari elemen
    // dengan class bernama dot". Yang diambil hanya yang PERTAMA ditemukan.
    const statusDot = document.querySelector(".dot");
    const infoCam1 = document.getElementById("info-cam1");
    const infoCam2 = document.getElementById("info-cam2");
    const stream1 = document.getElementById("stream1");
    const stream2 = document.getElementById("stream2");

    // Check status periodically
    // "async" menandai fungsi yang bisa MENUNGGU sesuatu (pakai kata "await")
    // tanpa membuat halaman web membeku.
    async function checkStatus() {
        // try/catch: coba jalankan, kalau error tangani di bagian catch.
        try {
            // fetch() meminta data ke server. "await" artinya tunggu balasannya
            // datang dulu sebelum lanjut ke baris berikutnya.
            const res = await fetch("/status");
            // .json() mengubah teks balasan menjadi objek JavaScript.
            // Perlu await lagi karena pengubahannya juga butuh waktu.
            const data = await res.json();

            // Berhasil terhubung -> bulatan indikator dibuat hijau.
            // className mengganti daftar class CSS elemen tersebut, dan warnanya
            // diatur oleh aturan .dot-green di file style.css.
            statusDot.className = "dot dot-green";
            // textContent mengganti tulisan di dalam elemen HTML.
            statusText.textContent = "Connected";

            // Object.keys(data) mengambil daftar nama kunci dari objek,
            // contoh: ["Camera_1", "Camera_2"].
            const keys = Object.keys(data);
            // Diperiksa jumlahnya dulu agar tidak error kalau ternyata cuma
            // ada satu kamera yang terpasang.
            if (keys.length >= 1) {
                const c1 = data[keys[0]];
                // Tanda backtick (`) membuat "template string": isi di dalam
                // ${...} diganti dengan nilai variabelnya.
                infoCam1.textContent = `${c1.device} — ${c1.fps} FPS`;
            }
            if (keys.length >= 2) {
                const c2 = data[keys[1]];
                infoCam2.textContent = `${c2.device} — ${c2.fps} FPS`;
            }
        } catch {
            // Server tidak membalas (Raspberry Pi mati / Wi-Fi putus)
            // -> tampilkan indikator merah dan kosongkan angka FPS.
            statusDot.className = "dot dot-red";
            statusText.textContent = "Disconnected";
            infoCam1.textContent = "--";
            infoCam2.textContent = "--";
        }
    }

    // Handle image load errors — reload stream
    function setupStreamReload(img, url) {
        // addEventListener memasang "pendengar": kerjakan fungsi ini setiap kali
        // peristiwa "error" terjadi pada gambar (yaitu saat gambar gagal dimuat).
        img.addEventListener("error", function () {
            // setTimeout menjalankan sesuatu SETELAH sekian milidetik.
            // Di sini: tunggu 2000 ms (2 detik) sebelum mencoba lagi, agar
            // tidak membanjiri server dengan permintaan bertubi-tubi.
            setTimeout(() => {
                // Date.now() memberi angka waktu yang selalu berbeda. Menempelkannya
                // sebagai "?t=..." memaksa browser mengambil gambar BARU dari
                // server, bukan memakai gambar lama yang tersimpan di cache.
                img.src = url + "?t=" + Date.now();
            }, 2000);
        });
    }

    // Pasang mekanisme muat-ulang otomatis untuk kedua siaran kamera.
    setupStreamReload(stream1, "/video_feed_1");
    setupStreamReload(stream2, "/video_feed_2");

    // Initial check + interval
    // Panggil sekali di awal supaya status langsung tampil, tidak menunggu
    // 2 detik pertama.
    checkStatus();
    // setInterval mengulang fungsi tersebut selamanya tiap 2000 ms (2 detik).
    setInterval(checkStatus, 2000);
})();
