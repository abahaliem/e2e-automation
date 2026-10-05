# QA Agent — Sub-proyek 1: Core + Web Runner

- **Tanggal:** 2026-10-05
- **Status:** Draft, menunggu review
- **Pemilik:** QA (pengguna tunggal untuk tahap ini)

## 1. Tujuan

Membangun sistem self-hosted berbasis Python yang menjalankan testing E2E secara otomatis oleh AI yang berperan sebagai QA automation engineer. Input cukup URL aplikasi web dan akun test. Output berupa **dokumentasi test**: daftar test case dan laporan eksekusi lengkap dengan screenshot evidence.

**Masalah yang diselesaikan:** testing selama ini manual, dan dokumentasi test case beserta evidence sering tidak tersedia untuk lead, dev, maupun PM. QA tidak punya akses ke kode developer, jadi semua pengujian bersifat black-box.

**Kriteria sukses sub-proyek 1:**

1. Dari satu URL + akun, `qa-agent explore` menghasilkan inventaris fitur (modul → halaman → form/aksi) beserta screenshot.
2. `qa-agent deep` untuk satu modul menghasilkan test case (positif, negatif, validasi, boundary, navigasi), mengeksekusinya, dan menghasilkan `report.xlsx` + `report.html`.
3. Pada aplikasi demo dengan bug buatan, agent menemukan minimal 2 dari 3 bug memakai GLM kantor.
4. Di mode `production`, tidak ada satu pun request yang mengubah data (non-GET, selain login) yang lolos.
5. Laporan bisa direview, dan status final dari reviewer tercermin di dokumen akhir.

## 2. Konteks & Batasan

| Aspek | Keputusan |
|---|---|
| Pengguna | Satu QA, dijalankan di laptop Windows |
| Platform target | Web (sub-proyek ini). Android menyusul di atas core yang sama. |
| Sumber test case | AI mengeksplorasi aplikasi sendiri. PRD (sering tidak lengkap) bersifat opsional sebagai konteks. |
| Model AI | Endpoint AI kantor, kompatibel OpenAI (`http://192.168.151.121/v1`), default `z-ai/glm-5.3-flash`, mendukung input gambar. Claude (key terpisah) sebagai provider alternatif. |
| Login | Username/password biasa, tanpa OTP/2FA/CAPTCHA |
| Environment | `dev` (default) atau `production` (mode aman), dipilih per sesi |
| Output | Excel (`.xlsx`) + laporan HTML satu file |
| Bahasa | Test case dan laporan dalam Bahasa Indonesia |

## 3. Dekomposisi Proyek

Sistem lengkap dipecah menjadi sub-proyek. Masing-masing punya siklus spec → plan → implementasi sendiri.

1. **Core + Web** ← *dokumen ini*
2. Android runner (adb + uiautomator2 + scrcpy untuk mirror layar dan rekam video)
3. API runner (input OpenAPI/Swagger atau Postman collection)
4. Dashboard web (upload APK, paste URL, lihat hasil)
5. Replay / regression tanpa AI

Urutan sub-proyek 2–5 diputuskan setelah sub-proyek 1 berjalan.

## 4. Pendekatan

Agent loop dibuat sendiri dengan satu interface **Driver** untuk setiap platform. Framework agent pihak ketiga (browser-use, DroidRun) tidak dipakai, karena:

- satu format test case, satu Safety Guard, dan satu generator laporan berlaku untuk web dan Android;
- prompt bisa dituning khusus untuk GLM;
- setiap langkah tercatat lengkap untuk debugging dan replay di masa depan.

## 5. Arsitektur

