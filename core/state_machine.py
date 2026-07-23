"""
SortController — state machine sortasi buah naga.

Alur:
  IDLE -> CLASSIFY -> FORWARD_CLEAR -> FORWARD_EXTRA -> DISPATCH
    matang           -> STRAIGHT_OUT -> STRAIGHT_EXTRA -> COOLDOWN
    mentah/setengah  -> SERVO_SORT -> SERVO_RETURN -> COOLDOWN
  COOLDOWN -> IDLE
  (FAULT bila watchdog motor / kamera bermasalah)

Optimasi Pi: hanya SATU kamera di-inference per state
  - cam1 saat IDLE/CLASSIFY/FORWARD*
  - cam2 saat STRAIGHT*/SERVO*
"""
import os
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2

from detector import filter_dets, draw_overlay
from store import store

UPLOAD_DIR = Path(__file__).resolve().parent / "static" / "uploads"


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
        self.ripeness_conf = 0.0
        self.last_message = "Menunggu buah di kamera 1"
        self.last_action = None

        self._votes = Counter()
        self._presence = 0
        self._empty = 0
        self._t_state = time.time()
        self._t_motor = 0.0
        self._snapshot_path = None

        self.estop = False
        self.manual_mode = False
        self.running = False

        # frame teranotasi terbaru untuk stream web
        self.annotated = {"cam1": None, "cam2": None}
        self._ann_lock = threading.Lock()
        self.fault_count = 0

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
            self._enter_fault("motor melebihi batas waktu (buah tidak terdeteksi keluar)")
            return True
        return False

    # ---------------------------------------------------------
    def _loop(self):
        while self.running:
            t0 = time.time()
            try:
                self._tick()
            except Exception as exc:
                print(f"[SM] error tick: {exc}")
            # jaga ~ maksimal 20 Hz; sisanya dibatasi kecepatan inference
            dt = time.time() - t0
            if dt < 0.05:
                time.sleep(0.05 - dt)

    def _infer_cam(self, cam_key, det_cfg, roi):
        cam = self.cams.cam1 if cam_key == "cam1" else self.cams.cam2
        frame = cam.read()
        dets_all = self.detector.infer(
            frame,
            imgsz=int(self.cfg.get("detect", "imgsz", default=480)),
            conf=min(det_cfg["conf_per_class"].values()) if det_cfg["conf_per_class"] else det_cfg["conf_threshold"],
        ) if frame is not None else []
        dets = filter_dets(dets_all, roi, det_cfg["min_area"], det_cfg["conf_threshold"], det_cfg["conf_per_class"])
        return frame, dets

    def _detcfg_cam1(self):
        d = self.cfg.get("detect")
        return {"conf_threshold": d["conf_threshold"], "conf_per_class": d["conf_per_class"],
                "min_area": d["min_box_area"]}

    def _detcfg_cam2(self):
        s = self.cfg.get("sort_cam2")
        d = self.cfg.get("detect")
        return {"conf_threshold": d["conf_threshold"], "conf_per_class": d["conf_per_class"],
                "min_area": s["min_box_area"]}

    # ---------------------------------------------------------
    def _tick(self):
        # E-STOP / manual mode: state machine ditahan
        if self.estop or self.manual_mode:
            f1 = self.cams.cam1.read()
            f2 = self.cams.cam2.read()
            self._set_annotated("cam1", draw_overlay(f1, [], self.cfg.get("detect", "roi"),
                                                      "E-STOP" if self.estop else "MANUAL"))
            self._set_annotated("cam2", draw_overlay(f2, [], None,
                                                     "E-STOP" if self.estop else "MANUAL"))
            time.sleep(0.1)
            return

        st = self.state

        # ---- FASE KAMERA 1 (deteksi + klasifikasi + forward) ----
        if st in ("IDLE", "CLASSIFY", "FORWARD_CLEAR", "FORWARD_EXTRA"):
            roi = self.cfg.get("detect", "roi")
            frame, dets = self._infer_cam("cam1", self._detcfg_cam1(), roi)
            self._set_annotated("cam1", draw_overlay(frame, dets, roi, st, self.last_message))
            # cam2 raw (idle)
            self._set_annotated("cam2", draw_overlay(self.cams.cam2.read(), [], None, "idle"))

            if st == "IDLE":
                self._state_idle(dets, frame)
            elif st == "CLASSIFY":
                self._state_classify()
            elif st == "FORWARD_CLEAR":
                self._state_forward_clear(dets)
            elif st == "FORWARD_EXTRA":
                self._state_forward_extra()

        # ---- FASE KAMERA 2 (sorting) ----
        elif st in ("STRAIGHT_OUT", "STRAIGHT_EXTRA", "SERVO_SORT", "SERVO_RETURN"):
            roi2 = self.cfg.get("sort_cam2", "paddle_roi")
            frame, dets = self._infer_cam("cam2", self._detcfg_cam2(), None)
            self._set_annotated("cam2", draw_overlay(frame, dets, roi2, st, self.last_message))
            self._set_annotated("cam1", draw_overlay(self.cams.cam1.read(), [], self.cfg.get("detect", "roi"), "idle"))

            if st == "STRAIGHT_OUT":
                self._state_straight_out(dets)
            elif st == "STRAIGHT_EXTRA":
                self._state_straight_extra()
            elif st == "SERVO_SORT":
                self._state_servo_sort(dets, frame)
            elif st == "SERVO_RETURN":
                self._state_servo_return()

        elif st == "COOLDOWN":
            self._state_cooldown()
        elif st == "FAULT":
            self._state_fault()

    # ---------------------------------------------------------
    # STATE HANDLERS
    # ---------------------------------------------------------
    def _state_idle(self, dets, frame):
        self.bridge.motor_stop()
        d = best_det(dets)
        if d is not None:
            self._presence += 1
            self._votes[d.label] += 1
            if d.conf > self.ripeness_conf:
                self.ripeness_conf = d.conf
            if self._presence == 1:
                self._snapshot_frame(frame)  # simpan snapshot awal
        else:
            self._presence = 0
            self._votes.clear()
            self.ripeness_conf = 0.0

        need = int(self.cfg.get("detect", "presence_frames", default=5))
        if self._presence >= need and self._votes:
            self.ripeness = self._votes.most_common(1)[0][0]
            self._transition("CLASSIFY", f"Terklasifikasi: {self.ripeness} ({self.ripeness_conf:.2f})")

    def _state_classify(self):
        # LED + beep hasil di firmware
        self.bridge.result(self.ripeness)
        self._empty = 0
        self.bridge.motor_forward()
        self._t_motor = time.time()
        self._transition("FORWARD_CLEAR", "Forward: menunggu buah keluar frame kamera 1")

    def _state_forward_clear(self, dets):
        if self._motor_watchdog():
            return
        if best_det(dets) is None:
            self._empty += 1
        else:
            self._empty = 0
        if self._empty >= int(self.cfg.get("detect", "exit_frames", default=6)):
            self._transition("FORWARD_EXTRA", "Buah keluar frame, forward tambahan")

    def _state_forward_extra(self):
        extra = float(self.cfg.get("timing", "forward_extra_seconds", default=2.0))
        if time.time() - self._t_state >= extra:
            self._dispatch()

    def _dispatch(self):
        action = self.cfg.get("mapping", default={}).get(self.ripeness, "straight")
        self.last_action = action
        self._empty = 0
        self.bridge.motor_backward()
        self._t_motor = time.time()
        if action == "straight":
            self._transition("STRAIGHT_OUT", "Matang: backward lurus sampai keluar")
        else:
            servo_n = 1 if action == "servo1" else 2
            self.bridge.servo_open(servo_n)
            self._active_servo = servo_n
            self._transition("SERVO_SORT", f"{self.ripeness}: servo{servo_n} open, backward + track kamera 2")

    def _state_straight_out(self, dets):
        if self._motor_watchdog():
            return
        if best_det(dets) is None:
            self._empty += 1
        else:
            self._empty = 0
        if self._empty >= int(self.cfg.get("detect", "exit_frames", default=6)):
            self._transition("STRAIGHT_EXTRA", "Keluar frame kamera 2, backward tambahan 5s")

    def _state_straight_extra(self):
        extra = float(self.cfg.get("timing", "backward_extra_matang_seconds", default=5.0))
        if time.time() - self._t_state >= extra:
            self.bridge.motor_stop()
            self._goto_cooldown()

    def _state_servo_sort(self, dets, frame):
        if self._motor_watchdog():
            self.bridge.servo_close(getattr(self, "_active_servo", 1))
            return
        d = best_det(dets)
        if d is None:
            return
        roi = self.cfg.get("sort_cam2", "paddle_roi")
        slap_ratio = float(self.cfg.get("sort_cam2", "slap_x_ratio", default=0.45))
        w = frame.shape[1] if frame is not None else 1280
        in_paddle = roi["x"] <= d.cx <= roi["x"] + roi["w"] and roi["y"] <= d.cy <= roi["y"] + roi["h"]
        left_enough = (d.cx / w) < slap_ratio
        if in_paddle and left_enough:
            self.bridge.servo_close(self._active_servo)  # TAMPOL: kembali ke 0 derajat
            self._transition("SERVO_RETURN", f"Tampol! servo{self._active_servo} -> 0")

    def _state_servo_return(self):
        hold = float(self.cfg.get("timing", "servo_slap_hold_ms", default=500)) / 1000.0
        if time.time() - self._t_state >= hold:
            self.bridge.motor_stop()
            self._goto_cooldown()

    def _goto_cooldown(self):
        # simpan riwayat + beep selesai
        if self.cfg.get("feedback", "buzzer_on_sort", default=True):
            self.bridge.beep(2)
        store.add(self.ripeness, round(self.ripeness_conf, 3), self.last_action or "straight", self._snapshot_path)
        self._transition("COOLDOWN", f"Selesai: {self.ripeness} -> {self.last_action}")

    def _state_cooldown(self):
        self.bridge.motor_stop()
        self.bridge.s1_close()
        self.bridge.s2_close()
        if time.time() - self._t_state >= float(self.cfg.get("timing", "cooldown_seconds", default=3.0)):
            self._reset_cycle()
            self._transition("IDLE", "Menunggu buah di kamera 1")

    def _state_fault(self):
        self.bridge.motor_stop()
        auto = float(self.cfg.get("timing", "fault_auto_reset_seconds", default=5.0))
        if time.time() - self._t_state >= auto:
            self._reset_cycle()
            self._transition("IDLE", "Recover dari fault, menunggu buah")

    # ---------------------------------------------------------
    def _reset_cycle(self):
        self.ripeness = None
        self.ripeness_conf = 0.0
        self.last_action = None
        self._votes.clear()
        self._presence = 0
        self._empty = 0
        self._t_motor = 0.0
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
    # KONTROL EKSTERNAL (dari API/web)
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
        self._transition("IDLE", "E-STOP dilepas, menunggu buah")

    def set_manual(self, on):
        self.manual_mode = bool(on)
        if on:
            self.bridge.motor_stop()
        else:
            self._reset_cycle()
            self._transition("IDLE", "Mode auto aktif")

    def status(self):
        return {
            "state": self.state,
            "ripeness": self.ripeness,
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
            "counts_today": store.counts_today(),
        }
