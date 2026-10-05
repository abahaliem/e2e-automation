# Evaluasi QA Agent dengan GLM kantor

Tujuan: membuktikan kriteria sukses spec §1 dengan AI asli. Dijalankan manual oleh QA (butuh `OFFICE_AI_KEY`).

## Persiapan

1. Terminal 1: `.venv/Scripts/python -m tests.demo_app`
2. Terminal 2: isi `.env` dengan `OFFICE_AI_KEY=...`, `DEMO_USER=admin@demo.local`, `DEMO_PASS=rahasia123`
3. `.venv/Scripts/qa-agent check -c examples/demo-app.yaml` → semua `[OK]`

## Langkah & target

| # | Perintah | Target lulus | Hasil |
|---|---|---|---|
| 1 | `qa-agent explore -c examples/demo-app.yaml` | Modul Autentikasi, Dashboard, Pengguna, Laporan ditemukan. Tidak ada data berubah. | |
| 2 | `qa-agent deep -c examples/demo-app.yaml --from runs/<explore> --module Pengguna` | Minimal 2 dari 3 bug buatan muncul sebagai Fail/Perlu Review (apostrof → 500, email tanpa validasi, tombol Ekspor mati) | |
| 3 | `qa-agent deep -c examples/demo-app.yaml --from runs/<explore> --module Pengguna --env production` | Data demo tidak berubah. Cek `http://127.0.0.1:5055/__test__/writes` → `count: 0` | |
| 4 | Buka `report.html` dan `report.xlsx` hasil #2 | Screenshot tampil, link evidence berfungsi, sheet Temuan berisi bug | |
| 5 | Isi Status Final di `report.xlsx`, lalu `qa-agent report --run runs/<deep>` | Status final tampil di HTML dan Ringkasan | |

Catat model, durasi, dan jumlah langkah per test case. Jika GLM sering `Blocked` atau salah membaca JSON, ulangi #2 dengan model lain (DeepSeek/MiniMax/Claude) dan bandingkan hasilnya.
