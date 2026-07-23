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
