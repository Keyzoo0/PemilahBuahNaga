// CATATAN UNTUK PEMULA:
// Halaman Kalibrasi: tempat mengubah semua angka pengaturan (config.json)
// lewat browser, tanpa perlu mengedit file di Raspberry Pi.
//
// Konsep penting di halaman ini: "controlled input". Di React, isi kotak input
// TIDAK disimpan oleh kotak itu sendiri, melainkan oleh state. Alurnya:
//   pengguna mengetik -> onChange dipanggil -> state diperbarui ->
//   React menggambar ulang -> kotak input menampilkan nilai state yang baru.
// Karena itu setiap input di sini selalu punya pasangan value + onChange.
import React, { useEffect, useState } from "react";
import { getConfig, saveConfig, manualCmd, calibrateEmpty } from "../api.js";
import RoiEditor from "../components/RoiEditor.jsx";

// util set nilai nested immutable via path array
// "Immutable" artinya objek lama tidak diubah, melainkan dibuatkan salinan baru
// yang sudah dimodifikasi. Ini WAJIB di React: kalau objek lama diubah langsung,
// React menganggap tidak ada perubahan dan layar tidak ikut diperbarui.
//
// "path" adalah alamat bertingkat berupa daftar, contoh ["detect", "roi"]
// menunjuk ke cfg.detect.roi. Cara ini dipakai agar satu fungsi bisa mengubah
// bagian mana pun dari config, sedalam apa pun tingkatannya.
function setPath(obj, path, val) {
  // structuredClone membuat salinan menyeluruh (deep copy) — objek di dalam
  // objek pun ikut disalin, bukan sekadar ditunjuk ulang.
  const clone = structuredClone(obj);
  let node = clone;
  // Telusuri sampai SATU TINGKAT SEBELUM tujuan (perhatikan length - 1),
  // karena elemen terakhir dipakai untuk menulis nilainya di baris berikut.
  for (let i = 0; i < path.length - 1; i++) node = node[path[i]];
  node[path[path.length - 1]] = val;
  return clone;
}

// Mengambil nilai dari alamat bertingkat.
function getPath(obj, path) {
  // .reduce() menelusuri daftar sambil membawa hasil sementara (n).
  // Pemeriksaan (n == null ? n : n[k]) mencegah error kalau ada tingkat yang
  // belum terisi — penelusuran berhenti dan mengembalikan null/undefined.
  return path.reduce((n, k) => (n == null ? n : n[k]), obj);
}

