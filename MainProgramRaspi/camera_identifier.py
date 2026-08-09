#!/usr/bin/env python3
"""
Camera Identifier untuk PemilahBuahNaga
Mengidentifikasi dan membedakan 2 kamera USB yang identik berdasarkan USB path.

CATATAN UNTUK PEMULA:
Ini program BANTU yang dijalankan SEKALI saat pemasangan alat, bukan bagian
dari sistem yang berjalan terus-menerus.

Masalah yang dipecahkan: kedua kamera USB-nya bermerek sama persis. Di Linux
mereka muncul sebagai /dev/video0, /dev/video2, dan seterusnya — tapi nomor
itu bisa bertukar setiap kali Raspberry Pi dinyalakan ulang.

Solusinya: kenali kamera dari LUBANG USB tempat ia dicolok (disebut "bus-key",
contoh "usb3-3-1"). Lubang USB tidak akan berpindah, jadi identitasnya tetap.

Cara pakai: jalankan di terminal Raspberry Pi
    python3 camera_identifier.py
Hasilnya disimpan ke camera_config.json, lalu bus-key-nya disalin ke
core/config.json bagian "camera".
"""

import subprocess   # menjalankan perintah terminal dari Python
import os           # urusan file & folder
import json         # menulis hasil ke file JSON
import glob         # mencari file dengan pola, contoh "/dev/video*"
import re           # mencocokkan pola dalam teks (regular expression)


def get_camera_devices():
    """Ambil hanya USB camera devices"""
    devices = []
    # Cari semua file perangkat video di Linux. Pola [0-9]* artinya
    # "diikuti angka", jadi cocok untuk video0, video1, video10, dst.
    video_devices = glob.glob("/dev/video[0-9]*")

    # sorted() mengurutkan agar hasilnya konsisten tiap kali dijalankan.
    for vf in sorted(video_devices):
        # basename mengambil nama file saja: "/dev/video0" -> "video0"
        dev_name = os.path.basename(vf)

        # Baca card name
        # Linux menyimpan informasi tiap perangkat di folder khusus /sys.
        # File "name" berisi merek/nama kamera menurut pabriknya.
        name_file = f"/sys/class/video4linux/{dev_name}/name"
        # Lewati kalau file info-nya tidak ada (perangkat aneh / bukan kamera).
        if not os.path.exists(name_file):
            continue
        with open(name_file) as f:
            card_name = f.read().strip()

        # Hanya USB cameras
        # Raspberry Pi punya beberapa perangkat video bawaan (encoder video, dll)
        # yang bukan kamera. Saringan ini membuang semuanya.
        if "USB" not in card_name and "DV20" not in card_name:
            continue

        # Dapatkan sysfs device path
        device_link = f"/sys/class/video4linux/{dev_name}/device"
        if not os.path.exists(device_link):
            continue
        # realpath mengikuti "jalan pintas" (symlink) sampai alamat aslinya,
        # yang memuat informasi lubang USB tempat kamera dicolok.
        real_path = os.path.realpath(device_link)

        # Extract USB bus-device info dari path
        # Contoh: ...xhci-hcd.0/usb1/1-1/1-1:1.0
        # Pola r"usb(\d+)/(\d+-\d+)" dibaca begini:
        #   usb      -> harus ada tulisan "usb"
        #   (\d+)    -> satu angka atau lebih, DIAMBIL sebagai group 1
        #   /        -> harus ada garis miring
        #   (\d+-\d+)-> pola "angka-angka", DIAMBIL sebagai group 2
        usb_m = re.search(r"usb(\d+)/(\d+-\d+)", real_path)
        if not usb_m:
            continue

        usb_bus_num = usb_m.group(1)   # contoh: "1"
        usb_port = usb_m.group(2)      # contoh: "1-1"

        # Cek capabilities via udev
        # udevadm adalah perintah Linux untuk menanyakan detail sebuah perangkat.
        # Kita perlu tahu: perangkat ini benar-benar bisa MENANGKAP gambar atau
        # cuma menyediakan metadata?
        udev = subprocess.run(
            ["udevadm", "info", "--query=property", f"--name={vf}"],
            capture_output=True, text=True, timeout=5
        )
        caps = ""
        for line in udev.stdout.splitlines():
            if line.startswith("ID_V4L_CAPABILITIES="):
                # split("=", 1) memecah pada tanda "=" PERTAMA saja (angka 1),
                # lalu [1] mengambil bagian setelahnya (nilainya).
                caps = line.split("=", 1)[1]
                break

        # Satu kamera fisik sering memunculkan 2 perangkat: satu untuk gambar,
        # satu lagi untuk metadata. Hanya yang punya ":capture" yang berguna.
        if ":capture" not in caps:
            continue

        # Semua saringan lolos -> simpan sebagai kamera yang sah.
        devices.append({
            "video_dev": vf,                                # /dev/video0
            "card_name": card_name,                         # nama menurut pabrik
            "usb_bus": usb_bus_num,                         # nomor bus USB
            "usb_port": usb_port,                           # nomor port USB
            "bus_key": f"usb{usb_bus_num}-{usb_port}",      # penanda unik gabungan
            "sysfs_path": real_path,                        # alamat lengkap di /sys
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

    # \n di dalam teks berarti "pindah baris".
    print(f"\n  Ditemukan {len(devices)} kamera USB:\n")

    # Group by USB bus-port (setiap camera punya 2 device: video + metadata)
    # Perangkat dengan bus_key sama = satu kamera fisik yang sama.
    groups = {}
    for d in devices:
        key = d["bus_key"]
        # Kalau kunci ini belum pernah ada, siapkan dulu daftar kosongnya.
        if key not in groups:
            groups[key] = []
        groups[key].append(d)

    # .items() memberi pasangan (kunci, nilai). Diurutkan berdasarkan kunci
    # (x[0]) agar penomoran Camera_1 / Camera_2 selalu konsisten.
    sorted_groups = sorted(groups.items(), key=lambda x: x[0])
    config = {}

    # enumerate(daftar, 1) memberi nomor urut sambil mengulang, dimulai dari 1
    # (bukan 0), supaya penamaannya jadi Camera_1, Camera_2 — bukan Camera_0.
    for idx, (bus_key, devs) in enumerate(sorted_groups, 1):
        cam_name = f"Camera_{idx}"
        primary = devs[0]["video_dev"]                      # perangkat utama
        all_devs = [d["video_dev"] for d in devs]           # semua perangkat kamera ini

        # Karakter ├─ dan └─ hanya hiasan agar tampilan terminal rapi seperti pohon.
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
    # Alamat file dibuat relatif terhadap letak file skrip ini, agar hasilnya
    # selalu tersimpan di tempat yang benar walau dijalankan dari folder mana pun.
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"  Config tersimpan: {config_path}")
    print()
    print("=" * 60)
    print("  QUICK USAGE")
    print("=" * 60)
    # Teks di dalam tiga tanda kutip boleh ditulis beberapa baris; semua
    # baris baru dan spasinya ikut tercetak apa adanya.
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


# Hanya jalan kalau file ini dieksekusi langsung dari terminal.
if __name__ == "__main__":
    identify_cameras()
