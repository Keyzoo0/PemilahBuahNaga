"""SQLite penyimpan riwayat sortasi.

CATATAN UNTUK PEMULA:
File ini bertugas MENYIMPAN CATATAN setiap buah yang sudah disortir, supaya
riwayatnya bisa dilihat lagi di halaman web (misalnya: hari ini sudah menyortir
berapa buah matang, berapa mentah).

Istilah:
- SQLite  : database sederhana yang isinya cuma SATU file (sorting.db).
            Tidak perlu instal server database terpisah.
- tabel   : mirip lembar Excel — punya kolom (judul) dan baris (isi data).
- SQL     : bahasa perintah untuk berbicara dengan database, contoh
            "SELECT" (ambil data), "INSERT" (tambah data), "DELETE" (hapus data).
"""
import sqlite3                              # pustaka bawaan Python untuk database SQLite
import threading                            # untuk penguncian agar aman dipakai banyak thread
from contextlib import contextmanager       # untuk membuat blok "with" buatan sendiri
from datetime import datetime               # untuk mengambil tanggal & jam sekarang
from pathlib import Path                    # penulisan alamat file yang aman

# Alamat file database: <folder core>/database/sorting.db
DB_PATH = Path(__file__).resolve().parent / "database" / "sorting.db"


class Store:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        # Buat folder "database" bila belum ada.
        #   parents=True   -> ikut membuat folder induk bila juga belum ada
        #   exist_ok=True  -> jangan error kalau foldernya memang sudah ada
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        # Siapkan tabelnya (kalau belum ada).
        self._init()

    def _conn(self):
        """Membuka koneksi baru ke file database."""
        conn = sqlite3.connect(self.path)
        # Secara bawaan, hasil query berupa tuple biasa yang diakses dengan
        # angka: row[0], row[1]. Dengan sqlite3.Row, hasilnya bisa diakses
        # dengan nama kolom: row["ripeness"] — jauh lebih mudah dibaca.
        conn.row_factory = sqlite3.Row
        return conn

    # @contextmanager mengubah fungsi biasa menjadi fungsi yang bisa dipakai
    # dengan kata kunci "with". Kode SEBELUM yield jalan saat blok with dimulai,
    # kode SETELAH yield jalan saat blok with selesai.
    @contextmanager
    def _session(self):
        """Buka koneksi, commit/rollback, lalu TUTUP.

        Versi lama memakai `with self._conn() as c:` langsung. Itu jebakan
        terdokumentasi di modul sqlite3: memakai Connection sebagai context
        manager hanya commit/rollback transaksi, TIDAK menutup koneksinya.
        Akibatnya tiap query membocorkan satu file descriptor sampai GC jalan.
        counts_today() dipanggil di tiap /api/status dan tiap tick WebSocket
        (2x per detik), jadi fd numpuk cepat — terpantau 22 handle menganga ke
        sorting.db pada 2026-07-28.

        Untuk pemula: "file descriptor" itu semacam nomor antrean yang dipakai
        sistem operasi tiap kali sebuah file dibuka. Jumlahnya terbatas. Kalau
        file dibuka terus tapi tidak pernah ditutup, jatahnya habis dan program
        akan error. Itulah kenapa blok "finally" di bawah wajib ada.
        """
        conn = self._conn()
        try:
            # "with conn:" mengurus transaksi: kalau isi blok sukses, perubahan
            # disimpan permanen (commit); kalau error, perubahan dibatalkan
            # semua (rollback) sehingga data tidak setengah jadi.
            with conn:
                # yield = "serahkan koneksi ini ke pemakai, lalu tunggu sampai
                # blok with di sisi pemakai selesai, baru lanjutkan ke bawah".
                yield conn
        finally:
            # finally SELALU dijalankan (sukses maupun error) -> koneksi pasti ditutup.
            conn.close()

    def _init(self):
        """Membuat tabel 'sortings' bila belum ada."""
        # Menulis dua "with" dipisah koma artinya keduanya dijalankan sekaligus:
        # kunci thread DAN buka sesi database.
        with self.lock, self._session() as c:
            # Perintah SQL ditulis di dalam tiga tanda kutip agar boleh
            # ditulis beberapa baris supaya rapi.
            c.execute("""
                CREATE TABLE IF NOT EXISTS sortings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- nomor urut, terisi otomatis
                    created_at TEXT NOT NULL,              -- kapan dicatat (wajib diisi)
                    ripeness TEXT,                         -- hasil klasifikasi: matang/mentah/setengah
                    confidence REAL,                       -- tingkat keyakinan (REAL = desimal)
                    action TEXT,                           -- aksi yang diambil: servo1/servo2/lurus
                    image TEXT                             -- alamat file foto (boleh kosong)
                )
            """)
            # commit = simpan permanen ke file database.
            c.commit()

    def add(self, ripeness, confidence, action, image=None):
        """Menambah satu baris catatan hasil sortir. Mengembalikan nomor id-nya."""
        with self.lock, self._session() as c:
            cur = c.execute(
                # Tanda tanya (?) adalah "placeholder": tempat kosong yang nanti
                # diisi nilai dari tuple di baris berikutnya. Cara ini WAJIB
                # dipakai (jangan menyambung teks SQL dengan +) karena mencegah
                # celah keamanan bernama SQL injection.
                "INSERT INTO sortings (created_at, ripeness, confidence, action, image) VALUES (?,?,?,?,?)",
                # strftime mengubah waktu menjadi teks dengan format yang kita mau:
                # %Y=tahun 4 digit, %m=bulan, %d=tanggal, %H=jam, %M=menit, %S=detik.
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ripeness, confidence, action, image),
            )
            c.commit()
            # lastrowid = nomor id baris yang baru saja dimasukkan.
            return cur.lastrowid

    def recent(self, limit=100):
        """Mengambil catatan terbaru, paling banyak sejumlah 'limit' baris."""
        with self.lock, self._session() as c:
            # ORDER BY id DESC = urutkan dari nomor terbesar (terbaru) ke terkecil.
            # LIMIT ? = batasi jumlah baris yang diambil.
            # .fetchall() = ambil semua baris hasilnya sekaligus.
            rows = c.execute("SELECT * FROM sortings ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            # Ubah tiap baris menjadi dictionary biasa agar mudah dikirim ke web
            # dalam format JSON. Ini "list comprehension": cara ringkas membuat
            # list baru dari list lama.
            return [dict(r) for r in rows]

    def delete(self, row_id):
        """Menghapus satu catatan berdasarkan nomor id-nya."""
        with self.lock, self._session() as c:
            # WHERE id=? artinya hanya baris dengan id tersebut yang dihapus.
            # (row_id,) ditulis dengan koma di belakang agar dianggap tuple
            # berisi 1 elemen — tanpa koma, Python menganggapnya kurung biasa.
            c.execute("DELETE FROM sortings WHERE id=?", (row_id,))
            c.commit()
            return True

    def clear_all(self):
        """Menghapus SELURUH catatan. Mengembalikan jumlah baris yang terhapus."""
        with self.lock, self._session() as c:
            # Hitung dulu ada berapa baris, agar bisa dilaporkan ke pengguna.
            # COUNT(*) n artinya hasil hitungan diberi nama kolom "n".
            # .fetchone() = ambil satu baris hasil saja.
            n = c.execute("SELECT COUNT(*) n FROM sortings").fetchone()["n"]
            # DELETE tanpa WHERE = hapus semua isi tabel.
            c.execute("DELETE FROM sortings")
            c.commit()
            return n

    def counts_today(self):
        """Menghitung jumlah sortir HARI INI, dikelompokkan per tingkat kematangan."""
        # Ambil tanggal hari ini dalam bentuk teks "2026-08-09".
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock, self._session() as c:
            rows = c.execute(
                # date(created_at) mengambil bagian tanggalnya saja (buang jamnya).
                # GROUP BY ripeness = kelompokkan berdasarkan kematangan, lalu
                # hitung tiap kelompok. Hasilnya misalnya:
                #   matang | 12
                #   mentah | 5
                "SELECT ripeness, COUNT(*) n FROM sortings WHERE date(created_at)=? GROUP BY ripeness",
                (today,),
            ).fetchall()
            # Ubah jadi dictionary: {"matang": 12, "mentah": 5}
            return {r["ripeness"]: r["n"] for r in rows}


# Satu objek Store dipakai bersama oleh seluruh program (pola singleton).
store = Store()
