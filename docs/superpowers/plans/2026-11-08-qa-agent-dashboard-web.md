# QA Agent Dashboard Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dashboard web lokal (`qa-agent serve`) untuk menjalankan, menonton live, mengintervensi, dan mereview pengujian web, di atas mesin `qa_agent` yang sudah ada.

**Architecture:** FastAPI di `127.0.0.1` memanggil mesin lama lewat `RunManager` (satu worker thread per run). Mesin mendapat dua tambahan: `RunControl` (titik kontrol intervensi) dan callback event. Frame live dari CDP screencast dan event dialirkan lewat WebSocket ke aplikasi React (Vite + Tailwind v4 + shadcn/ui) yang di-build ke `qa_agent/server/static/`. SQLite hanya indeks; evidence tetap di folder `runs/`. Rahasia lewat `SecretStore`.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, keyring, sqlite3 (stdlib), Playwright (CDP), pytest + httpx (TestClient); Node 24, React 19, TypeScript, Vite, Tailwind v4, shadcn/ui, TanStack Query, React Router, Phosphor icons, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-08-qa-agent-dashboard-web-design.md` (mockup: `docs/design/mockups/`)

## Global Constraints

- Server hanya bind `127.0.0.1`; port default `8787`, pakai port kosong berikutnya bila terpakai.
- Maksimal 2 run paralel (bisa diatur); dua run untuk aplikasi yang sama tidak boleh paralel.
- Frame live: JPEG, lebar maks 1280 px, sekitar 6 fps, hanya dikirim saat ada penonton.
- Folder data default `%USERPROFILE%\QA Agent\` (`--data-dir`), berisi `qa-agent.db`, `runs/`, `auth/`.
- Rahasia hanya lewat `SecretStore`; API tidak pernah mengembalikan nilai rahasia, hanya tersamar (`sk-••••3f9a`); tidak ada fallback teks biasa.
- Tema terang; aksen `#2560e8`; status pass `#1b8f5b`, fail `#cf3b36`, review `#a8760f`; font Geist + Geist Mono; ikon Phosphor; tanpa em dash di teks UI.
- Semua teks UI Bahasa Indonesia. Nilai status persis: `Pass`, `Fail`, `Perlu Review`, `Blocked`, `Skipped`.
- TDD: setiap task menulis test dulu, lihat gagal, baru implementasi. 216 test lama harus tetap lulus.
- Perintah test: `.venv/Scripts/python -m pytest ...` dan `npm --prefix web run test`.
- Setiap commit diakhiri `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Klien WebSocket tersambung ulang di tengah run harus menerima snapshot lalu stream, tanpa langkah hilang atau ganda (test di Task 10).
2. Perintah intervensi saat run tidak dalam kondisi yang cocok (input saat bukan ambil alih, Pikir ulang saat tidak dijeda, perintah ke run yang sudah selesai) ditolak 409 tanpa mengubah state (test di Task 3 dan Task 9).
3. Server restart saat ada run berjalan: run ditandai Terhenti dan bisa dilanjutkan (test di Task 8).
4. Editan Status Final dari dashboard saat `report.xlsx` terkunci tetap tersimpan di `review.json` dan UI menampilkan peringatan (test di Task 9).
5. Kotak overlay dan klik ambil alih pada layar live harus tetap tepat saat panel layar live diperkecil (koordinat ternormalisasi 0..1; test di Task 15).

## Struktur File

```
qa_agent/
  agent/control.py          # RunControl, ControlDecision, InterventionError
  agent/loop.py             # (ubah) titik kontrol + callback event + langkah manual
  orchestrator/deep.py      # (ubah) event tc.started/tc.finished, hasil Lewati/akhiri manual
  orchestrator/explore.py   # (ubah) event layar baru
  drivers/web.py            # (ubah) screencast CDP, manual_input
  models.py                 # (ubah) StepRecord.actor
  runtime.py                # (ubah) kredensial/API key eksplisit, control, on_event
  llm/factory.py            # (ubah) build_llm dengan api_key eksplisit
  report/pdf.py             # HTML → PDF via Chromium
  server/
    __init__.py
    app.py                  # create_app(settings) -> FastAPI
    settings.py             # ServerSettings (data_dir, port, max_parallel)
    secrets.py              # SecretStore, KeyringSecretStore, MemorySecretStore, mask_secret
    store.py                # Store (SQLite): apps, accounts, ai_profiles, runs, test_cases_index, stats
    events.py               # EventHub: snapshot + fan-out ke WebSocket, ref-count penonton
    runs.py                 # RunManager
    api/apps.py, api/profiles.py, api/runs.py, api/results.py, api/stats.py
    ws.py                   # /ws/runs/{id}, /ws/events
    static/                 # hasil build web/ (di-generate, di-gitignore kecuali .gitkeep)
  cli.py                    # (ubah) perintah serve
