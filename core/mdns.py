"""
mDNS/Zeroconf — publikasikan hostname `buahnaga.local` di LAN dari Python,
sehingga web bisa diakses via http://buahnaga.local:5000 tanpa perlu IP.

Bekerja berdampingan dengan avahi-daemon (Zeroconf memakai SO_REUSEPORT).
"""
import socket

from zeroconf import ServiceInfo, Zeroconf


def get_lan_ip():
    """IP LAN aktif (bukan 127.0.0.1)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class MDNSPublisher:
    def __init__(self, hostname="buahnaga", port=5000, service_name="PemilahBuahNaga"):
        self.hostname = hostname[:-6] if hostname.endswith(".local") else hostname
        self.port = int(port)
        self.service_name = service_name
        self.zc = None
        self.info = None

    def start(self):
        ip = get_lan_ip()
        self.zc = Zeroconf()
        server = f"{self.hostname}.local."       # -> buahnaga.local.
        self.info = ServiceInfo(
            type_="_http._tcp.local.",
            name=f"{self.service_name}._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={"path": "/"},
            server=server,                        # publikasikan A record buahnaga.local -> ip
        )
        # allow_name_change=True: kalau bentrok, zeroconf pilih nama unik
        self.zc.register_service(self.info, allow_name_change=True)
        print(f"[mDNS] Aktif: http://{self.hostname}.local:{self.port}  ->  {ip}")
        return f"{self.hostname}.local"

    def stop(self):
        try:
            if self.zc and self.info:
                self.zc.unregister_service(self.info)
        finally:
            if self.zc:
                self.zc.close()
