// Detail satu sesi training: confusion matrix, metrik per kelas, grafik per
// epoch, parameter, dan log. Muncul saat satu baris di Riwayat Training diklik.
import React, { useEffect, useState } from "react";
import { trainRun, runImgUrl } from "../api.js";
import { ConfusionMatrix, LineChart } from "./Charts.jsx";

// Label status + ikon, supaya tidak hanya mengandalkan warna.
export const STATUS = {
  completed: { icon: "✓", label: "Selesai", color: "var(--green)" },
  stopped: { icon: "■", label: "Dihentikan", color: "var(--yellow)" },
  failed: { icon: "✕", label: "Gagal", color: "var(--red)" },
  running: { icon: "●", label: "Berjalan", color: "var(--pink)" },
};

export function StatusBadge({ status }) {
  const s = STATUS[status] || { icon: "?", label: status || "-", color: "var(--text-dim)" };
  return (
    <span className="status">
      <span style={{ color: s.color }}>{s.icon}</span> {s.label}
    </span>
  );
}

// "2026-09-23 07:12:34" -> "23 Sep 2026 · 07:12"
const BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
export function fmtWhen(s) {
  const [d, t] = s.split(" ");
  const [y, m, dd] = d.split("-");
  return `${Number(dd)} ${BULAN[Number(m) - 1]} ${y} · ${t.slice(0, 5)}`;
}
export const fmtDur = (s) => (s == null ? "—" : s < 3600 ? `${Math.round(s / 60)} mnt` : `${(s / 3600).toFixed(1)} jam`);
export const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