web/                        # React app (Vite)
  src/lib/api.ts, src/lib/ws.ts, src/lib/types.ts
  src/components/ (AppShell, StatusBadge, LiveView, InterventionPanel, ...)
  src/pages/ (Dashboard, RunNew, RunLive, RunResult, History, Apps, Settings)
tests/server/ (unit + integration), tests/e2e/test_dashboard_e2e.py
```

---

### Task 1: Dependency server & scaffold package

**Files:** Modify `pyproject.toml`; Create `qa_agent/server/__init__.py`, `qa_agent/server/settings.py`; Test `tests/server/__init__.py`, `tests/server/test_settings.py`

**Interfaces:**
- Produces: `ServerSettings(data_dir: Path, host="127.0.0.1", port=8787, max_parallel=2)` dengan property `db_path`, `runs_dir`, `auth_dir`; `default_data_dir() -> Path` (= `Path.home() / "QA Agent"`); `ServerSettings.ensure_dirs()`.

- [ ] Tambah dependency `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `keyring>=25`; dev: `httpx>=0.27`. Tambah `qa_agent = ["report/templates/*.j2", "server/static/**/*"]` di package-data. Install: `.venv/Scripts/python -m pip install -e ".[dev]"`.
- [ ] Test gagal `test_settings_paths` (data_dir tmp → `db_path == data_dir/"qa-agent.db"`, `runs_dir == data_dir/"runs"`, `auth_dir == data_dir/"auth"`, `ensure_dirs()` membuat ketiganya), `test_default_host_port` (`127.0.0.1`, `8787`, `max_parallel == 2`).
- [ ] Implementasi; jalankan `pytest tests/server/test_settings.py` → PASS; commit `chore: scaffold server dashboard`.

### Task 2: SecretStore

**Files:** Create `qa_agent/server/secrets.py`; Test `tests/server/test_secrets.py`

**Interfaces:**
- Produces: `class SecretStore(Protocol): get(key) -> str | None; set(key, value) -> None; delete(key) -> None`; `MemorySecretStore`; `KeyringSecretStore(service="qa-agent")`; `class SecretStoreUnavailable(Exception)`; `mask_secret(value: str | None) -> str` (`"sk-abcdef123456"` → `"sk-••••3456"`, string ≤ 4 karakter → `"••••"`, None → `""`).

- [ ] Test gagal: roundtrip Memory (set/get/delete, get kunci tak ada → None); `mask_secret` tiga kasus; `KeyringSecretStore` memakai backend keyring palsu (`keyring.set_keyring(...)` dengan backend in-memory di test) untuk roundtrip; backend `keyring.backends.fail.Keyring` → operasi melempar `SecretStoreUnavailable` (tidak ada fallback).
- [ ] Implementasi; PASS; commit `feat: SecretStore (keyring + memori) dan masking`.

### Task 3: RunControl (state intervensi)

**Files:** Create `qa_agent/agent/control.py`; Test `tests/unit/test_control.py`

**Interfaces:**
- Produces:
  - `class InterventionError(Exception)` (dipetakan ke HTTP 409).
  - `ControlState = Literal["running", "paused", "takeover", "stopped"]`.
  - `RunControl(confirm_each_step: bool = False)` thread-safe dengan method: `pause()`, `resume()`, `takeover()`, `release()` (kembali ke AI → paused lalu resume), `hint(text)`, `think_again()`, `skip()`, `stop()`, `end_case(status: Literal["pass","fail"], note="")`, `confirm_step()`, `queue_input(event: dict)`; properti `state`.
  - `RunControl.wait_before_decide(timeout=None) -> ControlDecision` dan `wait_before_execute(timeout=None) -> ControlDecision`, memblok selama `paused`/`takeover` (sambil mengembalikan input manual satu per satu), mengembalikan `ControlDecision(kind: Literal["continue","think_again","skip","stop","end_case","manual_input"], hints: list[str], input: dict | None, end_status: str | None, note: str)`.
  - `drain_hints() -> list[str]`.
