#!/usr/bin/env python3
# Baris paling atas di atas ini namanya "shebang". Gunanya: kalau file ini
# dijalankan langsung dari terminal (contoh: ./main.py), sistem Linux tahu
# bahwa file ini harus dijalankan memakai program "python3".
"""
PemilahBuahNaga — Core Service (headless, offline-first)
Menyatukan: kamera, YOLO, state machine sorting, serial Arduino, dan web API.
Jalan sebagai systemd service; sorting tetap berjalan walau web tak dibuka.

CATATAN UNTUK PEMULA:
Tulisan yang diapit tiga tanda kutip (\"\"\" ... \"\"\") di awal file namanya
"docstring", yaitu penjelasan tentang isi file. Python mengabaikannya saat
program berjalan, jadi fungsinya murni sebagai catatan untuk manusia.

File ini adalah "pintu masuk" (entry point) program. Tugasnya cuma dua:
  1. Menyalakan semua komponen (kamera, model AI, koneksi Arduino, dll).
  2. Menjalankan web server supaya bisa dipantau lewat browser.
"""
# "import" artinya meminjam kode dari file/pustaka lain supaya bisa dipakai di sini.
# uvicorn = program kecil yang tugasnya menjalankan web server Python.
import uvicorn

# Baris-baris di bawah ini mengambil komponen dari file lain di folder yang sama.
# Bentuk "from X import Y" artinya: dari file X.py, ambil bagian bernama Y saja.
from config import config              # objek pengaturan (dibaca dari config.json)
from camera import CameraManager       # kelas pengatur 2 kamera USB
from detector import YOLODetector      # kelas pembungkus model AI YOLOv8
from serial_bridge import SerialBridge # kelas penghubung ke Arduino lewat kabel USB
from state_machine import SortController  # kelas otak logika sortir buah
from mdns import MDNSPublisher         # kelas agar alamat "buahnaga.local" bisa dipakai
import api                             # file api.py (web server) diambil seluruhnya


def build():
    """Fungsi ini menyalakan dan menyambungkan semua komponen sistem.

    Kata "def" artinya kita sedang membuat sebuah fungsi (kumpulan perintah yang
    diberi nama). Isi fungsi tidak langsung jalan; baru jalan kalau dipanggil
    dengan menulis build().
    """
    # print() = menampilkan tulisan ke layar terminal.
    # "=" * 56 artinya karakter "=" diulang 56 kali, jadi garis pemisah.
    print("=" * 56)
    print("  PemilahBuahNaga — Core Service")
    print("=" * 56)

    # Muat model YOLO DULU (berat, ~detik) sebelum start kamera, agar init
    # kamera tidak berebut CPU dengan loading model (penyebab verifikasi frame
    # timeout -> salah satu kamera gagal init).
    # YOLODetector() = membuat objek baru dari kelas YOLODetector. Saat objek
    # dibuat, file model best.pt dibaca ke memori (ini bagian yang lambat).
    detector = YOLODetector()

    # Membuat objek pengatur kamera, dan menyerahkan "config" agar ia tahu
    # kamera mana yang dipakai serta resolusinya berapa.
    cams = CameraManager(config)
    # start() menyuruh kamera mulai menyala dan mengambil gambar terus-menerus
    # di belakang layar (background).
    cams.start()

    # config.get("serial") mengambil bagian "serial" dari file config.json.
    # Isinya kira-kira: {"port": "/dev/ttyUSB0", "baud": 115200, ...}
    scfg = config.get("serial")
    # Membuat objek penghubung ke Arduino. Nilai di dalam kurung disebut
    # "argumen": data yang kita berikan supaya objeknya tahu harus pakai
    # port dan kecepatan berapa.
    bridge = SerialBridge(
        # port = nama alamat perangkat Arduino di Linux, contoh /dev/ttyUSB0.
        # baud = kecepatan kirim data per detik (harus sama dengan di firmware).
        port=scfg["port"], baud=scfg["baud"],
        # .get("nama", nilai_cadangan) artinya: ambil nilai "nama" dari config,
        # tapi kalau tidak ada, pakai nilai cadangan. Ini mencegah program error.
        heartbeat_seconds=scfg.get("heartbeat_seconds", 1.0),   # kirim sinyal "saya hidup" tiap 1 detik
        auto_reconnect=scfg.get("auto_reconnect", True),        # sambung ulang otomatis kalau kabel lepas
    )
    # Mulai proses baca-tulis serial di belakang layar.
    bridge.start()

    # SortController adalah "otak" sistem. Ia butuh 4 hal: pengaturan, kamera,
    # detektor AI, dan jalur komunikasi ke Arduino. Semuanya kita serahkan di sini.
    controller = SortController(config, cams, detector, bridge)
    # start() menjalankan loop sortir terus-menerus di belakang layar.
    controller.start()

    # api.ctx adalah sebuah dictionary (kamus) di file api.py yang dipakai
    # sebagai "papan pengumuman": kita titipkan objek-objek penting ke sana
    # supaya halaman web nanti bisa memakainya.
    # Dictionary = wadah data berpasangan kunci -> nilai, ditulis dengan kurung siku.
    api.ctx["controller"] = controller
    api.ctx["bridge"] = bridge
    api.ctx["config"] = config
    api.ctx["detector"] = detector
    # "return" mengembalikan hasil fungsi ke pihak yang memanggilnya.
    return controller


