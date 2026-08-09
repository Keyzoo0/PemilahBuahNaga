"""
mDNS/Zeroconf — publikasikan hostname `buahnaga.local` di LAN dari Python,
sehingga web bisa diakses via http://buahnaga.local:5000 tanpa perlu IP.

Bekerja berdampingan dengan avahi-daemon (Zeroconf memakai SO_REUSEPORT).

Diperbaiki 2026-07-28. Versi lama memanggil get_lan_ip() SEKALI saat startup dan
mendaftarkan satu alamat saja. Pi ini punya dua jalur (Wi-Fi 192.168.100.241 dan
USB-ethernet 10.42.0.104); begitu jalur aktif berpindah, record mDNS tetap
menunjuk IP lama yang sudah mati sehingga buahnaga.local tidak bisa dibuka
padahal service-nya sehat. Sekarang:
  - SEMUA IPv4 global didaftarkan, jadi klien di jaringan mana pun bisa resolve.
  - Sebuah thread latar memantau perubahan IP dan mendaftar ulang otomatis.

CATATAN UNTUK PEMULA:
Normalnya, untuk membuka halaman web di Raspberry Pi kita harus tahu alamat
IP-nya (contoh: 192.168.1.15) — dan alamat itu bisa berubah-ubah. Repot.

mDNS (multicast DNS) memecahkan masalah ini: Pi "berteriak" ke seluruh jaringan
lokal, "Nama saya buahnaga.local, alamat saya sekian!". Jadi kita cukup mengetik
http://buahnaga.local:5000 di browser HP atau laptop, tanpa perlu hafal angka IP.

Istilah:
- LAN      : jaringan lokal (Wi-Fi/kabel di rumah atau lab yang sama).
- IPv4     : format alamat internet berupa 4 angka, contoh 192.168.1.15.
- resolve  : proses menerjemahkan nama (buahnaga.local) menjadi alamat IP.
"""
import socket        # pustaka jaringan bawaan Python
import subprocess    # untuk menjalankan perintah terminal dari dalam Python
import threading     # untuk thread pemantau IP di latar belakang
import time          # untuk jeda waktu

from zeroconf import ServiceInfo, Zeroconf   # pustaka yang mengerjakan mDNS


def get_lan_ips():
    """Semua IPv4 global aktif. Terurut, tanpa duplikat."""
    ips = []
    try:
        # subprocess.run menjalankan perintah terminal Linux dari Python.
        # Perintah "ip -4 -o addr show scope global" menampilkan daftar alamat
        # IPv4 yang sedang aktif di semua kartu jaringan.
        #   capture_output=True -> tangkap hasilnya, jangan cetak ke layar
        #   text=True           -> hasilnya berupa teks, bukan byte mentah
        #   timeout=5           -> menyerah kalau lebih dari 5 detik tak selesai
        # .stdout mengambil teks keluarannya.
        out = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        # .splitlines() memecah teks panjang menjadi daftar per baris.
        for line in out.splitlines():
            # .split() memecah satu baris menjadi kata-kata (dipisah spasi).
            # Contoh baris: "2: wlan0 inet 192.168.100.241/24 brd ..."
            # Setelah dipecah: parts[0]="2:", parts[1]="wlan0",
            #                  parts[2]="inet", parts[3]="192.168.100.241/24"
            parts = line.split()
            # Pastikan barisnya cukup panjang DAN kata ketiga adalah "inet"
            # (penanda alamat IPv4), supaya kita tidak salah ambil.
            if len(parts) >= 4 and parts[2] == "inet":
                # Buang bagian "/24" (penanda ukuran jaringan), ambil alamatnya saja.
                # split("/") -> ["192.168.100.241", "24"], lalu [0] ambil yang pertama.
                ips.append(parts[3].split("/")[0])
    except Exception:
        # Kalau perintah "ip" tidak tersedia (misal bukan Linux), abaikan saja
        # dan lanjut ke cara cadangan di bawah.
        pass

    if not ips:
        # cadangan: tanya kernel rute mana yang dipakai keluar
        # Trik umum: buat socket UDP dan "sambungkan" ke alamat internet.
        # UDP tidak benar-benar mengirim data, tapi sistem operasi terpaksa
        # menentukan kartu jaringan mana yang akan dipakai — dari situ kita
        # bisa mengetahui alamat IP lokal kita sendiri.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))       # 8.8.8.8 = DNS milik Google
            # getsockname() memberi tahu alamat lokal kita untuk rute ini;
            # [0] mengambil bagian alamat IP-nya (elemen kedua adalah nomor port).
            ips.append(s.getsockname()[0])
        except Exception:
            # Tidak ada jaringan sama sekali -> pakai alamat "diri sendiri".
            ips.append("127.0.0.1")
        finally:
            # Socket wajib ditutup agar tidak membocorkan sumber daya sistem.
            s.close()

    # set(ips)     -> buang alamat yang kembar (set tidak boleh punya isi ganda)
    # sorted(...)  -> urutkan agar hasilnya konsisten setiap kali dipanggil
    return sorted(set(ips))


