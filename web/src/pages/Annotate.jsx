// CATATAN UNTUK PEMULA:
// Halaman Anotasi: tempat MENANDAI di mana letak buah pada tiap foto dataset,
// dengan cara menyeret kotak mengelilinginya.
//
// Kenapa perlu ditandai manual? Karena AI belajar dengan mencontoh. Kita harus
// menunjukkan dulu "ini buah matang, letaknya di sini" berkali-kali, barulah
// model bisa menebak sendiri pada foto yang belum pernah dilihat.
//
// Koordinat kotak disimpan dalam bentuk 0..1 (pecahan dari ukuran gambar),
// bukan piksel. Jadi label tetap benar walau gambarnya diperbesar/diperkecil.
import React, { useEffect, useRef, useState } from "react";
import { dsList, dsGetLabel, dsSaveLabel } from "../api.js";

// warna per index kelas (0=matang, 1=mentah, 2=setengah matang)
// Urutan array ini HARUS sama dengan urutan CLASSES di core/dataset.py.
const CLS_COLOR = ["#22c55e", "#ef4444", "#eab308"];

export default function Annotate({ initial }) {
  const [images, setImages] = useState([]);    // daftar semua foto dataset
  const [classes, setClasses] = useState([]);  // daftar nama kelas
  const [cur, setCur] = useState(initial || null);   // foto yang sedang dibuka
  const [boxes, setBoxes] = useState([]);      // kotak-kotak pada foto ini
  const [cls, setCls] = useState(0);           // kelas yang sedang dipilih
  const [drag, setDrag] = useState(null);      // kotak yang sedang digambar
  const [toast, setToast] = useState(null);
  const wrapRef = useRef(null);                // pengait ke elemen pembungkus gambar

  const reload = () =>
    dsList().then((d) => {
      setImages(d.images || []);
      setClasses(d.classes || []);
      // Kalau belum ada foto yang dipilih, buka foto pertama secara otomatis.
      // d.images?.length memakai tanda tanya agar aman bila images belum ada.
      if (!cur && d.images?.length) setCur(d.images[0].name);
    });

  // Efek 1: muat daftar foto sekali saat halaman dibuka.
  useEffect(() => {
    reload();
  }, []);

  // Efek 2: muat label setiap kali foto yang dibuka BERGANTI.
  // Perhatikan [cur] di akhir — daftar ini disebut "dependency array": efek
  // dijalankan ulang setiap kali nilai di dalamnya berubah.
  useEffect(() => {
    if (cur) dsGetLabel(cur).then((d) => setBoxes(d.boxes || []));
  }, [cur]);

  // Mengubah posisi mouse menjadi pecahan 0..1 terhadap ukuran gambar.
  const rel = (e) => {
    const r = wrapRef.current.getBoundingClientRect();
    return {
      // Math.max(0, Math.min(1, ...)) menahan nilai tetap di rentang 0..1
      // agar kotak tidak bisa keluar dari batas gambar.
      x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    };
  };

  // Tombol mouse ditekan -> mulai menggambar kotak baru.
  const onDown = (e) => {
    const p = rel(e);
    setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };
  // Mouse digerakkan -> perbarui titik ujung kotak.
  const onMove = (e) => {
    if (!drag) return;
    const p = rel(e);
    // Tiga titik (...d) menyalin isi lama, lalu x1/y1 diganti yang baru.
    setDrag((d) => ({ ...d, x1: p.x, y1: p.y }));
  };
  // Tombol mouse dilepas -> simpan kotak ke daftar.
  const onUp = () => {
    if (!drag) return;
    // Format YOLO menyimpan kotak sebagai TITIK TENGAH + lebar + tinggi,
    // bukan sebagai dua sudut. Maka dihitung dulu di sini.
    const w = Math.abs(drag.x1 - drag.x0);    // abs = nilai mutlak (selalu positif)
    const h = Math.abs(drag.y1 - drag.y0);
    const cx = (drag.x0 + drag.x1) / 2;       // titik tengah mendatar
    const cy = (drag.y0 + drag.y1) / 2;       // titik tengah tegak
    setDrag(null);
    // Kotak lebih kecil dari 2% lebar gambar dianggap salah klik, bukan anotasi.
    // [...b, kotakBaru] membuat daftar BARU berisi isi lama + satu tambahan.
    if (w > 0.02 && h > 0.02) setBoxes((b) => [...b, { cls, cx, cy, w, h }]);
  };

  const save = async () => {
    await dsSaveLabel(cur, boxes);
    setToast({ t: "ok", m: `Tersimpan ${boxes.length} kotak` });
    setTimeout(() => setToast(null), 2500);
    reload();   // muat ulang agar penanda "sudah dianotasi" ikut diperbarui
  };

  // Melompat ke foto berikutnya yang belum dianotasi — mempercepat kerja
  // saat harus menandai puluhan foto berturut-turut.
  const nextUnlabeled = () => {
    // findIndex memberi posisi foto yang sedang dibuka di dalam daftar.
    const i = images.findIndex((x) => x.name === cur);
    // Trik memutar daftar: ambil bagian SETELAH foto sekarang, lalu sambung
    // dengan bagian SEBELUMNYA. Hasilnya pencarian berputar melingkar sampai
    // kembali ke awal, bukan berhenti di ujung daftar.
    const rest = [...images.slice(i + 1), ...images.slice(0, i)];
    // Cari yang belum dianotasi; kalau semuanya sudah, ambil yang pertama saja.
    const nxt = rest.find((x) => !x.labeled) || rest[0];
    if (nxt) setCur(nxt.name);
  };

  // Kotak yang ditampilkan = kotak tersimpan + kotak yang sedang digambar,
  // supaya pengguna melihat kotaknya bergerak mengikuti mouse secara langsung.
  const shown = drag
    ? [...boxes, {
        cls,
        cx: (drag.x0 + drag.x1) / 2,
        cy: (drag.y0 + drag.y1) / 2,
        w: Math.abs(drag.x1 - drag.x0),
        h: Math.abs(drag.y1 - drag.y0),
      }]
    : boxes;

  return (
    // gridTemplateColumns "260px 1fr" = dua kolom: kiri tetap 260 piksel
    // (daftar foto), kanan mengisi sisa ruang (kanvas anotasi).
    <div className="grid" style={{ gridTemplateColumns: "260px 1fr", gap: 16 }}>
      {/* daftar gambar */}
      {/* maxHeight 80vh = tinggi maksimal 80% tinggi layar; kalau fotonya
          banyak, daftar ini bisa digulir sendiri tanpa memanjangkan halaman. */}
      <div className="card" style={{ maxHeight: "80vh", overflowY: "auto" }}>
        <h3>Gambar ({images.length})</h3>
        {images.map((im) => (
          <div
            key={im.name}
            onClick={() => setCur(im.name)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 8px",
              borderRadius: 8,
              cursor: "pointer",
              // Foto yang sedang dibuka diberi latar & garis tepi berbeda
              // agar mudah dikenali dalam daftar.
              background: cur === im.name ? "var(--pink-soft)" : "transparent",
              // Garis tepi transparan tetap dipasang saat tidak aktif, supaya
              // ukuran barisnya tidak berubah-ubah (tidak "meloncat") saat dipilih.
              border: cur === im.name ? "1px solid var(--pink)" : "1px solid transparent",
              marginBottom: 4,
            }}
          >
            {/* objectFit "cover" memotong gambar agar mengisi penuh kotak kecil
                tanpa gepeng. */}
            <img src={`/dsimg/${im.name}`} style={{ width: 44, height: 30, objectFit: "cover", borderRadius: 4 }} />
            <span style={{ fontSize: 11, flex: 1, color: "var(--text-dim)" }}>
              {/* Nama file berbentuk "20260809_143012_527.jpg". slice(9,15)
                  mengambil huruf ke-9 sampai ke-14, yaitu bagian jam-menit-detik
                  ("143012") — cukup untuk membedakan tanpa memenuhi ruang. */}
              {im.name.slice(9, 15)}
            </span>
            <span style={{ fontSize: 11, color: im.labeled ? "var(--green)" : "var(--red)" }}>
              {im.labeled ? im.boxes : "—"}
            </span>
          </div>
        ))}
      </div>

      {/* kanvas anotasi */}
      <div className="card">
        <h3>Anotasi — {cur || "pilih gambar"}</h3>

        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          {/* Tombol pemilih kelas. Parameter kedua .map (yaitu i) adalah nomor
              urut, yang kebetulan sama dengan index kelas di model. */}
          {classes.map((c, i) => (
            <button
              key={c}
              className={"btn sm" + (cls === i ? " primary" : "")}
              onClick={() => setCls(i)}
              // Kelas yang aktif memakai gaya "primary"; yang tidak aktif
              // diberi warna sesuai kelasnya agar mudah dibedakan.
              style={cls === i ? {} : { borderColor: CLS_COLOR[i], color: CLS_COLOR[i] }}
            >
              [{i}] {c}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <button className="btn sm" onClick={() => setBoxes([])}>Hapus semua kotak</button>
          {/* slice(0, -1) membuat daftar baru tanpa elemen terakhir = Undo. */}
          <button className="btn sm" onClick={() => setBoxes((b) => b.slice(0, -1))}>Undo</button>
          <button className="btn primary" onClick={save} disabled={!cur}>Simpan</button>
          <button className="btn sm" onClick={nextUnlabeled}>Berikutnya ▶</button>
        </div>

        {/* Kanvas hanya ditampilkan kalau ada foto yang dipilih. */}
        {cur && (
          <div
            ref={wrapRef}
            className="roi-wrap"
            onMouseDown={onDown}
            onMouseMove={onMove}
            onMouseUp={onUp}
            // Seretan diselesaikan juga saat kursor keluar area, agar kotaknya
            // tidak "nyangkut" mengikuti mouse.
            onMouseLeave={onUp}
          >
            <img src={`/dsimg/${cur}`} alt={cur} draggable={false} />
            {shown.map((b, i) => (
              <div
                // Di sini key memakai nomor urut karena kotak belum punya id
                // sendiri. Boleh dilakukan untuk daftar yang tidak diurutkan ulang.
                key={i}
                style={{
                  // position absolute menempatkan kotak menumpuk di atas gambar,
                  // dengan patokan elemen pembungkus (.roi-wrap).
                  position: "absolute",
                  // Ubah dari titik tengah ke pojok kiri-atas: kurangi setengah
                  // lebar/tinggi. Dikali 100 karena satuannya persen.
                  left: `${(b.cx - b.w / 2) * 100}%`,
                  top: `${(b.cy - b.h / 2) * 100}%`,
                  width: `${b.w * 100}%`,
                  height: `${b.h * 100}%`,
                  // || "#fff" sebagai cadangan bila nomor kelasnya di luar daftar warna.
                  border: `2px solid ${CLS_COLOR[b.cls] || "#fff"}`,
                  // Akhiran "22" pada kode warna adalah tingkat transparansi
                  // (sekitar 13%), agar isi kotak tembus pandang dan buah di
                  // baliknya tetap terlihat.
                  background: `${CLS_COLOR[b.cls] || "#fff"}22`,
                }}
              >
                <span
                  style={{
                    position: "absolute",
                    // Nilai -18 menaruh label DI ATAS kotak, bukan di dalamnya,
                    // supaya tidak menutupi buah yang sedang ditandai.
                    top: -18,
                    left: 0,
                    fontSize: 11,
                    fontWeight: 700,
                    color: CLS_COLOR[b.cls],
                    background: "rgba(0,0,0,.6)",
                    padding: "1px 5px",
                    borderRadius: 4,
                  }}
                >
                  {b.cls} {classes[b.cls]}
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="roi-hint">
          Pilih kelas dulu, lalu seret kotak mengelilingi buah. Kotak memakai warna kelasnya.
          {toast && <span className={"toast " + toast.t} style={{ marginLeft: 10 }}>{toast.m}</span>}
        </div>

        {/* Daftar ringkas kotak yang sudah dibuat, masing-masing dengan tombol hapus. */}
        <div style={{ marginTop: 10 }}>
          {boxes.map((b, i) => (
            <span key={i} className="tag" style={{ marginRight: 6, color: CLS_COLOR[b.cls] }}>
              {classes[b.cls]}
              <button
                className="btn sm"
                style={{ marginLeft: 4, padding: "0 5px" }}
                // filter menyaring: simpan semua kotak KECUALI yang nomornya
                // sama dengan i. Parameter pertama tidak dipakai, jadi diberi
                // nama garis bawah (_); j adalah nomor urutnya.
                onClick={() => setBoxes((x) => x.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
