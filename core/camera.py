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

CATATAN UNTUK PEMULA:
Masalah utama file ini: kedua kamera USB-nya BERMEREK SAMA. Di Linux, kamera
muncul sebagai file /dev/video0, /dev/video1, dst. Masalahnya, nomor itu bisa
bertukar setiap kali Raspberry Pi dinyalakan ulang! Kalau tertukar, kamera
deteksi bisa jadi dianggap kamera sorting -> sistem salah total.

Solusinya: "bus-key" — kita mengenali kamera dari LUBANG USB tempat ia dicolok,
bukan dari nomor /dev/videoN. Selama kabelnya tidak dipindah lubang, kamera 1
akan selalu terbaca sebagai kamera 1.

Istilah:
- self-healing : memperbaiki diri sendiri tanpa dibantu manusia.
- hang / wedged: perangkat masih terpasang tapi macet, tidak mengirim data.
- V4L2         : Video4Linux2, sistem bawaan Linux untuk mengurus kamera.
- race         : dua proses berebut sumber daya bersamaan sehingga salah satu gagal.
"""
import glob         # mencari nama file dengan pola, contoh "/dev/video*"
import os           # urusan file & folder sistem operasi
import re           # "regular expression": mencocokkan pola dalam teks
import subprocess   # menjalankan perintah terminal dari Python
import threading    # menjalankan pekerjaan bersamaan
import time         # jeda waktu & pengukuran waktu

import cv2          # OpenCV: membuka kamera dan mengambil gambar

# Serialkan init: cuma satu VideoCapture dibuka pada satu waktu.
# Ini kunci global (dipakai bersama semua objek kamera). Kalau dua kamera
# identik dibuka bersamaan, driver Linux sering bingung dan salah satu gagal.
_OPEN_LOCK = threading.Lock()


def candidates_by_bus_key(bus_key):
    """Semua node /dev/videoN untuk bus_key tertentu (tanpa membukanya).

    Satu kamera fisik bisa memunculkan BEBERAPA /dev/videoN (misal video0 untuk
    gambar, video1 untuk metadata). Fungsi ini mengumpulkan semua yang berasal
    dari lubang USB yang sama.
    """
    out = []
    # glob.glob("/dev/video[0-9]*") mencari semua file yang cocok polanya.
    # key=lambda p: ... adalah cara mengurutkan: "lambda" = fungsi mini tanpa nama.
    #   re.sub(r"\D", "", p) -> hapus semua karakter yang BUKAN angka dari nama file
    #                           ("/dev/video10" menjadi "10")
    #   or 0                 -> kalau hasilnya teks kosong, pakai 0 agar int() tidak error
    # Tujuannya: urutkan sebagai ANGKA (video2 sebelum video10), bukan sebagai
    # teks (yang keliru menaruh video10 sebelum video2).
    for vf in sorted(glob.glob("/dev/video[0-9]*"), key=lambda p: int(re.sub(r"\D", "", p) or 0)):
        # basename mengambil nama file saja: "/dev/video0" -> "video0"
        dev_name = os.path.basename(vf)
        # Linux menyimpan info perangkat di folder khusus /sys.
        name_file = f"/sys/class/video4linux/{dev_name}/name"
        dev_link = f"/sys/class/video4linux/{dev_name}/device"
        # Lewati kalau info yang dibutuhkan tidak tersedia.
        if not os.path.exists(name_file) or not os.path.exists(dev_link):
            continue
        # realpath mengikuti "jalan pintas" (symlink) sampai ke alamat aslinya,
        # yang memuat informasi lubang USB. Contoh hasilnya:
        # /sys/devices/platform/.../usb3/3-1/3-1:1.0
        real = os.path.realpath(dev_link)
        # re.search mencari pola "usb<angka>/<angka>-<angka>" di dalam teks itu.
        # Tanda \d berarti "satu digit angka", tanda + berarti "satu atau lebih".
        # Kurung ( ) menandai bagian yang ingin diambil, disebut "group".
        m = re.search(r"usb(\d+)/(\d+-\d+)", real)
        # m.group(1) = isi kurung pertama ("3"), m.group(2) = kurung kedua ("3-1").
        # Digabung jadi "usb3-3-1" lalu dibandingkan dengan bus_key dari config.
        if m and f"usb{m.group(1)}-{m.group(2)}" == bus_key:
            out.append(vf)
    return out


def resolve_device_by_bus_key(bus_key):  # kompat lama
    """Mengambil SATU node video pertama untuk bus_key ini (dipertahankan untuk kode lama)."""
    c = candidates_by_bus_key(bus_key)
    return c[0] if c else None


def _usb_id_for_bus_key(bus_key):
    """ID USB device untuk unbind/bind (mis. '1-1' atau '3-1') dari bus_key."""
    for vf in candidates_by_bus_key(bus_key):
        real = os.path.realpath(f"/sys/class/video4linux/{os.path.basename(vf)}/device")
        # real berakhir pada antarmuka spt '.../1-1/1-1:1.0'
        iface = os.path.basename(real)          # '1-1:1.0'
        usb_id = iface.split(":")[0]            # '1-1'
        # re.match memeriksa apakah teks DIAWALI pola tersebut.
        # ^ berarti "mulai dari awal teks".
        if re.match(r"^\d+-\d+", usb_id):
            return usb_id
    # cadangan: turunkan dari bus_key 'usbB-P-Q' -> 'P-Q'
    m = re.match(r"usb\d+-(\d+-\d+)", bus_key)
    return m.group(1) if m else None


# Folder khusus Linux untuk mengendalikan driver USB. Menulis ke file
# "unbind" di sini = melepas perangkat; menulis ke "bind" = memasangnya lagi.
# Efeknya mirip mencabut lalu mencolokkan kabel USB, tapi lewat perangkat lunak.
DRV = "/sys/bus/usb/drivers/usb"


def _write_drv(fname, value):
    """Tulis ke bind/unbind. Coba langsung (file di-chmod o+w oleh service saat
    start via ExecStartPre root); kalau ditolak, fallback ke sudo -n."""
    path = f"{DRV}/{fname}"
    try:
        # Cara 1 (tercepat): tulis langsung. Berhasil kalau izin filenya sudah
        # dilonggarkan saat service dinyalakan.
        with open(path, "w") as f:
            f.write(value)
        return True
    except PermissionError:
        # Cara 2: minta bantuan sudo. Perhatikan "except PermissionError" —
        # ini hanya menangkap error IZIN saja, bukan semua jenis error.
        # sudo -n artinya "jangan tanya password"; kalau butuh password, langsung gagal
        # (agar program tidak menggantung menunggu ketikan yang tak akan pernah datang).
        r = subprocess.run(["sudo", "-n", "sh", "-c", f"printf %s '{value}' > {path}"],
                           capture_output=True, timeout=8)
        # returncode 0 = perintah sukses (aturan umum di Linux).
        return r.returncode == 0
    except Exception:
        return False


def usb_reset(bus_key):
    """Reset (re-enumerate) USB device lewat unbind/bind -> membangunkan device
    yang wedged/hang. Tidak butuh sudo bila file sudah di-chmod saat start."""
    usb_id = _usb_id_for_bus_key(bus_key)
    if not usb_id:
        return False
    ok_u = _write_drv("unbind", usb_id)   # "cabut" perangkat secara perangkat lunak
    time.sleep(1.5)                       # beri jeda agar benar-benar terlepas
    ok_b = _write_drv("bind", usb_id)     # "colok" kembali
    time.sleep(2.0)  # tunggu re-enumerate
    # (re-enumerate = Linux mengenali ulang perangkat dan membuatkan /dev/videoN baru)
    print(f"[CAM] USB reset {bus_key} (id {usb_id}) unbind={ok_u} bind={ok_b}")
    return ok_b


class CameraStream:
    """Mengurus SATU kamera: membuka, membaca frame terus-menerus, dan pulih sendiri."""

    def __init__(self, name, bus_key, width, height, fps, cfg=None):
        self.name = name          # nama untuk log, contoh "1-deteksi"
        self.bus_key = bus_key    # penanda lubang USB, contoh "usb3-3-1"
        self.width = width        # lebar gambar yang diminta (piksel)
        self.height = height      # tinggi gambar yang diminta (piksel)
        self.fps = fps            # frame per detik yang diminta ke kamera
        cfg = cfg or {}           # kalau cfg tidak diberikan, pakai dict kosong
        # Baris-baris berikut mengambil pengaturan dengan nilai bawaan (angka
        # setelah koma) bila tidak diatur di config.json.
        self._verify_reads = int(cfg.get("open_verify_reads", 15))     # berapa kali coba baca saat verifikasi
        self._reset_after = int(cfg.get("reset_after_failures", 4))    # gagal berapa kali sebelum reset USB
        self._enable_reset = bool(cfg.get("enable_usb_reset", True))   # boleh reset USB? True/False
        self._stall_seconds = float(cfg.get("stall_seconds", 4.0))     # diam berapa detik dianggap macet

        self.device = None          # alamat /dev/videoN yang sedang dipakai
        self.cap = None             # objek VideoCapture OpenCV
        self.frame = None           # gambar terbaru dari kamera
        self.lock = threading.Lock()  # kunci agar frame tidak dibaca saat ditulis
        self.running = False        # penanda loop masih boleh jalan
        self.last_ok = 0.0          # waktu terakhir berhasil dapat frame
        self._fps_count = 0         # penghitung frame untuk mengukur FPS asli
        self._fps_t = time.time()   # patokan waktu mulai menghitung FPS
        self.actual_fps = 0.0       # FPS nyata hasil pengukuran
        self._fail_reads = 0        # berapa kali berturut-turut gagal baca frame
        self._open_fails = 0        # berapa kali berturut-turut gagal membuka kamera
        self.reopen_count = 0       # statistik: sudah berapa kali dibuka ulang
        self.reset_count = 0        # statistik: sudah berapa kali USB di-reset

    def start(self):
        """Menyalakan loop pengambilan gambar di thread terpisah."""
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    # ---- pembukaan ----
    def _try_device(self, dev):
        """Mencoba membuka SATU node /dev/videoN. Mengembalikan objek cap kalau berhasil."""
        # cv2.CAP_V4L2 memaksa OpenCV memakai driver V4L2 Linux (paling stabil di Pi).
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not cap.isOpened():
            # release() melepas perangkat agar tidak "dikunci" program kita.
            cap.release()
            return None
        # Mengatur properti kamera. Nama properti selalu diawali cv2.CAP_PROP_.
        # MJPG = format kompresi. Kamera USB murah biasanya hanya sanggup
        # resolusi tinggi + FPS tinggi jika memakai MJPG, bukan format mentah.
        # Tanda * pada *"MJPG" memecah teks jadi 4 huruf terpisah: 'M','J','P','G'.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        # BUFFERSIZE 1 = simpan hanya 1 gambar di antrean. Penting untuk sistem
        # real-time: kita mau gambar TERBARU, bukan gambar lama yang menumpuk
        # di antrean (kalau menumpuk, sortir jadi telat bereaksi).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Verifikasi: isOpened() saja SERING BOHONG (mengaku terbuka padahal
        # tidak bisa mengirim gambar). Jadi kita buktikan dengan benar-benar
        # membaca frame beberapa kali.
        # "for _ in range(n)" = ulangi n kali; garis bawah (_) dipakai sebagai
        # nama variabel saat nilainya memang tidak kita butuhkan.
        for _ in range(self._verify_reads):
            # cap.read() mengembalikan DUA nilai sekaligus:
            #   ok    = True/False, berhasil atau tidak
            #   frame = gambarnya
            ok, frame = cap.read()
            if ok and frame is not None:
                return cap      # terbukti bisa mengirim gambar -> pakai ini
            time.sleep(0.12)    # beri jeda, mungkin kamera masih pemanasan
        # Sudah dicoba berkali-kali tapi tetap tidak ada gambar -> menyerah.
        cap.release()
        return None

    def _open(self):
        """Mencari dan membuka kamera sesuai bus_key. True kalau berhasil."""
        # Hanya bagian buka device yang di-lock (JANGAN panggil reset di dalam
        # lock -> Lock tidak reentrant -> deadlock).
        # ("reentrant" = boleh dikunci dua kali oleh thread yang sama.
        #  threading.Lock TIDAK reentrant, jadi kalau kode di dalam blok kunci
        #  mencoba mengunci lagi, program membeku selamanya. Itulah "deadlock".)
        with _OPEN_LOCK:
            cands = candidates_by_bus_key(self.bus_key)
            # Coba satu per satu, karena satu kamera bisa punya beberapa node
            # dan biasanya hanya salah satu yang benar-benar mengirim gambar.
            for dev in cands:
                cap = self._try_device(dev)
                if cap is not None:
                    self.cap = cap
                    self.device = dev
                    # Berhasil -> nolkan lagi penghitung kegagalan.
                    self._fail_reads = 0
                    self._open_fails = 0
                    print(f"[CAM {self.name}] {dev} ({self.bus_key}) streaming ✓")
                    return True
        # Sampai di sini berarti semua kandidat gagal.
        self._open_fails += 1
        if cands:
            # Perangkatnya terdeteksi tapi belum mau mengirim gambar.
            # Dua teks berdempetan dalam kurung otomatis disambung Python
            # menjadi satu kalimat panjang.
            print(f"[CAM {self.name}] {self.bus_key} ada {cands} tapi belum streaming "
                  f"(gagal ke-{self._open_fails})")
        self._maybe_reset()  # di luar lock
        return False

    def _maybe_reset(self):
        """Kalau sudah terlalu sering gagal, tempuh cara keras: reset port USB."""
        if self._enable_reset and self._open_fails >= self._reset_after:
            print(f"[CAM {self.name}] {self._open_fails}x gagal -> reset USB {self.bus_key}")
            with _OPEN_LOCK:  # aman: dipanggil dari _loop, bukan dari dalam _open
                if usb_reset(self.bus_key):
                    self.reset_count += 1
            # Nolkan penghitung agar tidak langsung reset lagi di putaran berikutnya.
            self._open_fails = 0

    # ---- loop utama ----
    def _loop(self):
        """Berputar terus: ambil gambar terbaru, simpan, hitung FPS, pulih bila error."""
        while self.running:
            # Belum ada koneksi kamera -> coba buka dulu.
            if self.cap is None:
                if not self._open():
                    time.sleep(2)   # gagal -> tunggu 2 detik sebelum coba lagi
                # "continue" = langsung ulangi dari atas while, lewati sisa kode.
                continue

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._fail_reads += 1
                # Gagal sekali-dua kali itu wajar (gangguan kecil). Tapi kalau
                # sudah 5 kali berturut-turut, berarti kamera bermasalah sungguhan.
                if self._fail_reads >= 5:
                    print(f"[CAM {self.name}] {self._fail_reads}x gagal baca -> reopen")
                    self._release_cap()      # tutup, agar putaran berikutnya membuka ulang
                    self.reopen_count += 1
                    time.sleep(0.4)
                else:
                    time.sleep(0.05)
                continue

            # Berhasil dapat gambar -> nolkan penghitung kegagalan.
            self._fail_reads = 0
            # Kunci sebentar saat menyimpan frame, agar thread lain tidak
            # membaca gambar yang sedang setengah tertulis.
            with self.lock:
                self.frame = frame
                self.last_ok = time.time()   # catat waktunya untuk pengecekan "sehat"
            # ---- perhitungan FPS nyata ----
            self._fps_count += 1
            now = time.time()
            # Setiap 1 detik sekali, hitung: jumlah frame dibagi lama waktunya.
            if now - self._fps_t >= 1.0:
                self.actual_fps = self._fps_count / (now - self._fps_t)
                # Nolkan penghitung untuk periode berikutnya.
                self._fps_count = 0
                self._fps_t = now

    def _release_cap(self):
        """Menutup koneksi kamera dengan aman (error diabaikan)."""
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass
        self.cap = None

    # ---- akses ----
    def read(self):
        """Mengambil SALINAN gambar terbaru. None kalau belum ada gambar."""
        with self.lock:
            # .copy() penting! Tanpa itu, pemanggil menerima gambar yang SAMA
            # persis di memori — kalau ia mencoret-coret gambar itu, loop kamera
            # ikut terpengaruh dan bisa error karena diubah saat dipakai.
            return None if self.frame is None else self.frame.copy()

    def healthy(self):
        """True kalau kamera masih mengirim gambar dalam 2 detik terakhir."""
        # Kalau last_ok masih 0 (belum pernah dapat gambar sama sekali) -> False.
        return (time.time() - self.last_ok) < 2.0 if self.last_ok else False

    def wait_healthy(self, timeout):
        """Menunggu sampai kamera sehat, maksimal 'timeout' detik. True kalau keburu sehat."""
        t0 = time.time()    # catat waktu mulai menunggu
        while time.time() - t0 < timeout:
            if self.healthy():
                return True
            time.sleep(0.2)  # periksa ulang tiap 0,2 detik
        return False         # waktu habis, kamera tetap belum sehat

    def stop(self):
        """Menghentikan loop dan menutup kamera."""
        self.running = False
        self._release_cap()

    def stats(self):
        """Ringkasan kondisi kamera untuk ditampilkan di halaman web."""
        # round(x, 1) membulatkan ke 1 angka di belakang koma (4.8571 -> 4.9).
        return {"device": self.device, "healthy": self.healthy(),
                "fps": round(self.actual_fps, 1), "reopen": self.reopen_count,
                "usb_reset": self.reset_count}


class CameraManager:
    """Mengurus KEDUA kamera sekaligus + watchdog pendeteksi kamera macet."""

    def __init__(self, cfg):
        # Ambil bagian "camera" dari config.json.
        cam = cfg.get("camera")
        # Jeda antara menyalakan cam1 dan cam2 (agar tidak berebut driver).
        self._stagger = float(cam.get("init_stagger_seconds", 1.5))
        # Buat dua objek kamera. Perhatikan bedanya hanya pada nama dan bus_key;
        # resolusi dan FPS-nya sama, diambil dari config yang sama.
        self.cam1 = CameraStream("1-deteksi", cam["cam1_bus_key"], cam["width"], cam["height"], cam["fps"], cam)
        self.cam2 = CameraStream("2-sorting", cam["cam2_bus_key"], cam["width"], cam["height"], cam["fps"], cam)
        self._watchdog_running = False

    def start(self):
        # Init benar-benar berurutan: cam1 dulu sampai streaming, baru cam2.
        self.cam1.start()
        # Tunggu cam1 benar-benar mengirim gambar sebelum menyalakan cam2.
        if not self.cam1.wait_healthy(timeout=self._stagger + 6):
            # Walau cam1 gagal, cam2 tetap dinyalakan — biar sistem tetap
            # sebagian jalan, dan mekanisme self-heal akan terus mencoba cam1.
            print("[CAM] cam1 belum sehat saat stagger; cam2 tetap dimulai (self-heal jalan)")
        time.sleep(self._stagger)
        self.cam2.start()

        # Nyalakan watchdog: penjaga yang memeriksa kondisi kamera secara berkala.
        self._watchdog_running = True
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        """Deteksi kamera yang tadinya sehat lalu hang -> paksa reopen."""
        while self._watchdog_running:
            time.sleep(2.0)   # periksa tiap 2 detik
            # Tanda kurung (a, b) membuat "tuple": daftar yang isinya tetap.
            # Di sini dipakai supaya kode pemeriksaan tidak perlu ditulis 2x.
            for cam in (self.cam1, self.cam2):
                # sudah pernah dapat frame, tapi kini basi > stall_seconds -> hang
                # Tiga syarat harus terpenuhi semua (dihubungkan kata "and"):
                #   1. cam.last_ok        -> pernah berhasil dapat gambar
                #   2. selisih waktu besar -> sudah lama tidak ada gambar baru
                #   3. cam.cap is not None -> koneksinya masih terbuka (jadi memang macet,
                #                             bukan sekadar sedang menunggu dibuka)
                if cam.last_ok and (time.time() - cam.last_ok) > cam._stall_seconds and cam.cap is not None:
                    print(f"[CAM {cam.name}] STALL {time.time() - cam.last_ok:.1f}s -> reopen paksa")
                    # Cukup ditutup; loop kamera akan otomatis membukanya lagi.
                    cam._release_cap()
                    cam.reopen_count += 1

    def stop(self):
        """Mematikan watchdog dan kedua kamera."""
        self._watchdog_running = False
        self.cam1.stop()
        self.cam2.stop()
