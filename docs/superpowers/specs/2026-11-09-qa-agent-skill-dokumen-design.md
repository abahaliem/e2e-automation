# QA Agent — Sub-proyek 3: Skill QA + Dokumen PDF baru + Template Excel

- **Tanggal:** 2026-11-09
- **Status:** Dikerjakan langsung (pengguna: "kerjakan sub proyek 3 sampai 4", semua harus sesuai mockup yang disepakati).
- **Mockup acuan:** `06-pengaturan-skill`, `08-laporan-pdf`, `09-laporan-excel`, tab di `04-pengaturan-ai`.

## 1. Skill QA (mockup 06)

- **Skill bawaan "QA Engineer profesional"** selalu aktif, isinya bisa dilihat ("Lihat isi"): Equivalence Partitioning & Boundary Value, Decision Table & State Transition, pengujian negatif & error guessing, struktur test case (pre-condition, langkah, expected), severity & prioritas, laporan bug yang bisa direproduksi.
- **Skill tambahan**: unggah `.md`, `.txt`, `.docx`, `.pdf` (maks 10 MB). Teks diekstrak sekali dan disimpan di `<data>/skills/<id>.txt`. Per skill: nama, file, jumlah halaman, cakupan aplikasi (semua / daftar aplikasi), tahap pemakaian (Menyusun test case, Menjalankan test, Menilai hasil, Menulis laporan), aktif/nonaktif.
- **Pemakaian di mesin**: tahap *Menyusun test case* dan *Menulis laporan* masuk ke prompt PLAN; *Menjalankan test* dan *Menilai hasil* masuk ke prompt EXECUTE (keputusan done pass/fail). Bagian prompt `## Skill QA`.
- **Kapasitas model terpakai**: estimasi token skill aktif (≈ karakter/4) dibanding konteks 128.000 token, ditampilkan sebagai persen.
- **Coba pada modul contoh**: menyusun test case (tanpa menjalankan) untuk satu modul aplikasi yang sudah dipetakan, memakai skill aktif, lalu menampilkan hasilnya.

## 2. Laporan PDF (mockup 08)

Template cetak khusus (bukan `report.html`): kepala (logo QA Agent, nomor run), judul "Laporan Hasil Pengujian", nama aplikasi + modul, metadata (Aplikasi, Environment, Tanggal, Durasi, Model AI, Status review), Ringkasan 5 angka + paragraf ringkasan otomatis (pass rate, jumlah bug, blocked), kartu **Temuan** (BUG-xxx, judul, status+severity, langkah reproduksi, expected/actual, bukti teknis, catatan reviewer, screenshot evidence), tabel **Daftar test case**, kaki "Dibuat otomatis oleh QA Agent dan direview oleh QA. Dokumen internal." + "Halaman X dari Y". Dicetak Chromium A4. Nama perusahaan (opsional, dari Pengaturan > Laporan) tampil di kepala.

## 3. Excel (mockup 09)

- Sheet: Ringkasan, Test Cases, Temuan, Inventaris Fitur.
- Test Cases: TC ID, Modul, Skenario, Tipe, Prioritas, Langkah, Expected Result, Actual Result, Status AI, Status Final, Catatan Reviewer, Evidence. Header biru `#2560e8` teks putih tebal; sel status berwarna (Pass hijau, Fail merah, Perlu Review kuning, Blocked abu). Pre-condition dan test data ditulis di awal/akhir sel Langkah supaya tidak hilang.
- **Template Excel kantor** (Pengaturan > Laporan): unggah `.xlsx` berisi baris header kolom kantor. Sheet Test Cases ditulis mengikuti urutan & gaya header template; kolom dikenali dari nama (sinonim umum, mis. "No. TC" → TC ID, "Hasil yang diharapkan" → Expected Result). Kolom tak dikenal dibiarkan kosong. Impor review dari Excel tetap berfungsi (dicari dari nama header).

## 4. Pengaturan > Laporan & tab lain

Tab Pengaturan mengikuti mockup 04: Model AI, Skill QA, Akun test, Keamanan, Laporan. Laporan: nama perusahaan/instansi, template Excel kantor. Keamanan: diisi sub-proyek 4.

## 5. Testing

Unit untuk ekstraksi teks (md/txt/docx/pdf), store skill, injeksi prompt per tahap, Excel (kolom mockup + template kantor), template PDF (konten HTML) + PDF nyata (marker browser), API skill & laporan, Vitest untuk tab Skill QA & Laporan.
