# Build & Upload Arduino Nano

## Overview

Panduan compile, upload, dan monitor firmware Arduino Nano untuk proyek PemilahBuahNaga.

---

## Prerequisites

| Komponen | Detail |
|----------|--------|
| **Board** | Arduino Nano (ATmega328P) |
| **OS** | Debian 13 (trixie) aarch64 |
| **USB Port** | `/dev/ttyUSB0` |
| **Baud Rate** | 115200 |
| **Arduino CLI** | v1.5.1 |
| **AVR Core** | arduino:avr@1.8.8 |
| **Servo Library** | 1.3.0 |

---

## Install Arduino CLI

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
export PATH="$HOME/bin:$PATH"
```

Tambahkan ke `.bashrc` agar persisten:

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
```

---

## Install Board & Library

```bash
# Update index
arduino-cli core update-index

# Install Arduino AVR core (untuk Nano)
arduino-cli core install arduino:avr

# Install Servo library
arduino-cli lib install Servo
```

---

## Compile

```bash
arduino-cli compile \
  --fqbn arduino:avr:nano \
  ~/PemilahBuahNaga/ArduinoNanoFirmware/main/main.ino
```

### Output yang diharapkan

```
Sketch uses 8046 bytes (26%) of program storage space. Maximum is 30720 bytes.
Global variables use 836 bytes (40%) of dynamic memory, leaving 1212 bytes for local variables. Maximum is 2048 bytes.
```

---

## Upload

```bash
arduino-cli upload \
  --fqbn arduino:avr:nano \
  --port /dev/ttyUSB0 \
  ~/PemilahBuahNaga/ArduinoNanoFirmware/main/main.ino
```

### Verifikasi upload

```bash
# Upload verbose mode
arduino-cli upload \
  --fqbn arduino:avr:nano \
  --port /dev/ttyUSB0 \
  --verbose \
  ~/PemilahBuahNaga/ArduinoNanoFirmware/main/main.ino
```

### Output yang diharapkan

```
avrdude: AVR device initialized and ready to accept instructions
Device signature = 1E 95 0F (ATmega328P)
Writing 8046 bytes to flash
Writing | ################################################## | 100% 0.95s
8046 bytes of flash written
Avrdude done.  Thank you.
```

---

## Serial Monitor

```bash
arduino-cli monitor \
  --port /dev/ttyUSB0 \
  --config baudrate=115200
```

Atau gunakan `screen`:

```bash
screen /dev/ttyUSB0 115200
```

Keluar dari screen: `Ctrl+A` lalu `K`.

---

## Troubleshooting

### Permission Denied pada `/dev/ttyUSB0`

```bash
# Tambahkan user ke group plugdev
sudo usermod -aG plugdev $USER

# Atau langsung set permission
sudo chmod 666 /dev/ttyUSB0
```

### Arduino Nano tidak terdeteksi

```bash
# Cek device
ls -la /dev/ttyUSB*

# Cek dmesg
dmesg | tail -20
```

### Upload gagal / timeout

- Pastikan kabel USB data (bukan charge-only)
- Tekan tombol reset pada Arduino Nano sesaat sebelum upload
- Coba port lain jika ada

---

## File Structure

```
PemilahBuahNaga/
├── ArduinoNanoFirmware/
│   └── main/
│       └── main.ino          # Firmware utama
├── MainProgramRaspi/          # Program Raspberry Pi
└── docs/
    ├── BuildNano.md           # Dokumentasi ini
    └── specHardware.md        # Spesifikasi hardware Raspi
```

---

## Command Reference

| Command | Fungsi |
|---------|--------|
| `arduino-cli core update-index` | Update board index |
| `arduino-cli core install arduino:avr` | Install AVR core |
| `arduino-cli lib install Servo` | Install Servo library |
| `arduino-cli compile --fqbn arduino:avr:nano <path>` | Compile sketch |
| `arduino-cli upload --fqbn arduino:avr:nano --port /dev/ttyUSB0 <path>` | Upload ke board |
| `arduino-cli monitor --port /dev/ttyUSB0 --config baudrate=115200` | Serial monitor |
| `arduino-cli board list` | List connected boards |
| `arduino-cli core list` | List installed cores |
| `arduino-cli lib list` | List installed libraries |

---

*Dihasilkan pada 23 Juli 2026*