```
                    ┌────────────────────────────────────┐
  CLI ────────────▶ │  Orchestrator                      │
                    │  • Explore: petakan app → app_map  │
                    │  • Deep: susun test case → jalankan│
                    └──────────────┬─────────────────────┘
                                   │ per test case
                    ┌──────────────▼─────────────────────┐
                    │  Agent Loop                        │
                    │  observe → think → guard → act     │
                    │         → verify → record          │
                    └──┬───────────┬──────────┬──────────┘
                       │           │          │
            ┌──────────▼──┐  ┌─────▼─────┐ ┌──▼───────────┐
            │ Driver      │  │ LLM Client│ │ Safety Guard │
            │ • Web       │  │ • OpenAI- │ │ dev / prod   │
            │ • (Android) │  │   compat  │ └──────────────┘
            └─────────────┘  │ • Claude  │
                             │ • Fake    │
                             └───────────┘
                       │
            ┌──────────▼───────────────────────────────┐
            │ Evidence Store → Reporter                │
            │ screenshots + steps.jsonl → .xlsx + .html│
            └──────────────────────────────────────────┘
```

**Prinsip:** Orchestrator, Agent Loop, Safety Guard, dan Reporter tidak tahu platform yang sedang dites. Hanya Driver yang tahu. Menambah Android berarti menambah satu implementasi Driver.

### 5.1 Struktur modul

```
qa_agent/
  cli.py                  # Typer: init, check, explore, deep, run, report
  config.py               # load qa-agent.yaml + .env, validasi Pydantic
  models.py               # Element, Observation, Action, ActionResult,
                          # TestCase, StepRecord, ScreenInfo, AppMap
  llm/
    base.py               # LLMClient protocol
    openai_compat.py      # endpoint kantor (GLM, DeepSeek, MiniMax)
    anthropic_client.py   # Claude
    fake.py               # jawaban terskrip untuk test
  drivers/
    base.py               # Driver protocol
    web.py                # Playwright
  agent/
    loop.py               # observe→think→guard→act→verify→record
    prompts.py            # prompt sistem & template pesan
    parser.py             # parsing + validasi JSON aksi
    loop_detect.py        # deteksi langkah berulang
  guard.py                # Safety Guard
  orchestrator/
    auth.py               # login + simpan/muat storage_state
    fingerprint.py        # sidik jari layar
    explore.py
    deep.py
  evidence.py             # folder run, screenshot, steps.jsonl
  report/
    humanize.py           # aksi → kalimat bahasa manusia (template)
    excel.py
    html.py
    templates/report.html.j2
tests/
  unit/
  integration/
  demo_app/               # aplikasi web demo dengan bug buatan (Flask)
```

## 6. Komponen

### 6.1 LLM Client

```python
class LLMClient(Protocol):
    def chat(self, system: str, messages: list[Message],
             images: list[bytes] | None = None) -> str: ...
```

- `openai_compat`: SDK `openai` dengan `base_url` dari config. Gambar dikirim sebagai `image_url` base64.
- `anthropic_client`: SDK `anthropic`.
- `fake`: mengembalikan daftar jawaban terskrip secara berurutan. Dipakai di integration test.
- Jika config `vision: false`, gambar tidak dikirim dan agent hanya memakai daftar elemen teks.

### 6.2 Driver

```python
class Driver(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def new_session(self, auth_state: Path | None) -> None: ...   # context bersih
    def save_auth_state(self, path: Path) -> None: ...
    def goto(self, location: str) -> None: ...                     # URL (web)
    def observe(self) -> Observation: ...
    def execute(self, action: Action, element: Element | None) -> ActionResult: ...
    def screenshot(self, highlight: Element | None = None) -> bytes: ...
```

**`Observation`** berisi:
- `screenshot_annotated`: PNG dengan kotak bernomor (Set-of-Mark), hanya untuk AI
- `elements: list[Element]`: index, role, name/label, type, value, bbox, selector
- `location`: URL atau nama layar
- `title`
- `signals: list[Signal]`: error console, response HTTP 4xx/5xx (method, URL, status), dan teks toast/alert error yang terdeteksi sejak observasi sebelumnya

**Ekstraksi elemen (web):**
- JavaScript di halaman mengambil elemen interaktif yang terlihat dan tidak disabled: `a`, `button`, `input`, `select`, `textarea`, `[role=button|link|tab|menuitem|checkbox|radio|combobox]`, `[onclick]`, `[contenteditable]`.
- Dibatasi 80 elemen per observasi. Elemen di luar viewport dijangkau lewat aksi `scroll`.
- Iframe same-origin ikut diproses.