# kompat lama: satu IP saja
# ("kompat" = kompatibilitas — fungsi ini dipertahankan agar kode lama yang
#  masih memanggil get_lan_ip() tidak rusak.)
def get_lan_ip():
    ips = get_lan_ips()
    # Bentuk "A if syarat else B" disebut ternary: kalau daftar ips ada isinya,
    # ambil elemen pertama; kalau kosong, pakai 127.0.0.1.
    return ips[0] if ips else "127.0.0.1"


class MDNSPublisher:
    def __init__(self, hostname="buahnaga", port=5000, service_name="PemilahBuahNaga",
                 refresh_seconds=10.0):
        # Kalau pengguna menulis "buahnaga.local", potong akhiran ".local"-nya
        # (6 huruf) karena nanti akhiran itu ditambahkan lagi otomatis —
        # supaya tidak jadi "buahnaga.local.local".
        # hostname[:-6] artinya "ambil semua huruf kecuali 6 terakhir".
        self.hostname = hostname[:-6] if hostname.endswith(".local") else hostname
        self.port = int(port)                          # pastikan berupa bilangan bulat
        self.service_name = service_name
        self.refresh_seconds = float(refresh_seconds)  # pastikan berupa bilangan desimal
        self.zc = None          # objek Zeroconf; None = belum dinyalakan
        self.info = None        # data layanan yang didaftarkan
        self._ips = []          # daftar IP yang sedang terdaftar sekarang
        self._running = False   # penanda thread pemantau masih boleh jalan
        self._thread = None     # wadah untuk thread pemantau

    def _build_info(self, ips, name=None):
        # `name` dipertahankan dari pendaftaran pertama: allow_name_change bisa
        # mengubahnya (mis. jadi "...-2") kalau ada bentrok di LAN, dan daftar
        # ulang harus memakai nama yang sama persis.
        return ServiceInfo(
            type_="_http._tcp.local.",   # jenis layanan: web (HTTP) lewat TCP
            # "name or nilai_lain" artinya: pakai name kalau ada isinya;
            # kalau name kosong/None, pakai nilai setelah kata "or".
            name=name or f"{self.service_name}._http._tcp.local.",
            # inet_aton mengubah alamat IP berbentuk teks "192.168.1.5" menjadi
            # bentuk byte yang dipahami protokol jaringan.
            addresses=[socket.inet_aton(ip) for ip in ips],
            port=self.port,
            properties={"path": "/"},           # info tambahan: halaman utama ada di "/"
            server=f"{self.hostname}.local.",   # A record buahnaga.local -> ip
        )

    def start(self):
        """Mulai mengumumkan nama buahnaga.local ke jaringan."""
        self._ips = get_lan_ips()          # kumpulkan semua IP aktif saat ini
        self.zc = Zeroconf()               # nyalakan mesin mDNS
        self.info = self._build_info(self._ips)
        # allow_name_change=True: kalau bentrok, zeroconf pilih nama unik
        self.zc.register_service(self.info, allow_name_change=True)
        # ", ".join(daftar) menggabungkan isi daftar menjadi satu teks
        # dipisah koma, contoh: "192.168.1.5, 10.42.0.1".
        print(f"[mDNS] Aktif: http://{self.hostname}.local:{self.port}  ->  {', '.join(self._ips)}")

        self._running = True
        # Nyalakan thread pemantau perubahan IP di latar belakang.
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return f"{self.hostname}.local"

    def _watch(self):
        """Pantau perubahan IP; daftar ulang kalau berubah."""
        while self._running:
            # Tidur dulu baru periksa — tidak perlu memeriksa terus-menerus.
            time.sleep(self.refresh_seconds)
            # Periksa lagi setelah bangun: bisa saja stop() dipanggil saat tidur.
            # "break" artinya keluar dari perulangan while.
            if not self._running:
                break
            try:
                now = get_lan_ips()
                # Daftar ulang HANYA kalau daftar IP-nya benar-benar berubah.
                # Tanda != berarti "tidak sama dengan".
                if now and now != self._ips:
                    print(f"[mDNS] IP berubah {self._ips} -> {now}, daftar ulang...")
                    # Pakai nama lama (self.info.name) agar klien tidak bingung.
                    new_info = self._build_info(now, name=self.info.name)
                    self.zc.update_service(new_info)
                    # Perbarui catatan di dalam objek agar sesuai kenyataan.
                    self.info = new_info
                    self._ips = now
            except Exception as exc:
                # Gagal daftar ulang bukan masalah fatal — sistem sortir tetap
                # bekerja; hanya akses lewat nama yang mungkin terganggu.
                print(f"[mDNS] gagal daftar ulang: {exc}")

    def stop(self):
        """Berhenti mengumumkan nama dan bersih-bersih."""
        self._running = False   # hentikan thread pemantau
        try:
            if self.zc and self.info:
                # Cabut pendaftaran agar perangkat lain tahu layanan sudah mati.
                self.zc.unregister_service(self.info)
        finally:
            # finally memastikan Zeroconf tetap ditutup walau baris di atas error.
            if self.zc:
                self.zc.close()
