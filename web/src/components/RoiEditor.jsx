// useRef = "pengait" untuk menyentuh elemen HTML secara langsung.
import React, { useRef, useState } from "react";

// Editor ROI: seret kotak di atas stream langsung. Koordinat disimpan
// dalam ruang frame (frameW x frameH) sesuai config kamera.
//
// CATATAN UNTUK PEMULA:
// Komponen ini memungkinkan pengguna menggambar kotak area dengan cara MENYERET
// mouse di atas siaran kamera — jauh lebih mudah daripada mengetik angka
// koordinat satu per satu.
//
// Tantangan utamanya: ada DUA sistem ukuran yang berbeda.
//   1. Ukuran tampil di layar  — bisa berubah-ubah (tergantung lebar browser/HP).
//   2. Ukuran asli frame kamera — tetap, misalnya 640x480 piksel.
// Yang disimpan ke config HARUS ukuran asli kamera, supaya kotaknya tetap benar
// walau nanti dibuka di layar HP yang jauh lebih kecil. Karena itu ada
// perhitungan konversi bolak-balik di bawah.
//
// Tulisan { label, streamSrc, ... } di dalam kurung parameter disebut
// "destructuring props": mengambil langsung isi props menjadi variabel terpisah.
export default function RoiEditor({ label, streamSrc, frameW, frameH, value, onChange }) {
  // wrapRef nanti "menempel" ke elemen div pembungkus gambar, sehingga kita
  // bisa menanyakan posisi dan ukurannya di layar.
  const wrapRef = useRef(null);
  // drag menyimpan kotak yang SEDANG digambar. null artinya tidak sedang menyeret.
  const [drag, setDrag] = useState(null);

  // Mengubah posisi kursor mouse -> koordinat dalam ukuran asli frame kamera.
  const toFrame = (e) => {
    // getBoundingClientRect memberi posisi & ukuran elemen di layar saat ini.
    const r = wrapRef.current.getBoundingClientRect();
    // e.clientX = posisi mouse dari tepi kiri jendela browser.
    // Dikurangi r.left -> jadi posisi relatif terhadap gambar.
    // Dibagi r.width  -> jadi pecahan 0..1 (0 = tepi kiri, 1 = tepi kanan).
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    return {
      // Math.max(0, Math.min(1, px)) memaksa nilai tetap di rentang 0..1,
      // supaya kotak tidak bisa digambar keluar dari area gambar.
      // Dikali frameW -> berubah menjadi piksel asli kamera.
      x: Math.max(0, Math.min(1, px)) * frameW,
      y: Math.max(0, Math.min(1, py)) * frameH,
    };
  };

  // Tombol mouse DITEKAN -> mulai menggambar. Titik awal dan akhir sama dulu.
  const onDown = (e) => {
    const p = toFrame(e);
    setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };

  // Mouse DIGERAKKAN -> perbarui titik akhir kotak.
  const onMove = (e) => {
    // Kalau tidak sedang menyeret, abaikan gerakan mouse.
    if (!drag) return;
    const p = toFrame(e);
    // Tiga titik (...d) disebut "spread": salin semua isi lama, lalu ganti
    // x1 dan y1 saja. Ini WAJIB di React — state tidak boleh diubah langsung,
    // harus dibuatkan objek baru agar React tahu ada perubahan.
    setDrag((d) => ({ ...d, x1: p.x, y1: p.y }));
  };

  // Tombol mouse DILEPAS -> selesaikan kotak dan simpan.
  const onUp = () => {
    if (!drag) return;
    // Pengguna bisa menyeret ke arah mana saja (dari kanan ke kiri pun boleh).
    // Math.min mengambil koordinat terkecil sebagai pojok kiri-atas, dan
    // Math.abs (nilai mutlak) memastikan lebar/tinggi selalu positif.
    const x = Math.round(Math.min(drag.x0, drag.x1));
    const y = Math.round(Math.min(drag.y0, drag.y1));
    const w = Math.round(Math.abs(drag.x1 - drag.x0));
    const h = Math.round(Math.abs(drag.y1 - drag.y0));
    setDrag(null);   // selesai menyeret
    // Kotak yang terlalu kecil (di bawah 10 piksel) dianggap salah klik,
    // bukan niat menggambar -> jangan disimpan.
    if (w > 10 && h > 10) onChange({ x, y, w, h });
  };

  // rect yang ditampilkan (dari drag aktif atau value tersimpan)
  // Saat sedang menyeret -> tampilkan kotak yang sedang digambar (bergerak
  // mengikuti mouse). Saat tidak -> tampilkan kotak yang sudah tersimpan.
  const shown = drag
    ? {
        x: Math.min(drag.x0, drag.x1),
        y: Math.min(drag.y0, drag.y1),
        w: Math.abs(drag.x1 - drag.x0),
        h: Math.abs(drag.y1 - drag.y0),
      }
    : value;

  // Konversi BALIK: dari piksel kamera menjadi persen posisi di layar.
  // Dipakai persen (bukan piksel) agar kotaknya ikut menyesuaikan sendiri
  // saat ukuran jendela browser berubah.
  const style = shown
    ? {
        left: `${(shown.x / frameW) * 100}%`,
        top: `${(shown.y / frameH) * 100}%`,
        width: `${(shown.w / frameW) * 100}%`,
        height: `${(shown.h / frameH) * 100}%`,
      }
    : null;

  return (
    <div>
      <div className="subhead">{label}</div>
      <div
        className="roi-wrap"
        // ref menghubungkan elemen ini dengan wrapRef di atas.
        ref={wrapRef}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        // onMouseLeave juga memanggil onUp: kalau kursor keluar dari area
        // gambar sambil menekan tombol, seretan tetap diselesaikan dengan
        // rapi — kalau tidak, kotaknya akan "nyangkut" mengikuti mouse.
        onMouseLeave={onUp}
      >
        {/* draggable={false} mematikan kebiasaan browser yang menyeret gambar
            sebagai file — kalau tidak dimatikan, ini mengganggu penggambaran kotak. */}
        <img src={streamSrc} alt={label} draggable={false} />
        {/* Kotak hanya digambar kalau style ada isinya. */}
        {style && <div className="roi-rect" style={style} />}
      </div>
      <div className="roi-hint">
        {/* value?.x memakai tanda tanya agar tidak error saat value masih kosong. */}
        Seret kotak di atas gambar untuk menetapkan area. Nilai: x={value?.x} y={value?.y} w={value?.w} h={value?.h}
      </div>
    </div>
  );
}