- Aturan: `queue_input` saat bukan `takeover` → `InterventionError`; `think_again` saat bukan `paused` → `InterventionError`; `end_case` hanya saat `takeover`; perintah setelah `stop` → `InterventionError`; `confirm_each_step=True` membuat `wait_before_execute` memblok sampai `confirm_step()`.

- [ ] Test gagal (pakai thread pembantu + `threading.Event`, timeout kecil): pause memblok `wait_before_decide` sampai `resume`; hint terkumpul dan di-drain sekali; think_again saat paused → decision `think_again`; skip → `skip`; stop → `stop` dan perintah berikutnya InterventionError; takeover + queue_input → decision `manual_input` berurutan; end_case → `end_case` dengan status; confirm_each_step memblok sampai `confirm_step`; tiga kasus 409 (Review Focus #2).
- [ ] Implementasi dengan `threading.Condition`; PASS; commit `feat: RunControl untuk intervensi`.

### Task 4: AgentLoop memakai RunControl + event

**Files:** Modify `qa_agent/agent/loop.py`, `qa_agent/models.py`; Test `tests/unit/test_agent_loop_control.py`

**Interfaces:**
- Consumes: `RunControl` (Task 3).
- Produces:
  - `AgentLoop.__init__(..., control: RunControl | None = None, on_event: Callable[[dict], None] = lambda e: None)`.
  - `StepRecord.actor: Literal["ai","manual"] = "ai"`; aksi baru di log: `"hint"` (value = teks arahan) dan `"manual"`.
  - Event (dict dengan `type`): `step.planned {tc_id, step_no, action, element(role,name,bbox), thought, risk}`, `step.done {tc_id, step_no, result, screenshot}`, `signal {tc_id, signal}`.
  - Arahan masuk prompt sebagai bagian `## Arahan QA` (di atas Catatan sistem) dan berlaku sampai `run()` selesai.
  - `LoopOutcome.error_kind` nilai baru: `"skipped_by_qa"`, `"ended_by_qa"`; `LoopOutcome.status` diisi dari `end_case` untuk `"ended_by_qa"`.

- [ ] Test gagal dengan FakeDriver/FakeLLM: tanpa control perilaku lama tetap (jalankan ulang `tests/unit/test_agent_loop.py`); event `step.planned` dikirim sebelum `driver.execute` dan `step.done` sesudahnya (urutan dicatat); hint muncul di pesan AI berikutnya di bawah `## Arahan QA` dan tercatat sebagai StepRecord `action="hint"`; think_again tidak memanggil `execute` untuk rencana yang dibuang dan memanggil LLM lagi; skip → outcome `final="blocked"`, `error_kind="skipped_by_qa"`, reason `"Dilewati oleh QA"`; stop → `error_kind="interrupted"`; confirm_each_step memblok sampai konfirmasi.
- [ ] Implementasi: panggil `wait_before_decide` di awal iterasi dan `wait_before_execute` setelah parse aksi; PASS (test baru + semua test lama `tests/unit`); commit `feat: titik kontrol intervensi dan event di agent loop`.

### Task 5: Ambil alih (input manual) di WebDriver dan loop

**Files:** Modify `qa_agent/drivers/web.py`, `qa_agent/drivers/base.py`, `qa_agent/agent/loop.py`, `tests/fakes.py`; Test `tests/unit/test_agent_loop_takeover.py`, `tests/integration/test_web_manual_input.py`

**Interfaces:**
- Produces: `Driver.manual_input(event: dict) -> ActionResult` dengan event `{"kind": "click", "x": 0..1, "y": 0..1}`, `{"kind": "type", "text": str}`, `{"kind": "key", "key": "Enter"}`, `{"kind": "scroll", "dy": int}`; koordinat dikalikan ukuran viewport. Di loop: setiap input manual dieksekusi, dicatat StepRecord `actor="manual"`, `action="manual"`, value deskripsi singkat ("Klik di (0.42, 0.31)", teks diketik dimask), dengan screenshot; setelah `release()` AI menerima catatan "QA melakukan langkah manual: ..." di prompt berikutnya. `end_case` → outcome `ended_by_qa` dengan actual "Diverifikasi manual oleh QA" (+ note).
- Filter jaringan production tetap aktif untuk input manual (route context tidak berubah); guard kata kunci tidak dipanggil untuk input manual.

- [ ] Test gagal unit (FakeDriver merekam `manual_input`): urutan takeover → input → release → AI lanjut dengan catatan; end_case pass/fail; integration (aplikasi demo, browser): `click` ternormalisasi di tombol "Masuk" setelah `type` email+password lewat `manual_input` → login berhasil; production driver: klik manual "Proses Ulang" tetap tidak menulis (`demo.state.writes == []`).
- [ ] Implementasi; PASS; commit `feat: ambil alih manual dari layar live`.

### Task 6: Screencast CDP

**Files:** Modify `qa_agent/drivers/web.py`; Test `tests/integration/test_web_screencast.py`

**Interfaces:**
- Produces: `WebDriver.set_frame_sink(sink: Callable[[bytes, dict], None] | None)` (dict meta: `{"width": int, "height": int}`), `WebDriver.set_streaming(enabled: bool)`. Saat sink ada dan streaming aktif, `Page.startScreencast` (format jpeg, quality 60, maxWidth 1280, everyNthFrame sesuai ~6 fps) berjalan; frame di-ack; screencast dipasang ulang otomatis di `new_session`; `set_streaming(False)` menghentikannya.

- [ ] Test gagal: setelah login demo dan `set_streaming(True)`, dalam 3 detik menerima ≥ 2 frame yang diawali `b"\xff\xd8"` dan lebar ≤ 1280; setelah `new_session` frame tetap mengalir; `set_streaming(False)` → tidak ada frame baru dalam 1 detik.
- [ ] Implementasi lewat `context.new_cdp_session(page)`; PASS; commit `feat: screencast CDP untuk layar live`.

### Task 7: Store SQLite

**Files:** Create `qa_agent/server/store.py`; Test `tests/server/test_store.py`

**Interfaces:**
- Produces: `Store(db_path: Path)` dengan skema dibuat otomatis; dataclass/pydantic `AppRow(id, name, platform="web", url, allowed_domains: list[str], login_endpoints: list[str], default_profile_id: int | None)`, `AccountRow(id, app_id, role, username)`, `ProfileRow(id, name, provider, base_url, model, vision, timeout_seconds, is_default)`, `RunRow(id, app_id, mode, module, environment, profile_id, account_id, status, started_at, finished_at, folder, counts: dict[str,int], note)`, `CaseRow(run_id, tc_id, title, type, status_ai, status_final, severity)`.
  - CRUD: `create_app/get_app/list_apps/update_app/delete_app` (delete ditolak `ValueError` bila ada run), `create_account/list_accounts(app_id)/delete_account`, `create_profile/list_profiles/update_profile/delete_profile/get_default_profile` (hanya satu default).
  - Run: `create_run(...) -> RunRow`, `update_run(id, **fields)`, `get_run`, `list_runs(status=None, app_id=None, limit=50)`, `mark_unfinished_interrupted() -> int`.
  - `upsert_cases(run_id, cases: list[QaTestCase])`, `list_cases(run_id)`, `latest_findings(limit=10)`.
  - `stats(since: datetime, until: datetime) -> dict` dengan kunci `total_runs`, `web_runs`, `android_runs`, `cases_executed`, `findings`, `fail`, `review`, `pass_rate` (Pass / dieksekusi tanpa Skipped, 0..1), `pass_rate_prev` (periode sebelumnya sama panjang).
  - `import_run_folder(path: Path, app_id: int) -> RunRow` (membaca `run.json` + `testcases.json` folder CLI lama).

- [ ] Test gagal untuk tiap kelompok di atas, termasuk: default profile tunggal; delete app ber-run → ValueError; `mark_unfinished_interrupted` mengubah `running`/`queued` → `interrupted`; stats dengan data contoh (3 run web, 1 android; 10 case: 7 Pass, 2 Fail, 1 Skipped → `pass_rate == 7/9`); status final menggantikan status AI dalam hitungan findings; import folder dari `tests/report_fixtures.sample_run`.
- [ ] Implementasi dengan `sqlite3` (`check_same_thread=False` + lock); PASS; commit `feat: store SQLite untuk indeks dashboard`.

### Task 8: Runtime eksplisit + RunManager

**Files:** Modify `qa_agent/runtime.py`, `qa_agent/llm/factory.py`, `qa_agent/orchestrator/deep.py`, `qa_agent/orchestrator/explore.py`; Create `qa_agent/server/events.py`, `qa_agent/server/runs.py`; Test `tests/server/test_events.py`, `tests/server/test_runs.py`

**Interfaces:**
- `build_llm(cfg, api_key: str | None = None)` dan `build_runtime(..., credentials: Credentials | None = None, api_key: str | None = None, control: RunControl | None = None, on_event=None)`: bila diberikan, dipakai alih-alih membaca environment (CLI lama tetap jalan).
- DeepRunner/Explorer menerima `on_event`; event `tc.started {tc_id, title}`, `tc.finished {tc_id, status}`, `screen.added {url, module}`; `judge` memetakan `skipped_by_qa` → `("Blocked", None)` dengan ai_note "Dilewati oleh QA" dan `ended_by_qa` → `Pass`/`Fail` sesuai status QA.
- `EventHub`: `publish(run_id: int, event: dict)` (thread-safe, dipanggil dari worker), `snapshot(run_id) -> dict` (status, test case berjalan, langkah terakhir N=50, daftar test case + status), `subscribe(run_id) -> asyncio.Queue`, `unsubscribe`, `publish_frame(run_id, jpeg: bytes, meta)`, `viewer_count(run_id)`, callback `on_viewers_changed(run_id, count)`; topik global `"*"` untuk status run.
- `RunManager(store, secrets, hub, settings, llm_factory=None)`: `start() / shutdown()`; `submit(RunRequest) -> RunRow` dengan `RunRequest(app_id, mode: Literal["explore","deep"], module=None, prd_text=None, profile_id, account_id, environment, confirm_each_step=False)`; validasi (deep tanpa explore sebelumnya → `ValueError("Jalankan Seluruh aplikasi dulu")`); `control(run_id) -> RunControl`; `resume(run_id) -> RunRow`. Worker: bangun Config di memori dari baris DB + rahasia dari `SecretStore`, jalankan explore/deep, perbarui store (status, counts, `upsert_cases` saat tc.finished), tulis laporan di akhir (`build_reports`), LLMError/LoginFailed → status `paused` dengan note, exception lain → `interrupted`. Antrian global maks `settings.max_parallel`; per-aplikasi maks 1. `start()` memanggil `store.mark_unfinished_interrupted()`. `llm_factory` hanya untuk test.

- [ ] Test gagal events: snapshot setelah beberapa event; dua subscriber menerima event yang sama; viewer_count memicu callback.
- [ ] Test gagal runs (FakeLLM `DemoBrain` + aplikasi demo, marker browser): submit explore → status `queued` → `running` → `completed`, app_map tersimpan, event `screen.added` diterbitkan; submit deep setelah explore → 3 test case di `list_cases` dengan status `Pass`/`Perlu Review`/`Fail`; deep tanpa explore → ValueError; dua run aplikasi sama → yang kedua `queued` sampai pertama selesai; LLM error → `paused`, `resume` melanjutkan; `RunManager.start()` setelah ada baris `running` → `interrupted` (Review Focus #3); kredensial berasal dari `MemorySecretStore`, bukan environment.
- [ ] Implementasi; PASS + semua test lama; commit `feat: RunManager, EventHub, runtime eksplisit`.

### Task 9: REST API

**Files:** Create `qa_agent/server/app.py`, `qa_agent/server/api/*.py`, `qa_agent/report/pdf.py`; Test `tests/server/test_api_*.py`

**Interfaces:**
- `create_app(settings, *, secrets: SecretStore | None = None, llm_factory=None) -> FastAPI` (lifespan: Store, EventHub, RunManager start/shutdown; static dari `server/static` di `/` dengan fallback `index.html` untuk route SPA).
- Endpoint (JSON; error validasi 422 per field, intervensi tidak valid 409, tidak ditemukan 404):
  - `GET/POST /api/apps`, `GET/PATCH/DELETE /api/apps/{id}`, `GET/POST /api/apps/{id}/accounts` (body berisi `password` → disimpan ke SecretStore `account:{id}`), `DELETE /api/accounts/{id}`, `GET /api/apps/{id}/modules` (dari explore terakhir).
  - `GET/POST /api/profiles`, `PATCH/DELETE /api/profiles/{id}` (`api_key` hanya write; response memuat `api_key_masked`), `POST /api/profiles/{id}/models` (daftar model via `/v1/models`, fallback `[]` + pesan), `POST /api/profiles/{id}/test` (teks + gambar; `{text_ok, vision_ok, latency_ms, message}`).
  - `GET /api/runs?status=&app_id=`, `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/state` (snapshot), `POST /api/runs/{id}/control` body `{command: pause|resume|takeover|release|hint|think_again|skip|stop|end_case|confirm_step|input, text?, status?, note?, event?}`, `POST /api/runs/{id}/resume`.
  - `GET /api/runs/{id}/cases`, `GET /api/runs/{id}/cases/{tc_id}` (detail + langkah + URL screenshot), `PATCH /api/runs/{id}/cases/{tc_id}` `{status_final, severity, reviewer_note}` → tulis `review.json`, `build_reports`, `upsert_cases`; bila `ReportLockedError` → 200 dengan `{"warning": "Tutup report.xlsx di Excel..."}` dan review tetap tersimpan (Review Focus #4).
  - `GET /api/runs/{id}/files/{path}` (hanya di dalam folder run; path traversal → 404), `GET /api/runs/{id}/download/{kind}` untuk `xlsx|html|pdf` (`pdf` dibuat lewat `report/pdf.py: html_to_pdf(html_path: Path, pdf_path: Path) -> Path` memakai Chromium `page.pdf`, A4).
  - `GET /api/stats?days=30`, `GET /api/findings?limit=10`, `POST /api/import-runs` `{folder, app_id}`.

- [ ] Test gagal per router dengan `TestClient` + `MemorySecretStore` + `llm_factory` palsu: CRUD apps/akun/profil; API key/password tidak pernah ada di response (cek seluruh JSON); masking; validasi 422; kontrol 409 untuk input tanpa takeover dan perintah ke run selesai; review PATCH memperbarui status final + laporan; Excel terkunci (monkeypatch `Workbook.save` PermissionError) → warning + `review.json` tetap; path traversal `../../qa-agent.db` → 404; download pdf menghasilkan file diawali `%PDF`.
- [ ] Implementasi; PASS; commit `feat: REST API dashboard`.

### Task 10: WebSocket live

**Files:** Create `qa_agent/server/ws.py`; Modify `qa_agent/server/runs.py`; Test `tests/server/test_ws.py`

**Interfaces:**
- `/ws/runs/{id}`: saat tersambung kirim pesan teks `{"type":"snapshot", ...}`, lalu event JSON dan frame sebagai pesan biner (`b"F" + json_meta_len(4 byte) + meta + jpeg`). Menambah viewer → RunManager menyalakan `WebDriver.set_streaming(True)`; viewer 0 → `False`.
- `/ws/events`: event global `run.status {run_id, status, counts}`.
- Pesan dari klien diabaikan kecuali `{"type":"ping"}` (kontrol lewat REST).

- [ ] Test gagal: snapshot pertama lalu event; dua klien menerima event sama; klien putus lalu sambung ulang menerima snapshot yang memuat langkah terakhir tanpa duplikasi id langkah (Review Focus #1); viewer count naik/turun memanggil set_streaming (driver palsu); `/ws/events` menerima `run.status`.
- [ ] Implementasi; PASS; commit `feat: WebSocket event dan frame live`.

### Task 11: Perintah `qa-agent serve`

**Files:** Modify `qa_agent/cli.py`; Test `tests/unit/test_cli_serve.py`

**Interfaces:**
- `qa-agent serve [--data-dir PATH] [--port 8787] [--no-browser] [--max-parallel 2]`; `find_free_port(start: int, host="127.0.0.1") -> int`.

- [ ] Test gagal: `find_free_port` melewati port yang sedang dipakai socket test; `serve` memanggil `uvicorn.run` dengan host `127.0.0.1` dan port hasil `find_free_port` (monkeypatch uvicorn + webbrowser); `--no-browser` tidak membuka browser.
- [ ] Implementasi; PASS; commit `feat: perintah qa-agent serve`.

### Task 12: Scaffold frontend + tema + shell

**Files:** Create `web/` (Vite React TS), `web/src/styles.css` (token Tailwind v4 dari `docs/design/mockups/assets/theme.js`), `web/src/components/AppShell.tsx`, `web/src/components/StatusBadge.tsx`; Modify `.gitignore` (`web/node_modules/`, `qa_agent/server/static/*` kecuali `.gitkeep`); Test `web/src/components/*.test.tsx`

**Interfaces:**
- `npm --prefix web run build` menulis ke `qa_agent/server/static/`; `npm --prefix web run test` (Vitest + jsdom); proxy dev `/api` dan `/ws` ke `127.0.0.1:8787`.
- `AppShell` sidebar: Dashboard, Run baru, Riwayat run, Aplikasi, Perangkat (nonaktif, "segera"), Pengaturan; indikator profil AI di bawah.
- `StatusBadge({status})` warna sesuai Global Constraints.

- [ ] Install: Vite React TS, `tailwindcss @tailwindcss/vite`, shadcn/ui init (komponen: button, input, select, tabs, dialog, switch, textarea, table, toast), `@tanstack/react-query`, `react-router-dom`, `@phosphor-icons/react`, `vitest @testing-library/react @testing-library/user-event jsdom`.
- [ ] Test gagal: StatusBadge merender label dan kelas warna untuk 5 status + "Belum dijalankan"; AppShell menandai menu aktif sesuai route.
- [ ] Implementasi; `npm --prefix web run test` PASS; `npm --prefix web run build` menghasilkan `qa_agent/server/static/index.html`; commit `feat: scaffold frontend dashboard`.

### Task 13: Klien API, tipe, dan hook WebSocket

**Files:** Create `web/src/lib/types.ts`, `web/src/lib/api.ts`, `web/src/lib/ws.ts`; Test `web/src/lib/*.test.ts`

**Interfaces:**
- `api` berisi fungsi bertipe per endpoint Task 9 (mis. `listApps()`, `createRun(body)`, `control(runId, cmd)`, `patchCase(runId, tcId, body)`), error 409/422 dilempar sebagai `ApiError {status, detail, fieldErrors}`.
- `useRunStream(runId)` → `{snapshot, events, frame: {url, width, height} | null, connected}`; reconnect backoff 1s, 2s, 4s, maks 10s; frame biner diubah jadi object URL (URL lama di-revoke).
- `useGlobalEvents()` untuk status run.

- [ ] Test gagal: parsing frame biner (`F` + meta + jpeg); reconnect memanggil snapshot ulang dan tidak menggandakan langkah yang sama id-nya; ApiError membawa fieldErrors dari 422.
- [ ] Implementasi; PASS; commit `feat: klien API dan stream WebSocket`.

### Task 14: Halaman Pengaturan (Model AI, Akun test) dan Aplikasi

**Files:** Create `web/src/pages/Settings*.tsx`, `web/src/pages/Apps.tsx`; Test `*.test.tsx`

Mengikuti mockup `04-pengaturan-ai`. Tab Skill QA tampil nonaktif ("segera", sub-proyek 3).

- [ ] Test gagal (mock api): form profil memvalidasi base URL wajib untuk OpenAI-compatible; API key ditampilkan tersamar dan tombol Ganti membuka input kosong; Tes koneksi menampilkan hasil sukses/gagal; Ambil daftar model mengisi pilihan; form aplikasi + akun (password tidak pernah diisi ulang dari server).
- [ ] Implementasi; PASS; commit `feat: halaman pengaturan dan aplikasi`.

### Task 15: Run baru (Web) dan Run berjalan (layar live + intervensi)

**Files:** Create `web/src/pages/RunNew.tsx`, `web/src/pages/RunLive.tsx`, `web/src/components/LiveView.tsx`, `web/src/components/InterventionPanel.tsx`; Test `*.test.tsx`

Mengikuti mockup `01-run-baru-web` dan `03-run-berjalan` (+ opsi "Konfirmasi tiap langkah", tombol Pikir ulang, Akhiri test case Pass/Fail saat ambil alih, banner AI tidak merespons dengan Coba lagi).

**Interfaces:**
- `LiveView({frame, overlay: {bbox, viewport}, takeover, onInput})`: `toNormalized(clientX, clientY, rect) -> {x, y}` (0..1, dibatasi), overlay digambar dengan persentase dari bbox / ukuran viewport.

- [ ] Test gagal: "Satu modul" nonaktif dengan petunjuk bila aplikasi belum di-explore; submit mengirim body sesuai Task 9; `toNormalized` benar untuk panel ukuran berbeda (Review Focus #5); overlay posisi persentase; tombol intervensi aktif/nonaktif sesuai state (Pikir ulang hanya saat dijeda, input hanya saat ambil alih); klik di LiveView saat takeover memanggil `control(input click x,y)`; banner paused-by-LLM menampilkan Coba lagi.
- [ ] Implementasi; PASS; commit `feat: run baru dan layar live dengan intervensi`.

### Task 16: Hasil Run, Riwayat, Dashboard

**Files:** Create `web/src/pages/RunResult.tsx`, `web/src/pages/History.tsx`, `web/src/pages/Dashboard.tsx`; Test `*.test.tsx`

Mengikuti mockup `07-hasil-run` dan `05-dashboard`.

- [ ] Test gagal: filter Semua/Temuan/Belum direview; panel detail menampilkan expected/actual/bukti teknis/evidence; ubah Status Final memanggil PATCH dan menampilkan warning Excel terkunci bila ada; tombol unduh Excel/HTML/PDF menunjuk endpoint download; "Salin sebagai laporan bug (Jira)" menyalin teks berisi langkah reproduksi; Dashboard menampilkan angka dari `/api/stats`, kartu Sedang berjalan ter-update dari `useGlobalEvents`, tabel Selesai dengan tombol dokumen; state kosong dan loading (skeleton) untuk tiap daftar.
- [ ] Implementasi; PASS; commit `feat: hasil run, riwayat, dan dashboard`.

### Task 17: End-to-end dashboard

**Files:** Create `tests/e2e/__init__.py`, `tests/e2e/conftest.py`, `tests/e2e/test_dashboard_e2e.py`

**Interfaces:** fixture `dashboard(demo, tmp_path)` menjalankan `create_app(..., secrets=MemorySecretStore(), llm_factory=lambda profile: FakeLLM(DemoBrain()))` dengan uvicorn di thread pada port bebas dan build frontend yang sudah ada (`qa_agent/server/static/index.html` wajib ada; skip dengan pesan bila belum di-build).

- [ ] Test gagal (Playwright Python, marker browser): buat profil + aplikasi demo + akun lewat UI → Run seluruh aplikasi → frame live tampil (img src blob) → Jeda → status Dijeda → Arahkan agent → Lanjutkan → selesai → Run satu modul Pengguna → Hasil menampilkan 3 test case → ubah Status Final TC-PEN-002 menjadi Fail → unduh Excel (file ada dan sheet "Test Cases" berisi Fail).
- [ ] Implementasi fixture; PASS; jalankan seluruh suite `pytest` + `npm --prefix web run test`; commit `test: end-to-end dashboard`.

### Task 18: Dokumentasi & cek visual

**Files:** Modify `README.md`; Create `docs/design/screens/` (screenshot halaman nyata)

- [ ] Tambah bagian "Dashboard" di README: `qa-agent serve`, lokasi data, impor run lama, keamanan (localhost, Credential Manager).
- [ ] Ambil screenshot tiap halaman nyata (Dashboard, Run baru, Run berjalan, Hasil, Pengaturan) dengan data demo ke `docs/design/screens/`, bandingkan manual dengan mockup, perbaiki selisih yang mencolok.
- [ ] Verifikasi akhir: `pytest` (semua, termasuk 216 lama) dan `npm --prefix web run test` PASS; commit `docs: panduan dashboard dan screenshot`.
