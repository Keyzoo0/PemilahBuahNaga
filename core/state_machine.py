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

CATATAN UNTUK PEMULA:
File ini adalah OTAK sistem. Isinya paling panjang karena di sinilah semua
keputusan diambil.

Apa itu "state machine" (mesin keadaan)?
Bayangkan lampu lalu lintas. Ia selalu berada di SATU keadaan: merah, kuning,
atau hijau. Perpindahan keadaan punya aturan jelas (merah -> hijau -> kuning ->
merah), tidak bisa loncat sembarangan. Program ini bekerja persis seperti itu.

Keadaan (state) di sistem ini:
  IDLE           : diam, menunggu buah ditaruh di kamera 1
  REJECT_FORWARD : ada benda asing -> konveyor maju untuk membuangnya
  STRAIGHT_OUT   : buah matang -> konveyor mundur lurus keluar
  SERVO_SORT     : buah mentah/setengah -> mundur sambil menunggu waktu "tampol"
  SERVO_RETURN   : servo baru saja menampol, tunggu sebentar
  COOLDOWN       : jeda istirahat sebelum siap menerima buah berikutnya
  FAULT          : ada masalah -> semua berhenti demi keamanan

Kenapa perlu "gerbang settle"?
Saat tangan kita meletakkan buah, tangan itu ikut terlihat kamera. Kalau sistem
langsung memutuskan, ia bisa salah menilai (atau konveyor jalan saat tangan
masih di atasnya — berbahaya). Maka sistem menunggu sampai gambar benar-benar
DIAM dulu, tanda tangan sudah ditarik, baru mengambil keputusan.
"""
import threading                    # menjalankan pekerjaan bersamaan
import time                         # pengukuran waktu & jeda
from collections import Counter     # alat penghitung suara (voting)
from datetime import datetime       # tanggal & jam
from pathlib import Path            # penulisan alamat file yang aman

import cv2                          # OpenCV: pengolahan gambar
import numpy as np                  # NumPy: perhitungan cepat pada array/matriks gambar

from detector import filter_dets, draw_overlay   # fungsi bantu dari detector.py
from store import store                          # penyimpan riwayat ke database

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"     # tempat menyimpan foto bukti
EMPTY_REF = BASE_DIR / "empty_ref.jpg"           # foto belt kosong sebagai pembanding


def best_det(dets):
    """Memilih deteksi dengan keyakinan (confidence) TERTINGGI dari daftar."""
    # max(daftar, key=fungsi) mencari elemen dengan nilai fungsi terbesar.
    # lambda d: d.conf artinya "bandingkan berdasarkan nilai conf tiap elemen".
    # Kalau daftarnya kosong, kembalikan None (max() akan error bila daftar kosong).
    return max(dets, key=lambda d: d.conf) if dets else None


class SortController:
    def __init__(self, cfg, cams, detector, bridge):
        # Empat komponen utama yang diserahkan dari main.py.
        self.cfg = cfg              # pengaturan (config.json)
        self.cams = cams            # pengatur kedua kamera
        self.detector = detector    # model AI YOLO
        self.bridge = bridge        # jalur perintah ke Arduino

        # ---- keadaan (state) sekarang ----
        self.state = "IDLE"                 # keadaan awal: menunggu
        self.ripeness = None                # hasil klasifikasi buah terakhir
        self.ripeness_index = None   # index kelas asli model (0/1/2)
        self.ripeness_conf = 0.0            # tingkat keyakinan hasil tersebut
        self.last_message = "Menunggu objek di kamera 1"   # pesan untuk ditampilkan di web
        self.last_action = None             # aksi terakhir: servo1/servo2/straight/reject

        # ---- variabel kerja internal ----
        # Counter adalah dictionary khusus untuk menghitung. Dipakai sebagai
        # kotak suara: tiap frame, hasil tebakan YOLO dimasukkan sebagai 1 suara.
        # Yang menang = keputusan akhir. Ini jauh lebih andal daripada percaya
        # satu frame saja, karena satu frame bisa saja salah tebak.
        self._votes = Counter()
        self._watching = False      # True setelah objek/gerakan masuk (tetap awasi walau diam)
        self._settle_low = 0        # frame berturut-turut tanpa gerakan
        self._empty = 0             # frame kosong (untuk fase cam2)
        self._prev_gray = None      # untuk deteksi gerakan
        self._t_state = time.time()   # kapan keadaan sekarang dimulai (untuk hitung durasi)
        self._t_motor = 0.0           # kapan motor mulai jalan (untuk watchdog)
        self._t_motor_cmd = 0.0     # kirim-ulang perintah motor (anti perintah hilang)
        self._motor_dir = None      # 'forward' / 'backward' / None
        self._snapshot_path = None    # alamat foto bukti siklus ini
        self._active_servo = 1        # servo mana yang sedang dipakai (1 atau 2)
        self._last_motion = 0.0       # nilai gerakan terakhir (untuk ditampilkan di web)
        self._last_fg = None          # rasio objek asing terakhir
        self._paddle_baseline = None  # ROI paddle kosong saat sorting mulai
        self._slap_hits = 0           # frame berturut ada perubahan di paddle
        self._last_paddle_change = 0.0  # nilai perubahan paddle terakhir (untuk kalibrasi)
        self._matang_seen = False     # buah matang sudah masuk cam2
        self._t_exit = 0.0            # penanda buah matang keluar cam2
        self._consec_rejects = 0    # pengaman: cegah loop reject tanpa henti
        self._t_watch_start = 0.0   # kapan mulai mengawasi (anti-deadlock settle)
        self._last_fruit = None     # (label, conf) buah terakhir terlihat saat watch
        self._led_status = None     # status indikator terakhir yang dikirim
        self._t_last_bip = 0.0      # penanda bip-bip terakhir saat sorting

        self.estop = False          # tombol darurat sedang ditekan?
        # Mode awal saat menyala diambil dari config; bawaannya "manual" agar
        # konveyor tidak langsung bergerak sendiri tanpa diawasi orang.
        self.manual_mode = cfg.get("system", "start_mode", default="manual") == "manual"
        if self.manual_mode:
            self.last_message = "Boot mode MANUAL — klik AUTO di web untuk mulai sortasi"
        self.running = False        # penanda loop utama masih boleh jalan

        # Gambar hasil coretan (kotak deteksi + teks) untuk dilihat di web.
        self.annotated = {"cam1": None, "cam2": None}
        self._ann_lock = threading.Lock()   # kunci agar aman dibaca web sambil ditulis
        self.fault_count = 0                # berapa kali sistem masuk FAULT

        # latar belt kosong (untuk deteksi objek reject)
        self._empty_ref = None
        if EMPTY_REF.exists():
            img = cv2.imread(str(EMPTY_REF))
            if img is not None:
                # Diubah ke grayscale (hitam-putih) karena perbandingan latar
                # cuma butuh terang-gelap, tidak perlu warna. Lebih cepat dan
                # lebih tahan terhadap perubahan pencahayaan.
                self._empty_ref = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                print("[SM] Latar kosong dimuat dari empty_ref.jpg")

    # ---------------------------------------------------------
    def start(self):
        """Menyalakan loop utama state machine di thread terpisah."""
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _set_annotated(self, key, frame):
        """Menyimpan gambar (sudah dicoret) dalam bentuk JPEG untuk stream web."""
        if frame is None:
            return
        # imencode memampatkan gambar menjadi format JPEG di dalam memori
        # (tidak menyentuh kartu SD sama sekali -> cepat & awet).
        # Kualitas 80 dari 100: cukup jernih untuk dipantau, ukurannya kecil.
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self._ann_lock:
                self.annotated[key] = buf.tobytes()

    def get_jpeg(self, key):
        """Dipanggil api.py untuk mengambil gambar terbaru yang akan dikirim ke browser."""
        with self._ann_lock:
            return self.annotated.get(key)

    # ---------------------------------------------------------
    def _transition(self, state, msg=None):
        """Berpindah ke keadaan baru + mencatat waktunya."""
        self.state = state
        # Waktu ini penting: banyak keadaan yang berakhir setelah sekian detik,
        # dan perhitungannya memakai patokan waktu ini.
        self._t_state = time.time()
        if msg:
            self.last_message = msg
        print(f"[SM] -> {state} :: {self.last_message}")

    def _enter_fault(self, reason):
        """Masuk keadaan darurat: semua gerakan dihentikan."""
        self._stop_motor()
        self.bridge.s1_close()
        self.bridge.s2_close()
        self.fault_count += 1
        self._transition("FAULT", f"FAULT: {reason}")

    def _motor_watchdog(self):
        """Pengaman: kalau motor jalan terlalu lama, pasti ada yang salah.

        Contoh masalah: buah tersangkut, sensor tidak melihat buah keluar,
        atau belt selip. Kalau dibiarkan, motor bisa jalan selamanya.
        Mengembalikan True bila FAULT dipicu.
        """
        limit = float(self.cfg.get("timing", "max_motor_runtime_seconds", default=15.0))
        if self._t_motor and (time.time() - self._t_motor) > limit:
            self._enter_fault("motor melebihi batas waktu (objek tidak terdeteksi keluar)")
            return True
        return False

    def _run_motor(self, direction):
        """Mulai motor + tandai arah agar terus dikirim ulang."""
        self._motor_dir = direction
        self._t_motor = time.time()
        self._t_motor_cmd = 0.0  # paksa kirim segera di _keep_motor
        # (dengan menyetel 0.0, selisih waktu di _keep_motor pasti besar,
        #  sehingga perintah langsung dikirim tanpa menunggu 0,5 detik)
        self._keep_motor()

    def _keep_motor(self):
        """Kirim ULANG perintah motor tiap 0.5s selama fase gerak. Mencegah buah
        'nyangkut' gara-gara satu perintah motor hilang di serial (glitch USB)."""
        if self._motor_dir is None:
            return
        now = time.time()
        if now - self._t_motor_cmd >= 0.5:
            if self._motor_dir == "backward":
                self.bridge.motor_backward()
            elif self._motor_dir == "forward":
                self.bridge.motor_forward()
            self._t_motor_cmd = now

    def _stop_motor(self):
        """Menghentikan motor dan membatalkan pengiriman ulang perintah."""
        # Urutannya penting: arah dinolkan DULU agar _keep_motor tidak
        # menyalakan motor lagi tepat setelah kita menyuruhnya berhenti.
        self._motor_dir = None
        self.bridge.motor_stop()

    # ---------------------------------------------------------
    # INDIKATOR LED & BUZZER (status sistem)
    #   KUNING = Raspi belum siap
    #   HIJAU  = siap, buah boleh ditaruh di kamera 1
    #   MERAH  = sedang sorting (buzzer bip-bip)
    #   transisi ke HIJAU = bip panjang 1.5 detik
    # ---------------------------------------------------------
    # Dua baris ini ditulis di dalam class tapi di luar fungsi, artinya nilainya
    # dipakai bersama oleh semua objek dan tidak pernah berubah (semacam tabel tetap).
    _LED_BY_STATUS = {"ready": "green", "busy": "red", "notready": "yellow"}
    _BUSY_STATES = ("REJECT_FORWARD", "STRAIGHT_OUT",
                    "SERVO_SORT", "SERVO_RETURN", "COOLDOWN")

    def _indicator_status(self):
        """Menentukan warna lampu berdasarkan kondisi sistem saat ini."""
        # "notready" bila ADA SATU SAJA masalah di antara syarat berikut.
        # Tanda "or" berarti cukup salah satu benar. Tanda kurung membuat
        # kondisi panjang ini boleh ditulis beberapa baris agar terbaca.
        if (self.estop or self.manual_mode or self.state == "FAULT"
                or not self.bridge.connected                    # Arduino tidak tersambung
                or not self.cams.cam1.healthy() or not self.cams.cam2.healthy()):  # kamera mati
            return "notready"
        # "in" memeriksa apakah state sekarang termasuk dalam daftar _BUSY_STATES.
        if self.state in self._BUSY_STATES:
            return "busy"
        return "ready"  # IDLE = siap ditaruh buah

    def _apply_status_led(self, status):
        """Menyalakan satu LED dan mematikan dua lainnya."""
        want = self._LED_BY_STATUS[status]
        for color in ("green", "yellow", "red"):
            # Kirim 1 (nyala) hanya untuk warna yang diinginkan, 0 (mati) untuk sisanya.
            self.bridge.send(f"led {color} {1 if color == want else 0}")

    def _long_beep(self):
        """Bunyi panjang penanda sistem siap menerima buah."""
        ms = int(self.cfg.get("feedback", "ready_beep_ms", default=1500))
        self.bridge.send("buzzer on")
        # threading.Timer menjalankan sesuatu SETELAH sekian detik, tanpa
        # menghentikan program (berbeda dengan time.sleep yang membekukan).
        # ms/1000.0 mengubah milidetik menjadi detik.
        # lambda: ... adalah fungsi mini yang akan dijalankan nanti saat waktunya tiba.
        threading.Timer(ms / 1000.0, lambda: self.bridge.send("buzzer off")).start()

    def _update_indicators(self):
        """Memperbarui LED & buzzer sesuai kondisi terkini."""
        if not self.bridge.connected:
            self._led_status = None  # paksa set ulang saat serial tersambung lagi
            return

        status = self._indicator_status()
        # Kirim perintah HANYA saat status berubah, bukan tiap putaran.
        # Kalau dikirim terus-menerus, jalur serial akan banjir perintah dan
        # perintah penting (motor/servo) bisa tertunda.
        if status != self._led_status:
            self._apply_status_led(status)
            if status == "ready":
                self._long_beep()  # transisi ke HIJAU -> bip panjang
            self._led_status = status
            self._t_last_bip = 0.0

        if status == "busy":
            # Selama sorting, bunyikan bip berkala sebagai peringatan
            # "hati-hati, mesin sedang bergerak".
            interval = int(self.cfg.get("feedback", "sorting_bip_interval_ms", default=1000)) / 1000.0
            now = time.time()
            if now - self._t_last_bip >= interval:
                self.bridge.beep(2)  # bip-bip selama lampu merah
                self._t_last_bip = now

    # ---------------------------------------------------------
    # HELPER VISI: gerakan & foreground
    # ---------------------------------------------------------
    def _roi_box(self):
        """Mengambil kotak ROI deteksi sebagai 4 angka: x, y, lebar, tinggi."""
        # Kalau ROI belum diatur, pakai kotak raksasa = seluruh gambar dianggap ROI.
        roi = self.cfg.get("detect", "roi") or {"x": 0, "y": 0, "w": 99999, "h": 99999}
        return int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"])

    def _roi_gray(self, frame):
        """Grayscale ROI untuk deteksi gerakan.

        Dikecilkan + di-blur agar NOISE SENSOR kamera (bintik) tidak terbaca
        sebagai gerakan. Tanpa ini, belt diam pun terukur ~5 dan gerbang settle
        tidak pernah selesai.
        """
        x, y, w, h = self._roi_box()
        # Koordinat negatif akan membuat pemotongan gambar kacau -> dipaksa minimal 0.
        x, y = max(0, x), max(0, y)
        # Memotong gambar dengan notasi [baris_awal:baris_akhir, kolom_awal:kolom_akhir].
        # Perhatikan: pada gambar, urutannya Y (tinggi) DULU baru X (lebar).
        crop = frame[y:y + h, x:x + w]
        # Kalau hasil potongan kosong (ROI di luar gambar), pakai gambar utuh.
        if crop.size == 0:
            crop = frame
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Diperkecil ke 160x120: perhitungan jadi jauh lebih ringan, dan bintik
        # halus ikut hilang karena tergabung saat pengecilan.
        small = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_AREA)
        # GaussianBlur mengaburkan gambar sedikit (kernel 5x5) untuk meredam
        # sisa bintik. Ibarat memicingkan mata agar detail kecil tak terlihat.
        return cv2.GaussianBlur(small, (5, 5), 0)

    def _motion(self, gray):
        """Rata-rata beda antar-frame di ROI (0-255). Besar = ada gerakan."""
        # Frame pertama belum punya pembanding -> anggap tidak ada gerakan.
        # Bentuk gambar juga dicek: kalau ROI baru diubah dari web, ukurannya
        # bisa berbeda dan absdiff akan error.
        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray
            return 0.0
        # absdiff = selisih mutlak tiap piksel antara gambar sekarang dan
        # sebelumnya. Kalau tidak ada yang bergerak, selisihnya mendekati nol.
        d = cv2.absdiff(gray, self._prev_gray)
        # Simpan gambar sekarang untuk jadi pembanding di putaran berikutnya.
        self._prev_gray = gray
        # .mean() = rata-rata seluruh piksel -> satu angka mewakili "seberapa
        # banyak yang berubah" di seluruh area.
        return float(d.mean())

    def _foreground_ratio(self, frame):
        """Luas objek asing di ROI (fraksi 0-1). None jika latar belum dikalibrasi.

        Memakai KOMPONEN TERBESAR, bukan total piksel berubah. Belt bertekstur
        yang bergeser menghasilkan bintik-bintik kecil tersebar (bukan objek) —
        itu dibuang lewat blur + morphological opening, sehingga tidak memicu
        reject palsu. Buah/objek nyata membentuk satu gumpalan besar.
        """
        # Belum ada foto belt kosong -> tidak bisa membandingkan apa pun.
        if self._empty_ref is None:
            return None
        x, y, w, h = self._roi_box()
        x, y = max(0, x), max(0, y)
        # Ambil bagian ROI dari gambar sekarang dan dari foto belt kosong.
        cur = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)[y:y + h, x:x + w]
        ref = self._empty_ref[y:y + h, x:x + w]
        # Ukuran keduanya harus sama persis agar bisa dibandingkan piksel per piksel.
        if cur.size == 0 or cur.shape != ref.shape:
            return None

        small = (160, 120)
        # Kedua gambar diperlakukan sama persis (kecilkan + blur) agar adil.
        cur_s = cv2.GaussianBlur(cv2.resize(cur, small, interpolation=cv2.INTER_AREA), (5, 5), 0)
        ref_s = cv2.GaussianBlur(cv2.resize(ref, small, interpolation=cv2.INTER_AREA), (5, 5), 0)

        thr = int(self.cfg.get("detect", "fg_pixel_threshold", default=30))
        # Membuat "mask": peta hitam-putih. Piksel bernilai 1 kalau bedanya
        # melebihi ambang (berarti ada sesuatu di sana), 0 kalau sama saja.
        # .astype(np.uint8) mengubah True/False menjadi angka 1/0.
        mask = (cv2.absdiff(cur_s, ref_s) > thr).astype(np.uint8)
        # MORPH_OPEN = "erosi lalu dilasi": menghapus bintik-bintik kecil
        # tapi membiarkan gumpalan besar tetap utuh. np.ones((3,3)) adalah
        # kuas 3x3 piksel yang dipakai untuk proses ini.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

        # connectedComponentsWithStats mengelompokkan piksel yang saling
        # bersentuhan menjadi objek-objek terpisah. Angka 8 artinya piksel
        # diagonal juga dihitung bersentuhan.
        # Fungsi ini mengembalikan 4 nilai; garis bawah (_) menandai nilai
        # yang tidak kita butuhkan.
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        # n = 1 berarti hanya ada latar belakang saja, tidak ada objek apa pun.
        if n <= 1:
            return 0.0
        # stats[1:] melewati baris ke-0 karena itu milik latar belakang.
        # CC_STAT_AREA adalah kolom yang berisi luas tiap objek; .max() mengambil
        # yang terbesar — inilah kandidat "objek sungguhan".
        largest = int(stats[1:, cv2.CC_STAT_AREA].max())
        # Dibagi total piksel agar hasilnya berupa fraksi 0-1 (misal 0.08 = 8% area).
        return float(largest) / float(mask.size)

    def save_empty_reference(self):
        """Menyimpan foto belt kosong sebagai pembanding (tombol di halaman Kalibrasi)."""
        frame = self.cams.cam1.read()
        if frame is None:
            return False
        cv2.imwrite(str(EMPTY_REF), frame)
        self._empty_ref = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        print("[SM] Latar kosong disimpan.")
        return True

    # ---------------------------------------------------------
    def _loop(self):
        """Loop utama: memanggil _tick() terus-menerus, kira-kira 20 kali per detik."""
        while self.running:
            t0 = time.time()      # catat waktu mulai putaran
            try:
                self._tick()
            except Exception as exc:
                # Error di satu putaran TIDAK BOLEH mematikan seluruh sistem.
                # Cukup dicatat, lalu putaran berikutnya jalan seperti biasa.
                print(f"[SM] error tick: {exc}")
            dt = time.time() - t0   # berapa lama putaran tadi memakan waktu
            # Kalau selesai lebih cepat dari 0,05 detik, tidur sisa waktunya.
            # Ini menjaga kecepatan tetap stabil ~20 putaran per detik dan
            # mencegah CPU terpakai 100% percuma.
            if dt < 0.05:
                time.sleep(0.05 - dt)

    def _detcfg_cam1(self):
        """Merangkum pengaturan deteksi menjadi satu dictionary siap pakai."""
        d = self.cfg.get("detect")
        return {"conf_threshold": d["conf_threshold"], "conf_per_class": d["conf_per_class"],
                "min_area": d["min_box_area"]}

    def _active_paddle_roi(self):
        """ROI paddle servo aktif. servo1(mentah)=paddle_roi_1, servo2(setengah)=paddle_roi_2."""
        s = self.cfg.get("sort_cam2")
        # Rantai "or" bertingkat = urutan cadangan:
        #   1. ROI khusus servo yang sedang aktif
        #   2. kalau tidak ada, ROI umum
        #   3. kalau tidak ada juga, kotak raksasa (seluruh gambar)
        return (s.get(f"paddle_roi_{self._active_servo}") or s.get("paddle_roi")
                or {"x": 0, "y": 0, "w": 999999, "h": 999999})

    def _gray_roi(self, frame, roi):
        """Grayscale kecil (ukuran tetap) dari ROI (roi=None -> seluruh frame)."""
        if frame is None:
            return None
        if roi is None:
            crop = frame
        else:
            x, y, w, h = int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"])
            x, y = max(0, x), max(0, y)
            crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            return None
        # Ukuran dipaksa selalu 120x90 agar hasil dari ROI mana pun bisa
        # dibandingkan langsung (bentuk arraynya pasti sama).
        g = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (120, 90), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(g, (5, 5), 0)

    def _area_change(self, frame, roi, baseline):
        """Fraksi area ROI yang BERUBAH WARNA dibanding baseline (0-1).

        Dipakai untuk mendeteksi "buah sudah sampai di depan lengan servo":
        saat buah masuk area paddle, warnanya berubah dari kondisi kosong.
        """
        cur = self._gray_roi(frame, roi)
        if cur is None or baseline is None or cur.shape != baseline.shape:
            return 0.0
        thr = int((self.cfg.get("sort_cam2") or {}).get("slap_pixel_threshold", 35))
        # .mean() atas hasil perbandingan True/False langsung memberi fraksinya:
        # misal 30 dari 100 piksel berubah -> hasilnya 0.30.
        return float((cv2.absdiff(cur, baseline) > thr).mean())

    def _infer(self, frame, det_cfg, roi):
        """Menjalankan YOLO lalu menyaring hasilnya sesuai ROI & ambang batas."""
        if frame is None:
            return []
        # conf_floor = ambang TERENDAH di antara semua kelas. YOLO dijalankan
        # dengan ambang paling longgar ini supaya tidak ada kandidat terbuang
        # terlalu dini; penyaringan ketat per-kelas dilakukan setelahnya oleh
        # filter_dets. Kalau langsung dijalankan dengan ambang tertinggi, kelas
        # yang ambangnya rendah tidak akan pernah muncul.
        conf_floor = min(det_cfg["conf_per_class"].values()) if det_cfg["conf_per_class"] else det_cfg["conf_threshold"]
        dets_all = self.detector.infer(frame, imgsz=int(self.cfg.get("detect", "imgsz", default=480)), conf=conf_floor)
        return filter_dets(dets_all, roi, det_cfg["min_area"], det_cfg["conf_threshold"], det_cfg["conf_per_class"])

    # ---------------------------------------------------------
    def _tick(self):
        """SATU putaran state machine: periksa keadaan sekarang lalu kerjakan tugasnya."""
        self._update_indicators()

        # Mode darurat / manual -> jangan ambil keputusan apa pun.
        # Kamera tetap ditampilkan agar bisa dipakai untuk kalibrasi.
        if self.estop or self.manual_mode:
            tag = "E-STOP" if self.estop else "MANUAL"
            self._set_annotated("cam1", draw_overlay(self.cams.cam1.read(), [], self.cfg.get("detect", "roi"), tag))
            self._set_annotated("cam2", draw_overlay(self.cams.cam2.read(), [], self.cfg.get("sort_cam2", "paddle_roi"), tag))
            time.sleep(0.1)
            return

        st = self.state

        # ---- kelompok keadaan yang memakai KAMERA 1 ----
        if st in ("IDLE", "REJECT_FORWARD"):
            frame1 = self.cams.cam1.read()
            if st == "IDLE":
                self._state_idle(frame1)
            else:
                self._state_reject(frame1)
            # Kamera 2 tetap ditampilkan, tapi tanpa dijalankan YOLO (hemat CPU).
            self._set_annotated("cam2", draw_overlay(self.cams.cam2.read(), [], self.cfg.get("sort_cam2", "paddle_roi"), "idle"))

        # ---- kelompok keadaan yang memakai KAMERA 2 ----
        elif st in ("STRAIGHT_OUT", "SERVO_SORT", "SERVO_RETURN"):
            frame2 = self.cams.cam2.read()
            roi2 = self._active_paddle_roi() if st in ("SERVO_SORT", "SERVO_RETURN") else None
            # tanpa YOLO di cam2 -> ringan; cukup gambar ROI + info perubahan
            self._set_annotated("cam2", draw_overlay(frame2, [], roi2, st, self.last_message))
            self._set_annotated("cam1", draw_overlay(self.cams.cam1.read(), [], self.cfg.get("detect", "roi"), "idle"))

            if st == "STRAIGHT_OUT":
                self._state_straight_out(frame2)
            elif st == "SERVO_SORT":
                self._state_servo_sort(frame2)
            elif st == "SERVO_RETURN":
                self._state_servo_return()

        # ---- keadaan yang tidak butuh gambar sama sekali ----
        elif st == "COOLDOWN":
            self._state_cooldown()
        elif st == "FAULT":
            self._state_fault()

    # ---------------------------------------------------------
    # IDLE + GERBANG SETTLE (anti-tangan)
    # ---------------------------------------------------------
    def _state_idle(self, frame):
        """Keadaan menunggu: pantau kamera 1, putuskan saat gambar sudah tenang."""
        # Pastikan motor benar-benar mati saat menunggu.
        if self._motor_dir is not None:
            self._stop_motor()
        if frame is None:
            self.last_message = "Menunggu frame kamera 1..."
            return

        # Jangan mulai siklus kalau perangkat belum siap (LED kuning):
        # serial putus / salah satu kamera mati -> sortir pasti gagal & memicu FAULT.
        if self._indicator_status() == "notready":
            # Kembalikan semua penanda ke kondisi awal agar tidak ada sisa data
            # setengah jadi saat perangkat nanti siap kembali.
            self._watching = False
            self._settle_low = 0
            self._votes.clear()
            self.last_message = "Perangkat belum siap (cek kamera/serial)"
            self._set_annotated("cam1", draw_overlay(frame, [], self.cfg.get("detect", "roi"),
                                                     "BELUM SIAP", self.last_message))
            return

        roi = self.cfg.get("detect", "roi")
        gray = self._roi_gray(frame)
        motion = self._motion(gray)              # seberapa banyak yang bergerak
        fg = self._foreground_ratio(frame)       # seberapa luas benda asing di belt
        # Menulis dua penugasan sekaligus dipisah koma — cara ringkas Python.
        self._last_motion, self._last_fg = motion, fg

        motion_thr = float(self.cfg.get("detect", "settle_motion_threshold", default=6.0))
        fg_thr = float(self.cfg.get("detect", "fg_area_ratio", default=0.04))
        fg_present = fg is not None and fg >= fg_thr

        # mulai "watch" begitu ada gerakan / objek muncul; tetap awasi walau lalu diam
        if not self._watching and (motion > motion_thr or fg_present):
            self._watching = True
            self._t_watch_start = time.time()
            self._last_fruit = None

        # Belum ada apa-apa -> tidur-tidur ayam, JANGAN jalankan YOLO.
        # Ini optimasi terpenting: YOLO berat, jadi hanya dinyalakan saat perlu.
        if not self._watching:
            self._settle_low = 0
            self._votes.clear()
            self.last_message = "Menunggu objek di kamera 1"
            self._set_annotated("cam1", draw_overlay(frame, [], roi, "IDLE", self.last_message))
            return

        # sedang mengawasi -> jalankan YOLO
        dets = self._infer(frame, self._detcfg_cam1(), roi)
        fruit = best_det(dets)
        if fruit is not None:
            # Simpan buah terakhir yang sempat terlihat, sebagai cadangan
            # kalau nanti gerbang settle kehabisan waktu.
            self._last_fruit = (fruit.label, fruit.conf)
        self._set_annotated("cam1", draw_overlay(frame, dets, roi, "IDLE (watch)", self.last_message))

        # ANTI-DEADLOCK: kalau gerakan tak pernah reda (mis. noise kamera tinggi),
        # jangan menggantung selamanya — putuskan dengan data yang sudah ada.
        # ("deadlock" = macet total karena menunggu sesuatu yang tak kunjung datang)
        timeout = float(self.cfg.get("detect", "settle_timeout_seconds", default=8.0))
        if self._t_watch_start and (time.time() - self._t_watch_start) > timeout:
            if self._last_fruit:
                # Tuple diakses dengan angka: [0] label, [1] confidence.
                self.ripeness = self._last_fruit[0]
                self.ripeness_conf = self._last_fruit[1]
                self.ripeness_index = getattr(self.detector, "label_to_index", {}).get(self.ripeness)
                print(f"[SM] settle timeout {timeout}s -> paksa putuskan: {self.ripeness}")
                self._start_dragonfruit()
                return
            if fg_present and self._reject_allowed():
                self._start_reject()
                return
            # Tidak ada apa-apa yang meyakinkan -> berhenti mengawasi, kembali menunggu.
            self._watching = False
            self._settle_low = 0
            self.last_message = "Menunggu objek di kamera 1"
            return

        if motion > motion_thr:
            # masih ada gerakan (tangan) -> reset settle, tunggu
            # Hitungan diNOLKAN, bukan dikurangi: syaratnya harus DIAM
            # BERTURUT-TURUT sekian frame, bukan sekadar total sekian frame.
            self._settle_low = 0
            self._votes.clear()
            self.ripeness_conf = 0.0
            self.last_message = "Tunggu gerakan berhenti (tangan menaruh)..."
            return

        # gerakan berhenti -> hitung settle + kumpulkan vote
        self._settle_low += 1
        if fruit is not None:
            self._votes[fruit.label] += 1                          # masukkan satu suara
            self.ripeness_conf = max(self.ripeness_conf, fruit.conf)  # simpan keyakinan tertinggi
            # Foto bukti diambil sekali saja per siklus.
            if self._snapshot_path is None:
                self._snapshot_frame(frame)
        self.last_message = f"Menstabilkan objek... ({self._settle_low})"

        settle_need = int(self.cfg.get("detect", "settle_frames", default=8))
        # Sudah cukup lama diam -> saatnya memutuskan.
        if self._settle_low >= settle_need:
            if self._votes:
                # most_common(1) memberi [(label, jumlah_suara)] terbanyak.
                # [0][0] mengambil labelnya saja: elemen pertama dari pasangan pertama.
                self.ripeness = self._votes.most_common(1)[0][0]
                self.ripeness_index = getattr(self.detector, "label_to_index", {}).get(self.ripeness)
                self._start_dragonfruit()
            elif fg_present and self._reject_allowed():
                # Ada benda di belt tapi YOLO tidak mengenalinya sebagai buah naga.
                self._start_reject()
            else:
                # tak ada objek konklusif (false trigger / sudah pergi) -> berhenti awasi
                self._watching = False
                self._settle_low = 0
                self.last_message = "Menunggu objek di kamera 1"

    def _start_dragonfruit(self):
        """Memulai proses sortir untuk buah naga yang sudah dikenali."""
        self._consec_rejects = 0  # ada buah naga nyata -> pengaman reject di-reset
        # LED kini menandakan STATUS sistem (lihat _update_indicators), bukan kelas buah.
        # mapping menerjemahkan kelas buah menjadi aksi, contoh:
        # {"matang": "straight", "mentah": "servo1", "setengah matang": "servo2"}
        action = (self.cfg.get("mapping", default={}) or {}).get(self.ripeness, "straight")
        self.last_action = action
        self._empty = 0
        self._run_motor("backward")        # BUAH NAGA -> mundur ke servo (bukan forward!)
        if action == "straight":
            # pastikan kedua servo TERTUTUP agar buah matang tak terganjal lengan
            self.bridge.s1_close()
            self.bridge.s2_close()
            self._transition("STRAIGHT_OUT", f"{self.ripeness}: mundur lurus keluar belakang")
        else:
            # Tentukan servo mana yang dipakai berdasarkan hasil mapping.
            self._active_servo = 1 if action == "servo1" else 2
            self._slap_hits = 0
            self._paddle_baseline = None  # diambil SETELAH jeda titik buta
            # Servo dibuka LEBIH DULU agar lengannya sudah siap menghadang
            # saat buah tiba — kalau menunggu buah sampai baru dibuka, terlambat.
            self.bridge.servo_open(self._active_servo)
            self._transition("SERVO_SORT",
                             f"{self.ripeness}: servo{self._active_servo} buka, mundur lewati titik buta")

    def _reject_allowed(self):
        """Cegah loop reject: kalau berkali-kali reject beruntun tanpa satu pun
        buah naga, kemungkinan besar latar kosong sudah tidak cocok."""
        limit = int(self.cfg.get("detect", "max_consecutive_rejects", default=3))
        if self._consec_rejects >= limit:
            self._watching = False
            self._settle_low = 0
            self.last_message = (f"Reject beruntun {self._consec_rejects}x dihentikan — "
                                 f"simpan ulang 'Latar Belt Kosong' di Kalibrasi")
            return False
        return True

    def _start_reject(self):
        """Memulai pembuangan benda yang bukan buah naga."""
        self._consec_rejects += 1
        self.ripeness = "bukan buah naga"
        self.last_action = "reject"
        self._run_motor("forward")         # REJECT -> maju buang
        # Perhatikan arahnya BERLAWANAN dengan sortir buah naga (mundur):
        # buah naga dikirim ke belakang menuju servo, sampah dibuang ke depan.
        self._transition("REJECT_FORWARD", "Bukan buah naga: maju untuk dibuang")

    # ---------------------------------------------------------
    def _state_reject(self, frame):
        """Keadaan membuang benda asing: maju selama sekian detik lalu berhenti."""
        # Kalau watchdog memicu FAULT, hentikan pemrosesan keadaan ini.
        if self._motor_watchdog():
            return
        self._keep_motor()  # jaga motor tetap maju (anti perintah hilang)
        self._set_annotated("cam1", draw_overlay(frame, [], self.cfg.get("detect", "roi"), "REJECT_FORWARD", self.last_message))
        dur = float(self.cfg.get("timing", "reject_forward_seconds", default=4.0))
        # Keadaan ini murni berbasis WAKTU, tidak perlu melihat kamera —
        # yang penting bendanya sudah cukup jauh terdorong keluar.
        if time.time() - self._t_state >= dur:
            self._stop_motor()
            store.add(self.ripeness, None, "reject", self._snapshot_path)
            self._transition("COOLDOWN", "Objek reject dibuang")

    # ---------------------------------------------------------
    # FASE CAM2 (sorting buah naga)
    # ---------------------------------------------------------
    def _state_straight_out(self, frame2):
        # matang: mundur lurus. Pakai YOLO utk tahu buah masih ADA di cam2 atau
        # sudah KELUAR. buah masuk cam2 -> terlihat -> keluar (tak terlihat lagi)
        # -> mundur delay sekian detik -> berhenti.
        if self._motor_watchdog():
            return
        self._keep_motor()  # jaga motor tetap mundur

        # present = True kalau ada buah terdeteksi di kamera 2.
        # roi=None artinya seluruh gambar kamera 2 diperiksa, tanpa batas area.
        present = best_det(self._infer(frame2, self._detcfg_cam1(), None)) is not None
        exitf = int(self.cfg.get("detect", "exit_frames", default=6))
        delay = float(self.cfg.get("timing", "backward_extra_matang_seconds", default=2.0))
        hard = float((self.cfg.get("sort_cam2") or {}).get("matang_max_seconds", 12.0))
        elapsed = time.time() - self._t_state

        if present:
            self._matang_seen = True    # buah sudah tiba di kamera 2
            self._empty = 0             # nolkan hitungan frame kosong
            self._t_exit = 0.0
        elif self._matang_seen:
            # Hanya dihitung kalau buah MEMANG PERNAH terlihat. Tanpa syarat ini,
            # frame kosong di awal (saat buah masih di perjalanan) akan salah
            # dianggap sebagai "buah sudah keluar".
            self._empty += 1

        # Tiga tahap pesan status, sesuai fase perjalanan buah.
        if not self._matang_seen:
            self.last_message = f"matang: mundur, menunggu buah masuk cam2 ({elapsed:.1f}s)"
        elif self._empty < exitf:
            self.last_message = "matang: buah di cam2, mundur terus"
        else:
            # Buah sudah keluar dari pandangan kamera 2 selama exitf frame.
            if self._t_exit == 0.0:
                self._t_exit = time.time()   # catat kapan mulai menghitung mundur tambahan
            remain = delay - (time.time() - self._t_exit)
            self.last_message = f"matang: keluar cam2, mundur {remain:.1f}s lagi"
            if remain <= 0:
                # Mundur tambahan selesai -> buah sudah benar-benar jatuh ke wadah.
                self._stop_motor()
                self._goto_cooldown()
                return

        # jaring pengaman: apa pun yang terjadi, jangan mundur > hard cap
        # Ini lapisan pengaman terakhir seandainya YOLO tidak pernah melihat buah
        # (misal buah terlalu gelap) sehingga logika di atas tak pernah selesai.
        if elapsed >= hard:
            self._stop_motor()
            self._goto_cooldown()

    def _state_servo_sort(self, frame2):
        # 1) mundur LEWATI TITIK BUTA dulu (buah dari cam1 -> cam2),
        # 2) ambil baseline paddle kosong yang segar,
        # 3) begitu ADA PERUBAHAN WARNA (buah masuk paddle) -> tampol.
        if self._motor_watchdog():
            # Kalau gagal, tutup servo agar lengan tidak tertinggal terbuka
            # dan menghalangi jalur konveyor.
            self.bridge.servo_close(self._active_servo)
            return
        self._keep_motor()  # jaga motor tetap mundur (anti perintah hilang)
        s = self.cfg.get("sort_cam2") or {}
        blind = float(s.get("blind_spot_seconds", 2.0))
        elapsed = time.time() - self._t_state
        # TAHAP 1 — titik buta: daerah antara kamera 1 dan kamera 2 yang tidak
        # terlihat kamera mana pun. Selama fase ini tidak ada yang bisa diukur,
        # jadi cukup tunggu sambil terus mundur.
        if elapsed < blind:
            self.last_message = (f"servo{self._active_servo}: mundur lewati titik buta "
                                 f"({elapsed:.1f}/{blind:.1f}s)")
            return
        # TAHAP 2 — ambil foto paddle dalam keadaan masih kosong sebagai pembanding.
        # Diambil SEKARANG (bukan di awal) agar sesuai kondisi cahaya terkini.
        if self._paddle_baseline is None:  # ambil sekali, tepat setelah titik buta
            self._paddle_baseline = self._gray_roi(frame2, self._active_paddle_roi())
            return

        # TAHAP 3 — pantau perubahan; begitu buah masuk area paddle, tampol.
        change = self._area_change(frame2, self._active_paddle_roi(), self._paddle_baseline)
        self._last_paddle_change = change
        # ambang bisa BEDA per servo (servo1 & servo2 kondisi/jarak beda)
        thr = float(s.get(f"slap_area_ratio_{self._active_servo}", s.get("slap_area_ratio", 0.12)))
        need = int(s.get("slap_frames", 2))
        # Tambah 1 kalau perubahan cukup besar, NOLKAN kalau tidak. Artinya
        # perubahan harus terjadi beberapa frame BERTURUT-TURUT — mencegah
        # servo menampol gara-gara satu frame bermasalah (kilatan cahaya, dll).
        self._slap_hits = self._slap_hits + 1 if change >= thr else 0
        self.last_message = (f"servo{self._active_servo}: perubahan paddle "
                             f"{change:.2f}/{thr:.2f} ({self._slap_hits}/{need})")
        if self._slap_hits >= need:
            self.bridge.servo_close(self._active_servo)  # TAMPOL -> 0 derajat
            # (servo dihentak dari 51° ke 0° dengan cepat, sehingga lengannya
            #  "menampol" buah ke jalur keluar yang sesuai)
            self._transition("SERVO_RETURN", f"Tampol! servo{self._active_servo} (Δ{change:.2f})")

    def _state_servo_return(self):
        """Jeda singkat setelah menampol, memastikan buah benar-benar terlempar keluar."""
        # Nilai config dalam milidetik, dibagi 1000 menjadi detik.
        hold = float(self.cfg.get("timing", "servo_slap_hold_ms", default=500)) / 1000.0
        if time.time() - self._t_state >= hold:
            self._stop_motor()
            self._goto_cooldown()

    def _goto_cooldown(self):
        """Menutup satu siklus: simpan riwayat lalu masuk masa istirahat."""
        # buzzer diatur oleh _update_indicators (bip-bip saat merah, bip panjang saat hijau)
        # (self.last_action or "straight") -> pakai "straight" bila entah kenapa kosong.
        store.add(self.ripeness, round(self.ripeness_conf, 3), self.last_action or "straight", self._snapshot_path)
        self._transition("COOLDOWN", f"Selesai: {self.ripeness} -> {self.last_action}")

    def _state_cooldown(self):
        """Masa istirahat: semua aktuator dikembalikan ke posisi aman."""
        self._stop_motor()
        self.bridge.s1_close()
        self.bridge.s2_close()
        if time.time() - self._t_state >= float(self.cfg.get("timing", "cooldown_seconds", default=3.0)):
            self._auto_refresh_empty_ref()
            self._reset_cycle()
            self._transition("IDLE", "Menunggu objek di kamera 1")

    def _auto_refresh_empty_ref(self):
        """Simpan ulang latar belt tiap siklus selesai.

        Belt terus berputar sehingga permukaannya tak pernah sama; latar lama
        cepat basi dan memicu reject palsu terus-menerus. Dengan refresh tiap
        siklus, pembanding selalu segar.
        """
        if not self.cfg.get("system", "auto_save_empty_after_cycle", default=True):
            return
        frame = self.cams.cam1.read()
        if frame is None:
            return
        # Jangan simpan kalau masih ada objek: buah bisa "menyatu" jadi latar
        # dan selamanya tak terdeteksi.
        # (Daftar hasil yang tidak kosong bernilai True dalam pemeriksaan if.)
        if self._infer(frame, self._detcfg_cam1(), self.cfg.get("detect", "roi")):
            print("[SM] latar TIDAK di-refresh: masih ada objek di cam1")
            return
        cv2.imwrite(str(EMPTY_REF), frame)
        self._empty_ref = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._consec_rejects = 0
        print("[SM] latar belt kosong di-refresh otomatis")

    def _state_fault(self):
        """Keadaan gangguan: semua berhenti, lalu coba pulih sendiri setelah beberapa detik."""
        self._stop_motor()
        auto = float(self.cfg.get("timing", "fault_auto_reset_seconds", default=5.0))
        if time.time() - self._t_state >= auto:
            self._reset_cycle()
            self._transition("IDLE", "Recover dari fault, menunggu objek")

    # ---------------------------------------------------------
    def _reset_cycle(self):
        """Mengembalikan SEMUA variabel kerja ke kondisi awal.

        Wajib dipanggil sebelum siklus baru. Kalau ada satu saja variabel yang
        lupa dinolkan, sisa data siklus lama bisa mengacaukan keputusan
        berikutnya (contoh: hitungan vote lama membuat buah baru salah kelas).
        """
        self.ripeness = None
        self.ripeness_index = None
        self.ripeness_conf = 0.0
        self.last_action = None
        self._votes.clear()
        self._watching = False
        self._t_watch_start = 0.0
        self._last_fruit = None
        self._paddle_baseline = None
        self._slap_hits = 0
        self._matang_seen = False
        self._t_exit = 0.0
        self._settle_low = 0
        self._empty = 0
        self._t_motor = 0.0
        self._motor_dir = None
        self._prev_gray = None
        self._snapshot_path = None

    def _snapshot_frame(self, frame):
        """Menyimpan foto bukti hasil sortir (dikelompokkan per tanggal)."""
        if frame is None or not self.cfg.get("system", "save_snapshots", default=True):
            return
        # Folder dipisah per tanggal, contoh: static/uploads/20260809/
        folder = UPLOAD_DIR / datetime.now().strftime("%Y%m%d")
        folder.mkdir(parents=True, exist_ok=True)
        # Nama file berisi jam-menit-detik-mikrodetik agar tidak pernah bentrok.
        fn = folder / f"cam1_{datetime.now().strftime('%H%M%S_%f')}.jpg"
        cv2.imwrite(str(fn), frame)
        # relative_to memotong bagian awal alamat sehingga tersimpan sebagai
        # "uploads/20260809/cam1_....jpg" — bentuk yang pas untuk alamat web,
        # bukan alamat file di kartu SD.
        self._snapshot_path = str(fn.relative_to(UPLOAD_DIR.parent))

    # ---------------------------------------------------------
    # KONTROL EKSTERNAL
    # (fungsi-fungsi di bawah dipanggil dari halaman web lewat api.py)
    # ---------------------------------------------------------
    def trigger_estop(self):
        """Tombol darurat ditekan: hentikan segalanya SEKARANG."""
        self.estop = True
        self._stop_motor()
        self.bridge.s1_close()
        self.bridge.s2_close()
        self.last_message = "E-STOP ditekan"

    def clear_estop(self):
        """Melepas kondisi darurat dan memulai dari keadaan bersih."""
        self.estop = False
        self._reset_cycle()
        self._transition("IDLE", "E-STOP dilepas, menunggu objek")

    def set_manual(self, on):
        """Berpindah antara mode MANUAL (untuk kalibrasi) dan AUTO (sortir jalan)."""
        # bool(on) memastikan nilainya benar-benar True/False, karena data dari
        # web bisa saja berupa teks "true" atau angka 1.
        self.manual_mode = bool(on)
        if on:
            self._stop_motor()
            self.last_message = "Mode MANUAL — otomatis ditahan"
        else:
            self._reset_cycle()
            self._transition("IDLE", "Mode AUTO aktif, menunggu objek")

    def status(self):
        """Ringkasan lengkap kondisi sistem, dikirim ke web 2x per detik lewat WebSocket."""
        return {
            "state": self.state,                                   # keadaan sekarang
            "ripeness": self.ripeness,                             # hasil klasifikasi
            "ripeness_index": self.ripeness_index,                 # nomor kelasnya
            "ripeness_conf": round(self.ripeness_conf, 3),         # keyakinan (3 desimal)
            "action": self.last_action,                            # aksi yang diambil
            "message": self.last_message,                          # pesan untuk pengguna
            "estop": self.estop,                                   # darurat aktif?
            "manual_mode": self.manual_mode,                       # sedang mode manual?
            "fault_count": self.fault_count,                       # jumlah gangguan
            "serial_connected": self.bridge.connected,             # Arduino tersambung?
            "cam1_ok": self.cams.cam1.healthy(),                   # kamera 1 sehat?
            "cam2_ok": self.cams.cam2.healthy(),                   # kamera 2 sehat?
            "cam1_fps": round(self.cams.cam1.actual_fps, 1),       # kecepatan kamera 1
            "cam2_fps": round(self.cams.cam2.actual_fps, 1),       # kecepatan kamera 2
            "paddle_change": round(self._last_paddle_change, 3),  # utk kalibrasi slap
            "indicator": self._led_status,  # ready(hijau)/busy(merah)/notready(kuning)
            "has_empty_ref": self._empty_ref is not None,          # latar sudah dikalibrasi?
            "motion": round(self._last_motion, 1),                 # nilai gerakan terkini
            # Pengaman: round() akan error kalau nilainya None, jadi diperiksa dulu.
            "fg_ratio": round(self._last_fg, 3) if self._last_fg is not None else None,
            "counts_today": store.counts_today(),                  # hitungan sortir hari ini
        }
