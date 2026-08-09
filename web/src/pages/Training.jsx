// CATATAN UNTUK PEMULA:
// Halaman Training: melatih model AI baru dari dataset yang sudah dianotasi,
// langsung di Raspberry Pi. Halaman ini juga memantau kemajuannya lewat log,
// dan bisa mengubah model ke format yang lebih ringan (ONNX/NCNN).
//
// Pola penting di sini: "polling". Proses training berjalan lama (bisa
// puluhan menit) di server. Browser tidak menunggu diam, melainkan bertanya
// "sudah sampai mana?" tiap 2 detik lalu memperbarui tampilan.
import React, { useEffect, useRef, useState } from "react";
import { dsList, trainStart, trainStop, trainStatus, listModels, activateModel, exportModel, exportStatus } from "../api.js";

export default function Training() {
  const [st, setSt] = useState({ running: false, log: [] });   // status training
  const [stats, setStats] = useState({});                      // ringkasan dataset
  const [models, setModels] = useState([]);                    // daftar model hasil training
  const [activeKind, setActiveKind] = useState("");            // format model yang dipakai
  const [exp, setExp] = useState({ running: false });          // status export model
  // Nilai awal parameter training. Angka-angka ini sudah disesuaikan agar
  // Raspberry Pi sanggup menjalankannya.
  const [p, setP] = useState({ epochs: 40, imgsz: 416, batch: 8, freeze: 10 });
  const [toast, setToast] = useState(null);
  const logRef = useRef(null);   // pengait ke kotak log, untuk menggulir otomatis

  // Mengambil semua data terbaru dari server sekaligus.
  const refresh = () => {
    trainStatus().then(setSt).catch(() => {});
    listModels().then((d) => {
      setModels(d.models || []);
      setActiveKind(d.active_kind || "");
    }).catch(() => {});
    exportStatus().then(setExp).catch(() => {});
  };

  const doExport = async (format) => {
    const res = await exportModel(format, p.imgsz);
    flash(res.ok ? "ok" : "err", res.ok
      ? `Export ${format} dimulai (sorting -> MANUAL). Tunggu selesai lalu restart service.`
      : res.message);
    refresh();
  };

  // Efek 1: muat data awal, lalu perbarui otomatis tiap 2 detik.
  useEffect(() => {
    dsList().then((d) => setStats(d.stats || {}));
    refresh();
    const t = setInterval(refresh, 2000);
    // Hentikan timer saat halaman ditinggalkan, agar tidak terus berjalan
    // di latar belakang dan membebani server.
    return () => clearInterval(t);
  }, []);

  // Efek 2: gulirkan kotak log ke bawah otomatis setiap ada baris baru,
  // supaya baris terbaru selalu terlihat tanpa perlu digulir manual.
  // [st.log] artinya efek ini dijalankan ulang tiap kali isi log berubah.
  useEffect(() => {
    // scrollTop = posisi gulir sekarang; scrollHeight = tinggi seluruh isi.
    // Menyamakan keduanya = menggulir sampai paling bawah.
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [st.log]);

  const flash = (t, m) => {
    setToast({ t, m });
    setTimeout(() => setToast(null), 5000);
  };

  const start = async () => {
    const res = await trainStart(p);
    if (res.ok) flash("ok", `Training dimulai: ${res.run}. Sorting dialihkan ke MANUAL.`);
    else flash("err", res.message);
    refresh();
  };

  const activate = async (path) => {
    // Konfirmasi wajib: mengganti model aktif mempengaruhi seluruh sistem.
    // "if (!confirm(...)) return" artinya kalau pengguna menekan Batal,
    // hentikan fungsi ini sekarang juga.
    if (!confirm("Pasang model ini sebagai model aktif? Model lama akan di-backup.")) return;
    const res = await activateModel(path);
    flash(res.ok ? "ok" : "err", res.message);
  };

  // Perkiraan kasar lama training, dalam detik.
  // Rumusnya: jumlah epoch x jumlah gambar x faktor berat sesuai ukuran gambar.
  // Rangkaian "a ? x : b ? y : z" adalah if-else bertingkat: imgsz kecil
  // (<=320) faktornya 0.35, sedang (<=416) 0.6, besar 1.4.
  // Angka-angka ini hasil pengukuran di Pi 5, bukan rumus baku.
  const eta = p.epochs * (stats.labeled || 0) * (p.imgsz <= 320 ? 0.35 : p.imgsz <= 416 ? 0.6 : 1.4);

  return (
    <>
      <div className="grid cards2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>Parameter Training</h3>
          <div className="row4">
            {/* Empat kotak input dibuat dari satu daftar berisi
                [judul, nama kunci, besar lompatan]. */}
            {[
              ["Epochs", "epochs", 1],
              ["Image size", "imgsz", 32],
              ["Batch", "batch", 1],
              ["Freeze layer", "freeze", 1],
            ].map(([lbl, key, step]) => (
              <div className="field" key={key}>
                <label>{lbl}</label>
                <input
                  type="number"
                  step={step}
                  value={p[key]}
                  // { ...p, [key]: ... } menyalin semua nilai lama, lalu
                  // mengganti satu saja. Kurung siku pada [key] disebut
                  // "computed property": nama kuncinya diambil dari isi
                  // variabel key, bukan tulisan "key" itu sendiri.
                  onChange={(e) => setP({ ...p, [key]: Number(e.target.value) })}
                />
              </div>
            ))}
          </div>
          <div className="roi-hint">
            Pi 5 melatih di CPU. <b>freeze=10</b> membekukan backbone sehingga hanya kepala
            deteksi yang dilatih — jauh lebih cepat dan cukup untuk kamera tetap.
            {/* eta dalam detik, dibagi 60 menjadi menit lalu dibulatkan. */}
            Perkiraan kasar: <b>±{Math.round(eta / 60)} menit</b> untuk {stats.labeled || 0} gambar
            berlabel. Turunkan <i>imgsz</i> ke 320 bila terlalu lama.
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 12, alignItems: "center" }}>
            {/* Tombol berganti sesuai kondisi: Mulai kalau sedang berhenti,
                Hentikan kalau sedang berjalan. */}
            {!st.running ? (
              // disabled saat gambar berlabel kurang dari 4 — dataset sesedikit
              // itu tidak bisa dibagi menjadi data latih dan data uji.
              <button className="btn primary" onClick={start} disabled={(stats.labeled || 0) < 4}>
                ▶ Mulai Training
              </button>
            ) : (
              <button className="btn estop" onClick={() => trainStop().then(refresh)}>
                ■ Hentikan
              </button>
            )}
            {st.running && (
              <span className="cam-meta">
                {/* st.params?.train_imgs memakai tanda tanya karena params
                    bisa saja belum terisi di detik-detik pertama. */}
                berjalan {Math.round(st.elapsed || 0)}s · {st.params?.train_imgs} train /{" "}
                {st.params?.val_imgs} val
              </span>
            )}
            {toast && <span className={"toast " + toast.t}>{toast.m}</span>}
          </div>
          {(stats.labeled || 0) < 4 && (
            <div className="toast err" style={{ marginTop: 8 }}>
              Minimal 4 gambar berlabel. Saat ini: {stats.labeled || 0}.
            </div>
          )}
        </div>

        <div className="card">
          <h3>Kesiapan Dataset</h3>
          <div className="grid cards3">
            <div className="stat">
              <div className="num">{stats.total ?? 0}</div>
              <div className="lbl">Total</div>
            </div>
            <div className="stat matang">
              <div className="num">{stats.labeled ?? 0}</div>
              <div className="lbl">Berlabel</div>
            </div>
            <div className="stat mentah">
              <div className="num">{stats.unlabeled ?? 0}</div>
              <div className="lbl">Belum</div>
            </div>
          </div>
          <div className="subhead" style={{ marginTop: 14 }}>Model hasil training</div>
          <table>
            <tbody>
              {models.length === 0 && (
                <tr><td style={{ color: "var(--text-dim)" }}>Belum ada model.</td></tr>
              )}
              {models.map((m) => (
                // Alamat file dipakai sebagai key karena pasti unik.
                <tr key={m.path}>
                  <td>{m.run}</td>
                  <td>{m.size_mb} MB</td>
                  <td>{m.mtime}</td>
                  <td>
                    <button className="btn sm primary" onClick={() => activate(m.path)}>
                      Aktifkan
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="subhead" style={{ marginTop: 16 }}>
            Optimasi Model (lebih ringan di Pi)
          </div>
          <div className="cam-meta" style={{ marginBottom: 8 }}>
            Model aktif sekarang: <b style={{ color: "var(--pink)" }}>{activeKind || "…"}</b>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            {/* Kedua tombol dimatikan selama export berjalan, agar tidak ada
                dua proses berat berjalan bersamaan di Pi. */}
            <button className="btn sm" disabled={exp.running} onClick={() => doExport("onnx")}>
              Export ONNX
            </button>
            <button className="btn sm primary" disabled={exp.running} onClick={() => doExport("ncnn")}>
              Export NCNN (tercepat)
            </button>
            {exp.running && <span className="cam-meta">meng-export {exp.format}…</span>}
            {/* Tanda sukses hanya muncul kalau ADA hasil DAN sudah tidak berjalan. */}
            {exp.result && !exp.running && <span className="toast ok">✓ {exp.format} siap</span>}
            {/* slice(0, 60) memotong pesan error agar tidak merusak tata letak. */}
            {exp.error && <span className="toast err">{exp.error.slice(0, 60)}</span>}
          </div>
          <div className="roi-hint" style={{ marginTop: 6 }}>
            Konversi best.pt → format ringan. NCNN paling cepat di ARM (~2×), ONNX ~1.3×.
            {/* &gt; adalah cara menulis tanda ">" di dalam HTML/JSX. Kalau
                ditulis langsung, ia akan disangka bagian dari tag. */}
            Setelah selesai, restart service: model ringan otomatis dipakai (NCNN &gt; ONNX &gt; .pt).
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Log Training {st.running && "· berjalan"}</h3>
        {/* Tag <pre> mempertahankan spasi dan baris apa adanya — cocok untuk
            menampilkan log agar kolomnya tetap sejajar. */}
        <pre
          ref={logRef}
          style={{
            background: "#0a0910",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: 12,
            // Tinggi dipatok 320 piksel + overflow auto: kotak log bisa
            // digulir sendiri tanpa membuat halaman memanjang tak terbatas.
            height: 320,
            overflow: "auto",
            fontSize: 12,
            fontFamily: "monospace",
            color: "var(--text-dim)",
            // pre-wrap: tetap hormati baris baru, TAPI baris yang terlalu
            // panjang tetap dilipat agar tidak keluar dari kotak.
            whiteSpace: "pre-wrap",
          }}
        >
          {/* join("\n") menyambung daftar baris log menjadi satu teks panjang. */}
          {(st.log || []).join("\n") || "Belum ada log."}
        </pre>
        {st.error && <div className="toast err">{st.error}</div>}
        {st.result_model && (
          <div className="toast ok">Selesai → {st.result_model} (klik Aktifkan di tabel model)</div>
        )}
      </div>
    </>
  );
}
