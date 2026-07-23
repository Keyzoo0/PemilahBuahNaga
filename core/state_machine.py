"""
SortController — state machine sortasi buah naga (alur terkoreksi).

Alur:
  IDLE (motor stop, pantau cam1)
    - objek/gerakan muncul -> masuk mode "watch"
    - GERBANG SETTLE: tunggu gerakan berhenti (tangan pergi) selama settle_frames
    - setelah settle:
        * terdeteksi BUAH NAGA -> mundur ke servo (sortir)
            matang           -> STRAIGHT_OUT (mundur lurus keluar +5s)
            mentah           -> SERVO_SORT servo1 (mundur, cam2 track, tampol)
            setengah matang  -> SERVO_SORT servo2
        * ada objek tapi BUKAN buah naga -> REJECT_FORWARD (maju buang)
        * kosong -> tetap IDLE
  COOLDOWN -> IDLE
  FAULT (watchdog motor / anomali)

Optimasi Pi: cam1 di-inference hanya saat ada aktivitas (watch); cam2 saat sorting.
Anti-tangan: keputusan hanya diambil saat scene stabil (tidak ada gerakan).
"""
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2

from detector import filter_dets, draw_overlay
from store import store

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
EMPTY_REF = BASE_DIR / "empty_ref.jpg"


def best_det(dets):
    return max(dets, key=lambda d: d.conf) if dets else None


