import React, { useEffect, useState } from "react";
import { getHistory, getClasses, deleteHistory, clearHistory } from "../api.js";

const RIPE_CLASS = {
  matang: "ripe-matang",
  "setengah matang": "ripe-setengah",
  mentah: "ripe-mentah",
};

// indikator LED fisik di mesin
const INDICATOR = {
  ready: { color: "#22c55e", label: "🟢 SIAP — buah boleh ditaruh di kamera 1" },
  busy: { color: "#ef4444", label: "🔴 SEDANG SORTING" },
  notready: { color: "#eab308", label: "🟡 BELUM SIAP" },
};

function CameraCard({ badge, title, src, fps, ok }) {
  return (
    <div className="card cam-card">
      <div className="cam-head">
        <span className="cam-badge">{badge}</span>
        <span className="cam-meta">
          {title} · {ok ? `${fps ?? "?"} fps` : "OFFLINE"}
        </span>
      </div>
      <div className="cam-view">
        <img src={src} alt={title} />
      </div>
    </div>
  );
}

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

  useEffect(() => {
    getClasses()
      .then((d) => {
        const map = {};
        Object.entries(d.classes || {}).forEach(([idx, label]) => {
          map[label] = Number(idx);
        });
        setLabelIndex(map);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const load = () => getHistory(20).then((d) => setHistory(d.rows || [])).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  const s = status || {};
  const counts = s.counts_today || {};
  const ripe = s.ripeness;
  const ripeCls = RIPE_CLASS[ripe] || "ripe-none";
  const ind = INDICATOR[s.indicator];
  // index kelas: dari core, atau fallback peta label->index
  const idx = s.ripeness_index ?? (ripe != null ? labelIndex[ripe] : undefined);

  return (
    <>
      <div className="state-banner">
        <div>
          {ind && (
            <div style={{ color: ind.color, fontWeight: 800, fontSize: 15, marginBottom: 6 }}>
              {ind.label}
            </div>
          )}
          <div className="state-name">{s.state || "—"}</div>
          <div className="state-msg">{s.message || "Menunggu koneksi core..."}</div>
          <div className="state-msg" style={{ marginTop: 4, fontFamily: "monospace" }}>
            gerakan: {s.motion ?? "—"} · objek: {s.fg_ratio ?? "—"} · latar:{" "}
            {s.has_empty_ref ? "✓ terkalibrasi" : "⚠ belum disimpan"}
            {s.cam2_best && (
              <> · cam2 buah @ x={s.cam2_best.cx} y={s.cam2_best.cy} ({s.cam2_best.conf})</>
            )}
          </div>
        </div>
        <div className="spacer" />
        <div style={{ textAlign: "right" }}>
          {ripe && idx != null && (
            <div
              style={{
                fontFamily: "monospace",
                fontSize: 13,
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
            onClick={async () => {
              if (confirm("Hapus SEMUA riwayat sortasi?")) {
                await clearHistory();
                setHistory([]);
              }
            }}
          >
            🗑 Hapus Semua
          </button>
        </div>
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
              {history.length === 0 && (
                <tr>
                  <td colSpan="6" style={{ color: "var(--text-dim)" }}>
                    Belum ada data hari ini.
                  </td>
                </tr>
              )}
              {history.map((r) => (
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
