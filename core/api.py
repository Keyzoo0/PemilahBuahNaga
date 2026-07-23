"""
FastAPI — monitoring + kalibrasi. Di-serve dari Pi (offline/LAN).
State machine tetap jalan lewat SortController walau API tak diakses.
"""
import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
WEB_DIST = BASE_DIR.parent / "web" / "dist"

app = FastAPI(title="PemilahBuahNaga Core")

# konteks di-inject oleh main.py
ctx = {"controller": None, "bridge": None, "config": None}


def mjpeg(key):
    controller = ctx["controller"]
    boundary = b"--frame\r\n"
    while True:
        jpg = controller.get_jpeg(key) if controller else None
        if jpg:
            yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
        time.sleep(0.06)


@app.get("/video/cam1")
def video_cam1():
    return StreamingResponse(mjpeg("cam1"), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/video/cam2")
def video_cam2():
    return StreamingResponse(mjpeg("cam2"), media_type="multipart/x-mixed-replace; boundary=frame")


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
    return {"models": ds.list_models()}


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
