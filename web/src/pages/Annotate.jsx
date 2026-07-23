import React, { useEffect, useRef, useState } from "react";
import { dsList, dsGetLabel, dsSaveLabel } from "../api.js";

// warna per index kelas (0=matang, 1=mentah, 2=setengah matang)
const CLS_COLOR = ["#22c55e", "#ef4444", "#eab308"];

export default function Annotate({ initial }) {
  const [images, setImages] = useState([]);
  const [classes, setClasses] = useState([]);
  const [cur, setCur] = useState(initial || null);
  const [boxes, setBoxes] = useState([]);
  const [cls, setCls] = useState(0);
  const [drag, setDrag] = useState(null);
  const [toast, setToast] = useState(null);
  const wrapRef = useRef(null);

  const reload = () =>
    dsList().then((d) => {
      setImages(d.images || []);
      setClasses(d.classes || []);
      if (!cur && d.images?.length) setCur(d.images[0].name);
    });

  useEffect(() => {
    reload();
  }, []);
  useEffect(() => {
    if (cur) dsGetLabel(cur).then((d) => setBoxes(d.boxes || []));
  }, [cur]);

  const rel = (e) => {
    const r = wrapRef.current.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    };
  };

  const onDown = (e) => {
    const p = rel(e);
    setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };
  const onMove = (e) => {
    if (!drag) return;
    const p = rel(e);
    setDrag((d) => ({ ...d, x1: p.x, y1: p.y }));
  };
  const onUp = () => {
    if (!drag) return;
    const w = Math.abs(drag.x1 - drag.x0);
    const h = Math.abs(drag.y1 - drag.y0);
    const cx = (drag.x0 + drag.x1) / 2;
    const cy = (drag.y0 + drag.y1) / 2;
    setDrag(null);
    if (w > 0.02 && h > 0.02) setBoxes((b) => [...b, { cls, cx, cy, w, h }]);
  };

  const save = async () => {
    await dsSaveLabel(cur, boxes);
    setToast({ t: "ok", m: `Tersimpan ${boxes.length} kotak` });
    setTimeout(() => setToast(null), 2500);
    reload();
  };

  const nextUnlabeled = () => {
    const i = images.findIndex((x) => x.name === cur);
    const rest = [...images.slice(i + 1), ...images.slice(0, i)];
    const nxt = rest.find((x) => !x.labeled) || rest[0];
    if (nxt) setCur(nxt.name);
  };

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
    <div className="grid" style={{ gridTemplateColumns: "260px 1fr", gap: 16 }}>
      {/* daftar gambar */}
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
              background: cur === im.name ? "var(--pink-soft)" : "transparent",
              border: cur === im.name ? "1px solid var(--pink)" : "1px solid transparent",
              marginBottom: 4,
            }}
          >
            <img src={`/dsimg/${im.name}`} style={{ width: 44, height: 30, objectFit: "cover", borderRadius: 4 }} />
            <span style={{ fontSize: 11, flex: 1, color: "var(--text-dim)" }}>
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
          {classes.map((c, i) => (
            <button
              key={c}
              className={"btn sm" + (cls === i ? " primary" : "")}
              onClick={() => setCls(i)}
              style={cls === i ? {} : { borderColor: CLS_COLOR[i], color: CLS_COLOR[i] }}
            >
              [{i}] {c}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <button className="btn sm" onClick={() => setBoxes([])}>Hapus semua kotak</button>
          <button className="btn sm" onClick={() => setBoxes((b) => b.slice(0, -1))}>Undo</button>
          <button className="btn primary" onClick={save} disabled={!cur}>Simpan</button>
          <button className="btn sm" onClick={nextUnlabeled}>Berikutnya ▶</button>
        </div>

        {cur && (
          <div
            ref={wrapRef}
            className="roi-wrap"
            onMouseDown={onDown}
            onMouseMove={onMove}
            onMouseUp={onUp}
            onMouseLeave={onUp}
          >
            <img src={`/dsimg/${cur}`} alt={cur} draggable={false} />
            {shown.map((b, i) => (
              <div
                key={i}
                style={{
                  position: "absolute",
                  left: `${(b.cx - b.w / 2) * 100}%`,
                  top: `${(b.cy - b.h / 2) * 100}%`,
                  width: `${b.w * 100}%`,
                  height: `${b.h * 100}%`,
                  border: `2px solid ${CLS_COLOR[b.cls] || "#fff"}`,
                  background: `${CLS_COLOR[b.cls] || "#fff"}22`,
                }}
              >
                <span
                  style={{
                    position: "absolute",
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

        <div style={{ marginTop: 10 }}>
          {boxes.map((b, i) => (
            <span key={i} className="tag" style={{ marginRight: 6, color: CLS_COLOR[b.cls] }}>
              {classes[b.cls]}
              <button
                className="btn sm"
                style={{ marginLeft: 4, padding: "0 5px" }}
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
