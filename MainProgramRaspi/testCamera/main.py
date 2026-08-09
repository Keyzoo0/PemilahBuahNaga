#!/usr/bin/env python3
"""
PemilahBuahNaga — Dual Camera Flask Streamer
Menampilkan 2 kamera USB DV20 secara real-time di web browser.

CATATAN UNTUK PEMULA:
Ini program UJI COBA sederhana, terpisah dari sistem utama di folder core/.
Gunanya cuma satu: memastikan kedua kamera benar-benar berfungsi dan
gambarnya bagus, SEBELUM menjalankan sistem sortir yang sesungguhnya.

Bedanya dengan core/api.py:
  - File ini memakai Flask (sederhana), core memakai FastAPI (lebih canggih).
  - File ini tidak ada AI, tidak ada motor — murni menampilkan gambar.

Cara pakai:
    python3 main.py
lalu buka http://<alamat-ip-raspi>:5000 di browser.
"""

import cv2          # OpenCV: membuka kamera & mengolah gambar
import json         # membaca file konfigurasi
import os           # urusan alamat file
import time         # jeda & pengukuran waktu
import threading    # menjalankan pengambilan gambar di latar belakang
# Flask = pustaka web sederhana untuk Python.
#   Flask          -> aplikasi webnya
#   Response       -> balasan khusus (dipakai untuk streaming video)
#   render_template-> menampilkan file HTML
#   jsonify        -> mengubah dictionary Python menjadi balasan JSON
from flask import Flask, Response, render_template, jsonify

# Membuat aplikasi web. Biasanya Flask mencari HTML di folder "templates",
# tapi di sini diarahkan ke folder "script" tempat file-filenya berada.
app = Flask(__name__, template_folder="script", static_folder="script")

# Load camera config
# ".." berarti "naik satu folder", jadi file config dicari di folder induk.
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "camera_config.json")
CAMERAS = {}
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        CAMERAS = json.load(f)

# Default jika config tidak ada
# Nilai cadangan agar program tetap bisa dicoba walau camera_identifier.py
# belum pernah dijalankan.
if not CAMERAS:
    CAMERAS = {
        "Camera_1": {"device": "/dev/video0"},
        "Camera_2": {"device": "/dev/video2"},
    }


