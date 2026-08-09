"""
FastAPI — monitoring + kalibrasi. Di-serve dari Pi (offline/LAN).
State machine tetap jalan lewat SortController walau API tak diakses.

CATATAN UNTUK PEMULA:
File ini adalah "pelayan" (server) yang melayani permintaan dari browser.

Cara kerja web secara sederhana:
  1. Browser mengirim permintaan ke alamat tertentu, contoh /api/status.
  2. Server (file ini) menerima, mengerjakan sesuatu, lalu membalas datanya.
Alamat-alamat itu disebut "endpoint" atau "route".

Istilah:
- FastAPI  : pustaka Python untuk membuat server web dengan cepat.
- endpoint : satu alamat yang bisa diakses, contoh /api/config.
- GET      : jenis permintaan untuk MENGAMBIL data (membaca).
- POST     : jenis permintaan untuk MENGIRIM data (menambah/mengubah).
- DELETE   : jenis permintaan untuk MENGHAPUS data.
- JSON     : format teks untuk bertukar data, mirip dictionary Python.
- async    : cara menulis kode yang bisa "menunggu tanpa memblokir" pekerjaan
             lain — penting agar server tetap gesit melayani banyak pengunjung.
"""
import asyncio                 # pustaka untuk pemrograman async (menunggu tanpa memblokir)
from pathlib import Path       # penulisan alamat file yang aman

from fastapi import FastAPI, Request                          # inti FastAPI
from fastapi.responses import StreamingResponse, JSONResponse  # jenis-jenis balasan
from fastapi.staticfiles import StaticFiles                    # untuk menyajikan file statis (html/js/gambar)

BASE_DIR = Path(__file__).resolve().parent          # folder core/
WEB_DIST = BASE_DIR.parent / "web" / "dist"         # folder hasil build React (web/dist)

# Membuat objek aplikasi web. Semua endpoint di bawah didaftarkan ke objek ini.
app = FastAPI(title="PemilahBuahNaga Core")

# konteks di-inject oleh main.py
# ctx = "papan pengumuman" berisi objek-objek penting. Nilainya masih None di
# sini, lalu diisi oleh main.py saat sistem dinyalakan. Pola ini disebut
# "dependency injection": komponen tidak membuat sendiri kebutuhannya,
# melainkan diberi dari luar.
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
#
# UNTUK PEMULA: MJPEG adalah cara paling sederhana menampilkan "video" di web —
# sebenarnya bukan video, melainkan rentetan foto JPEG yang dikirim beruntun
# dengan sangat cepat sehingga mata melihatnya seperti video.
# =========================================================

# Batas stream serentak sebagai jaring pengaman terakhir.
MAX_STREAMS = 6
_active_streams = 0     # penghitung stream yang sedang berjalan sekarang


# "async def" = fungsi asinkron; di dalamnya boleh memakai kata kunci "await".
# Fungsi ini juga sebuah "generator" karena memakai "yield": ia mengirim data
# sepotong demi sepotong, tidak sekaligus di akhir.
async def mjpeg(key, request: Request):
    # "global" artinya kita ingin MENGUBAH variabel yang ada di luar fungsi.
    # Tanpa kata ini, Python akan menganggap _active_streams sebagai variabel
    # baru milik fungsi ini saja, dan penghitungnya tidak akan pernah bertambah.
    global _active_streams
    _active_streams += 1
    controller = ctx["controller"]
    # Huruf b di depan tanda kutip berarti "bytes" (data mentah), bukan teks.
    # Protokol MJPEG memakai penanda batas antar-gambar seperti ini.
    # \r\n adalah kode ganti baris standar protokol internet.
    boundary = b"--frame\r\n"
    last = None  # referensi frame terakhir; ditahan supaya perbandingan `is` sah
    try:
        # "while True" = ulangi selamanya, sampai ada perintah break.
        while True:
            # klien menutup tab / pindah halaman -> hentikan stream
            # "await" artinya: tunggu hasilnya, tapi sementara menunggu,
            # persilakan server mengerjakan permintaan lain dulu.
            if await request.is_disconnected():
                break

            jpg = controller.get_jpeg(key) if controller else None
            # Kirim hanya kalau frame benar-benar baru. State machine membuat
            # objek bytes baru tiap encode, jadi identitas objek = frame baru.
            # Ini mencegah socket dibanjiri frame duplikat saat kamera lambat.
            # Catatan: "is not" membandingkan APAKAH OBJEKNYA SAMA di memori,
            # berbeda dengan "!=" yang membandingkan isinya. Di sini kita memang
            # sengaja memakai "is" karena isi dua foto bisa mirip, tapi objek
            # baru pasti berarti hasil encode yang baru.
            if jpg is not None and jpg is not last:
                last = jpg
                # yield = kirim potongan data ini ke browser SEKARANG, lalu
                # lanjutkan fungsi dari titik ini pada putaran berikutnya.
                yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"

            # Jeda 0,06 detik ≈ maksimal 16 gambar per detik. Cukup halus untuk
            # dipantau mata, dan tidak membebani jaringan maupun CPU.
            await asyncio.sleep(0.06)
    finally:
        # jalan juga saat generator dibatalkan (disconnect/shutdown)
        # Ini WAJIB ada: kalau penghitung tidak pernah dikurangi, lama-lama
        # sistem mengira batas MAX_STREAMS sudah penuh padahal sudah kosong.
        _active_streams -= 1


