"""
CameraManager — 2 kamera USB (identifikasi by USB bus-key) dengan SELF-HEALING.

Karena kamera dicolok permanen, target utama: sistem harus PULIH SENDIRI dari
gagal init, terputus, atau stream nge-hang — tanpa intervensi manual.

Lapisan pemulihan:
  1. Init diserialkan (_OPEN_LOCK) + di-stagger; cam2 baru dibuka setelah cam1
     benar-benar streaming -> hindari race V4L2/REQBUFS dua kamera identik.
  2. Pembukaan diverifikasi dengan MEMBACA frame (isOpened() tidak cukup).
  3. Watchdog: kalau kamera yang tadinya sehat berhenti mengirim frame
     (hang/putus), otomatis release + reopen.
  4. Eskalasi: setelah beberapa kali gagal buka, RESET port USB device
     (unbind/bind via sudo) untuk membangunkan device yang wedged, lalu
     lanjut retry. Semua best-effort; kalau reset gagal tetap retry biasa.
"""
import glob
import os
import re
import subprocess
import threading
import time

import cv2

# Serialkan init: cuma satu VideoCapture dibuka pada satu waktu.
_OPEN_LOCK = threading.Lock()


def candidates_by_bus_key(bus_key):
    """Semua node /dev/videoN untuk bus_key tertentu (tanpa membukanya)."""
    out = []
    for vf in sorted(glob.glob("/dev/video[0-9]*"), key=lambda p: int(re.sub(r"\D", "", p) or 0)):
        dev_name = os.path.basename(vf)
        name_file = f"/sys/class/video4linux/{dev_name}/name"
        dev_link = f"/sys/class/video4linux/{dev_name}/device"
        if not os.path.exists(name_file) or not os.path.exists(dev_link):
            continue
        real = os.path.realpath(dev_link)
        m = re.search(r"usb(\d+)/(\d+-\d+)", real)
        if m and f"usb{m.group(1)}-{m.group(2)}" == bus_key:
            out.append(vf)
    return out


def resolve_device_by_bus_key(bus_key):  # kompat lama
    c = candidates_by_bus_key(bus_key)
    return c[0] if c else None


def _usb_id_for_bus_key(bus_key):
    """ID USB device untuk unbind/bind (mis. '1-1' atau '3-1') dari bus_key."""
    for vf in candidates_by_bus_key(bus_key):
        real = os.path.realpath(f"/sys/class/video4linux/{os.path.basename(vf)}/device")
        # real berakhir pada antarmuka spt '.../1-1/1-1:1.0'
        iface = os.path.basename(real)          # '1-1:1.0'
        usb_id = iface.split(":")[0]            # '1-1'
        if re.match(r"^\d+-\d+", usb_id):
            return usb_id
    # cadangan: turunkan dari bus_key 'usbB-P-Q' -> 'P-Q'
    m = re.match(r"usb\d+-(\d+-\d+)", bus_key)
    return m.group(1) if m else None


DRV = "/sys/bus/usb/drivers/usb"


