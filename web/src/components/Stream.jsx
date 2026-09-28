// Tampilan siaran kamera MJPEG (pengganti <img src="/video/...">).
//
// CATATAN UNTUK PEMULA:
// Siaran MJPEG adalah satu koneksi yang TIDAK PERNAH selesai. Chrome ternyata
// tidak memutus koneksi itu saat gambarnya hilang dari layar (misal pindah
// tab Monitor -> Training). Padahal browser hanya mengizinkan ±6 koneksi ke
// satu server; setelah beberapa kali pindah tab, slotnya habis dan semua
// permintaan lain (/api/...) mengantre tanpa akhir — halaman tampak kosong.
// Mengosongkan src sebelum gambar dihapus memaksa browser menutup koneksinya.
import React, { useEffect, useRef } from "react";

export default function Stream(props) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    return () => { if (el) el.src = ""; };
  }, []);
  return <img ref={ref} {...props} />;
}
