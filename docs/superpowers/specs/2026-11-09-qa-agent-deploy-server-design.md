# QA Agent — Sub-proyek 4: Deploy ke server

- **Tanggal:** 2026-11-09
- **Status:** Dikerjakan langsung (permintaan pengguna: kerjakan sub-proyek 3 sampai 4).
- **Keputusan sebelumnya (disepakati):** akses sekarang localhost tanpa login, login ditambahkan saat ke server (pilihan C); rahasia lewat satu antarmuka `SecretStore`, backend server cukup ditambah.

## 1. Mode

| Mode | Cara jalan | Login |
|---|---|---|
| Lokal (default) | `qa-agent serve` → 127.0.0.1 | Tidak (seperti sekarang) |
| Server | `qa-agent serve --host 0.0.0.0 --auth` (atau Docker) | Wajib |

Server menolak menyala di alamat selain loopback tanpa `--auth`.

## 2. Pengguna & peran

- Tabel `users` (username unik, hash password PBKDF2-SHA256 600.000 iterasi + salt, peran, aktif) dan `sessions` (hash token, kedaluwarsa 12 jam sejak aktivitas terakhir, maksimal 7 hari).
- Peran: **Admin** (semua, termasuk Pengaturan: Model AI, Skill QA, Laporan, Keamanan/pengguna), **QA** (aplikasi & akun test, run, intervensi, review), **Viewer** (hanya melihat dan mengunduh dokumen).
- Cookie sesi `qa_session` HttpOnly, SameSite=Lax, `Secure` bila `--secure-cookies` (di belakang HTTPS). Request yang mengubah data wajib header `X-QA-Agent: 1` (perlindungan CSRF sederhana). Login dibatasi 5 percobaan gagal per 5 menit per username.
- Admin pertama dibuat lewat CLI: `qa-agent user add <nama> --role admin` (password diminta interaktif). Admin lain dikelola dari Pengaturan > Keamanan.
- WebSocket memeriksa cookie yang sama.
- Run mencatat siapa yang memulai (`created_by`).

## 3. Rahasia di server

`FileSecretStore`: file `secrets.json.enc` di folder data, terenkripsi Fernet (AES-128-CBC + HMAC) dengan kunci induk dari variabel lingkungan `QA_AGENT_MASTER_KEY` (dibuat dengan `qa-agent secret-key`). Dipilih dengan `--secrets file` atau `QA_AGENT_SECRET_BACKEND=file`; default tetap Windows Credential Manager (keyring). Tanpa kunci induk → server tidak menyala (tidak ada fallback teks biasa).

## 4. Docker & HTTPS

- `Dockerfile` multi-stage: build frontend (Node) → image Python 3.12 slim + Chromium Playwright + `adb`.
- `docker-compose.yml`: layanan `qa-agent` (volume `/data`) + `caddy` (HTTPS otomatis Let's Encrypt / sertifikat internal kantor) dengan `Caddyfile`.
- Android di server: HP lewat USB ke server, atau `adb connect <ip>:<port>` (Wireless debugging); dashboard punya isian "Sambungkan lewat jaringan".
- Panduan `docs/deploy.md`: spesifikasi server, langkah pasang, buat admin, backup, update.

## 5. Testing

Unit: hash/verify password, sesi & kedaluwarsa, rate limit, FileSecretStore (enkripsi, kunci salah), middleware peran (401/403), CSRF header, WS tanpa sesi ditolak, serve menolak host publik tanpa --auth, CLI user add. Vitest: halaman login, tab Keamanan (kelola pengguna), redirect 401.
