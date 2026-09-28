"""
Proses training terpisah, dijalankan oleh dataset.Trainer lewat subprocess.

Kenapa file tersendiri (bukan teks "python -c ...")?
  Supaya bisa MENANGKAP tombol Hentikan. Tombol itu mengirim SIGINT (sama
  seperti Ctrl+C). Ultralytics baru membuat confusion matrix di akhir
  training normal, jadi kalau dihentikan di tengah jalan hasilnya hilang.
  Di sini, apa pun cara training berakhir (selesai / dihentikan / error),
  model best.pt yang sudah ada tetap DIEVALUASI dan hasilnya disimpan.

Isi folder run setelah selesai (core/runs/train_YYYYmmdd_HHMMSS/):
  run.json        status run: completed / stopped / failed + waktu
  eval.json       confusion matrix (angka) + metrik per kelas
  eval/*.png      gambar confusion matrix & kurva dari ultralytics
  train.log       log lengkap (ditulis oleh Trainer di dataset.py)
  results.csv     metrik per epoch (ditulis ultralytics)
  weights/        best.pt & last.pt

Istilah:
- confusion matrix : tabel "aktual vs tebakan model". Diagonal = tebakan
                     benar; di luar diagonal = model salah mengira kelas.
- background       : "tidak ada buah". Aktual=buah tapi tebakan=background
                     artinya buah TERLEWAT; kebalikannya = deteksi palsu.
"""
import json
import signal
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _write_json(path, data):
    # Tulis ke file sementara lalu ganti nama: file tidak pernah setengah jadi
    # walau listrik mati di tengah penulisan.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def evaluate_run(best, data_yaml, imgsz, run_dir, val_images=None, retro=False):
    """Validasi best.pt terhadap data uji, simpan eval.json + gambar di run_dir.

    retro=True menandai evaluasi yang dibuat BELAKANGAN untuk run lama. Data
    ujinya belum tentu sama dengan saat run itu dilatih, jadi angkanya
    kemungkinan terlalu bagus.
    """
    from ultralytics import YOLO
    run_dir = Path(run_dir)
    r = YOLO(str(best)).val(
        data=str(data_yaml), imgsz=int(imgsz), batch=8, workers=2, device="cpu",
        plots=True, project=str(run_dir), name="eval", exist_ok=True,
    )
    names = [r.names[i] for i in sorted(r.names)]
    per_class = []
    ap_index = list(r.box.ap_class_index)
    for c, name in enumerate(names):
        row = {"name": name, "instances": int(r.nt_per_class[c])}
        # Kelas tanpa satu pun contoh di data uji tidak punya metrik.
        if c in ap_index:
            p, rc, ap50, ap = r.box.class_result(ap_index.index(c))
            row.update(precision=float(p), recall=float(rc), map50=float(ap50), map50_95=float(ap))
        per_class.append(row)
    _write_json(run_dir / "eval.json", {
        "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "retro": retro,
        "imgsz": int(imgsz),
        "val_images": val_images,
        # Ambang keyakinan bawaan ultralytics untuk confusion matrix (val tanpa conf=).
        "conf": 0.25,
        "names": names,
        # matrix[prediksi][aktual]; indeks terakhir = background.
        "matrix": r.confusion_matrix.matrix.astype(int).tolist(),
        "overall": {"precision": float(r.box.mp), "recall": float(r.box.mr),
                    "map50": float(r.box.map50), "map50_95": float(r.box.map)},
        "per_class": per_class,
    })


def main():
    cfg = json.loads(sys.argv[1])
    run_dir = Path(cfg["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "run.json"
    meta = {"run": run_dir.name, "status": "running",
            "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "params": cfg["params"]}
    _write_json(meta_path, meta)

    import torch
    torch.set_num_threads(4)                       # pakai 4 core Pi 5
    from ultralytics import YOLO

    p = cfg["params"]
    try:
        YOLO(cfg["base"]).train(
            data=cfg["data"], epochs=p["epochs"], imgsz=p["imgsz"], batch=p["batch"],
            # cache=True  -> simpan gambar di RAM agar tidak bolak-balik baca kartu SD
            # workers=2   -> 2 pekerja penyiap data (jangan banyak, CPU terbatas)
            # patience=10 -> berhenti otomatis bila 10 epoch tak ada perbaikan
            freeze=p["freeze"], cache=True, workers=2, device="cpu", patience=10,
            project=str(run_dir.parent), name=run_dir.name, exist_ok=True,
            # plots=False: grafik dibuat oleh evaluate_run di bawah, yang juga
            # jalan saat training dihentikan. Kurva per epoch digambar web dari results.csv.
            plots=False, val=True,
        )
        meta["status"] = "completed"
    except KeyboardInterrupt:
        meta["status"] = "stopped"
        print("[STOP] Training dihentikan, mengevaluasi best.pt terakhir...", flush=True)
    except Exception as exc:
        meta["status"] = "failed"
        meta["error"] = str(exc)
        traceback.print_exc()

    # Tombol Hentikan yang ditekan lagi tidak boleh memotong evaluasi.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    best = run_dir / "weights" / "best.pt"
    if best.exists():
        print("[EVAL] Membuat confusion matrix...", flush=True)
        try:
            evaluate_run(best, cfg["data"], p["imgsz"], run_dir, val_images=p.get("val_imgs"))
            print("[EVAL] Selesai.", flush=True)
        except Exception as exc:
            meta["eval_error"] = str(exc)
            traceback.print_exc()

    meta["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(meta_path, meta)
    # Exit 0 selama ada model yang bisa dipakai (termasuk run yang dihentikan).
    sys.exit(0 if best.exists() else 1)


if __name__ == "__main__":
    main()
