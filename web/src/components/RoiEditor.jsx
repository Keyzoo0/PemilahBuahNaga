import React, { useRef, useState } from "react";

// Editor ROI: seret kotak di atas stream langsung. Koordinat disimpan
// dalam ruang frame (frameW x frameH) sesuai config kamera.
export default function RoiEditor({ label, streamSrc, frameW, frameH, value, onChange }) {
  const wrapRef = useRef(null);
  const [drag, setDrag] = useState(null);

  const toFrame = (e) => {
    const r = wrapRef.current.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    return {
      x: Math.max(0, Math.min(1, px)) * frameW,
      y: Math.max(0, Math.min(1, py)) * frameH,
    };
  };

  const onDown = (e) => {
    const p = toFrame(e);
    setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };
  const onMove = (e) => {
    if (!drag) return;
    const p = toFrame(e);
    setDrag((d) => ({ ...d, x1: p.x, y1: p.y }));
  };
  const onUp = () => {
    if (!drag) return;
    const x = Math.round(Math.min(drag.x0, drag.x1));
    const y = Math.round(Math.min(drag.y0, drag.y1));
    const w = Math.round(Math.abs(drag.x1 - drag.x0));
    const h = Math.round(Math.abs(drag.y1 - drag.y0));
    setDrag(null);
    if (w > 10 && h > 10) onChange({ x, y, w, h });
  };

  // rect yang ditampilkan (dari drag aktif atau value tersimpan)
  const shown = drag
    ? {
        x: Math.min(drag.x0, drag.x1),
        y: Math.min(drag.y0, drag.y1),
        w: Math.abs(drag.x1 - drag.x0),
        h: Math.abs(drag.y1 - drag.y0),
      }
    : value;

  const style = shown
    ? {
        left: `${(shown.x / frameW) * 100}%`,
        top: `${(shown.y / frameH) * 100}%`,
        width: `${(shown.w / frameW) * 100}%`,
        height: `${(shown.h / frameH) * 100}%`,
      }
    : null;

  return (
    <div>
      <div className="subhead">{label}</div>
      <div
        className="roi-wrap"
        ref={wrapRef}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onMouseLeave={onUp}
      >
        <img src={streamSrc} alt={label} draggable={false} />
        {style && <div className="roi-rect" style={style} />}
      </div>
      <div className="roi-hint">
        Seret kotak di atas gambar untuk menetapkan area. Nilai: x={value?.x} y={value?.y} w={value?.w} h={value?.h}
      </div>
    </div>
  );
}
