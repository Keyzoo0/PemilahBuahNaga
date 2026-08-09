"""
SerialBridge — koneksi ke Arduino Nano (pyserial) dengan auto-reconnect
dan heartbeat (ping + watchdog on). Thread-safe write.

CATATAN UNTUK PEMULA:
File ini adalah "jembatan" komunikasi antara Raspberry Pi (Python) dan
Arduino Nano. Keduanya tersambung lewat kabel USB. Pi mengirim perintah
berupa teks biasa, contoh: "motor forward\n", lalu Arduino membacanya dan
menggerakkan motor.

Istilah:
- serial       : cara kirim data satu bit demi satu bit lewat kabel.
- baud rate    : kecepatan kirim data (115200 = 115.200 bit per detik).
                 Nilai di Pi dan di Arduino WAJIB sama, kalau beda datanya kacau.
- heartbeat    : sinyal "saya masih hidup" yang dikirim rutin. Kalau Arduino
                 tidak menerimanya lebih dari 2 detik, ia menghentikan motor
                 sendiri demi keamanan.
- thread       : jalur pekerjaan yang berjalan bersamaan dengan yang lain.
                 File ini memakai 3 thread sekaligus (jaga koneksi, kirim
                 heartbeat, dan membaca balasan Arduino).
"""
import threading   # untuk menjalankan beberapa pekerjaan bersamaan
import time        # untuk jeda waktu (time.sleep) dan pengukuran waktu

import serial      # pustaka pyserial: berkomunikasi lewat port serial/USB


