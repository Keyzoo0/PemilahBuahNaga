#!/usr/bin/env python3
"""
PemilahBuahNaga — Dual Camera Flask Streamer
Menampilkan 2 kamera USB DV20 secara real-time di web browser.
"""

import cv2
import json
import os
import time
import threading
from flask import Flask, Response, render_template, jsonify

app = Flask(__name__, template_folder="script", static_folder="script")

# Load camera config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "camera_config.json")
CAMERAS = {}
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        CAMERAS = json.load(f)

# Default jika config tidak ada
if not CAMERAS:
    CAMERAS = {
        "Camera_1": {"device": "/dev/video0"},
        "Camera_2": {"device": "/dev/video2"},
    }


class CameraStream:
    """Thread-safe camera stream dengan buffering."""

    def __init__(self, device, name, width=1920, height=1080):
        self.device = device
        self.name = name
        self.width = width
        self.height = height
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.cap = None
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()

    def start(self):
        self.running = True
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()

    def _capture_loop(self):
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            print(f"[ERROR] Cannot open {self.device}")
            return

        # Set format MJPG untuk max kualitas
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        print(f"[{self.name}] {self.device} → {actual_w}x{actual_h} @ {actual_fps:.0f}fps")

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            _, jpeg = cv2.imencode(
                ".jpg", frame,
                [cv2.IMWRITE_JPEG_QUALITY, 90, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
            )

            with self.lock:
                self.frame = jpeg.tobytes()
                self.frame_count += 1
                now = time.time()
                if now - self.last_fps_time >= 1.0:
                    self.fps = self.frame_count / (now - self.last_fps_time)
                    self.frame_count = 0
                    self.last_fps_time = now

    def get_frame(self):
        with self.lock:
            return self.frame

    def get_fps(self):
        return round(self.fps, 1)

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


# Initialize camera streams
streams = {}
for name, cfg in CAMERAS.items():
    dev = cfg["device"]
    s = CameraStream(dev, name)
    s.start()
    streams[name] = s

time.sleep(0.5)


def generate_stream(stream):
    """Generator untuk MJPEG stream."""
    while stream.running:
        frame = stream.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(0.001)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed_1")
def video_feed_1():
    cam = list(streams.values())[0]
    return Response(
        generate_stream(cam),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/video_feed_2")
def video_feed_2():
    cam = list(streams.values())[1] if len(streams) > 1 else list(streams.values())[0]
    return Response(
        generate_stream(cam),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/status")
def status():
    info = {}
    for name, s in streams.items():
        info[name] = {
            "device": s.device,
            "fps": s.get_fps(),
            "running": s.running,
        }
    return jsonify(info)


@app.route("/api/cameras")
def api_cameras():
    return jsonify(CAMERAS)


if __name__ == "__main__":
    print("=" * 50)
    print("  PemilahBuahNaga — Camera Stream Server")
    print("=" * 50)
    print(f"  Open http://localhost:5000")
    print(f"  Cameras: {', '.join(CAMERAS.keys())}")
    print("=" * 50)

    try:
        app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        for s in streams.values():
            s.stop()