def _write_drv(fname, value):
    """Tulis ke bind/unbind. Coba langsung (file di-chmod o+w oleh service saat
    start via ExecStartPre root); kalau ditolak, fallback ke sudo -n."""
    path = f"{DRV}/{fname}"
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except PermissionError:
        r = subprocess.run(["sudo", "-n", "sh", "-c", f"printf %s '{value}' > {path}"],
                           capture_output=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


def usb_reset(bus_key):
    """Reset (re-enumerate) USB device lewat unbind/bind -> membangunkan device
    yang wedged/hang. Tidak butuh sudo bila file sudah di-chmod saat start."""
    usb_id = _usb_id_for_bus_key(bus_key)
    if not usb_id:
        return False
    ok_u = _write_drv("unbind", usb_id)
    time.sleep(1.5)
    ok_b = _write_drv("bind", usb_id)
    time.sleep(2.0)  # tunggu re-enumerate
    print(f"[CAM] USB reset {bus_key} (id {usb_id}) unbind={ok_u} bind={ok_b}")
    return ok_b


class CameraStream:
    def __init__(self, name, bus_key, width, height, fps, cfg=None):
        self.name = name
        self.bus_key = bus_key
        self.width = width
        self.height = height
        self.fps = fps
        cfg = cfg or {}
        self._verify_reads = int(cfg.get("open_verify_reads", 15))
        self._reset_after = int(cfg.get("reset_after_failures", 4))
        self._enable_reset = bool(cfg.get("enable_usb_reset", True))
        self._stall_seconds = float(cfg.get("stall_seconds", 4.0))

        self.device = None
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.last_ok = 0.0
        self._fps_count = 0
        self._fps_t = time.time()
        self.actual_fps = 0.0
        self._fail_reads = 0
        self._open_fails = 0
        self.reopen_count = 0
        self.reset_count = 0

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    # ---- pembukaan ----
    def _try_device(self, dev):
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(self._verify_reads):
            ok, frame = cap.read()
            if ok and frame is not None:
                return cap
            time.sleep(0.12)
        cap.release()
        return None

    def _open(self):
        # Hanya bagian buka device yang di-lock (JANGAN panggil reset di dalam
        # lock -> Lock tidak reentrant -> deadlock).
        with _OPEN_LOCK:
            cands = candidates_by_bus_key(self.bus_key)
            for dev in cands:
                cap = self._try_device(dev)
                if cap is not None:
                    self.cap = cap
                    self.device = dev
                    self._fail_reads = 0
                    self._open_fails = 0
                    print(f"[CAM {self.name}] {dev} ({self.bus_key}) streaming ✓")
                    return True
        self._open_fails += 1
        if cands:
            print(f"[CAM {self.name}] {self.bus_key} ada {cands} tapi belum streaming "
                  f"(gagal ke-{self._open_fails})")
        self._maybe_reset()  # di luar lock
        return False

    def _maybe_reset(self):
        if self._enable_reset and self._open_fails >= self._reset_after:
            print(f"[CAM {self.name}] {self._open_fails}x gagal -> reset USB {self.bus_key}")
            with _OPEN_LOCK:  # aman: dipanggil dari _loop, bukan dari dalam _open
                if usb_reset(self.bus_key):
                    self.reset_count += 1
            self._open_fails = 0

    # ---- loop utama ----
    def _loop(self):
        while self.running:
            if self.cap is None:
                if not self._open():
                    time.sleep(2)
                continue

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._fail_reads += 1
                if self._fail_reads >= 5:
                    print(f"[CAM {self.name}] {self._fail_reads}x gagal baca -> reopen")
                    self._release_cap()
                    self.reopen_count += 1
                    time.sleep(0.4)
                else:
                    time.sleep(0.05)
                continue

            self._fail_reads = 0
            with self.lock:
                self.frame = frame
                self.last_ok = time.time()
            self._fps_count += 1
            now = time.time()
            if now - self._fps_t >= 1.0:
                self.actual_fps = self._fps_count / (now - self._fps_t)
                self._fps_count = 0
                self._fps_t = now

    def _release_cap(self):
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass
        self.cap = None

    # ---- akses ----
    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def healthy(self):
        return (time.time() - self.last_ok) < 2.0 if self.last_ok else False

    def wait_healthy(self, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.healthy():
                return True
            time.sleep(0.2)
        return False

    def stop(self):
        self.running = False
        self._release_cap()

    def stats(self):
        return {"device": self.device, "healthy": self.healthy(),
                "fps": round(self.actual_fps, 1), "reopen": self.reopen_count,
                "usb_reset": self.reset_count}


class CameraManager:
    def __init__(self, cfg):
        cam = cfg.get("camera")
        self._stagger = float(cam.get("init_stagger_seconds", 1.5))
        self.cam1 = CameraStream("1-deteksi", cam["cam1_bus_key"], cam["width"], cam["height"], cam["fps"], cam)
        self.cam2 = CameraStream("2-sorting", cam["cam2_bus_key"], cam["width"], cam["height"], cam["fps"], cam)
        self._watchdog_running = False

    def start(self):
        # Init benar-benar berurutan: cam1 dulu sampai streaming, baru cam2.
        self.cam1.start()
        if not self.cam1.wait_healthy(timeout=self._stagger + 6):
            print("[CAM] cam1 belum sehat saat stagger; cam2 tetap dimulai (self-heal jalan)")
        time.sleep(self._stagger)
        self.cam2.start()

        self._watchdog_running = True
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        """Deteksi kamera yang tadinya sehat lalu hang -> paksa reopen."""
        while self._watchdog_running:
            time.sleep(2.0)
            for cam in (self.cam1, self.cam2):
                # sudah pernah dapat frame, tapi kini basi > stall_seconds -> hang
                if cam.last_ok and (time.time() - cam.last_ok) > cam._stall_seconds and cam.cap is not None:
                    print(f"[CAM {cam.name}] STALL {time.time() - cam.last_ok:.1f}s -> reopen paksa")
                    cam._release_cap()
                    cam.reopen_count += 1

    def stop(self):
        self._watchdog_running = False
        self.cam1.stop()
        self.cam2.stop()
