"""
Dataset & Training di Raspberry Pi 5.

Prinsip agar RINGAN:
  - Gambar disimpan langsung pada ukuran latih (default 640 px sisi terpanjang),
    jadi tidak ada resize berulang saat training dan kartu SD hemat.
  - Label format YOLO (.txt) sejajar gambar -> tidak perlu database.
  - Training memakai FINE-TUNE dari model aktif dengan backbone DIBEKUKAN
    (freeze), imgsz kecil, batch kecil, cache RAM. Ini yang membuat training
    mungkin dilakukan di CPU ARM.
  - Training jalan sebagai SUBPROCESS ber-'nice' agar web tetap responsif,
    dan sorting otomatis dialihkan ke MANUAL supaya CPU tidak berebut.

CATATAN UNTUK PEMULA:
File ini memungkinkan model AI DILATIH ULANG langsung dari Raspberry Pi,
tanpa perlu komputer berkartu grafis mahal. Alurnya:
  foto -> ditandai kotaknya (anotasi) -> dilatih -> model baru dipakai.

Istilah:
- dataset    : kumpulan foto + label yang dipakai untuk mengajari AI.
- label      : keterangan "di titik ini ada buah matang", ditulis di file .txt.
- fine-tune  : melatih ulang model yang SUDAH pintar, bukan mulai dari nol.
               Jauh lebih cepat dan cukup dengan sedikit foto.
- freeze     : "membekukan" sebagian model agar tidak ikut berubah saat dilatih.
               Menghemat waktu dan mencegah model lupa yang sudah dipelajari.
- epoch      : satu putaran penuh mempelajari seluruh dataset.
- batch      : berapa gambar diproses sekaligus dalam satu langkah belajar.
- subprocess : program terpisah yang dijalankan dari dalam program kita.
- nice       : perintah Linux untuk menurunkan prioritas sebuah program.
"""
import sys           # untuk mengetahui program python mana yang sedang dipakai
import json          # membaca/menulis format JSON
import os            # urusan sistem operasi (di sini: membuat symlink)
import random        # untuk mengacak urutan data
import shutil        # menyalin & menghapus file/folder
import signal        # mengirim sinyal ke program lain (untuk menghentikan training)
import subprocess    # menjalankan program lain dari dalam Python
import threading     # menjalankan pekerjaan bersamaan
import time          # pengukuran waktu
from datetime import datetime   # tanggal & jam
from pathlib import Path        # penulisan alamat file yang aman

import cv2           # OpenCV: menyimpan & memperkecil gambar

BASE_DIR = Path(__file__).resolve().parent   # folder core/
DATA_DIR = BASE_DIR / "dataset"              # induk semua data latih
IMG_DIR = DATA_DIR / "images"                # tempat foto disimpan
LBL_DIR = DATA_DIR / "labels"                # tempat file label .txt disimpan
BUILD_DIR = DATA_DIR / "_build"      # struktur train/val untuk ultralytics
MODEL_DIR = BASE_DIR / "models"              # tempat menyimpan cadangan model
RUNS_DIR = BASE_DIR / "runs"                 # hasil tiap sesi training

CLASSES = ["matang", "mentah", "setengah matang"]  # index 0,1,2 (sama dengan model)
# PENTING: urutan daftar ini tidak boleh diubah sembarangan! Format YOLO
# menyimpan kelas sebagai ANGKA, jadi bila urutannya bergeser, semua label
# lama jadi salah arti (misal "matang" mendadak terbaca "mentah").

# Buat semua folder yang dibutuhkan sekaligus dengan satu perulangan.
for d in (IMG_DIR, LBL_DIR, MODEL_DIR):
    d.mkdir(parents=True, exist_ok=True)


# =========================================================
# DATASET
# =========================================================
def _label_path(name):
    """Menerjemahkan nama gambar menjadi alamat file labelnya.

    Path(name).stem mengambil nama tanpa akhiran: "foto1.jpg" -> "foto1".
    Jadi "foto1.jpg" menjadi ".../labels/foto1.txt".
    """
    return LBL_DIR / (Path(name).stem + ".txt")