def _stream(key, request):
    """Membungkus generator mjpeg menjadi balasan HTTP yang benar."""
    # Jaring pengaman: tolak permintaan baru kalau sudah terlalu banyak stream.
    if _active_streams >= MAX_STREAMS:
        # status_code 503 = "Service Unavailable" (layanan sedang penuh).
        return JSONResponse(
            {"ok": False, "message": f"Stream aktif sudah {MAX_STREAMS}. Tutup tab lain lalu coba lagi."},
            status_code=503,
        )
    # media_type ini yang memberi tahu browser: "ini rentetan gambar, terus
    # ganti gambar lama dengan yang baru" — sehingga tampil seperti video.
    return StreamingResponse(
        mjpeg(key, request), media_type="multipart/x-mixed-replace; boundary=frame"
    )


# @app.get("/alamat") adalah dekorator yang mendaftarkan fungsi di bawahnya
# sebagai penangan permintaan GET ke alamat tersebut.
@app.get("/video/cam1")
async def video_cam1(request: Request):
    """Siaran langsung kamera 1 (kamera deteksi)."""
    return _stream("cam1", request)


@app.get("/video/cam2")
async def video_cam2(request: Request):
    """Siaran langsung kamera 2 (kamera pelacak saat sorting)."""
    return _stream("cam2", request)


@app.get("/api/streams")
async def api_streams():
    """Diagnostik: berapa stream MJPEG yang sedang aktif."""
    # Dictionary yang dikembalikan otomatis diubah FastAPI menjadi JSON.
    return {"active": _active_streams, "max": MAX_STREAMS}


@app.get("/api/status")
def api_status():
    """Kondisi terkini sistem: state, hitungan hari ini, status kamera & serial."""
    return ctx["controller"].status()


@app.get("/api/classes")
def api_classes():
    """Peta index kelas model: {0: 'matang', 1: 'mentah', 2: 'setengah matang'}."""
    det = ctx.get("detector")
    # getattr(objek, "nama_atribut", nilai_cadangan) mengambil atribut dengan
    # aman: kalau atributnya tidak ada, kembalikan nilai cadangan alih-alih error.
    return {"classes": getattr(det, "class_names", {}) if det else {}}


@app.get("/api/config")
def api_get_config():
    """Mengirim seluruh isi config.json ke halaman kalibrasi."""
    return ctx["config"].all()


@app.post("/api/config")
async def api_set_config(request: Request):
    """Menyimpan config baru dari web; langsung aktif tanpa restart."""
    # await request.json() membaca isi kiriman browser dan mengubahnya
    # dari teks JSON menjadi dictionary Python.
    data = await request.json()
    ctx["config"].save(data)
    return {"ok": True, "message": "Config tersimpan & aktif (hot-reload)"}


@app.post("/api/estop")
def api_estop():
    """E-STOP: tombol darurat, menghentikan semua gerakan seketika."""
    ctx["controller"].trigger_estop()
    return {"ok": True}


@app.post("/api/estop/clear")
def api_estop_clear():
    """Membatalkan status darurat agar sistem bisa jalan lagi."""
    ctx["controller"].clear_estop()
    return {"ok": True}


@app.post("/api/calibrate/empty")
def api_calibrate_empty():
    """Simpan snapshot belt kosong sebagai latar untuk deteksi objek reject."""
    ok = ctx["controller"].save_empty_reference()
    # Pesan yang dikirim menyesuaikan hasil, memakai bentuk "A if syarat else B".
    return {"ok": ok, "message": "Latar kosong tersimpan" if ok else "Gagal: frame kamera 1 belum tersedia"}


