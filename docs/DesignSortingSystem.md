# PemilahBuahNaga — Rancangan Sistem Sortasi Otomatis (YOLOv8, Offline-First)

Dokumen acuan implementasi. Versi 1 — 23 Juli 2026.

---

## 1. Prinsip Utama

- **Semua diproses di Raspberry Pi 5** (mandiri). Tidak butuh laptop, tidak butuh internet.
- **Core = service headless (systemd)** yang selalu menyala saat boot. Sorting berjalan **walau web tidak dibuka**.
- **Web (Vite + React)** hanya untuk **monitoring + kalibrasi**. Boleh mati/ditutup tanpa mengganggu sorting.
- **Aktuator (motor, servo, LED, buzzer) digerakkan lewat Arduino Nano via serial** (`/dev/ttyUSB0`, 115200), memakai firmware `main.ino` yang sudah ada.

## 2. Peran Perangkat

| Perangkat | Peran |
|---|---|
| **Kamera 1 (top / area hitam)** | Deteksi keberadaan objek + **klasifikasi kematangan** (YOLOv8) |
| **Kamera 2 (sorting)** | **Tracking gerakan** buah saat fase sorting (bukan klasifikasi) |
| **Arduino Nano** | Eksekusi command motor L298N, Servo1, Servo2, LED, Buzzer |
| **Raspberry Pi 5** | YOLO inference, state machine, serial bridge, web server, SQLite |

## 3. Model YOLOv8 (`best.pt`)

Kelas (terkonfirmasi dari model):

| Index | Label | Aksi sorting |
|---|---|---|
| 0 | `matang` | **Lurus keluar** (tidak ada servo) |
| 1 | `mentah` | **Servo1** (paling dekat) |
| 2 | `setengah matang` | **Servo2** |

## 4. State Machine Sorting

```
IDLE
  └─(cam1: dragonfruit di ROI hitam selama `presence_frames`)─► CLASSIFY

CLASSIFY
  ├─ kunci ripeness = voting conf tertinggi selama window presence
  └─► motor FORWARD ─► FORWARD_CLEAR

FORWARD_CLEAR
  └─(cam1 kosong selama `exit_frames` = buah keluar frame)─► FORWARD_EXTRA

FORWARD_EXTRA
  └─(forward `forward_extra_seconds` = 2 dtk)─► DISPATCH

DISPATCH (berdasarkan ripeness)
  ├─ matang           ─► STRAIGHT_OUT
  ├─ mentah           ─► SERVO_SORT (servo1)
  └─ setengah matang  ─► SERVO_SORT (servo2)

STRAIGHT_OUT
  ├─ motor BACKWARD
  ├─(cam2 kosong = buah keluar)─► BACKWARD `backward_extra_matang_seconds` (5 dtk)
  └─► motor STOP ─► COOLDOWN

SERVO_SORT (servoN)
  ├─ servoN.open(`servo_open_angle` = 51°)
  ├─ motor BACKWARD
  ├─ cam2 track bbox buah
  ├─(bbox capai ROI paddle DAN cx < `slap_x_ratio` = "agak ke kiri")
  │      ─► servoN.write(0°)  // TAMPOL/tampar buah keluar belt
  ├─ hold `servo_slap_hold_ms`
  └─► motor STOP ─► COOLDOWN

COOLDOWN
  ├─ servo1 & servo2 home (0°), buzzer beep pendek
  ├─ jeda `cooldown_seconds`
  └─► IDLE
```

### Failsafe (WAJIB, tidak ada di kode lama)
- **Watchdog motor**: jika buah tak pernah "keluar frame" (YOLO meleset), motor tidak boleh nyala melebihi `max_motor_runtime_seconds` → STOP + alarm buzzer + kembali IDLE.
- **Serial auto-reconnect**: jika `/dev/ttyUSB0` putus, coba sambung ulang; selama putus → jangan mulai siklus baru.
- **Kamera hilang**: jika cam1/cam2 gagal baca N detik → STOP motor + status error di web.
- **Heartbeat firmware** (opsional di `main.ino`): jika tak ada command > X dtk, Arduino auto-stop motor.

## 5. Parameter Kalibrasi (`config.json`)

Diedit dari web, hot-reload tanpa restart core.

