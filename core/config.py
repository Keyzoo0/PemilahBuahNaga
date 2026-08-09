"""Config loader thread-safe dengan hot-reload untuk PemilahBuahNaga core.

CATATAN UNTUK PEMULA:
File ini bertugas membaca file pengaturan "config.json" (berisi angka-angka
kalibrasi: sudut servo, ukuran ROI, port serial, dll) dan menyediakannya ke
seluruh bagian program.

Dua istilah penting:
- "thread-safe": program ini menjalankan banyak pekerjaan bersamaan (kamera,
  serial, web) di jalur-jalur terpisah yang disebut thread. Kalau dua thread
  membaca/menulis data yang sama pada saat bersamaan, datanya bisa rusak.
  Thread-safe berarti sudah diberi pengaman agar hal itu tidak terjadi.
- "hot-reload": pengaturan bisa diubah dari halaman web dan langsung dipakai,
  tanpa perlu mematikan lalu menyalakan ulang program.
"""
# json = pustaka bawaan Python untuk membaca/menulis file berformat JSON.
import json
# os = pustaka untuk berurusan dengan sistem operasi (di sini: mengganti nama file).
import os
# threading = pustaka untuk mengatur banyak pekerjaan yang berjalan bersamaan.
import threading
# Path = cara modern menulis alamat file/folder yang aman di semua sistem operasi.
from pathlib import Path

# Menentukan lokasi file config.json secara otomatis:
#   __file__               -> alamat file config.py ini sendiri
#   .resolve()             -> ubah jadi alamat lengkap (absolut), bukan singkatan
#   .parent                -> naik satu tingkat, yaitu folder tempat file ini berada
#   / "config.json"        -> tanda "/" di sini berarti "gabungkan alamat folder + nama file"
# Hasilnya: .../core/config.json. Cara ini dipakai agar program tetap menemukan
# config.json walau dijalankan dari folder mana pun.
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


# "class" artinya kita membuat cetakan/blueprint sebuah objek.
# Dari satu class bisa dibuat banyak objek, masing-masing punya datanya sendiri.
class Config:
    # __init__ adalah fungsi khusus yang otomatis dijalankan saat objek dibuat
    # (contoh: Config()). Namanya "constructor".
    # Parameter "self" wajib ada di fungsi dalam class; artinya "objek ini sendiri".
    # path=CONFIG_PATH artinya kalau tidak diberi alamat, pakai CONFIG_PATH di atas.
    def __init__(self, path=CONFIG_PATH):
        # self.path = menyimpan alamat file ke dalam objek, agar bisa dipakai
        # oleh fungsi-fungsi lain di class ini.
        self.path = Path(path)
        # Lock = "kunci pintu". Hanya satu thread yang boleh masuk pada satu waktu.
        # Awalan garis bawah (_) pada nama adalah kesepakatan programmer Python
        # yang berarti "ini urusan dalam, jangan diutak-atik dari luar".
        self._lock = threading.Lock()
        # Wadah kosong untuk menampung isi config.json nanti.
        self._data = {}
        # Langsung baca file config.json saat objek dibuat.
        self.reload()

    def reload(self):
        """Membaca ulang isi config.json dari disk ke memori."""
        # "with self._lock:" artinya kunci pintunya dulu, kerjakan isi blok ini,
        # lalu kunci otomatis dilepas begitu blok selesai (walau terjadi error).
        with self._lock:
            # "with open(...) as f:" membuka file dan otomatis menutupnya lagi
            # setelah selesai. Variabel f mewakili file yang sedang terbuka.
            with open(self.path) as f:
                # json.load(f) membaca teks JSON dari file dan mengubahnya
                # menjadi dictionary Python yang bisa diakses seperti kamus.
                self._data = json.load(f)

    def save(self, new_data):
        """Tulis config baru (dari web) lalu langsung dipakai (hot-reload)."""
        with self._lock:
            # Simpan dulu ke memori supaya perubahan langsung terasa.
            self._data = new_data
            # Trik "tulis aman": jangan langsung menimpa file asli.
            # Tulis dulu ke file sementara berakhiran .json.tmp.
            tmp = self.path.with_suffix(".json.tmp")
            # Mode "w" artinya write (tulis / timpa isi lama).
            with open(tmp, "w") as f:
                # json.dump menulis dictionary ke file dalam format JSON.
                # indent=2 membuat hasilnya rapi bertingkat agar mudah dibaca manusia.
                json.dump(new_data, f, indent=2)
            # os.replace mengganti file lama dengan file sementara dalam satu
            # langkah yang tidak bisa terputus di tengah jalan (atomic).
            # Manfaatnya: kalau listrik mati saat menyimpan, config.json tidak
            # akan menjadi setengah tertulis alias rusak.
            os.replace(tmp, self.path)

    def all(self):
        """Mengembalikan SALINAN seluruh isi config."""
        with self._lock:
            # Trik membuat "deep copy" (salinan yang benar-benar terpisah):
            # json.dumps mengubah dictionary menjadi teks, lalu json.loads
            # mengubah teks itu kembali menjadi dictionary baru.
            # Kenapa perlu disalin? Supaya kalau pemanggil mengubah hasilnya,
            # data asli di dalam objek ini tidak ikut berubah.
            return json.loads(json.dumps(self._data))  # deep copy

    def get(self, *keys, default=None):
        """Mengambil satu nilai dari config, boleh bertingkat.

        Contoh pemakaian:
            config.get("serial")            -> ambil seluruh bagian "serial"
            config.get("serial", "port")    -> ambil isi "port" di dalam "serial"

        Tanda bintang pada *keys artinya fungsi ini menerima jumlah argumen
        sebebasnya, dan semuanya dikumpulkan menjadi sebuah daftar bernama keys.
        """
        with self._lock:
            # Mulai penelusuran dari data paling luar.
            node = self._data
            # Perulangan "for" mengambil kunci satu per satu, menelusuri ke dalam.
            for k in keys:
                # Pengaman: kalau yang sedang ditelusuri ternyata bukan dictionary,
                # atau kuncinya memang tidak ada, hentikan dan kembalikan nilai cadangan.
                # Tanpa pengaman ini program akan error dan mati.
                if not isinstance(node, dict) or k not in node:
                    return default
                # Turun satu tingkat lebih dalam.
                node = node[k]
            return node


# Baris ini membuat SATU objek Config yang dipakai bersama oleh seluruh program.
# Pola seperti ini disebut "singleton": cukup satu instance untuk semua.
# File lain memakainya dengan menulis: from config import config
config = Config()