class SortController:
    def __init__(self, cfg, cams, detector, bridge):
        self.cfg = cfg
        self.cams = cams
        self.detector = detector
        self.bridge = bridge

        self.state = "IDLE"
        self.ripeness = None
        self.ripeness_index = None   # index kelas asli model (0/1/2)
        self.ripeness_conf = 0.0
        self.last_message = "Menunggu objek di kamera 1"
        self.last_action = None

        self._votes = Counter()
        self._watching = False      # True setelah objek/gerakan masuk (tetap awasi walau diam)
        self._settle_low = 0        # frame berturut-turut tanpa gerakan
        self._empty = 0             # frame kosong (untuk fase cam2)
        self._prev_gray = None      # untuk deteksi gerakan
        self._t_state = time.time()
        self._t_motor = 0.0
        self._snapshot_path = None
        self._active_servo = 1
        self._last_motion = 0.0
        self._last_fg = None
        self._led_status = None     # status indikator terakhir yang dikirim
        self._t_last_bip = 0.0      # penanda bip-bip terakhir saat sorting

        self.estop = False
        self.manual_mode = cfg.get("system", "start_mode", default="manual") == "manual"
        if self.manual_mode:
            self.last_message = "Boot mode MANUAL — klik AUTO di web untuk mulai sortasi"
        self.running = False

        self.annotated = {"cam1": None, "cam2": None}
        self._ann_lock = threading.Lock()
        self.fault_count = 0

        # latar belt kosong (untuk deteksi objek reject)
        self._empty_ref = None
        if EMPTY_REF.exists():
            img = cv2.imread(str(EMPTY_REF))
            if img is not None:
                self._empty_ref = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                print("[SM] Latar kosong dimuat dari empty_ref.jpg")

    # ---------------------------------------------------------
    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _set_annotated(self, key, frame):
        if frame is None:
            return
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self._ann_lock:
                self.annotated[key] = buf.tobytes()

    def get_jpeg(self, key):
        with self._ann_lock:
            return self.annotated.get(key)

    # ---------------------------------------------------------
    def _transition(self, state, msg=None):
        self.state = state
        self._t_state = time.time()
        if msg:
            self.last_message = msg
        print(f"[SM] -> {state} :: {self.last_message}")

    def _enter_fault(self, reason):
        self.bridge.motor_stop()
        self.bridge.s1_close()
        self.bridge.s2_close()
        self.fault_count += 1
        self._transition("FAULT", f"FAULT: {reason}")

    def _motor_watchdog(self):
        limit = float(self.cfg.get("timing", "max_motor_runtime_seconds", default=15.0))
        if self._t_motor and (time.time() - self._t_motor) > limit:
            self._enter_fault("motor melebihi batas waktu (objek tidak terdeteksi keluar)")
            return True
        return False

    # ---------------------------------------------------------
    # INDIKATOR LED & BUZZER (status sistem)
    #   KUNING = Raspi belum siap
    #   HIJAU  = siap, buah boleh ditaruh di kamera 1
    #   MERAH  = sedang sorting (buzzer bip-bip)
    #   transisi ke HIJAU = bip panjang 1.5 detik
    # ---------------------------------------------------------
    _LED_BY_STATUS = {"ready": "green", "busy": "red", "notready": "yellow"}
    _BUSY_STATES = ("REJECT_FORWARD", "STRAIGHT_OUT", "STRAIGHT_EXTRA",
                    "SERVO_SORT", "SERVO_RETURN", "COOLDOWN")

    def _indicator_status(self):
        if (self.estop or self.manual_mode or self.state == "FAULT"
                or not self.bridge.connected
                or not self.cams.cam1.healthy() or not self.cams.cam2.healthy()):
            return "notready"
        if self.state in self._BUSY_STATES:
            return "busy"
        return "ready"  # IDLE = siap ditaruh buah

    def _apply_status_led(self, status):
        want = self._LED_BY_STATUS[status]
        for color in ("green", "yellow", "red"):
            self.bridge.send(f"led {color} {1 if color == want else 0}")

    def _long_beep(self):
        ms = int(self.cfg.get("feedback", "ready_beep_ms", default=1500))
        self.bridge.send("buzzer on")
        threading.Timer(ms / 1000.0, lambda: self.bridge.send("buzzer off")).start()

    def _update_indicators(self):
        if not self.bridge.connected:
            self._led_status = None  # paksa set ulang saat serial tersambung lagi
            return

        status = self._indicator_status()
        if status != self._led_status:
            self._apply_status_led(status)
            if status == "ready":
                self._long_beep()  # transisi ke HIJAU -> bip panjang
            self._led_status = status
            self._t_last_bip = 0.0

        if status == "busy":
            interval = int(self.cfg.get("feedback", "sorting_bip_interval_ms", default=1000)) / 1000.0
            now = time.time()
            if now - self._t_last_bip >= interval:
                self.bridge.beep(2)  # bip-bip selama lampu merah
                self._t_last_bip = now

    # ---------------------------------------------------------
    # HELPER VISI: gerakan & foreground
    # ---------------------------------------------------------
    def _roi_box(self):
        roi = self.cfg.get("detect", "roi") or {"x": 0, "y": 0, "w": 99999, "h": 99999}
        return int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"])

    def _roi_gray(self, frame):
        x, y, w, h = self._roi_box()
        x, y = max(0, x), max(0, y)
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            crop = frame
        return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    def _motion(self, gray):
        """Rata-rata beda antar-frame di ROI (0-255). Besar = ada gerakan."""
        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray
            return 0.0
        d = cv2.absdiff(gray, self._prev_gray)
        self._prev_gray = gray
        return float(d.mean())

    def _foreground_ratio(self, frame):
        """Fraksi piksel ROI yang beda dari latar kosong. None jika belum kalibrasi."""
        if self._empty_ref is None:
            return None
        x, y, w, h = self._roi_box()
        x, y = max(0, x), max(0, y)
        cur = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)[y:y + h, x:x + w]
        ref = self._empty_ref[y:y + h, x:x + w]
        if cur.size == 0 or cur.shape != ref.shape:
            return None
        diff = cv2.absdiff(cur, ref)
        thr = int(self.cfg.get("detect", "fg_pixel_threshold", default=30))
        return float((diff > thr).mean())

    def save_empty_reference(self):
        frame = self.cams.cam1.read()
        if frame is None:
            return False
        cv2.imwrite(str(EMPTY_REF), frame)
        self._empty_ref = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        print("[SM] Latar kosong disimpan.")
        return True

    # ---------------------------------------------------------
    def _loop(self):
        while self.running:
            t0 = time.time()
            try:
                self._tick()
            except Exception as exc:
                print(f"[SM] error tick: {exc}")
            dt = time.time() - t0
            if dt < 0.05:
                time.sleep(0.05 - dt)

    def _detcfg_cam1(self):
        d = self.cfg.get("detect")
        return {"conf_threshold": d["conf_threshold"], "conf_per_class": d["conf_per_class"],
                "min_area": d["min_box_area"]}

    def _detcfg_cam2(self):
        # tracking cam2: conf rendah + tanpa filter per-kelas agar buah yang
        # bergerak tetap terdeteksi (posisi lebih penting daripada kelas).
        s = self.cfg.get("sort_cam2")
        track_conf = float(s.get("track_conf", 0.25))
        return {"conf_threshold": track_conf, "conf_per_class": {}, "min_area": s["min_box_area"]}

    def _active_paddle_roi(self):
        """ROI paddle untuk servo yang sedang aktif (servo1/servo2 posisinya beda)."""
        s = self.cfg.get("sort_cam2")
        return (s.get(f"paddle_roi_{self._active_servo}") or s.get("paddle_roi")
                or {"x": 0, "y": 0, "w": 999999, "h": 999999})

    def _infer(self, frame, det_cfg, roi):
        if frame is None:
            return []
        conf_floor = min(det_cfg["conf_per_class"].values()) if det_cfg["conf_per_class"] else det_cfg["conf_threshold"]
        dets_all = self.detector.infer(frame, imgsz=int(self.cfg.get("detect", "imgsz", default=480)), conf=conf_floor)
        return filter_dets(dets_all, roi, det_cfg["min_area"], det_cfg["conf_threshold"], det_cfg["conf_per_class"])

    # ---------------------------------------------------------
    def _tick(self):
        self._update_indicators()

        if self.estop or self.manual_mode:
            tag = "E-STOP" if self.estop else "MANUAL"
            self._set_annotated("cam1", draw_overlay(self.cams.cam1.read(), [], self.cfg.get("detect", "roi"), tag))
            self._set_annotated("cam2", draw_overlay(self.cams.cam2.read(), [], self.cfg.get("sort_cam2", "paddle_roi"), tag))
            time.sleep(0.1)
            return

        st = self.state

        if st in ("IDLE", "REJECT_FORWARD"):
            frame1 = self.cams.cam1.read()
            if st == "IDLE":
                self._state_idle(frame1)
            else:
                self._state_reject(frame1)
            self._set_annotated("cam2", draw_overlay(self.cams.cam2.read(), [], self.cfg.get("sort_cam2", "paddle_roi"), "idle"))

        elif st in ("STRAIGHT_OUT", "STRAIGHT_EXTRA", "SERVO_SORT", "SERVO_RETURN"):
            roi2 = self._active_paddle_roi() if st in ("SERVO_SORT", "SERVO_RETURN") else self.cfg.get("sort_cam2", "paddle_roi")
            frame2 = self.cams.cam2.read()
            dets2 = self._infer(frame2, self._detcfg_cam2(), None)
            self._set_annotated("cam2", draw_overlay(frame2, dets2, roi2, st, self.last_message))
            self._set_annotated("cam1", draw_overlay(self.cams.cam1.read(), [], self.cfg.get("detect", "roi"), "idle"))

            if st == "STRAIGHT_OUT":
                self._state_straight_out(dets2)
            elif st == "STRAIGHT_EXTRA":
                self._state_straight_extra()
            elif st == "SERVO_SORT":
                self._state_servo_sort(dets2, frame2)
            elif st == "SERVO_RETURN":
                self._state_servo_return()

        elif st == "COOLDOWN":
            self._state_cooldown()
        elif st == "FAULT":
            self._state_fault()

    # ---------------------------------------------------------
    # IDLE + GERBANG SETTLE (anti-tangan)
    # ---------------------------------------------------------
    def _state_idle(self, frame):
        self.bridge.motor_stop()
        if frame is None:
            self.last_message = "Menunggu frame kamera 1..."
            return

        # Jangan mulai siklus kalau perangkat belum siap (LED kuning):
        # serial putus / salah satu kamera mati -> sortir pasti gagal & memicu FAULT.
        if self._indicator_status() == "notready":
            self._watching = False
            self._settle_low = 0
            self._votes.clear()
            self.last_message = "Perangkat belum siap (cek kamera/serial)"
            self._set_annotated("cam1", draw_overlay(frame, [], self.cfg.get("detect", "roi"),
                                                     "BELUM SIAP", self.last_message))
            return

        roi = self.cfg.get("detect", "roi")
        gray = self._roi_gray(frame)
        motion = self._motion(gray)
        fg = self._foreground_ratio(frame)
        self._last_motion, self._last_fg = motion, fg

        motion_thr = float(self.cfg.get("detect", "settle_motion_threshold", default=6.0))
        fg_thr = float(self.cfg.get("detect", "fg_area_ratio", default=0.04))
        fg_present = fg is not None and fg >= fg_thr

        # mulai "watch" begitu ada gerakan / objek muncul; tetap awasi walau lalu diam
        if not self._watching and (motion > motion_thr or fg_present):
            self._watching = True

        if not self._watching:
            self._settle_low = 0
            self._votes.clear()
            self.last_message = "Menunggu objek di kamera 1"
            self._set_annotated("cam1", draw_overlay(frame, [], roi, "IDLE", self.last_message))
            return

        # sedang mengawasi -> jalankan YOLO
        dets = self._infer(frame, self._detcfg_cam1(), roi)
        fruit = best_det(dets)
        self._set_annotated("cam1", draw_overlay(frame, dets, roi, "IDLE (watch)", self.last_message))

        if motion > motion_thr:
            # masih ada gerakan (tangan) -> reset settle, tunggu
            self._settle_low = 0
            self._votes.clear()
            self.ripeness_conf = 0.0
            self.last_message = "Tunggu gerakan berhenti (tangan menaruh)..."
            return

        # gerakan berhenti -> hitung settle + kumpulkan vote
        self._settle_low += 1
        if fruit is not None:
            self._votes[fruit.label] += 1
            self.ripeness_conf = max(self.ripeness_conf, fruit.conf)
            if self._snapshot_path is None:
                self._snapshot_frame(frame)
        self.last_message = f"Menstabilkan objek... ({self._settle_low})"

        settle_need = int(self.cfg.get("detect", "settle_frames", default=8))
        if self._settle_low >= settle_need:
            if self._votes:
                self.ripeness = self._votes.most_common(1)[0][0]
                self.ripeness_index = getattr(self.detector, "label_to_index", {}).get(self.ripeness)
                self._start_dragonfruit()
            elif fg_present:
                self._start_reject()
            else:
                # tak ada objek konklusif (false trigger / sudah pergi) -> berhenti awasi
                self._watching = False
                self._settle_low = 0
                self.last_message = "Menunggu objek di kamera 1"

    def _start_dragonfruit(self):
        # LED kini menandakan STATUS sistem (lihat _update_indicators), bukan kelas buah.
        action = (self.cfg.get("mapping", default={}) or {}).get(self.ripeness, "straight")
        self.last_action = action
        self._empty = 0
        self.bridge.motor_backward()       # BUAH NAGA -> mundur ke servo (bukan forward!)
        self._t_motor = time.time()
        if action == "straight":
            self._transition("STRAIGHT_OUT", f"{self.ripeness}: mundur lurus keluar belakang")
        else:
            self._active_servo = 1 if action == "servo1" else 2
            self.bridge.servo_open(self._active_servo)
            self._transition("SERVO_SORT", f"{self.ripeness}: servo{self._active_servo} buka, mundur + track cam2")

    def _start_reject(self):
        self.ripeness = "bukan buah naga"
        self.last_action = "reject"
        self.bridge.motor_forward()        # REJECT -> maju buang
        self._t_motor = time.time()
        self._transition("REJECT_FORWARD", "Bukan buah naga: maju untuk dibuang")

    # ---------------------------------------------------------
    def _state_reject(self, frame):
        if self._motor_watchdog():
            return
        # tampilkan
        self._set_annotated("cam1", draw_overlay(frame, [], self.cfg.get("detect", "roi"), "REJECT_FORWARD", self.last_message))
        dur = float(self.cfg.get("timing", "reject_forward_seconds", default=4.0))
        if time.time() - self._t_state >= dur:
            self.bridge.motor_stop()
            store.add(self.ripeness, None, "reject", self._snapshot_path)
            self._transition("COOLDOWN", "Objek reject dibuang")

    # ---------------------------------------------------------
    # FASE CAM2 (sorting buah naga)
    # ---------------------------------------------------------
    def _state_straight_out(self, dets):
        if self._motor_watchdog():
            return
        if best_det(dets) is None:
            self._empty += 1
        else:
            self._empty = 0
        if self._empty >= int(self.cfg.get("detect", "exit_frames", default=6)):
            self._transition("STRAIGHT_EXTRA", "Keluar frame cam2, mundur tambahan")

    def _state_straight_extra(self):
        extra = float(self.cfg.get("timing", "backward_extra_matang_seconds", default=5.0))
        if time.time() - self._t_state >= extra:
            self.bridge.motor_stop()
            self._goto_cooldown()

    def _state_servo_sort(self, dets, frame):
        if self._motor_watchdog():
            self.bridge.servo_close(self._active_servo)
            return
        d = best_det(dets)
        if d is None:
            return
        # TAMPOL saat titik tengah buah masuk zona paddle servo yang aktif
        roi = self._active_paddle_roi()
        in_paddle = (roi["x"] <= d.cx <= roi["x"] + roi["w"]
                     and roi["y"] <= d.cy <= roi["y"] + roi["h"])
        if in_paddle:
            self.bridge.servo_close(self._active_servo)  # kembali ke 0 derajat
            self._transition("SERVO_RETURN", f"Tampol! servo{self._active_servo} -> 0")

    def _state_servo_return(self):
        hold = float(self.cfg.get("timing", "servo_slap_hold_ms", default=500)) / 1000.0
        if time.time() - self._t_state >= hold:
            self.bridge.motor_stop()
            self._goto_cooldown()

    def _goto_cooldown(self):
        # buzzer diatur oleh _update_indicators (bip-bip saat merah, bip panjang saat hijau)
        store.add(self.ripeness, round(self.ripeness_conf, 3), self.last_action or "straight", self._snapshot_path)
        self._transition("COOLDOWN", f"Selesai: {self.ripeness} -> {self.last_action}")

    def _state_cooldown(self):
        self.bridge.motor_stop()
        self.bridge.s1_close()
        self.bridge.s2_close()
        if time.time() - self._t_state >= float(self.cfg.get("timing", "cooldown_seconds", default=3.0)):
            self._reset_cycle()
            self._transition("IDLE", "Menunggu objek di kamera 1")

    def _state_fault(self):
        self.bridge.motor_stop()
        auto = float(self.cfg.get("timing", "fault_auto_reset_seconds", default=5.0))
        if time.time() - self._t_state >= auto:
            self._reset_cycle()
            self._transition("IDLE", "Recover dari fault, menunggu objek")

    # ---------------------------------------------------------
    def _reset_cycle(self):
        self.ripeness = None
        self.ripeness_index = None
        self.ripeness_conf = 0.0
        self.last_action = None
        self._votes.clear()
        self._watching = False
        self._settle_low = 0
        self._empty = 0
        self._t_motor = 0.0
        self._prev_gray = None
        self._snapshot_path = None

    def _snapshot_frame(self, frame):
        if frame is None or not self.cfg.get("system", "save_snapshots", default=True):
            return
        folder = UPLOAD_DIR / datetime.now().strftime("%Y%m%d")
        folder.mkdir(parents=True, exist_ok=True)
        fn = folder / f"cam1_{datetime.now().strftime('%H%M%S_%f')}.jpg"
        cv2.imwrite(str(fn), frame)
        self._snapshot_path = str(fn.relative_to(UPLOAD_DIR.parent))

    # ---------------------------------------------------------
    # KONTROL EKSTERNAL
    # ---------------------------------------------------------
    def trigger_estop(self):
        self.estop = True
        self.bridge.motor_stop()
        self.bridge.s1_close()
        self.bridge.s2_close()
        self.last_message = "E-STOP ditekan"

    def clear_estop(self):
        self.estop = False
        self._reset_cycle()
        self._transition("IDLE", "E-STOP dilepas, menunggu objek")

    def set_manual(self, on):
        self.manual_mode = bool(on)
        if on:
            self.bridge.motor_stop()
            self.last_message = "Mode MANUAL — otomatis ditahan"
        else:
            self._reset_cycle()
            self._transition("IDLE", "Mode AUTO aktif, menunggu objek")

    def status(self):
        return {
            "state": self.state,
            "ripeness": self.ripeness,
            "ripeness_index": self.ripeness_index,
            "ripeness_conf": round(self.ripeness_conf, 3),
            "action": self.last_action,
            "message": self.last_message,
            "estop": self.estop,
            "manual_mode": self.manual_mode,
            "fault_count": self.fault_count,
            "serial_connected": self.bridge.connected,
            "cam1_ok": self.cams.cam1.healthy(),
            "cam2_ok": self.cams.cam2.healthy(),
            "cam1_fps": round(self.cams.cam1.actual_fps, 1),
            "cam2_fps": round(self.cams.cam2.actual_fps, 1),
            "indicator": self._led_status,  # ready(hijau)/busy(merah)/notready(kuning)
            "has_empty_ref": self._empty_ref is not None,
            "motion": round(self._last_motion, 1),
            "fg_ratio": round(self._last_fg, 3) if self._last_fg is not None else None,
            "counts_today": store.counts_today(),
        }
