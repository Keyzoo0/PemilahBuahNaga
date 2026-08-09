// CATATAN UNTUK PEMULA:
// Halaman Monitor adalah dashboard utama: menampilkan siaran 2 kamera,
// status sistem, hitungan hari ini, dan tabel riwayat sortir.
//
// Perhatikan bahwa halaman ini TIDAK mengambil data status sendiri — data itu
// dikirim dari App.jsx lewat props bernama "status". Pola ini disebut
// "single source of truth": data status hanya diurus di satu tempat, agar
// tidak ada dua bagian yang menampilkan angka berbeda.
import React, { useEffect, useState } from "react";
import { getHistory, getClasses, deleteHistory, clearHistory } from "../api.js";

// Peta: nama kematangan -> nama class CSS, untuk menentukan warna badge.
// Perhatikan "setengah matang" ditulis dalam tanda kutip karena mengandung
// spasi; kunci tanpa spasi boleh ditulis polos.
const RIPE_CLASS = {
  matang: "ripe-matang",
  "setengah matang": "ripe-setengah",
  mentah: "ripe-mentah",
};

// indikator LED fisik di mesin
// Tulisan ini menirukan lampu LED asli di mesin, agar pengguna yang melihat
// layar tahu persis kondisi yang sama dengan lampu di alatnya.
const INDICATOR = {
  ready: { color: "#22c55e", label: "🟢 SIAP — buah boleh ditaruh di kamera 1" },
  busy: { color: "#ef4444", label: "🔴 SEDANG SORTING" },
  notready: { color: "#eab308", label: "🟡 BELUM SIAP" },
};

// Komponen kecil untuk satu kartu kamera. Dibuat terpisah agar tidak perlu
// menulis kode yang sama dua kali (untuk cam1 dan cam2).
function CameraCard({ badge, title, src, fps, ok }) {
  return (
    <div className="card cam-card">
      <div className="cam-head">
        <span className="cam-badge">{badge}</span>
        <span className="cam-meta">
          {/* Tanda ?? disebut "nullish coalescing": pakai nilai kiri, tapi
              kalau nilainya null/undefined, pakai nilai kanan ("?").
              Bedanya dengan || : angka 0 tetap dianggap nilai sah oleh ??. */}
          {title} · {ok ? `${fps ?? "?"} fps` : "OFFLINE"}
        </span>
      </div>
      <div className="cam-view">
        {/* Alamat ini adalah siaran MJPEG dari server. Tag <img> biasa
            ternyata sanggup menampilkannya seperti video — inilah kenapa
            MJPEG dipilih: sederhana dan jalan di semua browser. */}
        <img src={src} alt={title} />
      </div>
    </div>
  );
}

// Komponen kecil untuk satu kotak angka statistik.
function Stat({ cls, num, lbl }) {
  return (
    <div className={"card stat " + cls}>
      <div className="num">{num}</div>
      <div className="lbl">{lbl}</div>
    </div>
  );
}