@app.post("/api/mode")
async def api_mode(request: Request):
    """Mengganti mode: otomatis (sortir jalan) atau manual (untuk kalibrasi)."""
    data = await request.json()
    # data.get("manual", False) -> kalau kunci "manual" tidak dikirim, anggap False.
    ctx["controller"].set_manual(data.get("manual", False))
    return {"ok": True, "manual_mode": ctx["controller"].manual_mode}


@app.post("/api/manual")
async def api_manual(request: Request):
    """Kirim command serial mentah (hanya saat manual mode) untuk kalibrasi."""
    # Pengaman penting: perintah mentah HANYA boleh saat manual mode. Kalau
    # tidak, perintah dari web bisa mengacaukan proses sortir yang sedang jalan.
    if not ctx["controller"].manual_mode:
        # status_code 400 = "Bad Request" (permintaan tidak sah).
        return JSONResponse({"ok": False, "message": "Aktifkan manual mode dulu"}, status_code=400)
    data = await request.json()
    # (data.get("cmd") or "") -> kalau "cmd" tidak ada / None, jadikan teks kosong
    # agar .strip() di belakangnya tidak error.
    cmd = (data.get("cmd") or "").strip()
    if not cmd:
        return JSONResponse({"ok": False, "message": "cmd kosong"}, status_code=400)
    ok = ctx["bridge"].send(cmd)
    return {"ok": ok, "sent": cmd, "reply": ctx["bridge"].last_line}


@app.get("/api/history")
def api_history(limit: int = 100):
    """Riwayat sortir terbaru. FastAPI otomatis membaca ?limit=... dari URL."""
    # import di dalam fungsi: modul store baru dimuat saat endpoint ini dipakai.
    from store import store
    return {"rows": store.recent(limit)}


# Bagian {row_id} di dalam alamat adalah "path parameter": nilainya diambil dari
# URL. Contoh: DELETE /api/history/7 membuat row_id bernilai 7.
# Penulisan "row_id: int" membuat FastAPI otomatis mengubahnya menjadi angka
# dan menolak permintaan bila yang dikirim ternyata bukan angka.
@app.delete("/api/history/{row_id}")
def api_history_delete(row_id: int):
    """Menghapus satu baris riwayat."""
    from store import store
    store.delete(row_id)
    return {"ok": True}


@app.delete("/api/history")
def api_history_clear():
    """Menghapus SELURUH riwayat, mengembalikan jumlah yang terhapus."""
    from store import store
    return {"ok": True, "deleted": store.clear_all()}


# =========================================================
# DATASET / ANOTASI / TRAINING
# Bagian ini untuk melatih ulang model AI langsung dari web:
# ambil foto -> tandai kotak objeknya (anotasi) -> latih model baru.
# =========================================================
@app.get("/api/dataset/list")
def api_ds_list():
    """Daftar foto dataset + statistik + daftar nama kelas."""
    # "import dataset as ds" = ambil modul dataset, lalu beri nama pendek "ds"
    # supaya tidak perlu menulis "dataset." panjang-panjang.
    import dataset as ds
    return {"images": ds.list_images(), "stats": ds.stats(), "classes": ds.CLASSES}


@app.post("/api/dataset/capture")
def api_ds_capture():
    """Mengambil satu foto dari kamera 1 dan menyimpannya ke dataset."""
    import dataset as ds
    frame = ctx["controller"].cams.cam1.read()
    name = ds.capture(frame)
    if not name:
        return JSONResponse({"ok": False, "message": "Frame kamera 1 belum tersedia"}, status_code=400)
    return {"ok": True, "name": name}


@app.delete("/api/dataset/image/{name}")
def api_ds_delete(name: str):
    """Menghapus satu foto dataset beserta labelnya."""
    import dataset as ds
    ds.delete_image(name)
    return {"ok": True}


@app.get("/api/dataset/label/{name}")
def api_ds_get_label(name: str):
    """Mengambil kotak-kotak anotasi yang sudah tersimpan untuk satu foto."""
    import dataset as ds
    return {"boxes": ds.get_label(name)}


@app.post("/api/dataset/label/{name}")
async def api_ds_save_label(name: str, request: Request):
    """Menyimpan kotak-kotak anotasi hasil menandai di halaman web."""
    import dataset as ds
    data = await request.json()
    n = ds.save_label(name, data.get("boxes", []))
    return {"ok": True, "saved": n}


