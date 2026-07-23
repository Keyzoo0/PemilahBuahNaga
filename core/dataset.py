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
"""
import json
import os
import random
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "dataset"
IMG_DIR = DATA_DIR / "images"
LBL_DIR = DATA_DIR / "labels"
BUILD_DIR = DATA_DIR / "_build"      # struktur train/val untuk ultralytics
MODEL_DIR = BASE_DIR / "models"
RUNS_DIR = BASE_DIR / "runs"

CLASSES = ["matang", "mentah", "setengah matang"]  # index 0,1,2 (sama dengan model)

for d in (IMG_DIR, LBL_DIR, MODEL_DIR):
    d.mkdir(parents=True, exist_ok=True)


# =========================================================
# DATASET
# =========================================================
def _label_path(name):
    return LBL_DIR / (Path(name).stem + ".txt")


def capture(frame, max_side=640):
    """Simpan frame kamera 1 sebagai gambar dataset (sudah diperkecil)."""
    if frame is None:
        return None
    h, w = frame.shape[:2]
    scale = min(1.0, float(max_side) / max(h, w))
    if scale < 1.0:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
    cv2.imwrite(str(IMG_DIR / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return name


def list_images():
    out = []
    for p in sorted(IMG_DIR.glob("*.jpg"), reverse=True):
        lp = _label_path(p.name)
        n = 0
        if lp.exists():
            n = len([l for l in lp.read_text().splitlines() if l.strip()])
        out.append({"name": p.name, "labeled": n > 0, "boxes": n})
    return out


def delete_image(name):
    name = Path(name).name  # cegah path traversal
    (IMG_DIR / name).unlink(missing_ok=True)
    _label_path(name).unlink(missing_ok=True)
    return True


def get_label(name):
    """Baca label YOLO -> list {cls, cx, cy, w, h} (ternormalisasi 0-1)."""
    lp = _label_path(Path(name).name)
    boxes = []
    if lp.exists():
        for line in lp.read_text().splitlines():
            parts = line.split()
            if len(parts) == 5:
                c, cx, cy, w, h = parts
                boxes.append({"cls": int(c), "cx": float(cx), "cy": float(cy),
                              "w": float(w), "h": float(h)})
    return boxes


def save_label(name, boxes):
    lp = _label_path(Path(name).name)
    lines = []
    for b in boxes:
        c = int(b["cls"])
        cx, cy, w, h = (max(0.0, min(1.0, float(b[k]))) for k in ("cx", "cy", "w", "h"))
        if w <= 0 or h <= 0:
            continue
        lines.append(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    lp.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def stats():
    imgs = list(IMG_DIR.glob("*.jpg"))
    labeled = [p for p in imgs if _label_path(p.name).exists()
               and _label_path(p.name).read_text().strip()]
    per_class = {c: 0 for c in CLASSES}
    for p in labeled:
        for b in get_label(p.name):
            if 0 <= b["cls"] < len(CLASSES):
                per_class[CLASSES[b["cls"]]] += 1
    return {"total": len(imgs), "labeled": len(labeled),
            "unlabeled": len(imgs) - len(labeled), "per_class": per_class}


# =========================================================
# BUILD STRUKTUR ULTRALYTICS (symlink -> hemat ruang & cepat)
# =========================================================
def build_split(val_ratio=0.2, seed=42):
    labeled = [p for p in sorted(IMG_DIR.glob("*.jpg"))
               if _label_path(p.name).exists() and _label_path(p.name).read_text().strip()]
    if len(labeled) < 4:
        raise ValueError(f"Dataset terlabel terlalu sedikit ({len(labeled)}). Minimal 4 gambar.")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (BUILD_DIR / sub).mkdir(parents=True, exist_ok=True)

    random.Random(seed).shuffle(labeled)
    n_val = max(1, int(len(labeled) * val_ratio))
    val, train = labeled[:n_val], labeled[n_val:]

    for split, items in (("train", train), ("val", val)):
        for p in items:
            os.symlink(p.resolve(), BUILD_DIR / f"images/{split}" / p.name)
            os.symlink(_label_path(p.name).resolve(), BUILD_DIR / f"labels/{split}" / (p.stem + ".txt"))

    yaml_path = BUILD_DIR / "dataset.yaml"
    yaml_path.write_text(
        f"path: {BUILD_DIR.resolve()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(CLASSES)}\n"
        f"names: {json.dumps(CLASSES)}\n"
    )
    return yaml_path, len(train), len(val)


# =========================================================
# TRAINING (subprocess ber-nice)
# =========================================================
class Trainer:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.log = []
        self.running = False
        self.started_at = None
        self.params = {}
        self.result_model = None
        self.error = None

    def _append(self, line):
        self.log.append(line.rstrip())
        if len(self.log) > 400:
            del self.log[:-400]

    def start(self, epochs=40, imgsz=416, batch=8, freeze=10, base_model=None):
        with self.lock:
            if self.running:
                return False, "Training sedang berjalan"
            self.log = []
            self.error = None
            self.result_model = None

            try:
                yaml_path, n_train, n_val = build_split()
            except Exception as exc:
                return False, str(exc)

            base = base_model or str(_active_model_path())
            run_name = datetime.now().strftime("train_%Y%m%d_%H%M%S")
            self.params = {"epochs": epochs, "imgsz": imgsz, "batch": batch,
                           "freeze": freeze, "base": base, "run": run_name,
                           "train_imgs": n_train, "val_imgs": n_val}

            venv_py = str((BASE_DIR.parent / ".venv" / "bin" / "python").resolve())
            code = (
                "from ultralytics import YOLO;"
                "import torch; torch.set_num_threads(4);"
                f"m=YOLO(r'{base}');"
                f"m.train(data=r'{yaml_path}', epochs={epochs}, imgsz={imgsz}, batch={batch},"
                f" freeze={freeze}, cache=True, workers=2, device='cpu', patience=10,"
                f" project=r'{RUNS_DIR}', name='{run_name}', exist_ok=True, plots=False, val=True)"
            )
            # nice: turunkan prioritas agar web & kamera tetap lancar
            cmd = ["nice", "-n", "10", venv_py, "-c", code]
            self._append(f"$ {' '.join(cmd[:4])} ...")
            self._append(f"# train={n_train} val={n_val} epochs={epochs} imgsz={imgsz} "
                         f"batch={batch} freeze={freeze}")
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, cwd=str(BASE_DIR))
            self.running = True
            self.started_at = time.time()
            threading.Thread(target=self._pump, daemon=True).start()
            return True, run_name

    def _pump(self):
        try:
            for line in self.proc.stdout:
                self._append(line)
        except Exception as exc:
            self._append(f"[pump error] {exc}")
        rc = self.proc.wait()
        self.running = False
        if rc == 0:
            best = RUNS_DIR / self.params.get("run", "") / "weights" / "best.pt"
            if best.exists():
                self.result_model = str(best)
                self._append(f"[OK] Model selesai: {best}")
            else:
                self.error = "Training selesai tetapi best.pt tidak ditemukan"
                self._append(f"[ERROR] {self.error}")
        else:
            self.error = f"Training gagal (exit {rc})"
            self._append(f"[ERROR] {self.error}")

    def stop(self):
        with self.lock:
            if self.proc and self.running:
                self.proc.send_signal(signal.SIGINT)
                return True
        return False

    def status(self):
        return {
            "running": self.running,
            "params": self.params,
            "elapsed": round(time.time() - self.started_at, 1) if self.started_at else None,
            "result_model": self.result_model,
            "error": self.error,
            "log": self.log[-120:],
        }


# =========================================================
# MODEL AKTIF
# =========================================================
def _active_model_path():
    for p in (BASE_DIR / "best.pt", MODEL_DIR / "best.pt"):
        if p.exists():
            return p
    return BASE_DIR / "best.pt"


def activate_model(path):
    """Pasang model hasil training sebagai model aktif (backup yang lama)."""
    src = Path(path)
    if not src.exists():
        return False, "File model tidak ditemukan"
    active = BASE_DIR / "best.pt"
    if active.exists():
        backup = MODEL_DIR / datetime.now().strftime("best_backup_%Y%m%d_%H%M%S.pt")
        shutil.copy2(active, backup)
    shutil.copy2(src, active)
    return True, f"Model aktif diganti. Backup: {active.name}"


def list_models():
    out = []
    for p in sorted(RUNS_DIR.glob("*/weights/best.pt")):
        out.append({"path": str(p), "run": p.parent.parent.name,
                    "size_mb": round(p.stat().st_size / 1e6, 1),
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")})
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


trainer = Trainer()
