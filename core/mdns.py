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
"""
import socket
import subprocess
import threading
import time

from zeroconf import ServiceInfo, Zeroconf


def get_lan_ips():
    """Semua IPv4 global aktif. Terurut, tanpa duplikat."""
    ips = []
    try:
        out = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "inet":
                ips.append(parts[3].split("/")[0])
    except Exception:
        pass

    if not ips:
        # cadangan: tanya kernel rute mana yang dipakai keluar
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        except Exception:
            ips.append("127.0.0.1")
        finally:
            s.close()

    return sorted(set(ips))


# kompat lama: satu IP saja
def get_lan_ip():
    ips = get_lan_ips()
    return ips[0] if ips else "127.0.0.1"


class MDNSPublisher:
    def __init__(self, hostname="buahnaga", port=5000, service_name="PemilahBuahNaga",
                 refresh_seconds=10.0):
        self.hostname = hostname[:-6] if hostname.endswith(".local") else hostname
        self.port = int(port)
        self.service_name = service_name
        self.refresh_seconds = float(refresh_seconds)
        self.zc = None
        self.info = None
        self._ips = []
        self._running = False
        self._thread = None

    def _build_info(self, ips, name=None):
        # `name` dipertahankan dari pendaftaran pertama: allow_name_change bisa
        # mengubahnya (mis. jadi "...-2") kalau ada bentrok di LAN, dan daftar
        # ulang harus memakai nama yang sama persis.
        return ServiceInfo(
            type_="_http._tcp.local.",
            name=name or f"{self.service_name}._http._tcp.local.",
            addresses=[socket.inet_aton(ip) for ip in ips],
            port=self.port,
            properties={"path": "/"},
            server=f"{self.hostname}.local.",   # A record buahnaga.local -> ip
        )

    def start(self):
        self._ips = get_lan_ips()
        self.zc = Zeroconf()
        self.info = self._build_info(self._ips)
        # allow_name_change=True: kalau bentrok, zeroconf pilih nama unik
        self.zc.register_service(self.info, allow_name_change=True)
        print(f"[mDNS] Aktif: http://{self.hostname}.local:{self.port}  ->  {', '.join(self._ips)}")

        self._running = True
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return f"{self.hostname}.local"

    def _watch(self):
        """Pantau perubahan IP; daftar ulang kalau berubah."""
        while self._running:
            time.sleep(self.refresh_seconds)
            if not self._running:
                break
            try:
                now = get_lan_ips()
                if now and now != self._ips:
                    print(f"[mDNS] IP berubah {self._ips} -> {now}, daftar ulang...")
                    new_info = self._build_info(now, name=self.info.name)
                    self.zc.update_service(new_info)
                    self.info = new_info
                    self._ips = now
            except Exception as exc:
                print(f"[mDNS] gagal daftar ulang: {exc}")

    def stop(self):
        self._running = False
        try:
            if self.zc and self.info:
                self.zc.unregister_service(self.info)
        finally:
            if self.zc:
                self.zc.close()
