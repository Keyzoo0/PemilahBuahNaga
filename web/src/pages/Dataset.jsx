// CATATAN UNTUK PEMULA:
// Halaman Dataset: tempat mengumpulkan FOTO untuk melatih ulang model AI.
// Alur besarnya: Dataset (ambil foto) -> Anotasi (tandai buahnya) ->
// Training (latih model baru).
import React, { useEffect, useState } from "react";
import { dsList, dsCapture, dsDelete } from "../api.js";

// { onAnnotate } adalah props berupa FUNGSI yang dikirim App.jsx. Saat foto
// diklik, fungsi ini dipanggil agar induk berpindah ke halaman Anotasi.
export default function Dataset({ onAnnotate }) {
  // Nilai awal sengaja diberi bentuk lengkap ({images: [], stats: null}) agar
  // baris data.images.length di bawah tidak error sebelum data datang.
  const [data, setData] = useState({ images: [], stats: null });
  const [busy, setBusy] = useState(false);     // sedang menyimpan foto?
  const [toast, setToast] = useState(null);    // pesan singkat

  const load = () => dsList().then(setData).catch(() => {});
  // [] = jalankan sekali saja saat halaman pertama dibuka.
  useEffect(() => {
    load();
  }, []);

  // Fungsi bantu: tampilkan pesan lalu hilangkan sendiri setelah 3 detik.
  const flash = (t, m) => {
    setToast({ t, m });
    setTimeout(() => setToast(null), 3000);
  };

  const capture = async () => {
    // Tombol dinonaktifkan selama proses agar pengguna tidak menekannya
    // berkali-kali dan membuat foto ganda.
    setBusy(true);
    const res = await dsCapture();
    setBusy(false);
    if (res.ok) {
      flash("ok", `Tersimpan: ${res.name}`);
      load();   // muat ulang daftar agar foto baru langsung terlihat
    } else flash("err", res.message || "Gagal capture");
  };

  const remove = async (name) => {
    await dsDelete(name);
    load();
  };

  // Pengaman kalau statistik belum tersedia.
  const st = data.stats || {};

  return (
    <>
      <div className="grid cards2" style={{ marginBottom: 16 }}>
        <div className="card cam-card">
          <div className="cam-head">
            <span className="cam-badge">CAM 1 · AMBIL DATASET</span>
            <span className="cam-meta">tekan Capture untuk menyimpan frame</span>
          </div>
          <div className="cam-view">
            {/* Siaran langsung kamera 1, agar pengguna bisa mengatur posisi
                buah dulu sebelum menekan Capture. */}
            <img src="/video/cam1" alt="cam1" />
          </div>
          <div style={{ padding: 14, display: "flex", gap: 10, alignItems: "center" }}>
            <button className="btn primary" onClick={capture} disabled={busy}>
              📷 {busy ? "Menyimpan..." : "Capture"}
            </button>
            {toast && <span className={"toast " + toast.t}>{toast.m}</span>}
          </div>
        </div>

        <div className="card">
          <h3>Ringkasan Dataset</h3>
          <div className="grid cards3">
            <div className="stat">
              {/* ?? 0 -> tampilkan 0 kalau data belum ada, bukan tulisan kosong. */}
              <div className="num">{st.total ?? 0}</div>
              <div className="lbl">Total gambar</div>
            </div>
            <div className="stat matang">
              <div className="num">{st.labeled ?? 0}</div>
              <div className="lbl">Sudah dianotasi</div>
            </div>
            <div className="stat mentah">
              <div className="num">{st.unlabeled ?? 0}</div>
              <div className="lbl">Belum dianotasi</div>
            </div>
          </div>
          <div className="subhead" style={{ marginTop: 16 }}>Jumlah kotak per kelas</div>
          <table>
            <tbody>
              {/* Object.entries mengubah objek {matang: 12, mentah: 5} menjadi
                  daftar pasangan [["matang",12], ["mentah",5]] agar bisa
                  diulang dengan .map() menjadi baris tabel. */}
              {Object.entries(st.per_class || {}).map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td style={{ textAlign: "right", fontWeight: 700 }}>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="roi-hint" style={{ marginTop: 12 }}>
            Tips: ambil gambar dari berbagai posisi, sudut, dan pencahayaan. Target minimal
            ±50 gambar per kelas agar model stabil.
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Dataset Tersimpan ({data.images.length})</h3>
        <div
          style={{
            // CSS Grid: menyusun foto dalam kolom-kolom otomatis.
            display: "grid",
            // repeat(auto-fill, minmax(160px, 1fr)) artinya: isi baris dengan
            // sebanyak mungkin kolom selebar minimal 160px. Jumlah kolomnya
            // menyesuaikan sendiri dengan lebar layar — inilah cara membuat
            // galeri yang rapi di HP maupun di laptop.
            gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
            gap: 12,
          }}
        >
          {data.images.length === 0 && (
            <div style={{ color: "var(--text-dim)" }}>Belum ada gambar. Tekan Capture di atas.</div>
          )}
          {data.images.map((img) => (
            <div
              // Nama file dipakai sebagai key karena pasti unik (berisi waktu).
              key={img.name}
              className="card"
              style={{ padding: 8, position: "relative", overflow: "hidden" }}
            >
              <img
                // /dsimg adalah alamat folder foto dataset yang disajikan server.
                src={`/dsimg/${img.name}`}
                alt={img.name}
                style={{ width: "100%", borderRadius: 8, display: "block", cursor: "pointer" }}
                // "onAnnotate &&" adalah pengaman: panggil hanya kalau fungsinya
                // memang dikirim. Tanpa ini, program error bila props terlupa.
                onClick={() => onAnnotate && onAnnotate(img.name)}
                title="Klik untuk anotasi"
              />
              <div
                className="cam-meta"
                style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 6 }}
              >
                <span
                  className="tag"
                  style={{
                    // Warna label ditentukan kondisi: hijau kalau sudah
                    // dianotasi, merah kalau belum. rgba(...,.15) artinya
                    // warna dengan tingkat transparansi 15%.
                    background: img.labeled ? "rgba(34,197,94,.15)" : "rgba(239,68,68,.15)",
                    color: img.labeled ? "var(--green)" : "var(--red)",
                  }}
                >
                  {img.labeled ? `${img.boxes} box` : "belum"}
                </span>
                {/* flex: 1 membuat elemen kosong ini melar mengisi ruang,
                    sehingga tombol hapus terdorong ke ujung kanan. */}
                <span style={{ flex: 1 }} />
                <button className="btn sm" onClick={() => remove(img.name)} title="Hapus gambar">
                  🗑
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
