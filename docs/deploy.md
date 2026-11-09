# Memasang QA Agent di server

Panduan ini untuk menjalankan dashboard QA Agent di server kantor supaya bisa dipakai bersama oleh tim QA. Di server, setiap orang wajib login. Untuk pemakaian di laptop sendiri cukup `qa-agent serve` seperti biasa, tanpa login.

## 1. Spesifikasi server

| | Minimal | Disarankan |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU (2 run paralel) |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 50 GB+ (screenshot evidence menumpuk) |
| OS | Linux 64-bit dengan Docker 24+ dan Docker Compose v2 | |
| Jaringan | Bisa mengakses aplikasi yang diuji dan endpoint AI kantor | |

Port 80 dan 443 dibuka untuk browser tim. Port 8787 tidak perlu dibuka karena hanya dipakai di dalam Docker.

## 2. Pasang

```bash
git clone <repo> qa-agent && cd qa-agent
cp .env.server.example .env.server
docker compose build
docker compose run --rm qa-agent qa-agent secret-key
```

Salin kunci yang muncul ke `QA_AGENT_MASTER_KEY` di `.env.server`. Isi juga `QA_AGENT_DOMAIN` dengan alamat dashboard, misalnya `qa-agent.kantor.local`.

> Kunci induk dipakai untuk mengenkripsi API key AI dan password akun test di `/data/secrets.json.enc`. **Simpan cadangannya di tempat aman.** Bila kunci hilang, semua API key dan password akun test harus diisi ulang. Tanpa kunci, server tidak mau menyala; tidak ada fallback ke teks biasa.

### HTTPS

- **Domain publik** (bisa diakses dari internet): Caddy otomatis meminta sertifikat Let's Encrypt.
- **Domain internal kantor**: buka `Caddyfile`, hapus tanda `#` di depan `tls internal`. Caddy membuat sertifikat sendiri. Pasang sertifikat akar Caddy di laptop tim (ambil dengan `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .`), atau pakai sertifikat dari tim IT.

## 3. Buat Admin pertama

```bash
docker compose run --rm qa-agent qa-agent user add admin --role admin --data-dir /data
docker compose up -d
```

Password diminta tanpa ditampilkan dan minimal 8 karakter. Buka `https://<QA_AGENT_DOMAIN>`, login sebagai admin, lalu tambahkan pengguna lain di **Pengaturan > Keamanan**.

| Peran | Bisa |
|---|---|
| Admin | Semua, termasuk Pengaturan (Model AI, Skill QA, Laporan, Keamanan/pengguna) |
| QA | Kelola aplikasi & akun test, jalankan run, intervensi, review hasil |
| Viewer | Hanya melihat dan mengunduh dokumen |

Aturan login:

- Sesi berakhir setelah 12 jam tidak aktif, dan paling lama 7 hari.
- Login dikunci 5 menit setelah 5 kali salah password.
- Admin lupa password: `docker compose run --rm qa-agent qa-agent user passwd admin --data-dir /data`.

## 4. HP Android di server

Ada dua cara menyambungkan HP:

- **Lewat jaringan (disarankan).**
  1. Di HP buka **Opsi pengembang > Wireless debugging**. HP dan server harus satu jaringan.
  2. Di dashboard buka **Perangkat > Sambungkan lewat jaringan**.
  3. Isi IP:port yang tampil di HP.
  4. Untuk Android 11+, pertama kali pilih **Pasangkan perangkat dengan kode**, lalu isi juga alamat dan kode pairing.
- **Lewat USB ke server.**
  1. Di `docker-compose.yml`, hapus komentar bagian `devices: /dev/bus/usb`.
  2. Jalankan `docker compose up -d`.
  3. Setujui dialog "Izinkan USB debugging" di HP.

## 5. Backup

Ada tiga hal yang perlu dicadangkan:

- **Volume `qa-data`:** database, hasil run, evidence, skill, template laporan, dan rahasia terenkripsi.
- **File `.env.server`:** kunci induk.
- **File `Caddyfile`.**

```bash
docker run --rm -v qa-agent_qa-data:/data -v "$PWD":/backup alpine tar czf /backup/qa-data-$(date +%F).tgz -C /data .
```

Untuk memulihkan, ekstrak arsip ke volume baru dengan `QA_AGENT_MASTER_KEY` yang sama.

## 6. Update

```bash
git pull
docker compose build
docker compose up -d
```

Struktur database diperbarui otomatis saat server menyala. Run yang sedang berjalan saat server di-restart ditandai **Terhenti** dan bisa dilanjutkan dari halaman Hasil.

## 7. Tanpa Docker

```bash
pip install .
playwright install --with-deps chromium
export QA_AGENT_MASTER_KEY=...   # dari: qa-agent secret-key
qa-agent user add admin --role admin
qa-agent serve --host 0.0.0.0 --auth --secrets file --secure-cookies --no-browser
```

Jalankan di belakang reverse proxy HTTPS seperti Caddy atau nginx. `--secure-cookies` hanya dipakai bila dashboard diakses lewat HTTPS. QA Agent menolak menyala di alamat selain 127.0.0.1 tanpa `--auth`.