**Selector stabil**, dengan prioritas:
1. `data-testid` / `data-test` / `id` yang tidak tampak auto-generated
2. role + accessible name (`get_by_role`)
3. teks
4. CSS path

Selector disimpan di setiap `StepRecord`.

**Evidence screenshot:** PNG bersih dengan kotak merah di elemen target (bukan versi bernomor).

### 6.3 Agent Loop

Input: `goal` (test case atau tujuan login), Driver, LLMClient, Guard, EvidenceStore, dan batas langkah.

Setiap iterasi:
1. **observe:** `driver.observe()`
2. **think:** kirim prompt sistem (peran QA automation, aturan aksi, format JSON) + goal + 8 langkah terakhir dalam ringkasan teks + observasi (screenshot bernomor + daftar elemen + sinyal).
3. **parse:** validasi JSON dengan Pydantic. Jika gagal, minta ulang sekali dengan pesan error. Jika gagal lagi, catat langkah sebagai error dan lanjut ke iterasi berikutnya (dihitung sebagai langkah).
4. **guard:** `guard.check(action, element, context)` → `allow` atau `block(reason)`.
5. **act:** `driver.execute()`. Jika diblok, aksi tidak dijalankan dan alasannya dikirim ke AI di langkah berikutnya.
6. **verify:** observasi berikutnya membawa perubahan layar + sinyal baru.
7. **record:** screenshot evidence + satu baris `StepRecord` di `steps.jsonl`, ditulis langsung (flush per langkah).

**Format aksi dari AI:**

```json
{"thought": "...", "action": "type", "element": 1, "value": "bukan-email",
 "expect": "Muncul pesan validasi format email", "risk": "low"}
```

Aksi yang tersedia: `click`, `type`, `select`, `scroll` (`value`: up/down), `back`, `navigate` (web, dalam allowlist domain), `wait`, `done` (`status`: pass|fail, `actual`), `blocked` (`reason`).

**Kredensial:** AI hanya melihat placeholder `{{username}}` dan `{{password}}`. Driver mengganti placeholder dengan nilai dari `.env` saat eksekusi. Nilai password tidak pernah masuk prompt, log, atau laporan (selalu ditampilkan `••••••`).

**Pengaman loop:**
- maksimal `max_steps_per_tc` langkah (default 25) → `blocked`
- timeout per aksi 15 detik
- kombinasi (fingerprint layar, aksi, elemen) yang sama 3 kali → AI diberi peringatan untuk memilih jalan lain. Kejadian keempat → `blocked`.

### 6.4 Orchestrator

**Folder run:** `runs/YYYY-MM-DD_HHMM_<mode>_<slug>/`

**Auth (`auth.py`):**
- Di awal sesi, agent loop menjalankan goal "login dengan akun `<role>`".
- Jika berhasil, `storage_state` disimpan di `.qa-agent/auth/<target>-<role>.json`. Lokasi ini di-gitignore dan **tidak** disimpan di folder run, karena folder run akan dibagikan.
- Setiap test case memakai `new_session(auth_state)`.
- Jika di tengah test case driver terlempar ke halaman login (heuristik: URL atau form login terdeteksi, padahal test case bukan tentang login), lakukan login ulang lalu lanjutkan.

**Fingerprint layar (`fingerprint.py`):**
- Path URL dinormalisasi: segmen numerik, UUID, atau hex panjang → `:id`. Query string dibuang.
- Ditambah hash 8 karakter dari daftar `(role, name)` elemen yang terurut.