export default function Settings({ status }) {
  const [cfg, setCfg] = useState(null);       // isi config; null = belum dimuat
  const [toast, setToast] = useState(null);   // pesan singkat hasil simpan
  const manual = status?.manual_mode;

  // Muat config dari server sekali saat halaman dibuka.
  useEffect(() => {
    getConfig().then(setCfg).catch(() => setToast({ t: "err", m: "Gagal memuat config" }));
  }, []);

  // "Early return": selama config belum datang, tampilkan tulisan memuat.
  // Ini melindungi seluruh kode di bawahnya yang mengandalkan cfg sudah ada
  // (misal cfg.camera.width akan error kalau cfg masih null).
  if (!cfg) return <div className="card">Memuat kalibrasi...</div>;

  // Jalan pintas untuk memperbarui satu nilai config.
  const upd = (path, val) => setCfg((c) => setPath(c, path, val));

  // "Pabrik komponen": fungsi yang MENGHASILKAN tampilan satu kotak input angka.
  // Dengan ini, puluhan kolom di bawah cukup ditulis satu baris masing-masing,
  // tidak perlu menyalin blok <div><label><input> berulang-ulang.
  const numField = (label, path, step = "any") => (
    <div className="field">
      <label>{label}</label>
      <input
        type="number"
        // step mengatur besar lompatan saat tombol panah atas/bawah ditekan.
        step={step}
        // ?? "" -> kalau nilainya kosong, tampilkan teks kosong (bukan
        // "undefined"), agar React tidak protes soal input tak terkendali.
        value={getPath(cfg, path) ?? ""}
        // Isi kotak input selalu berupa TEKS. Number() mengubahnya jadi angka,
        // kecuali saat kotaknya memang dikosongkan pengguna — kalau langsung
        // dipaksa Number(""), hasilnya 0 dan pengguna tidak bisa menghapus isi.
        onChange={(e) => upd(path, e.target.value === "" ? "" : Number(e.target.value))}
      />
    </div>
  );

  const save = async () => {
    // rapikan tipe angka pada beberapa field agar tetap number
    const res = await saveConfig(cfg);
    setToast(res.ok ? { t: "ok", m: res.message } : { t: "err", m: res.message || "Gagal" });
    // Hilangkan pesan otomatis setelah 4 detik.
    setTimeout(() => setToast(null), 4000);
  };

  const doCalibrateEmpty = async () => {
    const res = await calibrateEmpty();
    setToast(res.ok ? { t: "ok", m: res.message } : { t: "err", m: res.message });
    setTimeout(() => setToast(null), 4000);
  };

  // Ukuran asli frame kamera, dibutuhkan RoiEditor untuk mengubah posisi
  // seretan mouse menjadi koordinat piksel yang benar.
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
            // Saat pengguna selesai menyeret kotak, fungsi ini dipanggil
            // dengan koordinat barunya, lalu disimpan ke config.
            onChange={(v) => upd(["detect", "roi"], v)}
          />
        </div>
        <div className="card">
          <h3>ROI Paddle Kamera 2 — pemicu "tampol" per servo</h3>
          <RoiEditor
            label="Servo 1 (mentah): tampol saat buah masuk kotak ini"
            streamSrc="/video/cam2"
            frameW={frameW}
            frameH={frameH}
            // "|| cfg.sort_cam2.paddle_roi" adalah cadangan untuk config lama
            // yang dulu hanya punya satu ROI bersama, belum dipisah per servo.
            value={cfg.sort_cam2.paddle_roi_1 || cfg.sort_cam2.paddle_roi}
            onChange={(v) => upd(["sort_cam2", "paddle_roi_1"], v)}
          />
          {/* Div kosong ini hanya sebagai pemberi jarak antar editor. */}
          <div style={{ height: 12 }} />
          <RoiEditor
            label="Servo 2 (setengah matang): tampol saat buah masuk kotak ini"
            streamSrc="/video/cam2"
            frameW={frameW}
            frameH={frameH}
            value={cfg.sort_cam2.paddle_roi_2 || cfg.sort_cam2.paddle_roi}
            onChange={(v) => upd(["sort_cam2", "paddle_roi_2"], v)}
          />
          {/* Kurung kurawal { } menandai bahwa isinya adalah kode JavaScript.
              Fungsi numField dipanggil dan hasil tampilannya disisipkan di sini. */}
          {numField("Jeda titik buta — mundur dulu sebelum cek paddle (dtk)", ["sort_cam2", "blind_spot_seconds"], "0.1")}
          {numField("Sensitivitas SERVO 1 / mentah (rasio 0–1)", ["sort_cam2", "slap_area_ratio_1"], "0.01")}
          {numField("Sensitivitas SERVO 2 / setengah (rasio 0–1)", ["sort_cam2", "slap_area_ratio_2"], "0.01")}
          {numField("Frame berturut sebelum tampol", ["sort_cam2", "slap_frames"], "1")}
          {numField("Ambang beda piksel", ["sort_cam2", "slap_pixel_threshold"], "1")}
          <div className="roi-hint">
            Cara kerja simpel: begitu ADA PERUBAHAN WARNA di dalam kotak paddle (buah masuk),
            servo langsung menampol. Servo 1 (mentah) = kotak BAWAH, Servo 2 (setengah) = kotak ATAS.
            Lihat nilai "paddle" di tab Monitor saat kalibrasi.
          </div>
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
        <div className="subhead">Anti-tangan (gerbang settle) & deteksi reject</div>
        <div className="row4">
          {numField("Ambang gerakan (makin kecil makin sensitif)", ["detect", "settle_motion_threshold"], "0.5")}
          {numField("Settle frames (tunggu diam)", ["detect", "settle_frames"], "1")}
          {numField("Ambang piksel foreground", ["detect", "fg_pixel_threshold"], "1")}
          {numField("Rasio area objek reject (0–1)", ["detect", "fg_area_ratio"], "0.01")}
        </div>
        <div className="manual-grid" style={{ marginTop: 4 }}>
          <button className="btn sm primary" onClick={doCalibrateEmpty}>
            📷 Simpan Latar Belt Kosong
          </button>
          <span className="cam-meta" style={{ alignSelf: "center" }}>
            Kosongkan belt lalu klik — dipakai membedakan objek reject vs belt kosong.
          </span>
        </div>
      </div>

      {/* Timing */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Timing & Aktuator</h3>
        <div className="row4">
          {numField("Matang: delay mundur setelah keluar cam2 (dtk)", ["timing", "backward_extra_matang_seconds"], "0.1")}
          {numField("Servo open (°)", ["timing", "servo_open_angle"], "1")}
          {numField("Servo close (°)", ["timing", "servo_close_angle"], "1")}
          {numField("Servo slap hold (ms)", ["timing", "servo_slap_hold_ms"], "10")}
        </div>
        <div className="row4">
          {numField("Cooldown (dtk)", ["timing", "cooldown_seconds"], "0.1")}
          {numField("Max motor runtime (dtk)", ["timing", "max_motor_runtime_seconds"], "0.5")}
          {numField("Fault auto-reset (dtk)", ["timing", "fault_auto_reset_seconds"], "0.5")}
          {numField("Reject: durasi maju buang (dtk)", ["timing", "reject_forward_seconds"], "0.5")}
        </div>
      </div>

      {/* Mapping + serial + kamera */}
      <div className="grid cards3" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>Mapping Kelas → Aktuator</h3>
          {/* Daftar berisi pasangan [teks tampilan, kunci di config], lalu
              .map() mengubah tiap pasangan menjadi satu baris pilihan.
              Penulisan ([lbl, key]) langsung membongkar isi pasangan itu. */}
          {[
            ["mentah", "mentah"],
            ["setengah matang", "setengah matang"],
            ["matang", "matang"],
          ].map(([lbl, key]) => (
            // key={key} membantu React mengenali tiap baris dalam daftar.
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
            {/* Input teks biasa (bukan angka), karena bus_key berbentuk
                tulisan seperti "usb3-3-1". */}
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
          {/* Delapan tombol dibuat dari satu daftar, agar tidak perlu menulis
              blok <button> delapan kali. */}
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
            // disabled={!manual} mematikan tombol saat mode AUTO. Ini pengaman:
            // menggerakkan motor secara manual saat sortir sedang berjalan
            // bisa merusak proses (dan berbahaya).
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
        {/* Pesan hasil simpan hanya muncul kalau toast ada isinya.
            toast.t menentukan warnanya ("ok" hijau / "err" merah). */}
        {toast && <span className={"toast " + toast.t}>{toast.m}</span>}
        <span className="spacer" />
        <span className="cam-meta">Perubahan langsung aktif (hot-reload) tanpa restart.</span>
      </div>
    </>
  );
}