export default function Monitor({ status }) {
  const [history, setHistory] = useState([]);
  const [labelIndex, setLabelIndex] = useState({}); // label -> index kelas model

  // Efek 1: ambil daftar kelas model, SEKALI saja saat halaman dibuka.
  useEffect(() => {
    getClasses()
      // .then(...) dikerjakan setelah data berhasil datang.
      .then((d) => {
        const map = {};
        // Server mengirim {0: "matang", 1: "mentah"}, tapi kita butuh
        // kebalikannya: {"matang": 0, "mentah": 1}. Object.entries memecah
        // objek menjadi pasangan [kunci, nilai] agar bisa dibalik.
        Object.entries(d.classes || {}).forEach(([idx, label]) => {
          // Kunci objek selalu berupa teks, jadi Number() mengubahnya ke angka.
          map[label] = Number(idx);
        });
        setLabelIndex(map);
      })
      // .catch dengan isi kosong: kalau gagal, diamkan saja. Data ini cuma
      // pelengkap tampilan, tidak perlu memunculkan pesan error ke pengguna.
      .catch(() => {});
  }, []);

  // Efek 2: muat riwayat sortir, lalu perbarui tiap 3 detik.
  useEffect(() => {
    const load = () => getHistory(20).then((d) => setHistory(d.rows || [])).catch(() => {});
    load();                                  // panggil sekali agar langsung tampil
    const t = setInterval(load, 3000);       // lalu ulangi tiap 3 detik
    // Fungsi yang dikembalikan useEffect dijalankan saat halaman ditutup.
    // WAJIB menghentikan timer di sini — kalau tidak, timernya terus jalan
    // di latar belakang walau halaman sudah ditinggalkan.
    return () => clearInterval(t);
  }, []);

  // "status || {}" adalah pengaman: kalau status masih null (belum ada data
  // dari server), pakai objek kosong agar s.state dan kawan-kawan tidak error.
  const s = status || {};
  const counts = s.counts_today || {};
  const ripe = s.ripeness;
  const ripeCls = RIPE_CLASS[ripe] || "ripe-none";
  const ind = INDICATOR[s.indicator];
  // index kelas: dari core, atau fallback peta label->index
  // Dibaca: pakai s.ripeness_index; kalau kosong, cari sendiri lewat labelIndex;
  // kalau ripe juga kosong, biarkan undefined (tidak ditampilkan).
  const idx = s.ripeness_index ?? (ripe != null ? labelIndex[ripe] : undefined);

  return (
    // <> ... </> disebut "Fragment": pembungkus tak terlihat. Dipakai karena
    // komponen React wajib mengembalikan SATU elemen induk, tapi kita tidak
    // ingin menambah <div> yang tidak perlu di dalam struktur halaman.
    <>
      <div className="state-banner">
        <div>
          {/* Tampilkan baris indikator hanya kalau datanya tersedia. */}
          {ind && (
            // style={{...}} memakai dua kurung kurawal: satu untuk menandai
            // kode JavaScript di dalam JSX, satu lagi untuk objek gayanya.
            // Nama properti CSS ditulis gaya camelCase: font-weight -> fontWeight.
            <div style={{ color: ind.color, fontWeight: 800, fontSize: 15, marginBottom: 6 }}>
              {ind.label}
            </div>
          )}
          <div className="state-name">{s.state || "—"}</div>
          <div className="state-msg">{s.message || "Menunggu koneksi core..."}</div>
          <div className="state-msg" style={{ marginTop: 4, fontFamily: "monospace" }}>
            {/* Angka-angka mentah ini berguna saat kalibrasi: dari sini terlihat
                apakah ambang batas di halaman Kalibrasi sudah pas atau belum. */}
            gerakan: {s.motion ?? "—"} · objek: {s.fg_ratio ?? "—"} · latar:{" "}
            {s.has_empty_ref ? "✓ terkalibrasi" : "⚠ belum disimpan"}
            {s.paddle_change != null && <> · paddle Δ: {s.paddle_change}</>}
          </div>
        </div>
        <div className="spacer" />
        <div style={{ textAlign: "right" }}>
          {/* Ditampilkan hanya kalau ADA buah DAN indexnya diketahui. */}
          {ripe && idx != null && (
            <div
              style={{
                fontFamily: "monospace",
                fontSize: 13,
                // var(--text-dim) mengambil warna dari variabel CSS yang
                // didefinisikan di styles.css, agar warnanya seragam se-aplikasi.
                color: "var(--text-dim)",
                marginBottom: 6,
              }}
            >
              INDEX KELAS: <b style={{ color: "var(--pink)", fontSize: 18 }}>{idx}</b>
            </div>
          )}
          <span className={"ripe-badge " + ripeCls}>
            {ripe ? `${ripe} ${s.ripeness_conf ? "(" + s.ripeness_conf + ")" : ""}` : "belum ada buah"}
          </span>
        </div>
      </div>

      {/* Dua kartu kamera bersebelahan. Komponen CameraCard dipakai dua kali
          dengan props berbeda — inilah keuntungan memecah jadi komponen. */}
      <div className="grid cards2" style={{ marginBottom: 16 }}>
        <CameraCard
          badge="CAM 1 · DETEKSI"
          title="Area hitam / klasifikasi"
          src="/video/cam1"
          fps={s.cam1_fps}
          ok={s.cam1_ok}
        />
        <CameraCard
          badge="CAM 2 · SORTING"
          title="Tracking lengan servo"
          src="/video/cam2"
          fps={s.cam2_fps}
          ok={s.cam2_ok}
        />
      </div>

      {/* Tiga kotak hitungan hari ini.
          "counts[...] || 0" -> tampilkan 0 kalau belum ada data sama sekali. */}
      <div className="grid cards3" style={{ marginBottom: 16 }}>
        <Stat cls="matang" num={counts["matang"] || 0} lbl="Matang (lurus)" />
        <Stat cls="setengah" num={counts["setengah matang"] || 0} lbl="Setengah matang (Servo 2)" />
        <Stat cls="mentah" num={counts["mentah"] || 0} lbl="Mentah (Servo 1)" />
      </div>

      <div className="card">
        <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Riwayat Sortasi Terbaru</h3>
          <span className="spacer" style={{ flex: 1 }} />
          <button
            className="btn sm"
            // async dipakai karena di dalamnya ada "await".
            onClick={async () => {
              // confirm() memunculkan kotak dialog "OK / Batal" dari browser.
              // Wajib ada untuk aksi yang tidak bisa dibatalkan seperti ini.
              if (confirm("Hapus SEMUA riwayat sortasi?")) {
                await clearHistory();   // tunggu server selesai menghapus
                setHistory([]);         // baru kosongkan tampilan
              }
            }}
          >
            🗑 Hapus Semua
          </button>
        </div>
        {/* overflowX auto -> tabel bisa digeser ke samping di layar HP yang
            sempit, tanpa merusak susunan halaman. */}
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Waktu</th>
                <th>Index</th>
                <th>Kematangan</th>
                <th>Conf</th>
                <th>Aksi</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {/* Pesan khusus saat tabel masih kosong. colSpan="6" membuat
                  satu sel melebar menutupi keenam kolom. */}
              {history.length === 0 && (
                <tr>
                  <td colSpan="6" style={{ color: "var(--text-dim)" }}>
                    Belum ada data hari ini.
                  </td>
                </tr>
              )}
              {/* .map() mengubah setiap baris data menjadi satu baris tabel.
                  Inilah cara React menampilkan daftar. */}
              {history.map((r) => (
                // "key" WAJIB ada saat membuat daftar. React memakainya untuk
                // mengenali baris mana yang berubah, sehingga penggambaran
                // ulang jadi cepat dan tidak salah menempatkan data.
                <tr key={r.id}>
                  <td>{r.created_at}</td>
                  <td style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--pink)" }}>
                    {labelIndex[r.ripeness] ?? "—"}
                  </td>
                  <td>
                    <span className={"ripe-badge " + (RIPE_CLASS[r.ripeness] || "ripe-none")}>
                      {r.ripeness || "-"}
                    </span>
                  </td>
                  <td>{r.confidence ?? "-"}</td>
                  <td>{r.action || "-"}</td>
                  <td>
                    <button
                      className="btn sm"
                      title="Hapus baris ini"
                      onClick={async () => {
                        await deleteHistory(r.id);
                        // .filter() membuat daftar BARU tanpa baris yang dihapus.
                        // Daftar lama tidak diubah — ini aturan penting di React.
                        setHistory((h) => h.filter((x) => x.id !== r.id));
                      }}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