**Mode Explore:**
- BFS dari halaman awal setelah login. Kembali ke layar lain lewat navigasi URL.
- Layar tanpa URL unik (modal, drawer) dicatat sebagai bagian dari layar induknya dan tidak ditelusuri lebih dalam.
- Satu panggilan AI per layar baru mengembalikan: `module`, `page_name`, `purpose`, `forms` (field + tipe), `actions`, dan `nav_candidates` (index elemen navigasi).
- Hanya navigasi: tidak ada aksi `type`, tidak ada submit, dan elemen berisiko (kata kunci guard) tidak diklik **di semua environment**.
- Batas: `explore_max_screens` (60), `explore_max_depth` (5), `explore_max_minutes` (45).
- Output: `app_map.json`, screenshot per layar, dan sheet "Inventaris Fitur".

**Mode Deep:**
1. Input: `--from <run explore>` (membaca `app_map.json`, disalin ke folder run baru), `--module`, opsional `--prd <file .md/.txt>`.
2. **Susun test case:** satu panggilan AI berisi potongan app_map modul tersebut + PRD. Hasilnya maksimal `deep_max_tcs` (15) test case.
   - Field test case: `id` (`TC-<SINGKATAN>-NNN`), `module`, `page`, `title`, `type` (positif/negatif/validasi/boundary/navigasi), `priority`, `precondition`, `test_data`, `steps`, `expected`, `expected_source` (`PRD` | `Inferensi AI`).
   - Ditulis ke `testcases.json`.
3. Jika `--review`: tulis `testcases.xlsx` lalu berhenti. Setelah diedit, `qa-agent run --run <folder>` membaca ulang sheet Test Cases dari xlsx ke `testcases.json` lalu mengeksekusi.
4. **Eksekusi:** setiap test case dimulai dengan `new_session` lalu `goto` ke halaman awal modul, kemudian agent loop berjalan dengan goal = test case. Data yang dibuat diberi awalan `QA-AUTO-<YYYYMMDD-HHMM>`.
5. **Penilaian status** (aturan, diterapkan setelah `done`/`blocked`):

| Kondisi | Status |
|---|---|
| Ada sinyal HTTP 5xx atau uncaught JS exception selama test case | **Fail** |
| AI `done: fail` dan `expected_source = PRD` | **Fail** |
| AI `done: fail` dan `expected_source = Inferensi AI` | **Perlu Review** |
| AI `done: pass` | **Pass** |
| `blocked` karena loop/timeout/elemen tidak ditemukan/batas langkah | **Blocked** |
| Test case berakhir `blocked` **dan** minimal satu aksinya diblok Safety Guard | **Skipped** |

Aturan dievaluasi dari atas ke bawah. Aturan pertama yang cocok menentukan status.

### 6.5 Safety Guard

**Semua environment:**
- `navigate` hanya ke domain di `allowed_domains`. Link ke domain lain tidak diklik.
- Logout diblok, kecuali judul atau langkah test case memang tentang logout.
- Mode Explore: hanya navigasi (lihat 6.4).

**Mode `production`:**
1. **Aturan kata kunci** pada label elemen, teks tombol, dan judul form/dialog di sekitarnya (ID + EN, case-insensitive): hapus, delete, remove, bayar, pay, checkout, kirim, send, submit, simpan, save, update, approve, setujui, reject, tolak, transfer, nonaktifkan, deactivate, reset, konfirmasi, confirm, upload, import, broadcast. Daftarnya bisa ditambah lewat config.
2. **Field `risk` dari AI:** guard memakai tingkat risiko tertinggi antara aturan kata kunci dan penilaian AI. AI tidak bisa menurunkan risiko.
3. **Pengaman jaringan (web):** Playwright `route` membatalkan semua request `POST`/`PUT`/`PATCH`/`DELETE`, kecuali endpoint login (`login_endpoints` di config, dengan default heuristik path `login`/`auth`/`signin`/`token`). Setiap request yang dibatalkan dicatat.

Aksi yang diblok dicatat sebagai `blocked_by_guard` beserta alasannya. Jika test case tidak bisa diselesaikan karenanya, statusnya **Skipped (production guard)**.

### 6.6 Evidence Store

