# QA Agent

AI yang berperan sebagai QA automation engineer untuk aplikasi web. Agent menjelajahi aplikasi sendiri, menyusun test case, menjalankannya di browser, lalu menghasilkan dokumen test case (Excel) dan laporan eksekusi (HTML) lengkap dengan screenshot. Pengujian bersifat black-box, tanpa akses ke kode developer.

## Instalasi (Windows)

1. Pasang Python 3.12: `winget install -e --id Python.Python.3.12`
2. Di folder proyek:
   ```powershell
   & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
   .venv/Scripts/python -m pip install -e ".[dev]"
   .venv/Scripts/python -m playwright install chromium
   ```
3. `.venv/Scripts/qa-agent init`, lalu salin `.env.example` menjadi `.env` dan isi:
   - `OFFICE_AI_KEY`: API key AI kantor
   - `QA_ADMIN_USER` / `QA_ADMIN_PASS`: akun **test** aplikasi yang dites
4. Sesuaikan `target.url` di `qa-agent.yaml`, lalu jalankan `.venv/Scripts/qa-agent check`. Semua baris harus `[OK]`.

## Alur kerja

1. **Petakan aplikasi:** `qa-agent explore`
   Hasilnya ada di `runs/<tanggal>_explore_<host>/`: sheet *Inventaris Fitur* dan daftar modul.
2. **Tes satu modul:** `qa-agent deep --from runs/<folder-explore> --module "Pengguna" [--prd prd_pengguna.md]`
   - Tambahkan `--review` untuk mengecek atau mengedit `testcases.xlsx` dulu, lalu jalankan `qa-agent run --run runs/<folder-deep>`.
3. **Review hasil:** buka `report.xlsx`, cek baris **Perlu Review**, lalu isi kolom **Status Final** dan **Catatan Reviewer**.
4. **Finalisasi:** `qa-agent report --run runs/<folder-deep>` membuat ulang Excel dan HTML dengan status final. Bagikan folder run dalam bentuk zip, atau cukup `report.html` saja.

## Status

| Status | Arti |
|---|---|
| Pass | Hasil sesuai expected |
| Fail | Ada bukti jelas: HTTP 5xx / error JavaScript, atau bertentangan dengan expected dari PRD |
| Perlu Review | Tidak sesuai expected hasil inferensi AI. Kamu yang memutuskan. |
| Blocked | Tidak bisa dieksekusi (elemen tidak ditemukan, loop, timeout, batas langkah) |
| Skipped | Diblok Safety Guard (mode production) |

## Mode production

`--env production` memblok aksi berisiko (hapus, simpan, kirim, bayar, dan sejenisnya) **dan** membatalkan semua request POST/PUT/PATCH/DELETE. Pengecualiannya hanya endpoint login, dan itu pun **hanya selama agent sedang login**. Service Worker juga diblok supaya request tidak bisa lewat jalur lain.

- Jika endpoint login aplikasi tidak mengandung login/auth/signin/token/session, isi `target.login_endpoints` (dicocokkan per path, misalnya `/api/v2/masuk`).
- Aplikasi yang memakai POST untuk membaca data (GraphQL, pencarian via POST) atau WebSocket tidak cocok dites di mode ini.
- Gunakan mode production hanya jika benar-benar perlu.

## Jika ada masalah

- **AI kantor mati di tengah run:** status run menjadi `paused`. Lanjutkan dengan `qa-agent run --run <folder> --resume`.
- **Ctrl+C:** tekan sekali untuk berhenti dengan rapi (laporan parsial tetap ditulis), dua kali untuk keluar paksa.
- **"Tutup file itu di Excel":** tutup `report.xlsx` lalu jalankan `qa-agent report --run <folder>`.
- **Ganti model:** ubah `llm.model` di config. Untuk Claude: `provider: anthropic`, `model: claude-sonnet-5-5`, `api_key_env: ANTHROPIC_API_KEY`.

## Keterbatasan

Saat ini hanya untuk web. Belum mendukung OTP/2FA/CAPTCHA, login yang disimpan di sessionStorage (agent akan login ulang tiap test case), elemen canvas, shadow DOM tertutup, iframe lintas domain, PRD selain `.md`/`.txt`, maupun template Excel kustom. Screenshot di laporan bisa berisi data aplikasi (termasuk password, jika AI menekan tombol "lihat password"), jadi perlakukan laporan sebagai dokumen internal.

## Pengembangan

- Test: `.venv/Scripts/python -m pytest` (otomatis menjalankan aplikasi demo + Chromium headless)
- Aplikasi demo manual: `.venv/Scripts/python -m tests.demo_app` → http://127.0.0.1:5055
