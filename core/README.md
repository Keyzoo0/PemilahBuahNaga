# PemilahBuahNaga — Core Service

Otak sistem sortasi (offline-first). YOLO + state machine + serial Arduino + web API,
semua jalan di Raspberry Pi 5 sebagai systemd service. Web hanya untuk monitoring & kalibrasi.

## Struktur
| File | Fungsi |
|---|---|
| `main.py` | Bootstrap: rangkai semua komponen + jalankan web (port 8000) |
| `config.py` / `config.json` | Parameter kalibrasi, hot-reload dari web |
| `camera.py` | 2 kamera USB by USB bus-key (anti-tertukar) |
| `detector.py` | Wrapper YOLOv8 (`best.pt`, auto-NCNN bila ada) |
| `state_machine.py` | Logika sorting (IDLE→klasifikasi→forward→servo/lurus) |
| `serial_bridge.py` | Serial Arduino: auto-reconnect + heartbeat (`ping`,`watchdog on`) |
| `store.py` | SQLite riwayat sortasi |
| `api.py` | FastAPI: stream MJPEG, WebSocket status, GET/POST config, E-STOP |

## Jalankan manual (test)
```bash
cd ~/PemilahBuahNaga/core
./run.sh
# buka http://<ip-pi>:8000/api/status
```

## Pasang sebagai service (auto-start saat boot)
```bash
sudo cp pemilah-core.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pemilah-core
sudo systemctl status pemilah-core
journalctl -u pemilah-core -f      # lihat log
```

## Endpoint
- `GET  /api/status` — status realtime (state, kematangan, fps, koneksi)
- `GET  /video/cam1` `/video/cam2` — stream MJPEG teranotasi
- `WS   /ws` — push status tiap 0.5s
- `GET/POST /api/config` — baca/tulis kalibrasi (hot-reload)
- `POST /api/estop` `/api/estop/clear` — darurat
- `POST /api/mode` `{ "manual": true }` — mode manual (pause otomatis)
- `POST /api/manual` `{ "cmd": "s1 open" }` — kirim serial mentah (mode manual)
- `GET  /api/history?limit=100` — riwayat

## Percepat inference (opsional)
```bash
../.venv/bin/yolo export model=best.pt format=ncnn
# hasil best_ncnn_model/ otomatis dipakai detector.py
```
