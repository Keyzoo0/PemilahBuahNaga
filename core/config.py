"""Config loader thread-safe dengan hot-reload untuk PemilahBuahNaga core."""
import json
import os
import threading
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


class Config:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = {}
        self.reload()

    def reload(self):
        with self._lock:
            with open(self.path) as f:
                self._data = json.load(f)

    def save(self, new_data):
        """Tulis config baru (dari web) lalu langsung dipakai (hot-reload)."""
        with self._lock:
            self._data = new_data
            tmp = self.path.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(new_data, f, indent=2)
            os.replace(tmp, self.path)

    def all(self):
        with self._lock:
            return json.loads(json.dumps(self._data))  # deep copy

    def get(self, *keys, default=None):
        with self._lock:
            node = self._data
            for k in keys:
                if not isinstance(node, dict) or k not in node:
                    return default
                node = node[k]
            return node


config = Config()
