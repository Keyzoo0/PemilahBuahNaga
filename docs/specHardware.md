# Raspberry Pi 5 Model B Rev 1.1 — Spesifikasi Hardware & OS

## Identifikasi Sistem

| Item | Detail |
|------|--------|
| **Model** | Raspberry Pi 5 Model B Rev 1.1 |
| **SoC** | Broadcom BCM2712 |
| **Revision** | d04171 |
| **Serial** | 0ff249e86fc4dbcc |
| **Device Tree** | `raspberrypi,5-model-b` / `brcm,bcm2712` |

---

## Sistem Operasi

| Item | Detail |
|------|--------|
| **OS** | Debian GNU/Linux 13 (trixie) |
| **Debian Version** | 13.5 |
| **Kernel** | 6.18.34+rpt-rpi-2712 |
| **Architektur** | aarch64 (ARM 64-bit, Little Endian) |
| **Compiler** | aarch64-linux-gnu-gcc 14.2.0 |
| **Build Date Kernel** | 2026-06-09 |
| **Mode** | SMP PREEMPT |

---

## CPU (Central Processing Unit)

| Item | Detail |
|------|--------|
| **Jenis** | ARM Cortex-A76 |
| **Jumlah Core** | 4 (single-thread per core) |
| **Clock Speed** | 1500 MHz (min) — 2400 MHz (max) |
| **BogoMIPS** | 108.00 per core |
| **Architecture** | ARMv8.2 (CPU arch: 8, variant: 0x4, part: 0xd0b) |
| **L1d Cache** | 256 KiB (4 x 64 KiB) |
| **L1i Cache** | 256 KiB (4 x 64 KiB) |
| **L2 Cache** | 2 MiB (4 x 512 KiB per core) |
| **L3 Cache** | 2 MiB (shared) |
| **Frequency Boost** | Disabled |

### Fitur CPU (Flags)
| Flag | Deskripsi |
|------|-----------|
| `fp` | Floating Point |
| `asimd` | Advanced SIMD (NEON) |
| `evtstrm` | Event Stream |
| `aes` / `pmull` | Hardware AES Encryption |
| `sha1` / `sha2` | Hardware SHA Hashing |
| `crc32` | Hardware CRC32 |
| `atomics` | Atomic operations (LSE) |
| `fphp` | Half-precision float |
| `asimdhp` | Advanced SIMD half-precision |
| `cpuid` | CPU ID instruction |
| `asimdrdm` | Rounding double multiply |
| `lrcpc` | Load-Acquire RCpc |
| `dcpop` | Data cache clean to PoC |
| `asimddp` | SIMD dot product (i8mm) |

### Keamanan CPU (Vulnerabilities)
Semua mitigasi aktif — tidak terpengaruh oleh: Meltdown, Spectre v1/v2, MDS, L1TF, Ghostwrite, dan lainnya.

---

## GPU (Graphics Processing Unit)

| Item | Detail |
|------|--------|
| **GPU** | VideoCore VII (integrated) |
| **Driver** | DRM VC4 V3D (`vc4-kms-v3d`) |
| **Max Framebuffers** | 2 |

---

## Memori (RAM)

| Item | Detail |
|------|--------|
| **Total** | 8 GiB (8,251,776 KiB) |
| **Tipe** | LPDDR4X-4267 (soldered) |
| **Used** | ~2.9 GiB |
| **Available** | ~5.0 GiB |
| **Swap** | 2.0 GiB (zram0) |

### Memori Detail
| Item | Nilai |
|------|-------|
| MemFree | 1,203,072 KiB |
| MemAvailable | 5,250,880 KiB |
| Buffers | 156,688 KiB |
| Cached | 3,719,024 KiB |
| Active (anon) | 2,487,712 KiB |

---

## Penyimpanan (Storage)

| Item | Detail |
|------|--------|
| **Tipe** | eMMC / microSD (SD) |
| **Nama** | SE32G |
| **Kapasitas Total** | 29.7 GiB (~32 GB) |
| **Tanggal Produksi** | 12/2025 |
| **Root FS** (`/`) | `/dev/mmcblk0p2` — 29.2 GiB (6.8 GiB used, 21 GiB available) |
| **Boot** (`/boot/firmware`) | `/dev/mmcblk0p1` — 505 MiB (87 MiB used) |
| **Swap** | zram0 — 2 GiB (compressed RAM disk) |

---

## Konektivitas Jaringan

### Ethernet
| Item | Detail |
|------|--------|
| **Interface** | eth0 |
| **Status** | DOWN (tidak terhubung) |
| **MAC** | 88:a2:9e:b0:e0:69 |

