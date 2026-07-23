import React, { useEffect, useState } from "react";
import { getConfig, saveConfig, manualCmd } from "../api.js";
import RoiEditor from "../components/RoiEditor.jsx";

// util set nilai nested immutable via path array
function setPath(obj, path, val) {
  const clone = structuredClone(obj);
  let node = clone;
  for (let i = 0; i < path.length - 1; i++) node = node[path[i]];
  node[path[path.length - 1]] = val;
  return clone;
}
function getPath(obj, path) {
  return path.reduce((n, k) => (n == null ? n : n[k]), obj);
}

export default function Settings({ status }) {
  const [cfg, setCfg] = useState(null);
  const [toast, setToast] = useState(null);
  const manual = status?.manual_mode;

  useEffect(() => {
    getConfig().then(setCfg).catch(() => setToast({ t: "err", m: "Gagal memuat config" }));
  }, []);

  if (!cfg) return <div className="card">Memuat kalibrasi...</div>;

  const upd = (path, val) => setCfg((c) => setPath(c, path, val));
  const numField = (label, path, step = "any") => (
    <div className="field">
      <label>{label}</label>
      <input
        type="number"
        step={step}
        value={getPath(cfg, path) ?? ""}
        onChange={(e) => upd(path, e.target.value === "" ? "" : Number(e.target.value))}
      />
    </div>
  );

  const save = async () => {
    // rapikan tipe angka pada beberapa field agar tetap number
    const res = await saveConfig(cfg);
    setToast(res.ok ? { t: "ok", m: res.message } : { t: "err", m: res.message || "Gagal" });
    setTimeout(() => setToast(null), 4000);
  };

  const frameW = cfg.camera.width;
  const frameH = cfg.camera.height;

  return (
    <>
      {/* ROI editors */}
      <div className="grid cards2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>ROI Deteksi — Kamera 1 (area hitam)</h3>
          <RoiEditor
            label="Hanya buah di dalam kotak yang dihitung"
            streamSrc="/video/cam1"
            frameW={frameW}
            frameH={frameH}
            value={cfg.detect.roi}
            onChange={(v) => upd(["detect", "roi"], v)}
          />
        </div>
        <div className="card">
          <h3>ROI Paddle — Kamera 2 (pemicu tampol)</h3>
          <RoiEditor
            label="Servo snap ke 0° saat buah masuk kotak & cukup ke kiri"
            streamSrc="/video/cam2"
            frameW={frameW}
            frameH={frameH}
            value={cfg.sort_cam2.paddle_roi}
            onChange={(v) => upd(["sort_cam2", "paddle_roi"], v)}
          />
          {numField("Ambang 'agak ke kiri' (slap_x_ratio 0–1)", ["sort_cam2", "slap_x_ratio"], "0.01")}
        </div>
      </div>

      {/* Deteksi */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Parameter Deteksi</h3>
        <div className="row4">
          {numField("imgsz (kecepatan↔akurasi)", ["detect", "imgsz"], "32")}
          {numField("Confidence threshold", ["detect", "conf_threshold"], "0.01")}
          {numField("Min box area (px²)", ["detect", "min_box_area"], "100")}
          {numField("Min box area cam2", ["sort_cam2", "min_box_area"], "100")}
        </div>
        <div className="row4">
          {numField("Presence frames (konfirmasi ada)", ["detect", "presence_frames"], "1")}
          {numField("Exit frames (konfirmasi keluar)", ["detect", "exit_frames"], "1")}
        </div>
      </div>

      {/* Timing */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Timing & Aktuator</h3>
        <div className="row4">
          {numField("Forward setelah keluar (dtk)", ["timing", "forward_extra_seconds"], "0.1")}
          {numField("Backward matang (dtk)", ["timing", "backward_extra_matang_seconds"], "0.1")}
          {numField("Servo open (°)", ["timing", "servo_open_angle"], "1")}
          {numField("Servo close (°)", ["timing", "servo_close_angle"], "1")}
        </div>
        <div className="row4">
          {numField("Servo slap hold (ms)", ["timing", "servo_slap_hold_ms"], "10")}
          {numField("Cooldown (dtk)", ["timing", "cooldown_seconds"], "0.1")}
          {numField("Max motor runtime (dtk)", ["timing", "max_motor_runtime_seconds"], "0.5")}
          {numField("Fault auto-reset (dtk)", ["timing", "fault_auto_reset_seconds"], "0.5")}
        </div>
      </div>

      {/* Mapping + serial + kamera */}
      <div className="grid cards3" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>Mapping Kelas → Aktuator</h3>
          {[
            ["mentah", "mentah"],
            ["setengah matang", "setengah matang"],
            ["matang", "matang"],
          ].map(([lbl, key]) => (
            <div className="field" key={key}>
              <label>{lbl}</label>
              <select value={cfg.mapping[key]} onChange={(e) => upd(["mapping", key], e.target.value)}>
                <option value="servo1">Servo 1 (dekat)</option>
                <option value="servo2">Servo 2</option>
                <option value="straight">Lurus (tanpa servo)</option>
              </select>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Kamera</h3>
          <div className="field">
            <label>Cam1 bus_key (deteksi)</label>
            <input value={cfg.camera.cam1_bus_key} onChange={(e) => upd(["camera", "cam1_bus_key"], e.target.value)} />
          </div>
          <div className="field">
            <label>Cam2 bus_key (sorting)</label>
            <input value={cfg.camera.cam2_bus_key} onChange={(e) => upd(["camera", "cam2_bus_key"], e.target.value)} />
          </div>
          <div className="row3">
            {numField("Width", ["camera", "width"], "1")}
            {numField("Height", ["camera", "height"], "1")}
            {numField("FPS", ["camera", "fps"], "1")}
          </div>
        </div>

        <div className="card">
          <h3>Serial Arduino</h3>
          <div className="field">
            <label>Port</label>
            <input value={cfg.serial.port} onChange={(e) => upd(["serial", "port"], e.target.value)} />
          </div>
          <div className="row3">
            {numField("Baud", ["serial", "baud"], "1")}
            {numField("Heartbeat (dtk)", ["serial", "heartbeat_seconds"], "0.5")}
          </div>
        </div>
      </div>

      {/* Manual control */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Kontrol Manual {manual ? "" : "(aktifkan Mode: MANUAL di atas dulu)"}</h3>
        <div className="manual-grid">
          {[
            ["Motor Forward", "motor forward"],
            ["Motor Backward", "motor backward"],
            ["Motor Stop", "motor stop"],
            ["Servo1 Open", "s1 open"],
            ["Servo1 Close", "s1 close"],
            ["Servo2 Open", "s2 open"],
            ["Servo2 Close", "s2 close"],
            ["Buzzer beep", "beep 2"],
          ].map(([lbl, cmd]) => (
            <button key={cmd} className="btn sm" disabled={!manual} onClick={() => manualCmd(cmd)}>
              {lbl}
            </button>
          ))}
        </div>
      </div>

      <div className="savebar">
        <button className="btn primary" onClick={save}>
          Simpan Kalibrasi
        </button>
        {toast && <span className={"toast " + toast.t}>{toast.m}</span>}
        <span className="spacer" />
        <span className="cam-meta">Perubahan langsung aktif (hot-reload) tanpa restart.</span>
      </div>
    </>
  );
}
