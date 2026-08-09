"""
YOLODetector — wrapper YOLOv8 (ultralytics). Otomatis pakai model NCNN
kalau tersedia (best_ncnn_model/) untuk kecepatan di Pi 5.

CATATAN UNTUK PEMULA:
File ini adalah "pembungkus" (wrapper) untuk model kecerdasan buatan YOLOv8.
Tugasnya: menerima satu gambar (frame) dari kamera, lalu mengembalikan daftar
objek yang terdeteksi beserta posisi kotaknya dan tingkat keyakinannya.

Istilah yang sering muncul:
- frame      : satu lembar gambar hasil jepretan kamera.
- inference  : proses model AI "menebak" isi gambar.
- bounding box: kotak persegi yang mengelilingi objek yang ditemukan.
- confidence : nilai 0.0 sampai 1.0, seberapa yakin model dengan tebakannya.
               0.9 berarti 90% yakin.
"""
import threading                        # untuk mengunci akses agar aman dipakai banyak thread
from dataclasses import dataclass       # cara singkat membuat class penampung data
from pathlib import Path                # penulisan alamat file yang aman

import cv2                              # OpenCV: pustaka pengolahan gambar (menggambar kotak & teks)

# Folder tempat file detector.py ini berada (yaitu folder core/).
BASE_DIR = Path(__file__).resolve().parent
# Urutan prioritas: format teroptimasi utk ARM dulu (lebih ringan/cepat di Pi),
# baru fallback ke .pt PyTorch. NCNN biasanya tercepat di ARM, lalu ONNX.
# Ini sebuah "list" (daftar), ditandai kurung siku [ ]. Isinya diperiksa dari
# atas ke bawah; yang pertama ketemu itulah yang dipakai.
MODEL_CANDIDATES = [
    BASE_DIR / "best_ncnn_model",   # NCNN (tercepat di ARM)
    BASE_DIR / "best.onnx",         # ONNX (onnxruntime)
    BASE_DIR / "best.pt",           # PyTorch
    BASE_DIR.parent / "best.pt",    # cadangan: satu folder di atas core/
]

# normalisasi label model -> label baku Indonesia
# Ini dictionary (kamus): sisi kiri = tulisan apa adanya dari model,
# sisi kanan = tulisan baku yang dipakai seragam di seluruh program.
# Gunanya: model bisa saja memberi label "ripe" atau "matang"; keduanya
# kita samakan menjadi "matang" agar sisa program tidak bingung.
LABEL_MAP = {
    "matang": "matang", "ripe": "matang",
    "mentah": "mentah", "unripe": "mentah", "raw": "mentah",
    "setengah matang": "setengah matang", "half ripe": "setengah matang",
    "setengah": "setengah matang",
}


def normalize_label(label):
    """Membakukan penulisan label agar konsisten."""
    # Kalau label kosong / None, kembalikan None (tidak ada nilai).
    if not label:
        return None
    # Baris di bawah dikerjakan dari dalam ke luar, bertahap:
    #   str(label)              -> pastikan bentuknya teks
    #   .lower()                -> jadikan huruf kecil semua ("Matang" -> "matang")
    #   .strip()                -> buang spasi di awal/akhir ("  matang " -> "matang")
    #   .replace("_", " ")      -> ganti garis bawah jadi spasi
    #   .replace("-", " ")      -> ganti tanda hubung jadi spasi
    # Hasil bersih itu dicari di LABEL_MAP. Kalau tidak ketemu, pakai nilai
    # cadangan yaitu str(label).lower() (label aslinya dalam huruf kecil).
    return LABEL_MAP.get(str(label).lower().strip().replace("_", " ").replace("-", " "), str(label).lower())