```jsonc
{
  "camera": {
    "cam1_bus_key": "usb1-1-1",      // deteksi  (by USB bus/port, anti-tertukar)
    "cam2_bus_key": "usb3-3-1",      // sorting
    "width": 1280, "height": 720, "fps": 30, "fourcc": "MJPG"
  },
  "detect": {
    "roi": { "x": 300, "y": 40, "w": 640, "h": 640 },  // area hitam cam1
    "conf_threshold": 0.50,
    "conf_per_class": { "matang": 0.50, "mentah": 0.50, "setengah matang": 0.50 },
    "min_box_area": 4000,
    "presence_frames": 5,
    "exit_frames": 6
  },
  "timing": {
    "forward_extra_seconds": 2.0,
    "backward_extra_matang_seconds": 5.0,
    "servo_open_angle": 51,
    "servo_close_angle": 0,
    "servo_slap_hold_ms": 500,
    "cooldown_seconds": 3.0,
    "max_motor_runtime_seconds": 15.0
  },
  "mapping": {
    "mentah": "servo1",
    "setengah matang": "servo2",
    "matang": "straight"
  },
  "sort_cam2": {
    "paddle_roi": { "x": 0, "y": 200, "w": 400, "h": 320 },
    "slap_x_ratio": 0.45,            // ambang "posisi agak ke kiri"
    "min_box_area": 4000
  },
  "serial": {
    "port": "/dev/ttyUSB0", "baud": 115200,
    "auto_reconnect": true,
    "motor_forward_is_reversed": false   // kalau wiring kebalik, set true
  },
  "feedback": {
    "led_per_class": { "matang": "green", "setengah matang": "yellow", "mentah": "red" },
    "buzzer_on_sort": true
  }
}
```

## 6. Struktur Folder Target

```
PemilahBuahNaga/
├─ ArduinoNanoFirmware/main/main.ino     # (+ heartbeat failsafe)
├─ core/                                  # service Python di Pi (systemd)
│  ├─ main.py            # bootstrap: kamera, yolo, state machine, serial, api
│  ├─ config.py          # load/save/watch config.json
│  ├─ config.json
│  ├─ camera.py          # CameraManager (pakai bus_key, thread capture)
│  ├─ detector.py        # wrapper YOLOv8 (ultralytics / NCNN)
│  ├─ state_machine.py   # logika sorting (§4)
│  ├─ serial_bridge.py   # pyserial → Arduino, auto-reconnect, heartbeat
│  ├─ api.py             # FastAPI: WS status, MJPEG, GET/POST /config, E-STOP
│  ├─ store.py           # SQLite riwayat
│  └─ pemilah-core.service
├─ web/                                   # Vite + React (build → statik)
│  ├─ src/pages/Monitor.tsx  Settings.tsx
│  └─ dist/              # di-serve FastAPI (offline)
└─ docs/
```

## 7. Protokol Serial (dari `main.ino` yang sudah ada)

| Command | Fungsi |
|---|---|
| `motor forward` / `motor backward` / `motor stop` | Konveyor L298N |
| `s1 open` / `s1 close` | Servo1 → 51° / 0° |
| `s2 open` / `s2 close` | Servo2 → 51° / 0° |
| `servo 1 <0-180>` / `servo 2 <0-180>` | Servo sudut bebas |
| `led green\|yellow\|red 0\|1` | LED indikator |
| `buzzer on` / `buzzer off` | Buzzer |

## 8. Performa Inference di Pi 5

- YOLOv8n imgsz 480–512 → target 10–20 FPS di Cortex-A76 4-core.
- Jika kurang cepat: ekspor ke **NCNN** (`yolo export format=ncnn`) atau ONNX; jalankan cam2-tracking dengan tracker ringan saat fase sorting agar hemat.

## 9. Yang Dipakai Ulang dari Kode Lama

- `camera_identifier.py` → dasar `camera.py` (identifikasi by USB bus-key).
- `main.ino` → firmware serial (tambah failsafe).
- Skema SQLite `detections` di `app.py` → dasar `store.py`.
- `main.py` (PyQt) → referensi command serial.

---

*Keputusan terkunci: mentah→Servo1, setengah→Servo2, matang→lurus • semua di Pi 5 • sorting = backward ke arah servo/cam2.*