@app.post("/api/train/start")
async def api_train_start(request: Request):
    """Memulai pelatihan model baru dari dataset yang sudah dianotasi."""
    import dataset as ds
    # "await request.body()" memeriksa apakah browser mengirim isi.
    # Kalau tidak ada isi sama sekali, pakai dictionary kosong agar tidak error.
    body = await request.json() if await request.body() else {}
    # sorting dialihkan ke MANUAL supaya CPU tidak berebut dengan training
    # (training sangat berat; kalau sortir tetap jalan, keduanya jadi lambat).
    ctx["controller"].set_manual(True)
    # Fungsi start() mengembalikan DUA nilai sekaligus: status ok dan pesan.
    ok, msg = ds.trainer.start(
        epochs=int(body.get("epochs", 40)),   # berapa kali seluruh dataset dipelajari ulang
        imgsz=int(body.get("imgsz", 416)),    # ukuran gambar saat dilatih
        batch=int(body.get("batch", 8)),      # berapa gambar diproses sekaligus
        freeze=int(body.get("freeze", 10)),   # berapa lapisan model dibekukan (tidak ikut dilatih)
    )
    if not ok:
        # Gagal memulai -> kembalikan sortir ke mode otomatis seperti semula.
        ctx["controller"].set_manual(False)
        return JSONResponse({"ok": False, "message": msg}, status_code=400)
    return {"ok": True, "run": msg}


@app.get("/api/train/status")
def api_train_status():
    """Kemajuan pelatihan: sedang epoch ke berapa, sudah selesai atau belum."""
    import dataset as ds
    return ds.trainer.status()


@app.post("/api/train/stop")
def api_train_stop():
    """Menghentikan pelatihan di tengah jalan."""
    import dataset as ds
    return {"ok": ds.trainer.stop()}


@app.get("/api/models")
def api_models():
    """Daftar model yang tersedia + jenis model yang sedang aktif."""
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
    """Kemajuan proses konversi model."""
    import dataset as ds
    return ds.export_state


@app.post("/api/models/activate")
async def api_models_activate(request: Request):
    """Menjadikan sebuah model sebagai model yang dipakai sistem."""
    import dataset as ds
    data = await request.json()
    ok, msg = ds.activate_model(data.get("path", ""))
    # Pesan tambahan hanya disambung bila berhasil (ok bernilai True).
    return {"ok": ok, "message": msg + (" — restart service untuk memuat model baru." if ok else "")}


# WebSocket berbeda dari endpoint biasa: koneksinya TETAP TERBUKA sehingga
# server bisa terus-menerus mendorong data baru ke browser tanpa diminta.
# Dipakai agar angka-angka di dashboard bergerak sendiri secara real-time.
@app.websocket("/ws")
async def ws(websocket):
    # accept() = menerima permintaan koneksi dari browser.
    await websocket.accept()
    try:
        while True:
            # Kirim status terbaru dalam bentuk JSON.
            await websocket.send_json(ctx["controller"].status())
            # Jeda 0,5 detik -> data diperbarui 2 kali per detik.
            await asyncio.sleep(0.5)
    except Exception:
        # Browser menutup koneksi -> ini normal, jadi errornya diabaikan saja.
        pass


# static uploads (snapshot)
# app.mount menempelkan seluruh isi sebuah FOLDER ke sebuah alamat. Contoh:
# file core/static/foto.jpg jadi bisa dibuka lewat http://.../static/foto.jpg
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# gambar dataset (untuk galeri & anotasi)
# Folder dibuat dulu bila belum ada, karena StaticFiles akan error kalau
# foldernya tidak ditemukan.
(BASE_DIR / "dataset" / "images").mkdir(parents=True, exist_ok=True)
app.mount("/dsimg", StaticFiles(directory=str(BASE_DIR / "dataset" / "images")), name="dsimg")

# web build (Vite) kalau sudah ada; kalau belum, tampilkan info
if WEB_DIST.exists():
    # html=True membuat alamat "/" otomatis membuka index.html.
    # PENTING: mount "/" harus ditulis PALING BAWAH, karena FastAPI mencocokkan
    # alamat dari atas ke bawah — kalau ditaruh di atas, ia akan menelan semua
    # alamat /api/... sehingga endpoint di atas tidak pernah terpanggil.
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
else:
    # Web belum di-build (belum menjalankan "npm run build") -> tampilkan
    # keterangan singkat supaya pengguna tidak bingung melihat halaman kosong.
    @app.get("/")
    def root():
        return JSONResponse({
            "app": "PemilahBuahNaga Core",
            "status": "running (headless)",
            "note": "Web UI belum di-build. Endpoint aktif: /api/status, /video/cam1, /video/cam2, /ws",
        })