# @dataclass adalah "dekorator": penanda di atas class yang memberi kemampuan
# tambahan secara otomatis. Dengan @dataclass, Python otomatis membuatkan
# fungsi __init__ sehingga kita cukup menulis nama-nama datanya saja di bawah.
@dataclass
class Detection:
    """Menyimpan hasil SATU deteksi objek."""
    # Format penulisannya "nama: tipe_data". Tipe data hanya penanda untuk
    # manusia dan editor kode; Python tidak memaksakannya.
    label: str      # nama kelas, contoh "matang"
    conf: float     # tingkat keyakinan 0.0 - 1.0 (float = bilangan desimal)
    x1: float       # koordinat kiri kotak (dalam piksel)
    y1: float       # koordinat atas kotak
    x2: float       # koordinat kanan kotak
    y2: float       # koordinat bawah kotak
    cls_id: int = -1  # nomor kelas dari model; -1 artinya "tidak diketahui"

    # @property membuat sebuah fungsi bisa dipanggil seperti data biasa.
    # Jadi ditulis d.cx (tanpa kurung), bukan d.cx().
    @property
    def cx(self):
        """Titik tengah kotak pada sumbu X (mendatar)."""
        # Rata-rata sisi kiri dan kanan = titik tengah horizontal.
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self):
        """Titik tengah kotak pada sumbu Y (tegak)."""
        return (self.y1 + self.y2) / 2.0

    @property
    def area(self):
        """Luas kotak dalam satuan piksel persegi."""
        # max(0.0, ...) adalah pengaman: kalau hasil pengurangan negatif
        # (koordinat terbalik), anggap saja 0 supaya luas tidak pernah minus.
        # Luas = lebar x tinggi.
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


class YOLODetector:
    def __init__(self):
        # import di DALAM fungsi (bukan di atas file) dilakukan agar pustaka
        # berat seperti torch baru dimuat saat benar-benar dibutuhkan.
        import torch
        torch.set_num_threads(4)  # Pi 5: pakai semua core (default 1 -> 4x lebih lambat)
        from ultralytics import YOLO
        # Cari file model yang benar-benar ada di antara daftar kandidat.
        # Penjelasan bagian dalam:
        #   (p for p in MODEL_CANDIDATES if p.exists())  -> ambil kandidat yang filenya ada
        #   next(..., None)                              -> ambil yang PERTAMA; kalau tak ada, None
        model_path = next((p for p in MODEL_CANDIDATES if p.exists()), None)
        if model_path is None:
            # raise = sengaja memunculkan error dan menghentikan program, karena
            # tanpa model, sistem ini tidak bisa bekerja sama sekali.
            raise FileNotFoundError(
                "best.pt tidak ditemukan. Letakkan best.pt di core/ atau folder proyek."
            )
        print(f"[YOLO] Memuat model: {model_path}")
        # Memuat model ke memori. Ini langkah yang paling lama (beberapa detik).
        self.model = YOLO(str(model_path))
        # Kunci agar model tidak dipakai oleh dua thread sekaligus (bisa error).
        self.lock = threading.Lock()
        # index kelas asli dari model: {0: 'matang', 1: 'mentah', 2: 'setengah matang'}
        # Baris ini disebut "dict comprehension": cara ringkas membuat dictionary
        # baru dari dictionary lama sambil mengubah isinya. Artinya: untuk setiap
        # pasangan k (nomor) dan v (nama) di model.names, simpan sebagai
        # nomor(int) -> nama yang sudah dibakukan.
        self.class_names = {int(k): normalize_label(v) for k, v in self.model.names.items()}
        # Membuat kamus kebalikannya: nama -> nomor. Berguna kalau kita punya
        # nama kelas dan ingin tahu nomor indeksnya.
        self.label_to_index = {v: k for k, v in self.class_names.items()}
        print(f"[YOLO] Model siap. Kelas: {self.class_names}")

    def infer(self, frame, imgsz=480, conf=0.25):
        """Menjalankan model AI pada satu gambar, mengembalikan daftar Detection.

        imgsz = ukuran gambar saat diproses model. Makin kecil makin cepat
                tapi makin kurang teliti (480 ~5 FPS, 320 ~10 FPS di Pi 5).
        conf  = ambang batas keyakinan minimum; tebakan di bawah ini dibuang.
        """
        # Pengaman: kalau kamera belum mengirim gambar, kembalikan daftar kosong.
        if frame is None:
            return []
        # Kunci dulu, supaya hanya satu thread yang memakai model pada satu waktu.
        with self.lock:
            # predict() = perintah model untuk menganalisis gambar.
            # verbose=False artinya jangan cetak log panjang ke terminal.
            results = self.model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)
        # Daftar kosong untuk menampung hasil yang sudah dirapikan.
        dets = []
        # results berisi hasil untuk banyak gambar; kita hanya kirim 1 gambar,
        # jadi ambil hasil pertama saja (indeks 0 = elemen pertama).
        r = results[0]
        # Ulangi untuk setiap kotak objek yang ditemukan model.
        for box in r.boxes:
            # Nomor kelas hasil tebakan, diubah ke bilangan bulat.
            cid = int(box.cls[0])
            # box.xyxy[0] berisi 4 angka koordinat. .tolist() mengubahnya jadi
            # list Python biasa, lalu tiap nilai diubah ke float.
            # Menulis 4 variabel sekaligus di kiri "=" disebut "unpacking".
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
            # Buat objek Detection dan tambahkan ke daftar hasil.
            dets.append(Detection(normalize_label(r.names[cid]), float(box.conf[0]), x1, y1, x2, y2, cid))
        return dets


