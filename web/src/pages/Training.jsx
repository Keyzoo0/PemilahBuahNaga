import React, { useEffect, useRef, useState } from "react";
import { dsList, trainStart, trainStop, trainStatus, listModels, activateModel } from "../api.js";

export default function Training() {
  const [st, setSt] = useState({ running: false, log: [] });
  const [stats, setStats] = useState({});
  const [models, setModels] = useState([]);
  const [p, setP] = useState({ epochs: 40, imgsz: 416, batch: 8, freeze: 10 });
  const [toast, setToast] = useState(null);
  const logRef = useRef(null);

  const refresh = () => {
    trainStatus().then(setSt).catch(() => {});
    listModels().then((d) => setModels(d.models || [])).catch(() => {});
  };
  useEffect(() => {
    dsList().then((d) => setStats(d.stats || {}));
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
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
    if (!confirm("Pasang model ini sebagai model aktif? Model lama akan di-backup.")) return;
    const res = await activateModel(path);
    flash(res.ok ? "ok" : "err", res.message);
  };

  const eta = p.epochs * (stats.labeled || 0) * (p.imgsz <= 320 ? 0.35 : p.imgsz <= 416 ? 0.6 : 1.4);

  return (
    <>
      <div className="grid cards2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>Parameter Training</h3>
          <div className="row4">
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
                  onChange={(e) => setP({ ...p, [key]: Number(e.target.value) })}
                />
              </div>
            ))}
          </div>
          <div className="roi-hint">
            Pi 5 melatih di CPU. <b>freeze=10</b> membekukan backbone sehingga hanya kepala
            deteksi yang dilatih — jauh lebih cepat dan cukup untuk kamera tetap.
            Perkiraan kasar: <b>±{Math.round(eta / 60)} menit</b> untuk {stats.labeled || 0} gambar
            berlabel. Turunkan <i>imgsz</i> ke 320 bila terlalu lama.
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 12, alignItems: "center" }}>
            {!st.running ? (
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
        </div>
      </div>

      <div className="card">
        <h3>Log Training {st.running && "· berjalan"}</h3>
        <pre
          ref={logRef}
          style={{
            background: "#0a0910",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: 12,
            height: 320,
            overflow: "auto",
            fontSize: 12,
            fontFamily: "monospace",
            color: "var(--text-dim)",
            whiteSpace: "pre-wrap",
          }}
        >
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
