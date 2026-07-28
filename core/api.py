"""
FastAPI — monitoring + kalibrasi. Di-serve dari Pi (offline/LAN).
State machine tetap jalan lewat SortController walau API tak diakses.
"""
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
WEB_DIST = BASE_DIR.parent / "web" / "dist"

app = FastAPI(title="PemilahBuahNaga Core")

# konteks di-inject oleh main.py
ctx = {"controller": None, "bridge": None, "config": None}


# =========================================================
# MJPEG STREAMING
#
# Versi lama: `def mjpeg(key)` — generator SYNC, `while True`, `time.sleep(0.06)`,
# tanpa cek client disconnect. Starlette menjalankan generator sync di threadpool
# AnyIO yang kapasitasnya cuma 40 thread. Tiap stream menahan satu slot dan tidak
# pernah melepasnya, jadi tiap refresh browser menambah 2 slot (cam1+cam2) sampai
# habis — lalu SEMUA endpoint sync (/api/status, /api/history, file statis) ikut
# macet. Itu penyebab "web lag lalu tidak bisa dibuka".
#
# Versi ini async: jalan di event loop, nol pemakaian threadpool, dan berhenti
# sendiri saat klien pergi.
# =========================================================

# Batas stream serentak sebagai jaring pengaman terakhir.
MAX_STREAMS = 6
_active_streams = 0


async def mjpeg(key, request: Request):
    global _active_streams
    _active_streams += 1
    controller = ctx["controller"]
    boundary = b"--frame\r\n"
    last = None  # referensi frame terakhir; ditahan supaya perbandingan `is` sah
    try:
        while True:
            # klien menutup tab / pindah halaman -> hentikan stream
            if await request.is_disconnected():
                break

            jpg = controller.get_jpeg(key) if controller else None
            # Kirim hanya kalau frame benar-benar baru. State machine membuat
            # objek bytes baru tiap encode, jadi identitas objek = frame baru.
            # Ini mencegah socket dibanjiri frame duplikat saat kamera lambat.
            if jpg is not None and jpg is not last:
                last = jpg
                yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"

            await asyncio.sleep(0.06)
    finally:
        # jalan juga saat generator dibatalkan (disconnect/shutdown)
        _active_streams -= 1