def filter_dets(dets, roi, min_area, conf_threshold, conf_per_class):
    """Saring deteksi: dalam ROI, cukup besar, dan lolos threshold per-kelas.

    ROI = Region Of Interest, yaitu kotak area yang kita perhatikan saja.
    Deteksi di luar kotak itu diabaikan (misalnya buah di pinggir meja).
    """
    out = []
    for d in dets:
        # Tiap kelas boleh punya ambang keyakinan sendiri. Kalau tidak diatur
        # khusus, pakai ambang umum conf_threshold.
        thr = conf_per_class.get(d.label, conf_threshold) if conf_per_class else conf_threshold
        # "continue" artinya lewati objek ini, langsung lanjut ke objek berikutnya.
        # Buang tebakan yang keyakinannya terlalu rendah (kemungkinan salah).
        if d.conf < thr:
            continue
        # Buang objek yang terlalu kecil (biasanya cuma noise/bintik, bukan buah).
        if d.area < min_area:
            continue
        # Buang objek yang titik tengahnya berada di LUAR kotak ROI.
        # Syarat di dalam ROI: x tengah antara sisi kiri dan kanan ROI,
        # DAN y tengah antara sisi atas dan bawah ROI.
        if roi and not (roi["x"] <= d.cx <= roi["x"] + roi["w"] and roi["y"] <= d.cy <= roi["y"] + roi["h"]):
            continue
        # Kalau lolos semua saringan di atas, simpan sebagai hasil yang sah.
        out.append(d)
    return out


def draw_overlay(frame, dets, roi=None, state="", extra=""):
    """Gambar bounding box, ROI, dan teks status untuk stream monitoring.

    Fungsi ini murni untuk tampilan di web. Coretan ini tidak mempengaruhi
    keputusan sortir sama sekali.
    """
    if frame is None:
        return frame
    # Warna di OpenCV ditulis (Biru, Hijau, Merah) — BGR, bukan RGB seperti biasa.
    # Nilainya 0-255. Contoh (0, 200, 0) = hijau, (0, 0, 230) = merah.
    colors = {"matang": (0, 200, 0), "setengah matang": (0, 200, 255), "mentah": (0, 0, 230)}
    if roi:
        # cv2.rectangle menggambar kotak. Urutan argumennya:
        # (gambar, titik pojok kiri-atas, titik pojok kanan-bawah, warna, ketebalan garis)
        cv2.rectangle(frame, (int(roi["x"]), int(roi["y"])),
                      (int(roi["x"] + roi["w"]), int(roi["y"] + roi["h"])), (181, 23, 91), 2)
    # Gambar satu kotak untuk tiap objek yang terdeteksi.
    for d in dets:
        # Ambil warna sesuai label; kalau labelnya tak dikenal, pakai abu-abu.
        c = colors.get(d.label, (200, 200, 200))
        cv2.rectangle(frame, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)), c, 2)
        # cv2.putText menulis teks di atas gambar.
        # f"{d.conf:.2f}" artinya tampilkan angka desimal 2 angka di belakang koma.
        # max(18, y1-6) memastikan teks tidak tertulis di luar atas gambar
        # (kalau kotaknya menempel di tepi atas, teks digeser turun ke y=18).
        cv2.putText(frame, f"{d.label} {d.conf:.2f}", (int(d.x1), max(18, int(d.y1) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
    # Siapkan tulisan status di pita atas gambar.
    banner = f"{state}"
    if extra:
        # Tanda "+=" artinya "tambahkan ke isi yang sudah ada".
        banner += f" | {extra}"
    # Gambar pita hitam sebagai alas teks.
    # frame.shape[1] = lebar gambar. Ketebalan -1 artinya kotaknya diisi penuh
    # (solid), bukan cuma garis tepi.
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 30), (20, 20, 25), -1)
    # banner[:80] artinya ambil 80 karakter pertama saja, agar teks tidak
    # kepanjangan dan keluar dari layar.
    cv2.putText(frame, banner[:80], (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return frame
