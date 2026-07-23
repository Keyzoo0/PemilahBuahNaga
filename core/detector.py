"""
YOLODetector — wrapper YOLOv8 (ultralytics). Otomatis pakai model NCNN
kalau tersedia (best_ncnn_model/) untuk kecepatan di Pi 5.
"""
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2

BASE_DIR = Path(__file__).resolve().parent
# best.pt diletakkan sejajar core/ (dari zip) atau di dalam core/
MODEL_CANDIDATES = [
    BASE_DIR / "best_ncnn_model",
    BASE_DIR / "best.pt",
    BASE_DIR.parent / "best.pt",
]

# normalisasi label model -> label baku Indonesia
LABEL_MAP = {
    "matang": "matang", "ripe": "matang",
    "mentah": "mentah", "unripe": "mentah", "raw": "mentah",
    "setengah matang": "setengah matang", "half ripe": "setengah matang",
    "setengah": "setengah matang",
}


def normalize_label(label):
    if not label:
        return None
    return LABEL_MAP.get(str(label).lower().strip().replace("_", " ").replace("-", " "), str(label).lower())


@dataclass
class Detection:
    label: str
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float
    cls_id: int = -1

    @property
    def cx(self):
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self):
        return (self.y1 + self.y2) / 2.0

    @property
    def area(self):
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


class YOLODetector:
    def __init__(self):
        import torch
        torch.set_num_threads(4)  # Pi 5: pakai semua core (default 1 -> 4x lebih lambat)
        from ultralytics import YOLO
        model_path = next((p for p in MODEL_CANDIDATES if p.exists()), None)
        if model_path is None:
            raise FileNotFoundError(
                "best.pt tidak ditemukan. Letakkan best.pt di core/ atau folder proyek."
            )
        print(f"[YOLO] Memuat model: {model_path}")
        self.model = YOLO(str(model_path))
        self.lock = threading.Lock()
        # index kelas asli dari model: {0: 'matang', 1: 'mentah', 2: 'setengah matang'}
        self.class_names = {int(k): normalize_label(v) for k, v in self.model.names.items()}
        self.label_to_index = {v: k for k, v in self.class_names.items()}
        print(f"[YOLO] Model siap. Kelas: {self.class_names}")

    def infer(self, frame, imgsz=480, conf=0.25):
        if frame is None:
            return []
        with self.lock:
            results = self.model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)
        dets = []
        r = results[0]
        for box in r.boxes:
            cid = int(box.cls[0])
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
            dets.append(Detection(normalize_label(r.names[cid]), float(box.conf[0]), x1, y1, x2, y2, cid))
        return dets


def filter_dets(dets, roi, min_area, conf_threshold, conf_per_class):
    """Saring deteksi: dalam ROI, cukup besar, dan lolos threshold per-kelas."""
    out = []
    for d in dets:
        thr = conf_per_class.get(d.label, conf_threshold) if conf_per_class else conf_threshold
        if d.conf < thr:
            continue
        if d.area < min_area:
            continue
        if roi and not (roi["x"] <= d.cx <= roi["x"] + roi["w"] and roi["y"] <= d.cy <= roi["y"] + roi["h"]):
            continue
        out.append(d)
    return out


def draw_overlay(frame, dets, roi=None, state="", extra=""):
    """Gambar bounding box, ROI, dan teks status untuk stream monitoring."""
    if frame is None:
        return frame
    colors = {"matang": (0, 200, 0), "setengah matang": (0, 200, 255), "mentah": (0, 0, 230)}
    if roi:
        cv2.rectangle(frame, (int(roi["x"]), int(roi["y"])),
                      (int(roi["x"] + roi["w"]), int(roi["y"] + roi["h"])), (181, 23, 91), 2)
    for d in dets:
        c = colors.get(d.label, (200, 200, 200))
        cv2.rectangle(frame, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)), c, 2)
        cv2.putText(frame, f"{d.label} {d.conf:.2f}", (int(d.x1), max(18, int(d.y1) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
    banner = f"{state}"
    if extra:
        banner += f" | {extra}"
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 30), (20, 20, 25), -1)
    cv2.putText(frame, banner[:80], (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return frame