def capture(frame, max_side=640):
    """Simpan frame kamera 1 sebagai gambar dataset (sudah diperkecil)."""
    if frame is None:
        return None
    # frame.shape berisi (tinggi, lebar, jumlah kanal warna).
    # [:2] mengambil dua nilai pertama saja: tinggi dan lebar.
    h, w = frame.shape[:2]
    # Hitung faktor pengecilan agar sisi terpanjang menjadi max_side piksel.
    # min(1.0, ...) memastikan gambar hanya DIPERKECIL, tidak pernah diperbesar
    # (memperbesar hanya membuat file besar tanpa menambah detail).
    scale = min(1.0, float(max_side) / max(h, w))
    if scale < 1.0:
        # INTER_AREA adalah metode pengecilan gambar dengan hasil paling bagus.
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    # Nama file dari waktu sekarang agar unik dan urut.
    # %f = mikrodetik (6 digit); [:-3] memotong 3 digit terakhir sehingga
    # menjadi milidetik. Contoh hasil: "20260809_143012_527.jpg"
    name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
    # Kualitas JPEG 88 dari 100: kompromi bagus antara ketajaman dan ukuran file.
    cv2.imwrite(str(IMG_DIR / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return name


def list_images():
    """Daftar semua foto dataset + info sudah dilabeli atau belum."""
    out = []
    # reverse=True membuat urutan dari nama terbesar ke terkecil; karena nama
    # file berupa tanggal-jam, hasilnya foto terbaru muncul paling atas.
    for p in sorted(IMG_DIR.glob("*.jpg"), reverse=True):
        lp = _label_path(p.name)
        n = 0
        if lp.exists():
            # Hitung jumlah baris yang berisi (baris kosong tidak dihitung).
            # Satu baris = satu kotak objek.
            n = len([l for l in lp.read_text().splitlines() if l.strip()])
        out.append({"name": p.name, "labeled": n > 0, "boxes": n})
    return out


def delete_image(name):
    """Menghapus foto beserta file labelnya."""
    name = Path(name).name  # cegah path traversal
    # (Penjelasan pengaman di atas: kalau pengguna nakal mengirim nama seperti
    #  "../../etc/passwd", Path(name).name hanya menyisakan "passwd" sehingga
    #  file di luar folder dataset tidak mungkin terhapus. Celah keamanan
    #  semacam itu namanya "path traversal".)
    # missing_ok=True artinya jangan error kalau filenya memang sudah tidak ada.
    (IMG_DIR / name).unlink(missing_ok=True)
    _label_path(name).unlink(missing_ok=True)
    return True


def get_label(name):
    """Baca label YOLO -> list {cls, cx, cy, w, h} (ternormalisasi 0-1).

    "Ternormalisasi" artinya nilainya berupa PERSENTASE dari ukuran gambar,
    bukan piksel. cx=0.5 berarti tepat di tengah gambar, apa pun resolusinya.
    Keuntungannya: label tetap benar walau gambarnya nanti diperbesar/diperkecil.
    """
    lp = _label_path(Path(name).name)
    boxes = []
    if lp.exists():
        for line in lp.read_text().splitlines():
            # Format satu baris YOLO: "kelas cx cy lebar tinggi"
            # Contoh: "0 0.512000 0.480000 0.220000 0.310000"
            parts = line.split()
            # Hanya proses baris yang benar-benar berisi 5 nilai (baris rusak dilewati).
            if len(parts) == 5:
                c, cx, cy, w, h = parts
                boxes.append({"cls": int(c), "cx": float(cx), "cy": float(cy),
                              "w": float(w), "h": float(h)})
    return boxes


def save_label(name, boxes):
    """Menyimpan kotak anotasi dari web ke file label format YOLO."""
    lp = _label_path(Path(name).name)
    lines = []
    for b in boxes:
        c = int(b["cls"])
        # Bagian ini membatasi tiap nilai agar tetap di rentang 0-1
        # (kalau pengguna menyeret kotak sampai keluar gambar):
        #   min(1.0, x) -> tidak boleh lebih dari 1
        #   max(0.0, ...) -> tidak boleh kurang dari 0
        # Tulisan for k in (...) mengerjakan hal yang sama untuk keempat nilai
        # sekaligus, hasilnya langsung dibongkar ke 4 variabel.
        cx, cy, w, h = (max(0.0, min(1.0, float(b[k]))) for k in ("cx", "cy", "w", "h"))
        # Kotak tanpa lebar/tinggi tidak masuk akal -> dilewati.
        if w <= 0 or h <= 0:
            continue
        # :.6f artinya tulis sebagai desimal dengan 6 angka di belakang koma.
        lines.append(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    # "\n".join(lines) menyambung semua baris dengan tanda ganti baris.
    # Bagian akhir menambahkan satu baris baru di ujung file, tapi hanya
    # kalau memang ada isinya (agar file kosong benar-benar kosong).
    lp.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def stats():
    """Ringkasan dataset: total foto, sudah dilabeli, dan jumlah per kelas."""
    imgs = list(IMG_DIR.glob("*.jpg"))
    # Foto dianggap "terlabel" kalau file labelnya ada DAN isinya tidak kosong.
    labeled = [p for p in imgs if _label_path(p.name).exists()
               and _label_path(p.name).read_text().strip()]
    # Siapkan penghitung mulai dari 0 untuk setiap kelas.
    per_class = {c: 0 for c in CLASSES}
    for p in labeled:
        for b in get_label(p.name):
            # Pengaman agar tidak error kalau ada nomor kelas di luar daftar.
            # Penulisan 0 <= x < n adalah cara ringkas Python untuk
            # "x lebih besar sama dengan 0 DAN x lebih kecil dari n".
            if 0 <= b["cls"] < len(CLASSES):
                per_class[CLASSES[b["cls"]]] += 1
    return {"total": len(imgs), "labeled": len(labeled),
            "unlabeled": len(imgs) - len(labeled), "per_class": per_class}


# =========================================================
# BUILD STRUKTUR ULTRALYTICS (symlink -> hemat ruang & cepat)
# =========================================================
def build_split(val_ratio=0.2, seed=42):
    """Membagi dataset menjadi data latih (train) dan data uji (val).

    Kenapa dibagi? Kalau AI diuji dengan foto yang sama persis seperti saat
    belajar, nilainya pasti bagus tapi menipu — seperti ujian dengan bocoran
    soal. Sebagian foto sengaja disisihkan (val) sebagai soal "baru" untuk
    mengukur kepintaran sesungguhnya.

    val_ratio=0.2 artinya 20% untuk uji, 80% untuk belajar.
    """
    labeled = [p for p in sorted(IMG_DIR.glob("*.jpg"))
               if _label_path(p.name).exists() and _label_path(p.name).read_text().strip()]
    if len(labeled) < 4:
        # raise = hentikan dan laporkan error ke pemanggil; ditangkap di Trainer.start().
        raise ValueError(f"Dataset terlabel terlalu sedikit ({len(labeled)}). Minimal 4 gambar.")

    # Hapus hasil pembagian lama agar tidak tercampur dengan yang baru.
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)   # rmtree = hapus folder beserta seluruh isinya
    # Ultralytics mewajibkan struktur folder seperti ini.
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (BUILD_DIR / sub).mkdir(parents=True, exist_ok=True)

    # random.Random(seed) membuat pengacak dengan "benih" tetap. Dengan benih
    # yang sama, hasil acakannya SELALU sama tiap kali dijalankan. Ini penting
    # supaya perbandingan antar-percobaan training tetap adil.
    random.Random(seed).shuffle(labeled)
    # max(1, ...) memastikan minimal ada 1 foto uji walau datasetnya sedikit.
    n_val = max(1, int(len(labeled) * val_ratio))
    # Notasi potong (slice): [:n] = n item pertama, [n:] = sisanya setelah item ke-n.
    val, train = labeled[:n_val], labeled[n_val:]

    for split, items in (("train", train), ("val", val)):
        for p in items:
            # symlink = "jalan pintas" ke file asli, bukan salinan. Isinya tidak
            # digandakan, jadi ruang kartu SD hemat dan prosesnya seketika.
            os.symlink(p.resolve(), BUILD_DIR / f"images/{split}" / p.name)
            os.symlink(_label_path(p.name).resolve(), BUILD_DIR / f"labels/{split}" / (p.stem + ".txt"))

    # Ultralytics butuh file .yaml yang menjelaskan letak data dan nama kelas.
    yaml_path = BUILD_DIR / "dataset.yaml"
    # Beberapa teks berdempetan dalam kurung otomatis disambung jadi satu.
    yaml_path.write_text(
        f"path: {BUILD_DIR.resolve()}\n"    # folder induk dataset
        f"train: images/train\n"            # letak foto latih
        f"val: images/val\n"                # letak foto uji
        f"nc: {len(CLASSES)}\n"             # nc = number of classes (jumlah kelas)
        f"names: {json.dumps(CLASSES)}\n"   # nama tiap kelas, ditulis format JSON
    )
    return yaml_path, len(train), len(val)


# =========================================================
# TRAINING (subprocess ber-nice)
# =========================================================
class Trainer:
    """Menjalankan dan memantau proses pelatihan model."""

    def __init__(self):
        self.proc = None          # objek proses training yang sedang berjalan
        self.lock = threading.Lock()
        self.log = []             # kumpulan baris log untuk ditampilkan di web
        self.running = False      # sedang melatih atau tidak
        self.started_at = None    # waktu mulai (untuk menghitung durasi)
        self.params = {}          # pengaturan yang dipakai sesi ini
        self.result_model = None  # alamat file model hasil training
        self.error = None         # pesan error bila gagal

    def _append(self, line):
        """Menambah satu baris log, dengan batas maksimal 400 baris."""
        self.log.append(line.rstrip())   # rstrip membuang enter/spasi di ujung
        # Batas ini penting: training bisa mencetak ribuan baris. Tanpa batas,
        # memori Raspberry Pi akan terus terpakai sampai habis.
        if len(self.log) > 400:
            # del self.log[:-400] menghapus semua kecuali 400 baris terakhir.
            del self.log[:-400]

    def start(self, epochs=40, imgsz=416, batch=8, freeze=10, base_model=None):
        """Memulai training. Mengembalikan (berhasil?, pesan/nama_run)."""
        with self.lock:
            # Cegah dua training berjalan bersamaan — Pi tidak akan sanggup.
            if self.running:
                return False, "Training sedang berjalan"
            # Bersihkan sisa sesi sebelumnya.
            self.log = []
            self.error = None
            self.result_model = None

            try:
                yaml_path, n_train, n_val = build_split()
            except Exception as exc:
                # str(exc) mengubah objek error menjadi teks pesannya saja.
                return False, str(exc)

            # Titik awal training: model yang diberikan, atau model aktif saat ini.
            base = base_model or str(_active_model_path())
            run_name = datetime.now().strftime("train_%Y%m%d_%H%M%S")
            self.params = {"epochs": epochs, "imgsz": imgsz, "batch": batch,
                           "freeze": freeze, "base": base, "run": run_name,
                           "train_imgs": n_train, "val_imgs": n_val}

            # sys.executable = python venv yang SEDANG menjalankan service.
            # Jangan pakai .resolve() (mengikuti symlink -> /usr/bin/python sistem
            # yang TIDAK punya ultralytics). Ini penyebab 'module not found'.
            venv_py = sys.executable
            # Ini kode Python yang ditulis sebagai TEKS, untuk dijalankan oleh
            # proses terpisah lewat perintah "python -c <kode>".
            # Huruf r di depan r'{base}' berarti "raw string": tanda backslash
            # dalam alamat file dianggap karakter biasa, bukan kode khusus.
            code = (
                "from ultralytics import YOLO;"
                "import torch; torch.set_num_threads(4);"      # pakai 4 core Pi 5
                f"m=YOLO(r'{base}');"
                f"m.train(data=r'{yaml_path}', epochs={epochs}, imgsz={imgsz}, batch={batch},"
                # cache=True  -> simpan gambar di RAM agar tidak bolak-balik baca kartu SD
                # workers=2   -> 2 pekerja penyiap data (jangan banyak, CPU terbatas)
                # device='cpu'-> Pi tidak punya GPU NVIDIA
                # patience=10 -> berhenti otomatis bila 10 epoch tak ada perbaikan
                f" freeze={freeze}, cache=True, workers=2, device='cpu', patience=10,"
                f" project=r'{RUNS_DIR}', name='{run_name}', exist_ok=True, plots=False, val=True)"
            )
            # nice: turunkan prioritas agar web & kamera tetap lancar
            # Angka nice 10 (rentang -20 s/d 19): makin besar makin "mengalah".
            cmd = ["nice", "-n", "10", venv_py, "-c", code]
            self._append(f"$ {' '.join(cmd[:4])} ...")
            self._append(f"# train={n_train} val={n_val} epochs={epochs} imgsz={imgsz} "
                         f"batch={batch} freeze={freeze}")
            # Popen menjalankan program lain TANPA menunggu selesai, sehingga
            # server web tetap bisa melayani permintaan sementara training jalan.
            #   stdout=PIPE          -> tangkap keluarannya agar bisa dibaca
            #   stderr=STDOUT        -> gabungkan pesan error ke keluaran biasa
            #   text=True            -> terima sebagai teks, bukan byte
            #   bufsize=1            -> kirim per baris, agar log tampil real-time
            #   cwd=...              -> folder kerja proses tersebut
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, cwd=str(BASE_DIR))
            self.running = True
            self.started_at = time.time()
            # Thread pembaca log berjalan terpisah agar tidak menghambat web.
            threading.Thread(target=self._pump, daemon=True).start()
            return True, run_name

    def _pump(self):
        """Thread: membaca log training baris demi baris sampai proses selesai."""
        try:
            # Perulangan ini otomatis berhenti saat proses training selesai
            # dan menutup salurannya.
            for line in self.proc.stdout:
                self._append(line)
        except Exception as exc:
            self._append(f"[pump error] {exc}")
        # wait() menunggu proses benar-benar berakhir dan memberi kode keluarnya.
        rc = self.proc.wait()
        self.running = False
        # Aturan umum Linux: kode 0 = sukses, selain 0 = ada masalah.
        if rc == 0:
            # ultralytics bisa menyisipkan subfolder (mis. detect/) -> cari rekursif
            run = self.params.get("run", "")
            # rglob mencari sampai ke dalam semua subfolder (r = recursive).
            # next(..., None) mengambil hasil pertama; None kalau tak ketemu.
            best = next(RUNS_DIR.rglob(f"{run}/weights/best.pt"), None)
            if best is None:  # fallback: best.pt terbaru
                # Urutkan semua best.pt berdasarkan waktu ubah (st_mtime),
                # terbaru di depan, lalu ambil yang pertama.
                cands = sorted(RUNS_DIR.rglob("*/weights/best.pt"),
                               key=lambda p: p.stat().st_mtime, reverse=True)
                best = cands[0] if cands else None
            if best is not None and best.exists():
                self.result_model = str(best)
                self._append(f"[OK] Model selesai: {best}")
            else:
                self.error = "Training selesai tetapi best.pt tidak ditemukan"
                self._append(f"[ERROR] {self.error}")
        else:
            self.error = f"Training gagal (exit {rc})"
            self._append(f"[ERROR] {self.error}")

    def stop(self):
        """Menghentikan training di tengah jalan."""
        with self.lock:
            if self.proc and self.running:
                # SIGINT = sinyal yang sama dengan menekan Ctrl+C di terminal.
                # Dipilih karena "sopan": ultralytics sempat menyimpan hasil
                # sementara sebelum berhenti, tidak dipaksa mati mendadak.
                self.proc.send_signal(signal.SIGINT)
                return True
        return False

    def status(self):
        """Kondisi training terkini, untuk ditampilkan di halaman Training."""
        return {
            "running": self.running,
            "params": self.params,
            # Lama berjalan dalam detik, dibulatkan 1 angka desimal.
            "elapsed": round(time.time() - self.started_at, 1) if self.started_at else None,
            "result_model": self.result_model,
            "error": self.error,
            # [-120:] artinya 120 baris TERAKHIR saja — cukup untuk ditampilkan
            # dan tidak membuat kiriman ke browser jadi berat.
            "log": self.log[-120:],
        }


# =========================================================
# MODEL AKTIF
# =========================================================
def _active_model_path():
    """Mencari letak model yang sedang aktif."""
    # Periksa berurutan; yang pertama ketemu itulah yang dipakai.
    for p in (BASE_DIR / "best.pt", MODEL_DIR / "best.pt"):
        if p.exists():
            return p
    # Tidak ada satu pun -> kembalikan alamat bawaan (walau filenya belum ada).
    return BASE_DIR / "best.pt"


def activate_model(path):
    """Pasang model hasil training sebagai model aktif (backup yang lama)."""
    src = Path(path)
    if not src.exists():
        return False, "File model tidak ditemukan"
    active = BASE_DIR / "best.pt"
    if active.exists():
        # Cadangkan model lama dulu SEBELUM ditimpa, agar bisa dikembalikan
        # kalau ternyata model baru malah lebih buruk.
        backup = MODEL_DIR / datetime.now().strftime("best_backup_%Y%m%d_%H%M%S.pt")
        # copy2 menyalin file lengkap dengan informasi waktunya.
        shutil.copy2(active, backup)
    shutil.copy2(src, active)
    return True, f"Model aktif diganti. Backup: {active.name}"


def list_models():
    """Daftar semua model hasil training beserta ukuran dan waktunya."""
    out = []
    for p in RUNS_DIR.rglob("*/weights/best.pt"):  # rekursif: tahan subfolder ultralytics
        out.append({"path": str(p), "run": p.parent.parent.name,
                    # st_size dalam byte; dibagi 1e6 (satu juta) menjadi megabyte.
                    "size_mb": round(p.stat().st_size / 1e6, 1),
                    # fromtimestamp mengubah waktu bentuk angka menjadi tanggal terbaca.
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")})
    # Urutkan berdasarkan waktu, terbaru di atas.
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


# Satu objek Trainer dipakai bersama seluruh program.
trainer = Trainer()


# =========================================================
# EXPORT MODEL (.pt -> ONNX / NCNN, lebih ringan di Pi/ARM)
#
# UNTUK PEMULA: model .pt adalah format asli PyTorch — pintar tapi berat.
# ONNX dan NCNN adalah format hasil "pemadatan" yang jalan jauh lebih cepat
# di prosesor ARM seperti Raspberry Pi, dengan ketelitian yang hampir sama.
# =========================================================
# Dictionary bersama untuk memantau kemajuan export dari halaman web.
export_state = {"running": False, "format": None, "result": None, "error": None}
_export_lock = threading.Lock()


def export_model_async(fmt="onnx", imgsz=480):
    """Memulai konversi model di latar belakang (tidak menunggu selesai)."""
    # Hanya menerima "ncnn" atau "onnx"; masukan lain otomatis jadi "onnx".
    # Ini pengaman agar nilai dari web tidak bisa sembarangan.
    fmt = "ncnn" if str(fmt).lower() == "ncnn" else "onnx"
    with _export_lock:
        if export_state["running"]:
            return False, "Export sedang berjalan"
        src = _active_model_path()
        if not src.exists():
            return False, "best.pt tidak ditemukan"
        # .update() mengubah beberapa isi dictionary sekaligus.
        export_state.update(running=True, format=fmt, result=None, error=None)
        # args=(...) adalah nilai-nilai yang diserahkan ke fungsi _do_export.
        # Perhatikan koma dan tanda kurung: args wajib berupa tuple.
        threading.Thread(target=_do_export, args=(str(src), fmt, int(imgsz)), daemon=True).start()
        return True, fmt


def _do_export(src, fmt, imgsz):
    """Thread: mengerjakan konversi model yang sesungguhnya."""
    try:
        import torch
        torch.set_num_threads(4)
        from ultralytics import YOLO
        # Muat model lalu ubah formatnya. Proses ini bisa memakan beberapa menit.
        out = YOLO(src).export(format=fmt, imgsz=imgsz)
        export_state["result"] = str(out)
        print(f"[EXPORT] {fmt} selesai: {out}")
    except Exception as exc:
        export_state["error"] = str(exc)
        print(f"[EXPORT] gagal: {exc}")
    finally:
        # Apa pun hasilnya, tandai sudah tidak berjalan — kalau tidak, tombol
        # export di web akan terkunci selamanya.
        export_state["running"] = False


def active_model_kind():
    """Format model yang SEDANG dipakai detector (paling prioritas yang ada)."""
    # Urutan pemeriksaan ini HARUS sama dengan MODEL_CANDIDATES di detector.py,
    # supaya keterangan di web sesuai dengan kenyataan.
    if (BASE_DIR / "best_ncnn_model").exists():
        return "ncnn"
    if (BASE_DIR / "best.onnx").exists():
        return "onnx"
    return "pytorch (.pt)"
