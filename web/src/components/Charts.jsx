// Komponen grafik untuk hasil training: confusion matrix & grafik garis per epoch.
//
// CATATAN UNTUK PEMULA:
// Grafik digambar sendiri dengan HTML/SVG (tanpa pustaka tambahan) supaya
// web tetap ringan di Raspberry Pi.
//
// Cara membaca confusion matrix:
//   - Baris  = kelas SEBENARNYA (aktual) dari label anotasi.
//   - Kolom  = tebakan MODEL (prediksi).
//   - Diagonal (aktual = prediksi) = tebakan benar. Makin pekat makin bagus.
//   - Kolom "latar"  = buah ada tapi TIDAK terdeteksi (terlewat).
//   - Baris "latar"  = model melihat buah padahal tidak ada (deteksi palsu).
import React, { useEffect, useRef, useState } from "react";

// Warna seri tetap berurutan (sudah dicek aman untuk buta warna di latar gelap).
export const SERIES = ["#e5157f", "#3b82f6"];

export function ConfusionMatrix({ names, matrix, conf }) {
  const [pct, setPct] = useState(false);   // tampilkan persen atau jumlah
  const labels = [...names, "latar"];
  const n = labels.length;
  // Data dari server: matrix[prediksi][aktual]. Dibalik agar baris = aktual.
  const cell = (t, p) => matrix[p][t];
  const rowSum = (t) => labels.reduce((s, _, p) => s + cell(t, p), 0);

  return (
    <div>
      <div className="seg" style={{ marginBottom: 10 }}>
        <button className={!pct ? "active" : ""} onClick={() => setPct(false)}>Jumlah</button>
        <button className={pct ? "active" : ""} onClick={() => setPct(true)}>Persen per baris</button>
      </div>
      <div className="cm-wrap">
        <table className="cm">
          <thead>
            <tr>
              <th className="cm-corner">aktual ↓ · prediksi →</th>
              {labels.map((l) => <th key={l}>{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {labels.map((tl, t) => {
              const sum = rowSum(t);
              return (
                <tr key={tl}>
                  <th>{tl}</th>
                  {labels.map((pl, p) => {
                    // latar-vs-latar tidak punya arti (tak ada yang dihitung).
                    if (t === n - 1 && p === n - 1) return <td key={pl} className="cm-na">—</td>;
                    const v = cell(t, p);
                    const frac = sum ? v / sum : 0;
                    // Satu warna (pink), makin pekat = makin besar porsi di baris itu.
                    const bg = `rgba(229, 21, 127, ${v ? 0.1 + 0.8 * frac : 0})`;
                    return (
                      <td
                        key={pl}
                        style={{ background: bg, color: frac > 0.45 ? "#fff" : v ? "var(--text)" : "var(--text-dim)" }}
                        title={`Aktual ${tl} → prediksi ${pl}: ${v} kotak (${(frac * 100).toFixed(1)}% dari baris)`}
                      >
                        {pct ? `${Math.round(frac * 100)}%` : v}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="roi-hint">
        Diagonal = benar. Kolom <b>latar</b> = buah terlewat; baris <b>latar</b> = deteksi palsu.
        Warna = porsi dari total baris aktual. Ambang keyakinan {conf ?? 0.25}.
      </div>
    </div>
  );
}

// Batas atas sumbu yang habis dibagi 4 dengan angka "bulat"
// (mis. 4 -> 0,1,2,3,4; 8 -> 0,2,4,6,8) agar mudah dibaca.
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const m = [1, 2, 4, 8, 10].find((k) => k * p >= v);
  return m * p;
}

// Grafik garis per epoch. series = [{ key, label }], warna mengikuti urutan SERIES.
export function LineChart({ data, series, yMax, fmt = (v) => v.toFixed(3), height = 180 }) {
  const boxRef = useRef(null);
  const [w, setW] = useState(480);
  const [hover, setHover] = useState(null);   // index epoch yang sedang disorot

  // Lebar grafik mengikuti lebar kartu (responsif di HP maupun laptop).
  useEffect(() => {
    if (!boxRef.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, e.contentRect.width)));
    ro.observe(boxRef.current);
    return () => ro.disconnect();
  }, []);

  if (!data.length) return <div className="roi-hint">Belum ada data epoch.</div>;

  const pad = { l: 40, r: 12, t: 8, b: 24 };
  const iw = w - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const top = yMax ?? niceMax(Math.max(...data.flatMap((d) => series.map((s) => d[s.key] ?? 0))));
  const x0 = data[0].epoch;
  const x1 = data[data.length - 1].epoch;
  const sx = (e) => pad.l + (x1 === x0 ? iw / 2 : ((e - x0) / (x1 - x0)) * iw);
  const sy = (v) => pad.t + ih - (v / top) * ih;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  const step = Math.max(1, Math.ceil((x1 - x0) / 6));
  const xTicks = data.map((d) => d.epoch).filter((e) => (e - x0) % step === 0);

  const onMove = (ev) => {
    const rect = ev.currentTarget.getBoundingClientRect();
    const px = ((ev.clientX - rect.left) / rect.width) * w;
    let best = 0;
    data.forEach((d, i) => { if (Math.abs(sx(d.epoch) - px) < Math.abs(sx(data[best].epoch) - px)) best = i; });
    setHover(best);
  };

  const hd = hover != null ? data[hover] : null;
  return (
    <div ref={boxRef} className="chart">
      <div className="legend">
        {series.map((s, i) => (
          <span key={s.key}><i style={{ background: SERIES[i] }} />{s.label}</span>
        ))}
      </div>
      <svg width={w} height={height} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={w - pad.r} y1={sy(v)} y2={sy(v)} stroke="var(--border)" strokeWidth="1" />
            <text x={pad.l - 6} y={sy(v) + 4} textAnchor="end" className="axis">{fmt(v)}</text>
          </g>
        ))}
        {xTicks.map((e) => (
          <text key={e} x={sx(e)} y={height - 6} textAnchor="middle" className="axis">{e}</text>
        ))}
        {series.map((s, i) => (
          <polyline
            key={s.key}
            fill="none"
            stroke={SERIES[i]}
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
            points={data.filter((d) => d[s.key] != null).map((d) => `${sx(d.epoch)},${sy(d[s.key])}`).join(" ")}
          />
        ))}
        {hd && <line x1={sx(hd.epoch)} x2={sx(hd.epoch)} y1={pad.t} y2={pad.t + ih} stroke="var(--text-dim)" strokeWidth="1" />}
        {/* Titik: di epoch yang disorot, atau di ujung garis bila tidak ada sorotan. */}
        {series.map((s, i) => {
          const d = hd || data[data.length - 1];
          return d[s.key] == null ? null : (
            <circle key={s.key} cx={sx(d.epoch)} cy={sy(d[s.key])} r="4" fill={SERIES[i]} stroke="var(--bg-card)" strokeWidth="2" />
          );
        })}
      </svg>
      {hd && (
        <div className="chart-tip" style={{ left: Math.min(sx(hd.epoch) + 10, w - 150) }}>
          <b>Epoch {hd.epoch}</b>
          {series.map((s, i) => (
            <div key={s.key}><i style={{ background: SERIES[i] }} />{s.label}: {hd[s.key] == null ? "—" : fmt(hd[s.key])}</div>
          ))}
        </div>
      )}
    </div>
  );
}
