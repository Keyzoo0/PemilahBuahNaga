#!/usr/bin/env python3
"""
PemilahBuahNaga — Core Service (headless, offline-first)
Menyatukan: kamera, YOLO, state machine sorting, serial Arduino, dan web API.
Jalan sebagai systemd service; sorting tetap berjalan walau web tak dibuka.
"""
import uvicorn

from config import config
from camera import CameraManager
from detector import YOLODetector
from serial_bridge import SerialBridge
from state_machine import SortController
from mdns import MDNSPublisher
import api


def build():
    print("=" * 56)
    print("  PemilahBuahNaga — Core Service")
    print("=" * 56)

    cams = CameraManager(config)
    cams.start()

    detector = YOLODetector()

    scfg = config.get("serial")
    bridge = SerialBridge(
        port=scfg["port"], baud=scfg["baud"],
        heartbeat_seconds=scfg.get("heartbeat_seconds", 1.0),
        auto_reconnect=scfg.get("auto_reconnect", True),
    )
    bridge.start()

    controller = SortController(config, cams, detector, bridge)
    controller.start()

    api.ctx["controller"] = controller
    api.ctx["bridge"] = bridge
    api.ctx["config"] = config
    api.ctx["detector"] = detector
    return controller


if __name__ == "__main__":
    build()

    web = config.get("web", default={}) or {}
    port = int(web.get("port", 5000))
    hostname = web.get("mdns_hostname", "buahnaga")

    # publikasikan mDNS: http://buahnaga.local:5000
    mdns = MDNSPublisher(hostname=hostname, port=port)
    try:
        host_local = mdns.start()
    except Exception as exc:
        host_local = f"{hostname}.local"
        print(f"[mDNS] gagal publish ({exc}); akses tetap via IP:{port}")

    print(f"[CORE] Web: http://{host_local}:{port}  (monitoring & kalibrasi)")
    try:
        uvicorn.run(api.app, host="0.0.0.0", port=port, log_level="warning")
    finally:
        mdns.stop()
