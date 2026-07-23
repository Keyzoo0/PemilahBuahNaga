#!/bin/bash
# Jalankan core service manual (untuk test). Produksi: pakai systemd.
cd "$(dirname "$0")"
exec ../.venv/bin/python main.py