def _stream(key, request):
    if _active_streams >= MAX_STREAMS:
        return JSONResponse(
            {"ok": False, "message": f"Stream aktif sudah {MAX_STREAMS}. Tutup tab lain lalu coba lagi."},
            status_code=503,
        )
    return StreamingResponse(
        mjpeg(key, request), media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/video/cam1")
async def video_cam1(request: Request):
    return _stream("cam1", request)


@app.get("/video/cam2")
async def video_cam2(request: Request):
    return _stream("cam2", request)


@app.get("/api/streams")
async def api_streams():
    """Diagnostik: berapa stream MJPEG yang sedang aktif."""
    return {"active": _active_streams, "max": MAX_STREAMS}


@app.get("/api/status")
def api_status():
    return ctx["controller"].status()


@app.get("/api/classes")
def api_classes():
    """Peta index kelas model: {0: 'matang', 1: 'mentah', 2: 'setengah matang'}."""
    det = ctx.get("detector")
    return {"classes": getattr(det, "class_names", {}) if det else {}}


@app.get("/api/config")
def api_get_config():
    return ctx["config"].all()


@app.post("/api/config")
async def api_set_config(request: Request):
    data = await request.json()
    ctx["config"].save(data)
    return {"ok": True, "message": "Config tersimpan & aktif (hot-reload)"}


@app.post("/api/estop")
def api_estop():
    ctx["controller"].trigger_estop()
    return {"ok": True}


@app.post("/api/estop/clear")
def api_estop_clear():
    ctx["controller"].clear_estop()
    return {"ok": True}


@app.post("/api/calibrate/empty")
def api_calibrate_empty():
    """Simpan snapshot belt kosong sebagai latar untuk deteksi objek reject."""
    ok = ctx["controller"].save_empty_reference()
    return {"ok": ok, "message": "Latar kosong tersimpan" if ok else "Gagal: frame kamera 1 belum tersedia"}


@app.post("/api/mode")
async def api_mode(request: Request):
    data = await request.json()
    ctx["controller"].set_manual(data.get("manual", False))
    return {"ok": True, "manual_mode": ctx["controller"].manual_mode}


@app.post("/api/manual")
async def api_manual(request: Request):
    """Kirim command serial mentah (hanya saat manual mode) untuk kalibrasi."""
    if not ctx["controller"].manual_mode:
        return JSONResponse({"ok": False, "message": "Aktifkan manual mode dulu"}, status_code=400)
    data = await request.json()
    cmd = (data.get("cmd") or "").strip()
    if not cmd:
        return JSONResponse({"ok": False, "message": "cmd kosong"}, status_code=400)
    ok = ctx["bridge"].send(cmd)
    return {"ok": ok, "sent": cmd, "reply": ctx["bridge"].last_line}


@app.get("/api/history")
def api_history(limit: int = 100):
    from store import store
    return {"rows": store.recent(limit)}


@app.delete("/api/history/{row_id}")
def api_history_delete(row_id: int):
    from store import store
    store.delete(row_id)
    return {"ok": True}


@app.delete("/api/history")
def api_history_clear():
    from store import store
    return {"ok": True, "deleted": store.clear_all()}


# =========================================================
# DATASET / ANOTASI / TRAINING
# =========================================================
@app.get("/api/dataset/list")
def api_ds_list():
    import dataset as ds
    return {"images": ds.list_images(), "stats": ds.stats(), "classes": ds.CLASSES}


@app.post("/api/dataset/capture")
def api_ds_capture():
    import dataset as ds
    frame = ctx["controller"].cams.cam1.read()
    name = ds.capture(frame)
    if not name:
        return JSONResponse({"ok": False, "message": "Frame kamera 1 belum tersedia"}, status_code=400)
    return {"ok": True, "name": name}


@app.delete("/api/dataset/image/{name}")
def api_ds_delete(name: str):
    import dataset as ds
    ds.delete_image(name)
    return {"ok": True}


@app.get("/api/dataset/label/{name}")
def api_ds_get_label(name: str):
    import dataset as ds
    return {"boxes": ds.get_label(name)}


@app.post("/api/dataset/label/{name}")
async def api_ds_save_label(name: str, request: Request):
    import dataset as ds
    data = await request.json()
    n = ds.save_label(name, data.get("boxes", []))
    return {"ok": True, "saved": n}


@app.post("/api/train/start")
async def api_train_start(request: Request):
    import dataset as ds
    body = await request.json() if await request.body() else {}
    # sorting dialihkan ke MANUAL supaya CPU tidak berebut dengan training
    ctx["controller"].set_manual(True)
    ok, msg = ds.trainer.start(
        epochs=int(body.get("epochs", 40)),
        imgsz=int(body.get("imgsz", 416)),
        batch=int(body.get("batch", 8)),
        freeze=int(body.get("freeze", 10)),
    )
    if not ok:
        ctx["controller"].set_manual(False)
        return JSONResponse({"ok": False, "message": msg}, status_code=400)
    return {"ok": True, "run": msg}


@app.get("/api/train/status")
def api_train_status():
    import dataset as ds
    return ds.trainer.status()


@app.post("/api/train/stop")
def api_train_stop():
    import dataset as ds
    return {"ok": ds.trainer.stop()}


@app.get("/api/models")
def api_models():
    import dataset as ds
    return {"models": ds.list_models(), "active_kind": ds.active_model_kind()}


@app.post("/api/model/export")
async def api_model_export(request: Request):
    """Konversi best.pt -> ONNX/NCNN agar inferensi lebih ringan di Pi."""
    import dataset as ds
    body = await request.json() if await request.body() else {}
    ctx["controller"].set_manual(True)  # bebaskan CPU selama export
    ok, msg = ds.export_model_async(fmt=body.get("format", "onnx"),
                                    imgsz=int(body.get("imgsz", 480)))
    if not ok:
        return JSONResponse({"ok": False, "message": msg}, status_code=400)
    return {"ok": True, "format": msg}


@app.get("/api/model/export/status")
def api_model_export_status():
    import dataset as ds
    return ds.export_state


@app.post("/api/models/activate")
async def api_models_activate(request: Request):
    import dataset as ds
    data = await request.json()
    ok, msg = ds.activate_model(data.get("path", ""))
    return {"ok": ok, "message": msg + (" — restart service untuk memuat model baru." if ok else "")}


@app.websocket("/ws")
async def ws(websocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(ctx["controller"].status())
            await asyncio.sleep(0.5)
    except Exception:
        pass


# static uploads (snapshot)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# gambar dataset (untuk galeri & anotasi)
(BASE_DIR / "dataset" / "images").mkdir(parents=True, exist_ok=True)
app.mount("/dsimg", StaticFiles(directory=str(BASE_DIR / "dataset" / "images")), name="dsimg")

# web build (Vite) kalau sudah ada; kalau belum, tampilkan info
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
else:
    @app.get("/")
    def root():
        return JSONResponse({
            "app": "PemilahBuahNaga Core",
            "status": "running (headless)",
            "note": "Web UI belum di-build. Endpoint aktif: /api/status, /video/cam1, /video/cam2, /ws",
        })