export default function RunDetail({ run, onActivate, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [attempt, setAttempt] = useState(0);   // naik saat tombol "Coba lagi" ditekan

  // Muat detail; selama run masih berjalan, perbarui tiap 3 detik agar
  // grafik & log ikut bergerak. Permintaan yang macet dibatalkan setelah
  // 15 detik supaya halaman tidak menampilkan "Memuat…" selamanya.
  useEffect(() => {
    let alive = true, t;
    const load = () => {
      const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error("server tidak membalas (15 detik)")), 15000));
      Promise.race([trainRun(run), timeout]).then((x) => {
        if (!alive) return;
        setD(x);
        setErr(null);
        if (x.status === "running") t = setTimeout(load, 3000);
      }).catch((e) => { if (alive) setErr(e.message || String(e)); });
    };
    setD(null);
    setErr(null);
    load();
    return () => { alive = false; clearTimeout(t); };
  }, [run, attempt]);

  if (!d) return (
    <div className="card">
      {err ? (
        <span className="toast err">
          Gagal memuat {run}: {err}.{" "}
          <button className="btn sm" onClick={() => setAttempt(attempt + 1)}>Coba lagi</button>
        </span>
      ) : `Memuat ${run}…`}
    </div>
  );
  if (d.ok === false) return <div className="card toast err">{d.message}</div>;

  const ev = d.eval_detail;
  return (
    <div className="card run-detail">
      <div className="run-head">
        <div>
          <h3 style={{ marginBottom: 4 }}>Hasil Training · {fmtWhen(d.started)}</h3>
          <div className="cam-meta">
            <StatusBadge status={d.status} /> · epoch {d.epochs_done}/{d.epochs} · {fmtDur(d.duration_s)}
            {d.train_imgs != null && ` · ${d.train_imgs} foto latih`}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {d.is_active ? (
            <span className="cam-badge">MODEL AKTIF</span>
          ) : (
            d.has_model && d.status !== "running" && (
              <button className="btn sm primary" onClick={() => onActivate(d.model_path)}>Aktifkan model ini</button>
            )
          )}
          <button className="btn sm ghost" onClick={onClose} aria-label="Tutup">✕</button>
        </div>
      </div>

      {ev?.retro && (
        <div className="warn">
          ⚠ Dievaluasi ulang pada {ev.evaluated_at} (run ini dibuat sebelum ada confusion matrix otomatis).
          Model lama ini kemungkinan sudah pernah melihat sebagian foto uji, jadi angkanya
          <b> cenderung terlalu bagus</b>. Pakai untuk perbandingan kasar saja.
        </div>
      )}
      {d.error && <div className="toast err" style={{ marginBottom: 10 }}>{d.error}</div>}

      {ev ? (
        <div className="grid cards2" style={{ marginBottom: 16 }}>
          <div>
            <div className="subhead">Confusion Matrix</div>
            <ConfusionMatrix names={ev.names} matrix={ev.matrix} conf={ev.conf} />
          </div>
          <div>
            <div className="subhead">Metrik ({ev.val_images ?? "?"} foto uji)</div>
            <div className="grid mini4" style={{ marginBottom: 14 }}>
              {[["Precision", ev.overall.precision], ["Recall", ev.overall.recall],
                ["mAP50", ev.overall.map50], ["mAP50-95", ev.overall.map50_95]].map(([l, v]) => (
                <div className="stat sm" key={l}><div className="num">{pct(v)}</div><div className="lbl">{l}</div></div>
              ))}
            </div>
            <table>
              <thead>
                <tr><th>Kelas</th><th>Jumlah</th><th>Precision</th><th>Recall</th><th>mAP50</th><th>mAP50-95</th></tr>
              </thead>
              <tbody>
                {ev.per_class.map((c) => (
                  <tr key={c.name}>
                    <td>{c.name}</td><td>{c.instances}</td><td>{pct(c.precision)}</td>
                    <td>{pct(c.recall)}</td><td>{pct(c.map50)}</td><td>{pct(c.map50_95)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="roi-hint" style={{ marginBottom: 16 }}>
          {d.status === "running"
            ? "Confusion matrix dibuat otomatis begitu training selesai atau dihentikan."
            : d.eval_error
              ? `Evaluasi gagal: ${d.eval_error}`
              : "Run ini tidak punya hasil evaluasi."}
        </div>
      )}

      <div className="grid cards2" style={{ marginBottom: 12 }}>
        <div>
          <div className="subhead">mAP per epoch</div>
          <LineChart
            data={d.curves}
            yMax={1}
            fmt={(v) => v.toFixed(2)}
            series={[{ key: "map50", label: "mAP50" }, { key: "map50_95", label: "mAP50-95" }]}
          />
        </div>
        <div>
          <div className="subhead">Loss per epoch (box + cls + dfl)</div>
          <LineChart
            data={d.curves}
            fmt={(v) => v.toFixed(1)}
            series={[{ key: "train_loss", label: "Latih" }, { key: "val_loss", label: "Uji" }]}
          />
        </div>
      </div>

      <details>
        <summary>Tabel per epoch</summary>
        <div className="cm-wrap">
          <table>
            <thead>
              <tr><th>Epoch</th><th>Precision</th><th>Recall</th><th>mAP50</th><th>mAP50-95</th><th>Loss latih</th><th>Loss uji</th></tr>
            </thead>
            <tbody>
              {d.curves.map((c) => (
                <tr key={c.epoch}>
                  <td>{c.epoch}</td><td>{pct(c.precision)}</td><td>{pct(c.recall)}</td><td>{pct(c.map50)}</td>
                  <td>{pct(c.map50_95)}</td><td>{c.train_loss.toFixed(3)}</td><td>{c.val_loss.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <details>
        <summary>Parameter</summary>
        <table>
          <tbody>
            {Object.entries(d.params).map(([k, v]) => (
              <tr key={k}><td style={{ color: "var(--text-dim)" }}>{k}</td><td className="cam-meta">{v ?? "—"}</td></tr>
            ))}
          </tbody>
        </table>
      </details>

      <details>
        <summary>Log training</summary>
        <pre className="logbox">{d.log.length ? d.log.join("\n") : "Log tidak tersimpan untuk run lama ini."}</pre>
      </details>

      {d.images.length > 0 && (
        <details>
          <summary>Gambar asli ultralytics ({d.images.length})</summary>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {d.images.map((n) => (
              <a key={n} className="btn sm" href={runImgUrl(d.run, n)} target="_blank" rel="noreferrer">{n}</a>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