# Baris ini artinya: "kalau file ini dijalankan langsung (bukan di-import file lain),
# maka jalankan kode di bawahnya". Ini cara standar Python menandai titik mulai program.
if __name__ == "__main__":
    # Panggil fungsi build() di atas untuk menyalakan seluruh sistem.
    build()

    # Ambil bagian "web" dari config.json. default={} artinya kalau bagian itu
    # tidak ada, anggap saja dictionary kosong.
    # Tanda "or {}" adalah pengaman tambahan: kalau hasilnya None (kosong),
    # ganti jadi dictionary kosong supaya baris berikutnya tidak error.
    web = config.get("web", default={}) or {}
    # int(...) mengubah nilai menjadi bilangan bulat. Kalau "port" tak ada di
    # config, pakai 5000 sebagai nilai bawaan.
    port = int(web.get("port", 5000))
    # Nama host untuk mDNS, bawaannya "buahnaga".
    hostname = web.get("mdns_hostname", "buahnaga")

    # publikasikan mDNS: http://buahnaga.local:5000
    # mDNS membuat Raspberry Pi bisa diakses lewat nama, bukan lewat angka IP.
    mdns = MDNSPublisher(hostname=hostname, port=port)
    # Blok "try / except" dipakai agar program tidak mati total kalau terjadi error.
    # Kode di dalam "try" dicoba dijalankan lebih dulu.
    try:
        host_local = mdns.start()
    # Kalau muncul error apa pun (Exception), tangkap dan simpan pesannya di "exc".
    except Exception as exc:
        # Program tetap lanjut, hanya saja aksesnya harus lewat alamat IP.
        host_local = f"{hostname}.local"
        # Huruf f di depan tanda kutip disebut "f-string": isi di dalam {} akan
        # diganti dengan nilai variabelnya saat ditampilkan.
        print(f"[mDNS] gagal publish ({exc}); akses tetap via IP:{port}")

    print(f"[CORE] Web: http://{host_local}:{port}  (monitoring & kalibrasi)")
    try:
        # uvicorn.run() menjalankan web server dan MENAHAN program di baris ini
        # selama server masih hidup (tidak lanjut ke baris berikutnya).
        #   api.app     = aplikasi web yang didefinisikan di api.py
        #   host        = "0.0.0.0" berarti bisa diakses dari perangkat lain di jaringan
        #   port        = nomor pintu, contoh 5000
        #   log_level   = "warning" berarti hanya tampilkan pesan penting saja
        uvicorn.run(api.app, host="0.0.0.0", port=port, log_level="warning")
    # Blok "finally" SELALU dijalankan, baik server berhenti normal maupun error.
    # Dipakai untuk bersih-bersih: di sini kita matikan pengumuman mDNS.
    finally:
        mdns.stop()