class SerialBridge:
    def __init__(self, port, baud, heartbeat_seconds=1.0, auto_reconnect=True):
        # Menyimpan semua pengaturan ke dalam objek agar bisa dipakai fungsi lain.
        self.port = port                              # contoh: "/dev/ttyUSB0"
        self.baud = baud                              # contoh: 115200
        self.heartbeat_seconds = heartbeat_seconds    # jeda antar-ping (detik)
        self.auto_reconnect = auto_reconnect          # sambung ulang otomatis? True/False
        self.ser = None                               # objek koneksi serial; None = belum tersambung
        self.lock = threading.Lock()                  # kunci agar tidak 2 thread menulis bersamaan
        self.connected = False                        # penanda status: sedang tersambung atau tidak
        self.last_line = ""                           # baris terakhir yang dikirim Arduino
        self.running = False                          # penanda: apakah semua loop masih boleh jalan

    def start(self):
        """Menyalakan 3 thread latar belakang."""
        self.running = True
        # threading.Thread(target=fungsi) membuat jalur kerja baru yang
        # menjalankan "fungsi" secara bersamaan dengan program utama.
        # PENTING: target=self._maintain_loop ditulis TANPA kurung, karena kita
        # menyerahkan fungsinya, bukan hasil pemanggilannya.
        # daemon=True artinya thread ini otomatis mati saat program utama
        # ditutup, jadi program tidak menggantung.
        threading.Thread(target=self._maintain_loop, daemon=True).start()   # jaga koneksi tetap hidup
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()  # kirim "ping" rutin
        threading.Thread(target=self._read_loop, daemon=True).start()       # baca balasan Arduino

    def _connect(self):
        """Mencoba membuka koneksi serial. Mengembalikan True kalau berhasil."""
        try:
            # timeout=0.2 artinya saat membaca data, tunggu paling lama 0,2 detik.
            # Tanpa timeout, program bisa menggantung selamanya menunggu data.
            self.ser = serial.Serial(self.port, self.baud, timeout=0.2)
            time.sleep(2.0)  # tunggu Nano reset
            # (Arduino otomatis restart tiap kali port serial dibuka. Jeda 2 detik
            #  ini memberi waktu Arduino menyelesaikan proses booting-nya.)
            self.connected = True
            print(f"[SERIAL] Terhubung ke {self.port}")
            self.send("watchdog on")  # aktifkan failsafe motor di firmware
            return True
        except Exception as exc:
            # Gagal (misal kabel belum dicolok atau port salah) -> jangan sampai
            # program mati; cukup catat statusnya lalu coba lagi nanti.
            self.connected = False
            print(f"[SERIAL] Gagal buka {self.port}: {exc}")
            return False

    def _maintain_loop(self):
        """Thread 1: memastikan koneksi selalu tersambung; sambung ulang bila putus."""
        # "while self.running:" = ulangi terus selama running bernilai True.
        while self.running:
            if not self.connected:
                # Belum tersambung -> coba sambungkan.
                # Kalau gagal DAN fitur auto_reconnect dimatikan, hentikan thread ini.
                if not self._connect() and not self.auto_reconnect:
                    return
                # Beri jeda sebelum mencoba lagi, supaya tidak membebani CPU
                # dengan percobaan ribuan kali per detik.
                time.sleep(1.5)
            else:
                # Sudah tersambung -> cukup istirahat sejenak lalu periksa lagi.
                time.sleep(0.5)

    def _heartbeat_loop(self):
        """Thread 2: mengirim "ping" secara berkala sebagai tanda Pi masih hidup."""
        while self.running:
            if self.connected:
                self.send("ping")
            # Tidur selama heartbeat_seconds (bawaan 1 detik), lalu kirim lagi.
            time.sleep(self.heartbeat_seconds)

    def _read_loop(self):
        """Thread 3: membaca teks balasan yang dikirim Arduino."""
        while self.running:
            if self.connected and self.ser:
                try:
                    # Rangkaian pemrosesan dari dalam ke luar:
                    #   readline()            -> baca sampai ketemu tanda ganti baris
                    #   .decode(...)          -> ubah data mentah (byte) menjadi teks
                    #      errors="ignore"      abaikan karakter rusak agar tidak error
                    #   .strip()              -> buang spasi & enter di ujung
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line:
                        # Simpan baris terakhir; bisa ditampilkan di halaman web.
                        self.last_line = line
                except Exception:
                    # Kalau error saat membaca (biasanya kabel dicabut),
                    # anggap koneksi putus agar thread 1 menyambungkan ulang.
                    self._drop()
            else:
                # Belum tersambung -> jangan sibuk; tidur sebentar.
                time.sleep(0.1)

    def _drop(self):
        """Menandai koneksi putus dan menutup port dengan rapi."""
        self.connected = False
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            # "pass" artinya tidak melakukan apa-apa. Di sini error sengaja
            # diabaikan: kita memang sedang menutup koneksi yang bermasalah,
            # jadi error saat menutup pun tidak jadi soal.
            pass
        self.ser = None

    def send(self, cmd):
        """Mengirim satu perintah teks ke Arduino. Mengembalikan True kalau terkirim."""
        # Dikunci agar dua thread tidak menulis bersamaan — kalau itu terjadi,
        # perintahnya bisa tercampur, contoh: "motor fors1 openward".
        with self.lock:
            if not self.ser or not self.connected:
                return False
            try:
                # (cmd + "\n") menambahkan karakter ganti baris sebagai penanda
                # "perintah selesai" — Arduino memakai ini untuk tahu batas perintah.
                # .encode() mengubah teks menjadi byte, karena jalur serial
                # hanya bisa mengirim byte, bukan teks.
                self.ser.write((cmd + "\n").encode())
                return True
            except Exception as exc:
                print(f"[SERIAL] write error: {exc}")
                self._drop()
                return False

    # ---- helper aktuator ----
    # Fungsi-fungsi pendek di bawah ini hanyalah "jalan pintas" agar kode di
    # file lain lebih mudah dibaca. Menulis bridge.motor_forward() jauh lebih
    # jelas maksudnya daripada bridge.send("motor forward").
    # Boleh ditulis satu baris seperti ini karena isinya cuma satu perintah.
    def motor_forward(self):  self.send("motor forward")    # konveyor maju
    def motor_backward(self): self.send("motor backward")   # konveyor mundur
    def motor_stop(self):     self.send("motor stop")       # konveyor berhenti
    def s1_open(self):        self.send("s1 open")          # servo 1 buka (51 derajat)
    def s1_close(self):       self.send("s1 close")         # servo 1 tutup (0 derajat / "tampol")
    def s2_open(self):        self.send("s2 open")          # servo 2 buka
    def s2_close(self):       self.send("s2 close")         # servo 2 tutup
    # Dua fungsi di bawah lebih fleksibel: nomor servonya dikirim lewat variabel n,
    # jadi servo_open(1) sama dengan mengirim "s1 open".
    def servo_open(self, n):  self.send(f"s{n} open")
    def servo_close(self, n): self.send(f"s{n} close")
    def result(self, label):  self.send(f"result {label}")  # nyalakan LED sesuai hasil
    def beep(self, n=1):      self.send(f"beep {n}")        # bunyikan buzzer n kali

    def stop(self):
        """Mematikan jembatan serial dengan aman."""
        # Set False agar semua loop while di atas berhenti berputar.
        self.running = False
        # Pastikan motor dimatikan dulu SEBELUM koneksi ditutup — kalau tidak,
        # motor bisa terus berputar tanpa ada yang mengendalikan.
        self.motor_stop()
        self._drop()