- `steps.jsonl`, satu baris per langkah: `tc_id`, `step_no`, `timestamp`, `location`, `fingerprint`, `thought`, `action`, `element` (role, name, selector), `value` (dimask jika rahasia), `expect`, `guard_result`, `result` (ok/error + pesan), `signals`, `screenshot`.
- `screenshots/<TC-ID>_step-<NN>.png`. Untuk explore: `screenshots/explore_<NNN>.png`.
- `run.json`: metadata run (target, env, model, waktu mulai/selesai, status run: running/paused/completed/interrupted).

### 6.7 Reporter

Kedua laporan dibuat murni dari `testcases.json`, `steps.jsonl`, `app_map.json`, dan `run.json`, sehingga bisa dibuat ulang tanpa AI.

**`report.xlsx` (openpyxl), 4 sheet:**
1. **Ringkasan:** target, environment, model, tanggal, durasi, jumlah per status (AI & final), pass rate.
2. **Test Cases:** TC ID, Modul, Halaman, Skenario, Tipe, Prioritas, Pre-condition, Test Data, Langkah, Expected, Sumber Expected, Actual, **Status AI** (warna), **Status Final** (dropdown, diisi reviewer), Catatan Reviewer, Evidence (hyperlink relatif ke screenshot terakhir + ke anchor di HTML).
3. **Temuan:** hanya Fail + Perlu Review. Isinya judul, severity (saran AI), langkah reproduksi, expected vs actual, sinyal teknis (HTTP status + endpoint, pesan console), dan evidence.
4. **Inventaris Fitur:** dari `app_map.json`.

Screenshot tidak ditanam di Excel. Untuk dibagikan, folder run di-zip.

**`report.html` (Jinja2), satu file:**
- Header ringkasan + filter status dan modul (vanilla JS, tanpa server).
- Daftar temuan di atas.
- Kartu test case yang bisa dibuka-tutup, berisi timeline langkah: kalimat aksi dari `humanize.py` (template, bukan AI), alasan AI, screenshot (klik untuk perbesar), dan sinyal.
- Screenshot ditanam sebagai JPEG base64, lebar maksimal 1280 px, kualitas 70.
- Bisa dicetak ke PDF dari browser.

**Alur review:** `qa-agent report --run <folder>` membaca kolom Status Final + Catatan Reviewer dari `report.xlsx` yang sudah diisi, menyimpannya ke `review.json`, lalu membuat ulang `report.xlsx` dan `report.html` dengan status final. Jika Status Final kosong, yang dipakai Status AI.

## 7. CLI

| Perintah | Fungsi |
|---|---|
| `qa-agent init` | Membuat `qa-agent.yaml` dan `.env.example` |
| `qa-agent check` | Cek config, koneksi + dukungan gambar endpoint AI, browser Playwright terpasang, target bisa diakses |
| `qa-agent explore [--env dev\|production]` | Mode Explore |
| `qa-agent deep --from <run> --module <nama> [--prd <file>] [--review] [--env ...]` | Mode Deep |
| `qa-agent run --run <folder> [--resume]` | Eksekusi test case (setelah review atau untuk melanjutkan) |
| `qa-agent report --run <folder>` | Membuat ulang laporan dengan hasil review |

## 8. Konfigurasi

`qa-agent.yaml` (di-commit, tanpa rahasia):

```yaml
target:
  platform: web
  url: https://app-dev.kantor.local
  allowed_domains: [app-dev.kantor.local]
  login_endpoints: []          # kosong = heuristik default
environment: dev               # dev | production
accounts:
  - role: admin
    username_env: QA_ADMIN_USER
    password_env: QA_ADMIN_PASS
llm:
  provider: openai_compatible  # openai_compatible | anthropic
  base_url: http://192.168.151.121/v1
  model: z-ai/glm-5.3-flash
  api_key_env: OFFICE_AI_KEY
  vision: true
  timeout_seconds: 60
limits:
  max_steps_per_tc: 25
  deep_max_tcs: 15
  explore_max_screens: 60
  explore_max_depth: 5
  explore_max_minutes: 45
guard:
  extra_risky_keywords: []
browser:
  headless: false
  viewport: 1366x768
```

