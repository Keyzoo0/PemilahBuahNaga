import React, { useEffect, useState } from "react";
import { dsList, dsCapture, dsDelete } from "../api.js";

export default function Dataset({ onAnnotate }) {
  const [data, setData] = useState({ images: [], stats: null });
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  const load = () => dsList().then(setData).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const flash = (t, m) => {
    setToast({ t, m });
    setTimeout(() => setToast(null), 3000);
  };

  const capture = async () => {
    setBusy(true);
    const res = await dsCapture();
    setBusy(false);
    if (res.ok) {
      flash("ok", `Tersimpan: ${res.name}`);
      load();
    } else flash("err", res.message || "Gagal capture");
  };

  const remove = async (name) => {
    await dsDelete(name);
    load();
  };

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
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
            gap: 12,
          }}
        >
          {data.images.length === 0 && (
            <div style={{ color: "var(--text-dim)" }}>Belum ada gambar. Tekan Capture di atas.</div>
          )}
          {data.images.map((img) => (
            <div
              key={img.name}
              className="card"
              style={{ padding: 8, position: "relative", overflow: "hidden" }}
            >
              <img
                src={`/dsimg/${img.name}`}
                alt={img.name}
                style={{ width: "100%", borderRadius: 8, display: "block", cursor: "pointer" }}
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
                    background: img.labeled ? "rgba(34,197,94,.15)" : "rgba(239,68,68,.15)",
                    color: img.labeled ? "var(--green)" : "var(--red)",
                  }}
                >
                  {img.labeled ? `${img.boxes} box` : "belum"}
                </span>
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