### Wi-Fi (WLAN)
| Item | Detail |
|------|--------|
| **Interface** | wlan0 |
| **Status** | UP (terhubung) |
| **MAC** | 88:a2:9e:b0:e0:6a |
| **IP Address** | 192.168.100.241/24 |
| **Gateway** | 192.168.100.255 (broadcast) |
| **MTU** | 1500 |
| **Qdisc** | fq_codel |

---

## USB

| Bus | Device | Vendor:Product | Deskripsi |
|-----|--------|---------------|-----------|
| 001 | 001 | 1d6b:0002 | USB 2.0 Root Hub |
| 001 | 002 | 10c4:0005 | Silicon Labs USB Optical Mouse |
| 002 | 001 | 1d6b:0003 | USB 3.0 Root Hub |
| 003 | 001 | 1d6b:0002 | USB 2.0 Root Hub |
| 003 | 002 | 2a7a:9597 | CASUE USB Keyboard |
| 004 | 001 | 1d6b:0003 | USB 3.0 Root Hub |

**Total USB Hub**: 2x USB 2.0, 2x USB 3.0
**Perangkat Terhubung**: Mouse (optical), Keyboard

---

## PCIe

| Address | Device |
|---------|--------|
| 0002:00:00.0 | BCM2712 PCIe Bridge (rev 30) |
| 0002:01:00.0 | RP1 PCIe 2.0 South Bridge |

---

## GPIO & Peripheral

| Item | Detail |
|------|--------|
| **GPIO Chips** | gpiochip512, gpiochip527, gpiochip533, gpiochip565, gpiochip569 |
| **I2C** | Tersedia (belum diaktifkan di config) |
| **SPI** | Tersedia (belum diaktifkan di config) |
| **I2S** | Tersedia (belum diaktifkan di config) |
| **Audio PWM** | Mode 2 (aktif via `dtparam=audio=on`) |

### LED
| Nama | Fungsi |
|------|--------|
| `ACT` | Activity LED (kedipan SD/mmc) |
| `PWR` | Power LED |

---

## Thermal & Power

| Item | Detail |
|------|--------|
| **Suhu CPU** | 54.9°C (54,000 mili°C) |
| **Sensor** | `cpu-thermal` (1 zona thermal) |
| **Throttled** | `0x0` — Tidak ada throttling |
| **DVFS** | Mode 4 (Dynamic Voltage & Frequency Scaling aktif) |
| **ARM Boost** | Aktif (`arm_boost=1`) |
| **AVS Temp** | 28,487 |

---

## Konfigurasi Firmware (`config.txt`)

| Parameter | Nilai | Keterangan |
|-----------|-------|------------|
| `arm_64bit` | 1 | Mode 64-bit aktif |
| `arm_boost` | 1 | Turbo boost diaktifkan |
| `arm_freq` | 2400 MHz | Frekuensi maks CPU |
| `arm_freq_min` | 1500 MHz | Frekuensi minimum CPU |
| `core_freq` | 910 MHz | Frekuensi GPU/cores |
| `core_freq_min` | 500 MHz | Frekuensi minimum GPU |
| `audio_pwm_mode` | 2 | Audio PWM mode 2 |
| `arm_peri_high` | 1 | Peripheral high mapping |
| `auto_initramfs` | 1 | Initramfs otomatis |
| `camera_auto_detect` | 1 | Kamera auto-detect |
| `display_auto_detect` | 1 | Display auto-detect |
| `disable_overscan` | 1 | Overscan dimatikan |
| `disable_fw_kms_setup` | 1 | Firmware KMS setup dimatikan |
| `dtoverlay` | vc4-kms-v3d | DRM VC4 V3D overlay |
| `max_framebuffers` | 2 | Dual framebuffer |

---

## Ringkasan

```
┌─────────────────────────────────────────────────────┐
│          RASPBERRY PI 5 MODEL B  (Rev 1.1)          │
├─────────────────────────────────────────────────────┤
│  SoC        : BCM2712 (Broadcom)                    │
│  CPU        : 4x ARM Cortex-A76 @ 2.4 GHz          │
│  GPU        : VideoCore VII                          │
│  RAM        : 8 GiB LPDDR4X                         │
│  Storage    : 32 GB microSD (SE32G)                 │
│  OS         : Debian 13 (trixie), Kernel 6.18       │
│  Network    : Wi-Fi 5 (802.11ac) — aktif            │
│              : Gigabit Ethernet — tidak terhubung    │
│  USB        : 2x USB 2.0 + 2x USB 3.0              │
│  PCIe       : Gen 2.0 x1 (via RP1 southbridge)     │
│  Thermal    : 54.9°C (normal, no throttling)        │
│  Suhu       : Idle @ 1500-2400 MHz                  │
└─────────────────────────────────────────────────────┘
```

---

*Dihasilkan pada 23 Juli 2026 — Data diambil langsung dari perangkat.*
