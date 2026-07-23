"""
SerialBridge — koneksi ke Arduino Nano (pyserial) dengan auto-reconnect
dan heartbeat (ping + watchdog on). Thread-safe write.
"""
import threading
import time

import serial


class SerialBridge:
    def __init__(self, port, baud, heartbeat_seconds=1.0, auto_reconnect=True):
        self.port = port
        self.baud = baud
        self.heartbeat_seconds = heartbeat_seconds
        self.auto_reconnect = auto_reconnect
        self.ser = None
        self.lock = threading.Lock()
        self.connected = False
        self.last_line = ""
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._maintain_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.2)
            time.sleep(2.0)  # tunggu Nano reset
            self.connected = True
            print(f"[SERIAL] Terhubung ke {self.port}")
            self.send("watchdog on")  # aktifkan failsafe motor di firmware
            return True
        except Exception as exc:
            self.connected = False
            print(f"[SERIAL] Gagal buka {self.port}: {exc}")
            return False

    def _maintain_loop(self):
        while self.running:
            if not self.connected:
                if not self._connect() and not self.auto_reconnect:
                    return
                time.sleep(1.5)
            else:
                time.sleep(0.5)

    def _heartbeat_loop(self):
        while self.running:
            if self.connected:
                self.send("ping")
            time.sleep(self.heartbeat_seconds)

    def _read_loop(self):
        while self.running:
            if self.connected and self.ser:
                try:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line:
                        self.last_line = line
                except Exception:
                    self._drop()
            else:
                time.sleep(0.1)

    def _drop(self):
        self.connected = False
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def send(self, cmd):
        with self.lock:
            if not self.ser or not self.connected:
                return False
            try:
                self.ser.write((cmd + "\n").encode())
                return True
            except Exception as exc:
                print(f"[SERIAL] write error: {exc}")
                self._drop()
                return False

    # ---- helper aktuator ----
    def motor_forward(self):  self.send("motor forward")
    def motor_backward(self): self.send("motor backward")
    def motor_stop(self):     self.send("motor stop")
    def s1_open(self):        self.send("s1 open")
    def s1_close(self):       self.send("s1 close")
    def s2_open(self):        self.send("s2 open")
    def s2_close(self):       self.send("s2 close")
    def servo_open(self, n):  self.send(f"s{n} open")
    def servo_close(self, n): self.send(f"s{n} close")
    def result(self, label):  self.send(f"result {label}")
    def beep(self, n=1):      self.send(f"beep {n}")

    def stop(self):
        self.running = False
        self.motor_stop()
        self._drop()
