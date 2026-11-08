# QA Agent — Sub-proyek 1 (baru): Platform Dashboard + Pengujian Web

- **Tanggal:** 2026-11-08
- **Status:** Draft, menunggu review pengguna
- **Dibangun di atas:** mesin `qa_agent` (spec 2026-10-05, PR #1). Mesin dipertahankan; semua pekerjaan dengan TDD.
- **Mockup acuan:** `docs/design/mockups/` (01, 03, 04, 05, 07, 08, 09 relevan untuk sub-proyek ini)

## 1. Tujuan

Mengganti cara pakai berbasis CLI dengan **dashboard web lokal yang bagus (tema terang)**: pengguna memasukkan URL, klik Run, menonton proses testing secara **live**, bisa **mengintervensi**, lalu melihat dan mereview hasil serta mengunduh dokumen (Excel, HTML, PDF).

**Kriteria sukses:**
1. `qa-agent serve` membuka dashboard di browser; tidak perlu CLI untuk alur normal.
2. Dari form Run baru (Web), run explore dan run modul berjalan dengan mesin yang ada.
3. Layar live menampilkan browser yang dites (~6 fps) plus kotak elemen yang sedang dikerjakan.
4. Jeda, Lanjutkan, Ambil alih, Arahkan agent, Pikir ulang, Lewati, Hentikan, dan mode "Konfirmasi tiap langkah" bekerja dan tercatat di laporan.
5. Halaman Hasil Run memungkinkan review (Status Final, Severity, Catatan) dan unduh Excel/HTML/PDF.
6. Dashboard menampilkan total pengujian (web/android), run berjalan, run selesai + dokumen, temuan terbaru.
7. Pengaturan AI: profil OpenAI-compatible / Anthropic, base URL, API key (disimpan di Windows Credential Manager), ambil daftar model, tes koneksi.
8. 216 test lama tetap lulus.

## 2. Keputusan yang disepakati

| Aspek | Keputusan |
|---|---|
| Akses | Hanya `127.0.0.1`, tanpa login; struktur memungkinkan login ditambahkan nanti (pilihan C) |
| Stack | FastAPI (Python) + React + TypeScript + Vite + Tailwind v4 + shadcn/ui; hasil build dibungkus dalam package Python |
| Tema | Terang, satu aksen biru `#2560e8`, hijau/merah/kuning hanya untuk status; font Geist + Geist Mono; ikon Phosphor |
| Urutan sub-proyek | 1 Dashboard + Web → 2 Android (HP fisik utama, emulator opsional, upload APK) → 3 Skill QA + dokumen PDF baru + template Excel |

## 3. Arsitektur

```
Browser (React) ──REST──► FastAPI 127.0.0.1 (qa-agent serve)
       ▲  ◄──WebSocket── event, frame live, perintah intervensi
       │
FastAPI: API & WS ─ RunManager (antrian, 1 worker thread per run, maks 2 paralel)
                     └─ Explorer / DeepRunner → AgentLoop → WebDriver (Playwright)
                        + RunControl (baru) + EventBus (baru)
         Store: SQLite (indeks) + folder runs/ (evidence, laporan)
         Secrets: Windows Credential Manager (keyring)
```

- `qa_agent/` (mesin): tambahan kecil saja — `RunControl` dan `EventBus` yang dipanggil di titik kontrol AgentLoop. CLI lama tetap berfungsi.
- `qa_agent/server/` (baru): app FastAPI, router REST, WebSocket, RunManager, store SQLite, secrets.
- `web/` (baru): aplikasi React; `npm run build` menghasilkan `qa_agent/server/static/`.
- Playwright tidak thread-safe: setiap run memiliki Playwright + browser sendiri di worker thread-nya; komunikasi server ↔ worker lewat antrian thread-safe.
- Dua run untuk aplikasi yang sama tidak boleh paralel (berbagi sesi login); run kedua menunggu.

## 4. Run & layar live

- POST Run baru → folder run + baris DB status **Menunggu** → worker mengambil saat slot kosong.
- "Satu modul" memakai modul dari explore terakhir aplikasi; nonaktif bila belum pernah explore.
- Browser selalu headless dari dashboard.
- **Frame live:** CDP `Page.startScreencast` (JPEG, lebar maks 1280 px, ~6 fps) → WebSocket biner. Dikirim hanya bila ada penonton. Screencast dipasang ulang setiap sesi browser baru (per test case).
- **Overlay kotak elemen** digambar frontend dari bbox di event langkah; frame asli tetap bersih.
- **Event (JSON):** `run.status`, `tc.started`, `tc.finished`, `step.planned` (alasan AI, aksi, bbox; dikirim sebelum eksekusi), `step.done` (hasil, URL screenshot), `signal`, `run.finished`.
- Server menyimpan snapshot kondisi run di memori; klien yang tersambung ulang mengambil snapshot dulu lalu berlangganan stream. Evidence permanen tetap di `steps.jsonl`.
- Dashboard berlangganan event status global sehingga kartu "Sedang berjalan" ter-update tanpa refresh.
- Desain frame/event bersifat umum supaya Android (sub-proyek 2) cukup mengganti sumber frame (scrcpy).

## 5. Intervensi

Titik kontrol: (a) sebelum AI memutuskan langkah, (b) setelah keputusan dan sebelum eksekusi.

| Perintah | Perilaku |
|---|---|
| Jeda | Aksi berjalan diselesaikan, run berhenti di titik kontrol berikutnya; status Dijeda; browser tetap terbuka |
| Lanjutkan | Observe ulang, lalu AI memutuskan |
| Ambil alih | Otomatis jeda; klik (koordinat ternormalisasi 0..1), ketik, tombol, scroll dari layar live diteruskan ke halaman (dieksekusi di worker thread) |
| Kembalikan ke AI | AI menerima catatan langkah manual QA, lanjut dari kondisi layar |
| Akhiri test case Pass/Fail | Saat ambil alih; menetapkan hasil test case oleh QA |
| Arahkan agent | Teks masuk prompt sebagai "Arahan QA" sampai test case selesai |
| Pikir ulang | Saat dijeda: rencana langkah dibuang, AI memilih ulang |
| Lewati | Test case → Blocked dengan catatan "Dilewati oleh QA" |
| Hentikan | Seperti Ctrl+C: berhenti rapi, laporan parsial, bisa resume |
| Konfirmasi tiap langkah | Opsi run: AI berhenti setelah setiap `step.planned`, menunggu "Jalankan" |

- Semua intervensi dicatat di `steps.jsonl` (field baru `actor: "ai" | "manual"`, aksi `hint`) dan muncul di laporan sebagai "Langkah manual oleh QA" / arahan QA.
- Mode production: filter jaringan tetap aktif untuk klik manual; aturan kata kunci Guard tidak berlaku untuk klik manusia.
- Perintah input hanya diterima saat mode ambil alih; selain itu ditolak (409).

## 6. Data & pengaturan

- Folder data default `%USERPROFILE%\QA Agent\` (opsi `--data-dir`): `qa-agent.db`, `runs/`, `auth/`.
- Tabel: `apps`, `accounts` (password di keyring), `ai_profiles` (API key di keyring), `runs` (status, waktu, folder, jumlah per status), `test_cases_index` (id, judul, status AI, status final, severity).
- API tidak pernah mengembalikan nilai rahasia; hanya versi tersamar (`sk-••••3f9a`). Tidak ada fallback teks biasa bila keyring tidak tersedia.
- Ambil daftar model via `/v1/models` (fallback input manual); Tes koneksi = teks + gambar (logika `qa-agent check`).
- Review dari dashboard menulis `review.json`, membangun ulang Excel/HTML, memperbarui indeks; editan di Excel tetap diimpor sebelum laporan dibangun ulang; Excel terkunci → peringatan.
- Unduh PDF di sub-proyek ini: `report.html` dicetak via Chromium `page.pdf()`.
- Dashboard: total run per platform, test case dijalankan, temuan (status efektif Fail/Perlu Review), pass rate = Pass / test case dieksekusi (tanpa Skipped), dibanding periode sebelumnya dengan panjang sama.
- "Impor run lama" memasukkan folder `runs/` dari CLI ke indeks.
- Indeks dapat dibangun ulang dari folder `runs/` bila database rusak.

## 7. Error handling

| Kondisi | Perilaku |
|---|---|
| Server/laptop mati di tengah run | Saat start, run berjalan/menunggu ditandai Terhenti; run modul bisa dilanjutkan (resume), explore dijalankan ulang |
| AI tidak merespons setelah retry | Run dijeda otomatis; banner + tombol Coba lagi |
| Login gagal | Run dijeda; pesan + tautan ke pengaturan akun |
| Exception tak terduga di worker | Run Terhenti; laporan parsial ditulis |
| WebSocket putus | Reconnect otomatis dengan backoff; snapshot lalu stream |
| Port dipakai | Pakai port kosong berikutnya, tampilkan alamat |
| Input form tidak valid | Error di bawah field (422 → pesan per field) |

## 8. Testing (TDD)

1. Mesin: RunControl dan urutan event dengan FakeDriver/FakeLLM.
2. Server: pytest + TestClient (REST & WebSocket); RunManager dengan FakeLLM terhadap aplikasi demo; secrets dengan backend keyring di memori.
3. Frontend: Vitest + Testing Library (form Run baru, badge status, pemetaan klik live view ke koordinat).
4. E2E: Playwright menjalankan dashboard sungguhan + aplikasi demo dengan AI palsu yang disuntikkan lewat fixture test (tidak bisa diaktifkan di produksi): buat aplikasi → Run → frame live → Jeda → arahan → Lanjutkan → selesai → Hasil → ubah Status Final → unduh Excel.
5. Semua test lama tetap lulus.
6. Kecocokan visual dengan mockup dicek manual lewat screenshot per halaman.

## 9. Di luar cakupan

Android, Skill QA, desain dokumen PDF baru, template Excel kantor, login multi-pengguna, packaging aplikasi desktop.
