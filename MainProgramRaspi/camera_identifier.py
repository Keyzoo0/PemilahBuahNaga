#!/usr/bin/env python3
"""
Camera Identifier untuk PemilahBuahNaga
Mengidentifikasi dan membedakan 2 kamera USB yang identik berdasarkan USB path.
"""

import subprocess
import os
import json
import glob
import re


def get_camera_devices():
    """Ambil hanya USB camera devices"""
    devices = []
    video_devices = glob.glob("/dev/video[0-9]*")

    for vf in sorted(video_devices):
        dev_name = os.path.basename(vf)

        # Baca card name
        name_file = f"/sys/class/video4linux/{dev_name}/name"
        if not os.path.exists(name_file):
            continue
        with open(name_file) as f:
            card_name = f.read().strip()

        # Hanya USB cameras
        if "USB" not in card_name and "DV20" not in card_name:
            continue

        # Dapatkan sysfs device path
        device_link = f"/sys/class/video4linux/{dev_name}/device"
        if not os.path.exists(device_link):
            continue
        real_path = os.path.realpath(device_link)

        # Extract USB bus-device info dari path
        # Contoh: ...xhci-hcd.0/usb1/1-1/1-1:1.0
        usb_m = re.search(r"usb(\d+)/(\d+-\d+)", real_path)
        if not usb_m:
            continue

        usb_bus_num = usb_m.group(1)
        usb_port = usb_m.group(2)

        # Cek capabilities via udev
        udev = subprocess.run(
            ["udevadm", "info", "--query=property", f"--name={vf}"],
            capture_output=True, text=True, timeout=5
        )
        caps = ""
        for line in udev.stdout.splitlines():
            if line.startswith("ID_V4L_CAPABILITIES="):
                caps = line.split("=", 1)[1]
                break

        if ":capture" not in caps:
            continue

        devices.append({
            "video_dev": vf,
            "card_name": card_name,
            "usb_bus": usb_bus_num,
            "usb_port": usb_port,
            "bus_key": f"usb{usb_bus_num}-{usb_port}",
            "sysfs_path": real_path,
        })

    return devices


def identify_cameras():
    """Identifikasi semua kamera USB"""
    print("=" * 60)
    print("  CAMERA IDENTIFIER — PemilahBuahNaga")
    print("=" * 60)

    devices = get_camera_devices()

    if not devices:
        print("\n[ERROR] Tidak ditemukan kamera USB!")
        return None

    print(f"\n  Ditemukan {len(devices)} kamera USB:\n")

    # Group by USB bus-port (setiap camera punya 2 device: video + metadata)
    groups = {}
    for d in devices:
        key = d["bus_key"]
        if key not in groups:
            groups[key] = []
        groups[key].append(d)

    sorted_groups = sorted(groups.items(), key=lambda x: x[0])
    config = {}

    for idx, (bus_key, devs) in enumerate(sorted_groups, 1):
        cam_name = f"Camera_{idx}"
        primary = devs[0]["video_dev"]
        all_devs = [d["video_dev"] for d in devs]

        print(f"  [{cam_name}]")
        print(f"  ├─ Device        : {primary}")
        print(f"  ├─ Semua Slot    : {', '.join(all_devs)}")
        print(f"  ├─ Card Name     : {devs[0]['card_name']}")
        print(f"  └─ USB Bus/Port  : {bus_key}")
        print()

        config[cam_name] = {
            "device": primary,
            "all_devices": all_devs,
            "bus_key": bus_key,
            "card_name": devs[0]["card_name"],
        }

    # Simpan config
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"  Config tersimpan: {config_path}")
    print()
    print("=" * 60)
    print("  QUICK USAGE")
    print("=" * 60)
    print("""
  # Python/OpenCV
  import json, cv2

  with open("camera_config.json") as f:
      cfg = json.load(f)

  cap1 = cv2.VideoCapture(cfg["Camera_1"]["device"])
  cap2 = cv2.VideoCapture(cfg["Camera_2"]["device"])

  # Shell
""")
    for name, cfg in config.items():
        print(f"  # {name}")
        print(f"  ls {cfg['device']}")
    print()

    return config


if __name__ == "__main__":
    identify_cameras()