`.env` (gitignored): `OFFICE_AI_KEY`, `ANTHROPIC_API_KEY` (opsional), dan kredensial akun test.

## 9. Error Handling

| Kondisi | Penanganan |
|---|---|
| LLM timeout / 5xx / 429 | Retry 3× dengan backoff (2, 4, 8 detik). Jika masih gagal, run berstatus `paused`. Run Deep dilanjutkan dengan `qa-agent run --run <folder> --resume` mulai dari test case pertama yang belum berstatus final. Run Explore tidak bisa di-resume: `app_map.json` parsial tetap tersimpan dan laporan dibuat, lalu explore dijalankan ulang jika perlu. |
| JSON aksi tidak valid | Minta ulang 1×. Jika masih gagal, langkah dicatat error. |
| Elemen stale / hilang saat aksi | Observe ulang, coba 1× |
| Timeout navigasi | Coba 1×, lalu test case **Blocked** |
| Browser / context crash | Buat context baru, test case **Blocked**, lanjut ke berikutnya |
| Sesi kedaluwarsa | Login ulang otomatis, lanjutkan test case |
| Ctrl+C | Selesaikan langkah berjalan, `run.json` = `interrupted`, tulis laporan parsial |

Prinsip: kegagalan satu test case tidak menghentikan run. Laporan selalu dibuat, termasuk untuk run parsial.

## 10. Pengujian

1. **Unit (pytest):** normalisasi fingerprint, aturan Safety Guard (kata kunci, risiko maksimum, blokir non-GET di production), parser aksi, prioritas selector, masking kredensial, `humanize`, generator Excel/HTML dari fixture data, impor Status Final dari xlsx.
2. **Integration (tanpa AI):** `tests/demo_app` adalah aplikasi Flask kecil berisi login, daftar user, form tambah/edit user dengan validasi, dan 3 bug buatan:
   - input tertentu memicu HTTP 500
   - validasi format email tidak berjalan
   - tombol "Ekspor" tidak melakukan apa-apa

   Agent dijalankan dengan `FakeLLM` untuk menguji agent loop, guard (termasuk blokir jaringan di production), auth, evidence, dan laporan secara deterministik.
3. **Evaluasi (manual, dengan GLM asli)** terhadap demo app. Target: ≥2 dari 3 bug ditemukan, 0 request pengubah data lolos di production, laporan terbuka benar.

## 11. Risiko

| Risiko | Mitigasi |
|---|---|
| Kemampuan GLM untuk agent UI belum terukur | Uji `check` + evaluasi demo app di awal implementasi. Provider bisa diganti lewat config (Claude). |
| Aplikasi dengan elemen canvas, shadow DOM tertutup, atau iframe lintas domain | Didokumentasikan sebagai keterbatasan. Elemen yang tidak bisa diekstrak tidak bisa diklik. |
| Screenshot di laporan berisi data sensitif | Password dimask. Laporan diperlakukan sebagai dokumen internal. Mode production disarankan hanya untuk kebutuhan mendesak. |
| `storage_state` berisi token sesi | Disimpan di `.qa-agent/auth/` yang di-gitignore, tidak di folder run |
| Hasil AI berbeda antar run | Status "Perlu Review" + review manual. Selector direkam untuk replay di sub-proyek 5. |

## 12. Di Luar Cakupan

Android, testing API, dashboard web, perintah `replay`, input PRD selain `.md`/`.txt`, template Excel kustom kantor, eksekusi paralel, dan login dengan OTP/2FA/CAPTCHA.

## 13. Prasyarat Lingkungan

- Python 3.11+ (saat ini terpasang 3.9.13, perlu upgrade)
- `playwright install chromium`
- Akses jaringan ke `192.168.151.121` dan API key AI kantor
- Dependency utama: `playwright`, `openai`, `anthropic`, `pydantic`, `typer`, `pyyaml`, `python-dotenv`, `openpyxl`, `jinja2`, `pillow`. Untuk dev: `pytest`, `flask`.
