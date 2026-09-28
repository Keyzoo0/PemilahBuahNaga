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
import csv           # membaca results.csv hasil training
import hashlib       # sidik jari file/nama (pembagian val stabil, cek model aktif)
import json          # membaca/menulis format JSON
import os            # urusan sistem operasi (di sini: membuat symlink)
import re            # pola teks, untuk memvalidasi nama run dari web
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
def _is_val(name, val_ratio):
    """Apakah foto ini masuk data uji? Ditentukan oleh sidik jari NAMA filenya.

    md5 mengubah nama file menjadi angka acak-tapi-tetap: nama yang sama
    selalu menghasilkan angka yang sama. Jadi sebuah foto SELAMANYA berada di
    kelompok yang sama, walau dataset terus bertambah. Dulu pembagian diacak
    ulang tiap training sehingga foto uji hari ini bisa jadi foto latih
    kemarin — nilai model jadi terlihat lebih bagus dari kenyataannya.
    """
    h = int(hashlib.md5(Path(name).stem.encode()).hexdigest()[:8], 16)
    return (h % 1000) < val_ratio * 1000


def build_split(val_ratio=0.2):
    """Membagi dataset menjadi data latih (train) dan data uji (val).

    Kenapa dibagi? Kalau AI diuji dengan foto yang sama persis seperti saat
    belajar, nilainya pasti bagus tapi menipu — seperti ujian dengan bocoran
    soal. Sebagian foto sengaja disisihkan (val) sebagai soal "baru" untuk
    mengukur kepintaran sesungguhnya.

    val_ratio=0.2 artinya ±20% untuk uji, ±80% untuk belajar.
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

    val = [p for p in labeled if _is_val(p.name, val_ratio)]
    train = [p for p in labeled if not _is_val(p.name, val_ratio)]
    # Dataset yang sangat kecil bisa saja tidak kebagian foto uji/latih sama
    # sekali -> pindahkan satu foto agar keduanya tidak kosong.
    if not val:
        val.append(train.pop())
    elif not train:
        train.append(val.pop())

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
        self.run_dir = None       # folder run yang sedang/terakhir berjalan
        self.log_fh = None        # file train.log yang sedang ditulis

    def _append(self, line):
        """Menambah satu baris log, dengan batas maksimal 400 baris di memori.

        Log LENGKAP juga ditulis ke runs/<run>/train.log agar tetap bisa dibaca
        dari tab Training walau service sudah restart.
        """
        line = line.rstrip()                # rstrip membuang enter/spasi di ujung
        self.log.append(line)
        if self.log_fh:
            self.log_fh.write(line + "\n")
            self.log_fh.flush()
        # Batas ini penting: training bisa mencetak ribuan baris. Tanpa batas,
        # memori Raspberry Pi akan terus terpakai sampai habis.
        if len(self.log) > 400:
            # del self.log[:-400] menghapus semua kecuali 400 baris terakhir.
            del self.log[:-400]

    def start(self, epochs=40, imgsz=416, batch=8, freeze=10, base_model=None, fresh=False):
        """Memulai training. Mengembalikan (berhasil?, pesan/nama_run).

        fresh=True -> mulai dari yolov8n.pt (belum pernah melihat dataset ini),
        bukan melanjutkan model aktif. Berguna untuk mendapat nilai evaluasi
        yang jujur setelah pembagian data uji diperbaiki.
        """
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
            # Kalau best.pt tak ada (mis. sengaja dihapus utk retrain dari nol)
            # atau diminta fresh, pakai yolov8n.pt pretrained.
            active = _active_model_path()
            pretrained = BASE_DIR / "yolov8n.pt"
            pretrained = str(pretrained) if pretrained.exists() else "yolov8n.pt"  # tak ada -> diunduh ultralytics
            if base_model:
                base = base_model
            elif fresh or not active.exists():
                base = pretrained
            else:
                base = str(active)
            run_name = datetime.now().strftime("train_%Y%m%d_%H%M%S")
            run_dir = RUNS_DIR / run_name
            run_dir.mkdir(parents=True, exist_ok=True)
            self.params = {"epochs": epochs, "imgsz": imgsz, "batch": batch,
                           "freeze": freeze, "base": base, "run": run_name,
                           "train_imgs": n_train, "val_imgs": n_val}

            # sys.executable = python venv yang SEDANG menjalankan service.
            # Jangan pakai .resolve() (mengikuti symlink -> /usr/bin/python sistem
            # yang TIDAK punya ultralytics). Ini penyebab 'module not found'.
            venv_py = sys.executable
            # Semua pengaturan dikirim ke train_worker.py sebagai satu teks JSON.
            cfg = {"run_dir": str(run_dir), "data": str(yaml_path), "base": base,
                   "params": self.params}
            # nice: turunkan prioritas agar web & kamera tetap lancar
            # Angka nice 10 (rentang -20 s/d 19): makin besar makin "mengalah".
            cmd = ["nice", "-n", "10", venv_py, str(BASE_DIR / "train_worker.py"), json.dumps(cfg)]
            self.run_dir = run_dir
            self.log_fh = open(run_dir / "train.log", "a")
            self._append(f"$ {' '.join(cmd[:5])} ...")
            self._append(f"# train={n_train} val={n_val} epochs={epochs} imgsz={imgsz} "
                         f"batch={batch} freeze={freeze} base={Path(base).name}")
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
        meta = _read_json(self.run_dir / "run.json") or {"run": self.run_dir.name}
        # Worker mati sebelum sempat menulis status (mis. gagal import) -> tandai gagal.
        if meta.get("status") in (None, "running"):
            meta.update(status="failed", error=f"Proses training berhenti (exit {rc})",
                        finished=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            (self.run_dir / "run.json").write_text(json.dumps(meta, indent=2))
        best = self.run_dir / "weights" / "best.pt"
        if best.exists():
            self.result_model = str(best)
            label = "dihentikan" if meta["status"] == "stopped" else "selesai"
            self._append(f"[OK] Training {label}. Model: {best}")
        else:
            self.error = meta.get("error") or f"Training gagal (exit {rc})"
            self._append(f"[ERROR] {self.error}")
        self.log_fh.close()
        self.log_fh = None
        prune_runs()
        # running dimatikan PALING AKHIR: web memakai perubahan ini sebagai
        # tanda untuk memuat ulang riwayat, jadi eval & pemangkasan harus sudah beres.
        self.running = False

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


# =========================================================
# RIWAYAT TRAINING (tab Training -> klik run -> confusion matrix dll)
# =========================================================
KEEP_RUNS = 10                                  # run yang disimpan; sisanya dihapus
RUN_NAME = re.compile(r"^train_\d{8}_\d{6}$")   # pola nama run yang sah
EVAL_FILE = re.compile(r"^[\w.-]+\.(png|jpg)$") # file gambar eval yang boleh diambil web
_md5_cache = {}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _run_dirs():
    """Semua folder run, terbaru dulu (nama berisi tanggal-jam, jadi urut nama = urut waktu)."""
    return sorted((d for d in RUNS_DIR.glob("train_*") if d.is_dir() and RUN_NAME.match(d.name)),
                  key=lambda d: d.name, reverse=True)


def prune_runs(keep=KEEP_RUNS):
    """Hapus folder run selain `keep` run terbaru. Model aktif (core/best.pt)
    adalah SALINAN, jadi tidak ikut terhapus."""
    for d in _run_dirs()[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def _read_args(run_dir):
    """args.yaml ultralytics isinya datar 'kunci: nilai' -> cukup dibaca per baris."""
    out = {}
    try:
        for line in (run_dir / "args.yaml").read_text().splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read_curves(run_dir):
    """results.csv -> daftar metrik per epoch untuk grafik di web."""
    rows = []
    try:
        with open(run_dir / "results.csv", newline="") as f:
            for r in csv.DictReader(f):
                r = {k.strip(): v for k, v in r.items()}
                loss = lambda s: sum(_num(r.get(f"{s}/{k}_loss")) or 0 for k in ("box", "cls", "dfl"))
                rows.append({
                    "epoch": int(float(r["epoch"])),
                    "time": _num(r.get("time")),
                    "precision": _num(r.get("metrics/precision(B)")),
                    "recall": _num(r.get("metrics/recall(B)")),
                    "map50": _num(r.get("metrics/mAP50(B)")),
                    "map50_95": _num(r.get("metrics/mAP50-95(B)")),
                    "train_loss": round(loss("train"), 5),
                    "val_loss": round(loss("val"), 5),
                })
    except (OSError, KeyError, ValueError):
        pass
    return rows


def _legacy_meta(run_dir, curves, args):
    """Run lama (sebelum ada run.json): tebak statusnya dari results.csv.

    Aturan early-stop ultralytics: berhenti bila `patience` epoch berturut-turut
    mAP50-95 tidak membaik. Kalau jumlah epoch belum penuh dan aturan itu tidak
    terpenuhi, berarti dihentikan manual.
    """
    meta = {"run": run_dir.name, "legacy": True}
    if not curves:
        meta["status"] = "failed"
        return meta
    target = int(_num(args.get("epochs")) or 0)
    patience = int(_num(args.get("patience")) or 100)
    done = curves[-1]["epoch"]
    scores = [c["map50_95"] or 0 for c in curves]
    best_epoch = curves[scores.index(max(scores))]["epoch"]
    meta["status"] = "completed" if done >= target or done - best_epoch >= patience else "stopped"
    return meta


def _file_md5(path):
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime)
    if key not in _md5_cache:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _md5_cache[key] = h.hexdigest()
    return _md5_cache[key]


def _is_active(best):
    """Model run ini sama persis dengan core/best.pt yang sedang dipakai?"""
    active = BASE_DIR / "best.pt"
    if not (best.exists() and active.exists()):
        return False
    # Bandingkan ukuran dulu (murah); hitung md5 hanya kalau ukurannya sama.
    return best.stat().st_size == active.stat().st_size and _file_md5(best) == _file_md5(active)


def _run_summary(run_dir):
    args = _read_args(run_dir)
    curves = _read_curves(run_dir)
    meta = _read_json(run_dir / "run.json") or _legacy_meta(run_dir, curves, args)
    ev = _read_json(run_dir / "eval.json")
    best = run_dir / "weights" / "best.pt"
    # Run yang masih berjalan milik Trainer; status di file bisa tertinggal.
    running = trainer.running and trainer.run_dir == run_dir
    return {
        "run": run_dir.name,
        "started": datetime.strptime(run_dir.name, "train_%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
        "status": "running" if running else meta.get("status"),
        "legacy": meta.get("legacy", False),
        "epochs_done": curves[-1]["epoch"] if curves else 0,
        "epochs": int(_num(args.get("epochs")) or meta.get("params", {}).get("epochs") or 0),
        "duration_s": curves[-1]["time"] if curves else None,
        "has_model": best.exists(),
        "model_path": str(best) if best.exists() else None,
        "is_active": _is_active(best),
        "eval": ({"retro": ev.get("retro", False), **ev["overall"]} if ev else None),
    }


def list_runs():
    """Ringkasan run terbaru (maksimal KEEP_RUNS) untuk tabel riwayat."""
    return [_run_summary(d) for d in _run_dirs()[:KEEP_RUNS]]


def _run_dir(run):
    """Nama run dari web -> folder. None kalau nama tidak sah / tidak ada."""
    if not RUN_NAME.match(run or ""):
        return None
    d = RUNS_DIR / run
    return d if d.is_dir() else None


def run_detail(run):
    """Semua isi satu run: ringkasan, confusion matrix, kurva, parameter, log."""
    d = _run_dir(run)
    if d is None:
        return None
    meta = _read_json(d / "run.json") or {}
    args = _read_args(d)
    log = []
    try:
        log = (d / "train.log").read_text(errors="replace").splitlines()[-300:]
    except OSError:
        pass
    eval_dir = d / "eval"
    images = sorted(p.name for p in eval_dir.glob("*") if EVAL_FILE.match(p.name)) if eval_dir.is_dir() else []
    return {
        **_run_summary(d),
        "params": {k: args.get(k) for k in ("model", "epochs", "imgsz", "batch", "freeze", "patience")},
        "train_imgs": meta.get("params", {}).get("train_imgs"),
        "error": meta.get("error"),
        "eval_error": meta.get("eval_error"),
        "eval_detail": _read_json(d / "eval.json"),
        "curves": _read_curves(d),
        "log": log,
        "images": images,
    }


def run_file(run, name):
    """Alamat gambar eval yang aman untuk dikirim ke browser, atau None."""
    d = _run_dir(run)
    if d is None or not EVAL_FILE.match(name):
        return None
    p = d / "eval" / name
    return p if p.is_file() else None


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