class CameraStream:
    """Thread-safe camera stream dengan buffering."""

    def __init__(self, device, name, width=1920, height=1080):
        # 1920x1080 = Full HD. Resolusi tinggi dipakai di sini karena tujuannya
        # memeriksa kualitas gambar; sistem utama memakai resolusi lebih kecil
        # agar AI-nya bisa berjalan cepat.
        self.device = device
        self.name = name
        self.width = width
        self.height = height
        self.frame = None                   # gambar terbaru (sudah jadi JPEG)
        self.lock = threading.Lock()        # kunci agar aman dipakai bersamaan
        self.running = False
        self.cap = None
        self.fps = 0                        # kecepatan gambar per detik
        self.frame_count = 0                # penghitung sementara untuk FPS
        self.last_fps_time = time.time()    # patokan waktu perhitungan FPS

    def start(self):
        """Menyalakan pengambilan gambar di thread terpisah."""
        self.running = True
        # daemon=True agar thread ikut mati saat program utama ditutup.
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()

    def _capture_loop(self):
        """Loop: ambil gambar dari kamera terus-menerus, ubah ke JPEG, simpan."""
        # CAP_V4L2 memaksa pemakaian driver kamera bawaan Linux (paling stabil).
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            print(f"[ERROR] Cannot open {self.device}")
            return

        # Set format MJPG untuk max kualitas
        # Tanpa MJPG, kamera USB murah hanya sanggup Full HD dengan 5 FPS.
        # Dengan MJPG bisa sampai 30 FPS karena datanya dimampatkan lebih dulu.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        # BUFFERSIZE 1 = simpan hanya 1 gambar di antrean, supaya yang tampil
        # selalu gambar TERBARU (tidak tertinggal beberapa detik).
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Membaca kembali nilai sebenarnya: kamera belum tentu menuruti
        # permintaan kita. Kalau ia hanya sanggup 1280x720, angka itulah
        # yang akan tercetak di sini.
        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        # :.0f artinya tampilkan tanpa angka di belakang koma (30.0 -> 30).
        print(f"[{self.name}] {self.device} → {actual_w}x{actual_h} @ {actual_fps:.0f}fps")

        while self.running:
            # read() memberi dua nilai: berhasil/tidak, dan gambarnya.
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)   # gagal -> tunggu sebentar lalu coba lagi
                continue

            # Ubah gambar menjadi JPEG di dalam memori (tanpa menyentuh kartu SD).
            # Nilai balik pertama tidak dipakai, jadi ditampung di garis bawah (_).
            #   JPEG_QUALITY 90  -> kualitas tinggi
            #   JPEG_OPTIMIZE 1  -> ukuran file lebih kecil, prosesnya sedikit lebih lama
            _, jpeg = cv2.imencode(
                ".jpg", frame,
                [cv2.IMWRITE_JPEG_QUALITY, 90, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
            )

            # Dikunci saat menulis agar browser tidak menerima gambar setengah jadi.
            with self.lock:
                self.frame = jpeg.tobytes()
                self.frame_count += 1
                now = time.time()
                # Tiap 1 detik, hitung FPS = jumlah gambar dibagi lama waktunya.
                if now - self.last_fps_time >= 1.0:
                    self.fps = self.frame_count / (now - self.last_fps_time)
                    self.frame_count = 0        # nolkan untuk periode berikutnya
                    self.last_fps_time = now

    def get_frame(self):
        """Mengambil gambar JPEG terbaru."""
        with self.lock:
            return self.frame

    def get_fps(self):
        """FPS terkini, dibulatkan 1 angka desimal."""
        return round(self.fps, 1)

    def stop(self):
        """Menghentikan pengambilan gambar dan melepas kamera."""
        self.running = False
        if self.cap:
            self.cap.release()


# Initialize camera streams
# Kode ini jalan begitu file dimuat: semua kamera di config langsung dinyalakan.
streams = {}
for name, cfg in CAMERAS.items():
    dev = cfg["device"]
    s = CameraStream(dev, name)
    s.start()
    streams[name] = s

# Beri jeda setengah detik agar kamera sempat menghasilkan gambar pertama
# sebelum server web mulai melayani permintaan.
time.sleep(0.5)


def generate_stream(stream):
    """Generator untuk MJPEG stream."""
    # MJPEG = rentetan foto JPEG yang dikirim beruntun sangat cepat, sehingga
    # di browser terlihat seperti video.
    while stream.running:
        frame = stream.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue
        # yield mengirim satu potong data lalu melanjutkan dari titik ini
        # pada putaran berikutnya. Tanda b"..." berarti data mentah (bytes).
        # "--frame" adalah penanda batas antar-gambar sesuai aturan MJPEG.
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        # Jeda sangat kecil agar CPU tidak terpakai 100%.
        time.sleep(0.001)


# @app.route("/alamat") mendaftarkan fungsi di bawahnya sebagai penangan
# permintaan browser ke alamat tersebut.
@app.route("/")
def index():
    """Halaman utama (script/index.html)."""
    return render_template("index.html")


@app.route("/video_feed_1")
def video_feed_1():
    """Siaran kamera pertama."""
    # streams adalah dictionary; .values() mengambil isinya, list(...) mengubah
    # menjadi daftar berurutan, lalu [0] mengambil yang pertama.
    cam = list(streams.values())[0]
    return Response(
        generate_stream(cam),
        # mimetype ini yang membuat browser terus mengganti gambar lama
        # dengan yang baru, sehingga tampak seperti video.
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/video_feed_2")
def video_feed_2():
    """Siaran kamera kedua (kalau hanya ada 1 kamera, tampilkan yang pertama)."""
    # Pengaman: kalau kamera kedua tidak ada, jangan error — pakai yang pertama.
    cam = list(streams.values())[1] if len(streams) > 1 else list(streams.values())[0]
    return Response(
        generate_stream(cam),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/status")
def status():
    """Kondisi tiap kamera dalam format JSON (dibaca oleh main.js)."""
    info = {}
    for name, s in streams.items():
        info[name] = {
            "device": s.device,
            "fps": s.get_fps(),
            "running": s.running,
        }
    return jsonify(info)


@app.route("/api/cameras")
def api_cameras():
    """Isi file konfigurasi kamera, apa adanya."""
    return jsonify(CAMERAS)


if __name__ == "__main__":
    print("=" * 50)
    print("  PemilahBuahNaga — Camera Stream Server")
    print("=" * 50)
    print(f"  Open http://localhost:5000")
    print(f"  Cameras: {', '.join(CAMERAS.keys())}")
    print("=" * 50)

    try:
        # app.run menjalankan server dan MENAHAN program di baris ini.
        #   host="0.0.0.0"      -> bisa diakses dari HP/laptop di jaringan yang sama
        #   threaded=True       -> layani beberapa pengunjung sekaligus
        #   use_reloader=False  -> jangan restart otomatis saat file berubah
        #                          (kalau menyala, kamera bisa dibuka dua kali
        #                           dan salah satunya gagal)
        app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        # Menangkap penekanan Ctrl+C agar kamera dilepas dengan rapi
        # sebelum program benar-benar berhenti.
        print("\nShutting down...")
        for s in streams.values():
            s.stop()
