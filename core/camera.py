"""
CameraManager — buka 2 kamera USB dengan identifikasi by USB bus-key
(anti-tertukar saat reboot). Tiap kamera dibaca di thread sendiri.
"""
import glob
import os
import re
import threading
import time

import cv2


def resolve_device_by_bus_key(bus_key):
    """Cari /dev/videoN yang cocok dengan bus_key (mis. 'usb1-1-1')."""
    for vf in sorted(glob.glob("/dev/video[0-9]*"), key=lambda p: int(re.sub(r"\D", "", p) or 0)):
        dev_name = os.path.basename(vf)
        name_file = f"/sys/class/video4linux/{dev_name}/name"
        dev_link = f"/sys/class/video4linux/{dev_name}/device"
        if not os.path.exists(name_file) or not os.path.exists(dev_link):
            continue
        real = os.path.realpath(dev_link)
        m = re.search(r"usb(\d+)/(\d+-\d+)", real)
        if not m:
            continue
        key = f"usb{m.group(1)}-{m.group(2)}"
        if key == bus_key:
            # pastikan node ini capture (bukan metadata)
            try:
                cap = cv2.VideoCapture(vf, cv2.CAP_V4L2)
                ok = cap.isOpened()
                cap.release()
                if ok:
                    return vf
            except Exception:
                continue
    return None


class CameraStream:
    def __init__(self, name, bus_key, width, height, fps):
        self.name = name
        self.bus_key = bus_key
        self.width = width
        self.height = height
        self.fps = fps
        self.device = None
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.last_ok = 0.0
        self._fps_count = 0
        self._fps_t = time.time()
        self.actual_fps = 0.0

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _open(self):
        self.device = resolve_device_by_bus_key(self.bus_key)
        if self.device is None:
            return False
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            return False
        self.cap = cap
        print(f"[CAM {self.name}] {self.device} ({self.bus_key}) terbuka")
        return True

    def _loop(self):
        while self.running:
            if self.cap is None:
                if not self._open():
                    print(f"[CAM {self.name}] bus_key {self.bus_key} belum ditemukan, retry 2s...")
                    time.sleep(2)
                    continue
            ok, frame = self.cap.read()
            if not ok:
                print(f"[CAM {self.name}] gagal baca frame, reopen...")
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
                time.sleep(0.5)
                continue
            with self.lock:
                self.frame = frame
                self.last_ok = time.time()
            self._fps_count += 1
            now = time.time()
            if now - self._fps_t >= 1.0:
                self.actual_fps = self._fps_count / (now - self._fps_t)
                self._fps_count = 0
                self._fps_t = now

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def healthy(self):
        return (time.time() - self.last_ok) < 2.0 if self.last_ok else False

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


class CameraManager:
    def __init__(self, cfg):
        cam = cfg.get("camera")
        self.cam1 = CameraStream("1-deteksi", cam["cam1_bus_key"], cam["width"], cam["height"], cam["fps"])
        self.cam2 = CameraStream("2-sorting", cam["cam2_bus_key"], cam["width"], cam["height"], cam["fps"])

    def start(self):
        self.cam1.start()
        self.cam2.start()

    def stop(self):
        self.cam1.stop()
        self.cam2.stop()
