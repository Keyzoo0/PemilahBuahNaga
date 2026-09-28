# Hasil Evaluasi Model (Confusion Matrix)

> **Catatan (2026-09-28):** angka di halaman ini **terlalu tinggi** dan hanya
> disimpan sebagai arsip. Saat evaluasi ini dibuat, pembagian train/val masih
> diacak ulang setiap training, sehingga model sudah pernah melihat sebagian
> foto uji. Pembagian sekarang stabil (berdasarkan nama file) dan hasil tiap
> training — termasuk confusion matrix — bisa dilihat langsung di web:
> **tab Training → Riwayat Training → klik salah satu run**.

Model: `core/best.pt` (YOLOv8, 3 kelas: `matang`, `mentah`, `setengah matang`)
Dataset validasi: `core/dataset/_build` (111 gambar val, pembagian lama)

## Ringkasan metrik (arsip)

| Kelas            | Precision | Recall | mAP50 | mAP50-95 |
|------------------|-----------|--------|-------|----------|
| all              | 0.980     | 0.991  | 0.995 | 0.764    |
| matang           | 0.980     | 1.000  | 0.995 | 0.800    |
| mentah           | 0.959     | 1.000  | 0.995 | 0.752    |
| setengah matang  | 1.000     | 0.973  | 0.995 | 0.738    |

## Confusion Matrix

![Confusion Matrix](confusion_matrix.png)

![Confusion Matrix (Normalized)](confusion_matrix_normalized.png)

![Precision-Recall Curve](BoxPR_curve.png)
