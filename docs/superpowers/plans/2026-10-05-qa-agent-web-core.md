# QA Agent — Core + Web Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Membangun CLI Python `qa-agent` yang menjalankan AI sebagai QA automation untuk aplikasi web. Mode explore memetakan aplikasi, mode deep menyusun dan mengeksekusi test case per modul. Hasilnya `report.xlsx` + `report.html` lengkap dengan screenshot evidence.

**Architecture:** Agent loop dibuat sendiri (observe → think → guard → act → verify → record) di atas interface `Driver` yang platform-agnostic. Implementasi pertamanya `WebDriver` (Playwright). AI dipanggil lewat interface `LLMClient`, dengan implementasi endpoint OpenAI-compatible kantor (GLM), Claude, dan `FakeLLM` untuk test. Safety Guard, Evidence Store, dan Reporter tidak tahu platform yang sedang dites.

**Tech Stack:** Python 3.12, Playwright (sync API), openai SDK, anthropic SDK, Pydantic v2, Typer, PyYAML, python-dotenv, openpyxl, Jinja2, Pillow, pytest, Flask (khusus aplikasi demo untuk test).

**Spec:** `docs/superpowers/specs/2026-10-05-qa-agent-web-core-design.md`

## Global Constraints

- Python **3.11+** (rencana ini memakai 3.12). Platform utama Windows 11, dan path proyek mengandung spasi (`D:\IT PSD\Automation E2E QA`). Semua I/O file memakai `encoding="utf-8"` dan `pathlib`.
- Semua teks untuk pengguna (pesan CLI, prompt AI, laporan) dalam **Bahasa Indonesia**.
- Pesan CLI memakai penanda ASCII `[OK]` / `[GAGAL]` (jangan ✓/✗, supaya aman di console Windows).
- Rahasia hanya ada di `.env` (gitignored). Nilai password tidak pernah dikirim ke AI, ditulis ke log, atau masuk laporan. Tampilan masking: `••••••`. AI hanya memakai placeholder `{{username}}` / `{{password}}`.
- Default LLM: `provider: openai_compatible`, `base_url: http://192.168.151.121/v1`, `model: z-ai/glm-5.3-flash`, `api_key_env: OFFICE_AI_KEY`, `vision: true`, `timeout_seconds: 60`.
- Default batas: `max_steps_per_tc: 25`, `deep_max_tcs: 15`, `explore_max_screens: 60`, `explore_max_depth: 5`, `explore_max_minutes: 45`. Timeout aksi 15 detik.
- Nilai status persis: `Pass`, `Fail`, `Perlu Review`, `Blocked`, `Skipped`.
- Awalan data buatan AI: `QA-AUTO-<YYYYMMDD-HHMM>`.
- Folder run: `runs/YYYY-MM-DD_HHMM_<mode>_<slug>/`, di sebelah file config.
- Sesi login (`storage_state`) disimpan di `.qa-agent/auth/` dan **tidak pernah** di folder run.
- Mode `production`: semua request `POST`/`PUT`/`PATCH`/`DELETE` dibatalkan kecuali endpoint login.
- Retry LLM: 3× dengan jeda 2, 4, 8 detik.
- Perintah test: `.venv/Scripts/python -m pytest ...` (berjalan di PowerShell maupun Git Bash).
- Setiap pesan commit diakhiri baris `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **`report.xlsx` sedang dibuka di Excel** saat `qa-agent report` atau akhir run menulis ulang file. Windows mengunci file itu. Yang diharapkan: pesan jelas "tutup file di Excel" dan data run tidak hilang. → Test di Task 19 (`test_locked_workbook_raises_friendly_error`).
2. **Jawaban GLM yang "kotor"**: blok `<think>…</think>`, pembungkus ```` ```json ````, angka dikirim sebagai string (`"element": "3"`, `"value": 30`), atau konten kosong. Yang diharapkan: tetap terbaca, atau ditolak dengan pesan yang bisa dipakai untuk retry. → Test di Task 6.
3. **Nama modul diketik tidak persis**, misalnya `--module " pengguna "`. Yang diharapkan: tetap cocok dengan "Pengguna". Jika modul tidak ada, pesan error menyebut daftar modul yang tersedia. → Test di Task 17.
4. **Path dengan spasi dan teks non-ASCII** (nama modul "Manajemen Pengguna — Ä", isi langkah beremoji). Yang diharapkan: folder run, `steps.jsonl`, dan laporan tetap valid. → Test di Task 8.
5. **Sesi login kedaluwarsa di tengah test case** (terlempar ke halaman login). Yang diharapkan: login ulang tepat sekali lalu kembali ke halaman terakhir, tanpa loop tak berujung. → Test di Task 14 (`test_relogin_once_when_session_expires`).

## Catatan Implementasi terhadap Spec

Detail berikut diputuskan saat menyusun rencana. Semuanya konsisten dengan spec, tetapi lebih spesifik:

1. **Explore** menandai halaman sudah dikunjungi berdasarkan URL yang dinormalisasi (`/users/1/edit` = `/users/2/edit`). Fingerprint lengkap tetap dicatat dan dipakai untuk deteksi loop. Alasannya, hash elemen berubah mengikuti data di halaman, sehingga halaman yang sama bisa terkunjungi berkali-kali.
2. **Explore mencatat halaman login sebagai layar publik** (`ScreenInfo.public = True`). Dengan begitu modul autentikasi bisa dites dengan mode deep, menggunakan sesi bersih tanpa login.
3. **`LLMClient.chat(system, messages)`**: gambar dibawa di dalam `Message.images`, bukan parameter terpisah.
4. **Guard**: aturan kata kunci hanya berlaku untuk `click`/`select`, karena mengetik saja tidak mengubah data. Alur login dikecualikan dari aturan kata kunci (`login=True`), supaya tombol "Submit" di form login tidak terblok di production.
5. **Excel**: selain kolom Evidence (link ke screenshot), ada kolom terpisah "Laporan HTML" (link ke `report.html#TC-ID`).
6. **Selector stabil** seperti `role=button[name="Masuk"]` adalah **format rekaman** untuk replay (sub-proyek 5) dan tidak dieksekusi sekarang. Eksekusi memakai atribut `data-qa-idx` yang dipasang di setiap observasi.
7. **Langkah lama dibersihkan** sebelum sebuah test case dijalankan ulang (`RunStore.drop_steps`), sehingga `--resume` tidak menghasilkan langkah ganda.
8. **Aksi `done` dari AI** boleh menyertakan `severity` (Critical/Major/Minor) sebagai saran untuk sheet Temuan.

## Struktur File

```
pyproject.toml
README.md
examples/demo-app.yaml
docs/evaluation.md
qa_agent/
  __init__.py
  cli.py                     # Typer: init, check, explore, deep, run, report
  config.py                  # Config Pydantic + load_config + ConfigError
  models.py                  # semua model data bersama
  evidence.py                # RunStore, Masker, slugify, module_abbr, now_iso
  imaging.py                 # annotate (Set-of-Mark), highlight, to_jpeg, solid_png
  guard.py                   # Guard (aturan aksi + filter request production)
  runtime.py                 # StopFlag, Runtime, build_runtime, make_* factories
  templates.py               # template qa-agent.yaml & .env.example untuk `init`
  llm/
    __init__.py
    base.py                  # Message, LLMClient, error, with_retry
    openai_compat.py         # endpoint kantor
    anthropic_client.py      # Claude
    fake.py                  # FakeLLM
    factory.py               # build_llm(cfg)
  drivers/
    __init__.py
    base.py                  # Driver protocol, DriverCrashed
    web_dom.py               # JS ekstraksi elemen + build_selector + to_element
    web.py                   # WebDriver (Playwright)
  agent/
    __init__.py
    parser.py                # extract_json, parse_action, ActionParseError
    prompts.py               # prompt EXECUTE / EXPLORE_SCREEN / PLAN
    loop_detect.py           # LoopDetector
    loop.py                  # AgentLoop, LoopOutcome, find_same
  orchestrator/
    __init__.py
    fingerprint.py           # normalize_location, fingerprint
    auth.py                  # AuthManager, LoginFailed, auth_state_path
    explore.py               # Explorer
    deep.py                  # DeepPlanner, judge, goal_for, DeepRunner
  report/
    __init__.py
    humanize.py              # humanize(), signal_text()
    excel.py                 # report.xlsx, testcases.xlsx, baca review
    html.py                  # report.html
    build.py                 # import_review, build_reports
    templates/report.html.j2
tests/
  __init__.py
  conftest.py                # fixture demo_server / demo
  fakes.py                   # FakeDriver, el(), screen(), act(), PNG
  report_fixtures.py         # sample_run()
  demo_app/{__init__.py, app.py, __main__.py}
  unit/__init__.py + test_*.py
  integration/__init__.py + test_*.py + brain.py
```

**Urutan dependensi:** 1 → 2 → 3 → (4, 5, 6, 7, 8, 9 independen) → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 19 → 20 → 21 → 22 → 23 → 24.

---

### Task 1: Lingkungan & scaffold proyek

**Files:**
- Create: `pyproject.toml`
- Create: `qa_agent/__init__.py`, `qa_agent/llm/__init__.py`, `qa_agent/drivers/__init__.py`, `qa_agent/agent/__init__.py`, `qa_agent/orchestrator/__init__.py`, `qa_agent/report/__init__.py` (kosong kecuali `qa_agent/__init__.py`)
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` (kosong)
- Test: `tests/unit/test_smoke.py`

**Interfaces:**
- Produces: package `qa_agent` (`qa_agent.__version__ == "0.1.0"`), entry point `qa-agent = qa_agent.cli:app` (dibuat di Task 22), marker pytest `browser` dan `llm`.

- [ ] **Step 1: Pasang Python 3.12 (LANGKAH MANUAL OLEH PENGGUNA)**

Laptop masih memakai Python 3.9.13. Instalasi butuh persetujuan lisensi, jadi minta pengguna menjalankan sendiri di PowerShell:

```powershell
winget install -e --id Python.Python.3.12
```

Verifikasi:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" --version
```

Expected: `Python 3.12.x`

- [ ] **Step 2: Buat virtualenv**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.venv/Scripts/python --version
```

Expected: `Python 3.12.x`

- [ ] **Step 3: Tulis `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "qa-agent"
version = "0.1.0"
description = "AI QA automation agent untuk aplikasi web (self-hosted)"
requires-python = ">=3.11"
dependencies = [
  "playwright>=1.47",
  "openai>=1.40",
  "anthropic>=0.34",
  "pydantic>=2.7",
  "typer>=0.12",
  "pyyaml>=6.0",
  "python-dotenv>=1.0",
  "openpyxl>=3.1",
  "jinja2>=3.1",
  "pillow>=10.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "flask>=3.0"]

[project.scripts]
qa-agent = "qa_agent.cli:app"

[tool.setuptools.packages.find]
include = ["qa_agent*"]

[tool.setuptools.package-data]
qa_agent = ["report/templates/*.j2"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
  "browser: butuh Playwright Chromium + aplikasi demo",
  "llm: butuh endpoint AI sungguhan (dijalankan manual)",
]
addopts = "-m 'not llm'"
```

- [ ] **Step 4: Buat package skeleton**

`qa_agent/__init__.py`:

```python
"""QA Agent — AI QA automation untuk aplikasi web."""

__version__ = "0.1.0"
```

Buat file kosong: `qa_agent/llm/__init__.py`, `qa_agent/drivers/__init__.py`, `qa_agent/agent/__init__.py`, `qa_agent/orchestrator/__init__.py`, `qa_agent/report/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`.

- [ ] **Step 5: Tulis smoke test**

`tests/unit/test_smoke.py`:

```python
import qa_agent


def test_version():
    assert qa_agent.__version__ == "0.1.0"
```

- [ ] **Step 6: Install dependency + browser**

```powershell
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m playwright install chromium
```

Expected: instalasi selesai tanpa error. Chromium terunduh ke cache Playwright.

- [ ] **Step 7: Jalankan smoke test**

Run: `.venv/Scripts/python -m pytest tests/unit/test_smoke.py -v`
Expected: `1 passed`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml qa_agent tests
git commit -m "chore: scaffold proyek qa-agent (Python 3.12, pytest)"
```

---

### Task 2: Config

**Files:**
- Create: `qa_agent/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(Exception)`
  - `class Config(BaseModel)` dengan field `target: TargetCfg` (`platform`, `url`, `allowed_domains`, `login_endpoints`), `environment: Literal["dev","production"]`, `accounts: list[AccountCfg]` (`role`, `username_env`, `password_env`), `llm: LLMCfg` (`provider`, `base_url`, `model`, `api_key_env`, `vision`, `timeout_seconds`), `limits: LimitsCfg`, `guard: GuardCfg` (`extra_risky_keywords`), `browser: BrowserCfg` (`headless`, `viewport`, property `size -> tuple[int,int]`)
  - `Config.domains() -> list[str]`, `Config.credentials(role: str | None = None) -> Credentials` (`role`, `username`, `password`), `Config.api_key() -> str`
  - `load_config(path: Path, env_file: Path | None = None) -> Config`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_config.py`:

```python
import pytest

from qa_agent.config import ConfigError, load_config

YAML = """
target:
  url: https://app-dev.kantor.local/
accounts:
  - role: admin
    username_env: QA_ADMIN_USER
    password_env: QA_ADMIN_PASS
llm:
  base_url: http://192.168.151.121/v1
  model: z-ai/glm-5.3-flash
  api_key_env: OFFICE_AI_KEY
"""


def write(tmp_path, text=YAML):
    path = tmp_path / "qa-agent.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults(tmp_path):
    cfg = load_config(write(tmp_path), env_file=tmp_path / "tidak-ada.env")
    assert cfg.target.url == "https://app-dev.kantor.local"
    assert cfg.environment == "dev"
    assert cfg.llm.provider == "openai_compatible"
    assert cfg.llm.vision is True
    assert cfg.llm.timeout_seconds == 60
    assert cfg.limits.max_steps_per_tc == 25
    assert cfg.limits.deep_max_tcs == 15
    assert cfg.limits.explore_max_screens == 60
    assert cfg.limits.explore_max_depth == 5
    assert cfg.limits.explore_max_minutes == 45
    assert cfg.browser.headless is False
    assert cfg.browser.size == (1366, 768)
    assert cfg.domains() == ["app-dev.kantor.local"]


def test_credentials_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_ADMIN_USER", "qa@kantor.local")
    monkeypatch.setenv("QA_ADMIN_PASS", "s3cret!")
    cfg = load_config(write(tmp_path), env_file=tmp_path / "x.env")
    creds = cfg.credentials()
    assert (creds.role, creds.username, creds.password) == ("admin", "qa@kantor.local", "s3cret!")
    assert cfg.credentials("admin").username == "qa@kantor.local"


def test_unknown_role(tmp_path, monkeypatch):
    cfg = load_config(write(tmp_path), env_file=tmp_path / "x.env")
    with pytest.raises(ConfigError, match="operator"):
        cfg.credentials("operator")


def test_missing_env_var_names_the_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_ADMIN_USER", "qa@kantor.local")
    monkeypatch.setenv("QA_ADMIN_PASS", "")
    cfg = load_config(write(tmp_path), env_file=tmp_path / "x.env")
    with pytest.raises(ConfigError, match="QA_ADMIN_PASS"):
        cfg.credentials()


def test_env_file_is_loaded(tmp_path, monkeypatch):
    # setenv lalu delenv: monkeypatch mencatat "tidak ada" sehingga variabel dibersihkan setelah test
    monkeypatch.setenv("DOTENV_TEST_KEY", "x")
    monkeypatch.delenv("DOTENV_TEST_KEY")
    (tmp_path / ".env").write_text("DOTENV_TEST_KEY=abc123\n", encoding="utf-8")
    cfg = load_config(write(tmp_path, YAML.replace("OFFICE_AI_KEY", "DOTENV_TEST_KEY")))
    assert cfg.api_key() == "abc123"


def test_invalid_url(tmp_path):
    with pytest.raises(ConfigError, match="target.url"):
        load_config(write(tmp_path, YAML.replace("https://app-dev.kantor.local/", "app-dev")), env_file=tmp_path / "x.env")


def test_invalid_viewport(tmp_path):
    text = YAML + "browser:\n  viewport: besar\n"
    with pytest.raises(ConfigError, match="browser.viewport"):
        load_config(write(tmp_path, text), env_file=tmp_path / "x.env")


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="qa-agent init"):
        load_config(tmp_path / "tidak-ada.yaml")


def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError, match="YAML"):
        load_config(write(tmp_path, "target: [tidak ditutup"), env_file=tmp_path / "x.env")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'qa_agent.config'`

- [ ] **Step 3: Implementasi**

`qa_agent/config.py`:

```python
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigError(Exception):
    """Config tidak valid atau variabel lingkungan belum diisi."""


class TargetCfg(BaseModel):
    platform: Literal["web"] = "web"
    url: str
    allowed_domains: list[str] = Field(default_factory=list)
    login_endpoints: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _url_has_scheme(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("harus diawali http:// atau https://")
        return v.rstrip("/")


class AccountCfg(BaseModel):
    role: str
    username_env: str
    password_env: str


class LLMCfg(BaseModel):
    provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str | None = None
    model: str
    api_key_env: str
    vision: bool = True
    timeout_seconds: int = 60


class LimitsCfg(BaseModel):
    max_steps_per_tc: int = 25
    deep_max_tcs: int = 15
    explore_max_screens: int = 60
    explore_max_depth: int = 5
    explore_max_minutes: int = 45


class GuardCfg(BaseModel):
    extra_risky_keywords: list[str] = Field(default_factory=list)


class BrowserCfg(BaseModel):
    headless: bool = False
    viewport: str = "1366x768"

    @field_validator("viewport")
    @classmethod
    def _viewport_format(cls, v: str) -> str:
        if not re.fullmatch(r"\d+x\d+", v.strip().lower()):
            raise ValueError("format harus LEBARxTINGGI, contoh 1366x768")
        return v.strip().lower()

    @property
    def size(self) -> tuple[int, int]:
        width, height = self.viewport.split("x")
        return int(width), int(height)


class Credentials(BaseModel):
    role: str
    username: str
    password: str


class Config(BaseModel):
    target: TargetCfg
    environment: Literal["dev", "production"] = "dev"
    accounts: list[AccountCfg]
    llm: LLMCfg
    limits: LimitsCfg = Field(default_factory=LimitsCfg)
    guard: GuardCfg = Field(default_factory=GuardCfg)
    browser: BrowserCfg = Field(default_factory=BrowserCfg)

    @field_validator("accounts")
    @classmethod
    def _at_least_one_account(cls, v: list[AccountCfg]) -> list[AccountCfg]:
        if not v:
            raise ValueError("minimal satu akun")
        return v

    def domains(self) -> list[str]:
        return self.target.allowed_domains or [urlsplit(self.target.url).hostname or ""]

    def credentials(self, role: str | None = None) -> Credentials:
        if role is None:
            account = self.accounts[0]
        else:
            account = next((a for a in self.accounts if a.role == role), None)
            if account is None:
                raise ConfigError(f"Akun dengan role '{role}' tidak ada di config")
        return Credentials(
            role=account.role,
            username=_env(account.username_env),
            password=_env(account.password_env),
        )

    def api_key(self) -> str:
        return _env(self.llm.api_key_env)


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ConfigError(f"Variabel lingkungan {name} belum diisi (cek file .env)")
    return value


def load_config(path: Path, env_file: Path | None = None) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"File config {path} tidak ditemukan. Jalankan 'qa-agent init' dulu.")
    env_files = [env_file] if env_file else [Path.cwd() / ".env", path.parent / ".env"]
    for candidate in env_files:
        load_dotenv(candidate, override=False)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML tidak valid di {path}: {e}") from e
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        lines = [f"- {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise ConfigError("Config tidak valid:\n" + "\n".join(lines)) from e
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/config.py tests/unit/test_config.py
git commit -m "feat: config qa-agent.yaml + .env dengan validasi"
```

---

### Task 3: Model data bersama

**Files:**
- Create: `qa_agent/models.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces (dipakai hampir semua task berikutnya):
  - Konstanta: `STATUSES = ("Pass", "Fail", "Perlu Review", "Blocked", "Skipped")`, `TC_TYPES = ("positif", "negatif", "validasi", "boundary", "navigasi")`
  - `Element(index:int, role:str, name:str="", input_type:str|None, value:str|None, bbox:tuple[float,float,float,float], selector:str="", href:str|None, context:str="", frame:int=0)`
  - `Signal(kind: "console_error"|"page_error"|"http_error"|"ui_error"|"blocked_request", message:str, status:int|None, url:str|None, method:str|None)`
  - `Observation(location, title, elements, signals, screenshot_annotated: bytes, fingerprint)` + property `is_login_screen -> bool`
  - `Action(thought, action, element:int|None, value:str|None, expect, risk, status, actual, reason, severity)`
  - `ActionResult(ok:bool, error:str|None, fatal:bool=False)`
  - `GuardDecision(allowed:bool, risk, reason:str)`
  - `QaTestCase(id, module, page, title, type, priority, precondition, test_data, steps:list[str], expected, expected_source, start_url, status_ai, actual, ai_note, severity, status_final, reviewer_note)` + property `effective_status`
  - `StepRecord(tc_id, step_no, timestamp, location, fingerprint, thought, action:str, element:dict[str,str]|None, value, expect, guard:str="allowed", result:str="ok", signals, screenshot:str|None)`
  - `ScreenInfo(fingerprint, url, module, page_name, purpose, forms:list[dict], actions:list[str], screenshot, depth, parent, public:bool=False)`
  - `AppMap(target, screens)` + `modules() -> list[str]`, `find_module(name) -> str|None`, `screens_for(module) -> list[ScreenInfo]`
  - `RunMeta(mode, target, environment, model, started_at, finished_at, status, module, source_run, note)`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_models.py`:

```python
from qa_agent.models import (
    Action,
    AppMap,
    Element,
    Observation,
    QaTestCase,
    ScreenInfo,
    Signal,
    StepRecord,
)


def screen(module, url, public=False):
    return ScreenInfo(fingerprint=url + "|x", url=url, module=module, page_name=url, public=public)


def test_action_defaults():
    a = Action(action="click", element=2)
    assert a.risk == "low" and a.value is None and a.status is None


def test_observation_login_detection():
    login = Observation(location="http://a/login", elements=[Element(index=1, role="input", name="Password", input_type="password")])
    home = Observation(location="http://a/", elements=[Element(index=1, role="link", name="Home")])
    change_password = Observation(location="http://a/akun", elements=[
        Element(index=1, role="input", name="Password lama", input_type="password"),
        Element(index=2, role="input", name="Password baru", input_type="password"),
    ])
    assert login.is_login_screen is True
    assert home.is_login_screen is False
    assert change_password.is_login_screen is False


def test_app_map_modules_ordered_unique():
    m = AppMap(target="http://a", screens=[screen("Dashboard", "http://a/"), screen("Pengguna", "http://a/users"), screen("Pengguna", "http://a/users/new")])
    assert m.modules() == ["Dashboard", "Pengguna"]


def test_app_map_find_module_case_and_whitespace():
    m = AppMap(target="http://a", screens=[screen("Pengguna", "http://a/users")])
    assert m.find_module("  pengguna ") == "Pengguna"
    assert m.find_module("Laporan") is None
    assert [s.url for s in m.screens_for(" PENGGUNA")] == ["http://a/users"]
    assert m.screens_for("Laporan") == []


def test_testcase_effective_status():
    tc = QaTestCase(id="TC-1", module="M", title="T", expected="E", status_ai="Perlu Review")
    assert tc.effective_status == "Perlu Review"
    tc.status_final = "Fail"
    assert tc.effective_status == "Fail"


def test_step_record_roundtrip_unicode():
    rec = StepRecord(
        tc_id="TC-1", step_no=1, timestamp="2026-10-05T10:00:00", action="type",
        element={"role": "input", "name": "Nama — Ä", "selector": "#nama"}, value="Budi 😀",
        signals=[Signal(kind="http_error", message="HTTP 500", status=500, url="http://a/x", method="POST")],
    )
    back = StepRecord.model_validate_json(rec.model_dump_json())
    assert back == rec
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_models.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'qa_agent.models'`

- [ ] **Step 3: Implementasi**

`qa_agent/models.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Risk = Literal["low", "medium", "high"]
ActionType = Literal["click", "type", "select", "scroll", "back", "navigate", "wait", "done", "blocked"]
Status = Literal["Pass", "Fail", "Perlu Review", "Blocked", "Skipped"]
Severity = Literal["Critical", "Major", "Minor"]
TcType = Literal["positif", "negatif", "validasi", "boundary", "navigasi"]

STATUSES: tuple[str, ...] = ("Pass", "Fail", "Perlu Review", "Blocked", "Skipped")
TC_TYPES: tuple[str, ...] = ("positif", "negatif", "validasi", "boundary", "navigasi")


class Element(BaseModel):
    index: int
    role: str
    name: str = ""
    input_type: str | None = None
    value: str | None = None
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    selector: str = ""
    href: str | None = None
    context: str = ""
    frame: int = 0


class Signal(BaseModel):
    kind: Literal["console_error", "page_error", "http_error", "ui_error", "blocked_request"]
    message: str
    status: int | None = None
    url: str | None = None
    method: str | None = None


class Observation(BaseModel):
    location: str
    title: str = ""
    elements: list[Element] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    screenshot_annotated: bytes = b""
    fingerprint: str = ""

    @property
    def is_login_screen(self) -> bool:
        # Tepat satu field password. Halaman ganti password (2-3 field) tidak dianggap login.
        return sum(1 for e in self.elements if e.input_type == "password") == 1


class Action(BaseModel):
    thought: str = ""
    action: ActionType
    element: int | None = None
    value: str | None = None
    expect: str = ""
    risk: Risk = "low"
    status: Literal["pass", "fail"] | None = None
    actual: str | None = None
    reason: str | None = None
    severity: Severity | None = None


class ActionResult(BaseModel):
    ok: bool
    error: str | None = None
    fatal: bool = False


class GuardDecision(BaseModel):
    allowed: bool
    risk: Risk = "low"
    reason: str = ""


class QaTestCase(BaseModel):
    id: str
    module: str
    page: str = ""
    title: str
    type: TcType = "positif"
    priority: Literal["High", "Medium", "Low"] = "Medium"
    precondition: str = ""
    test_data: str = ""
    steps: list[str] = Field(default_factory=list)
    expected: str
    expected_source: Literal["PRD", "Inferensi AI"] = "Inferensi AI"
    start_url: str = ""
    status_ai: Status | None = None
    actual: str = ""
    ai_note: str = ""
    severity: Severity | None = None
    status_final: Status | None = None
    reviewer_note: str = ""

    @property
    def effective_status(self) -> str | None:
        return self.status_final or self.status_ai


class StepRecord(BaseModel):
    tc_id: str
    step_no: int
    timestamp: str
    location: str = ""
    fingerprint: str = ""
    thought: str = ""
    action: str
    element: dict[str, str] | None = None
    value: str | None = None
    expect: str = ""
    guard: str = "allowed"
    result: str = "ok"
    signals: list[Signal] = Field(default_factory=list)
    screenshot: str | None = None


class ScreenInfo(BaseModel):
    fingerprint: str
    url: str
    module: str
    page_name: str
    purpose: str = ""
    forms: list[dict] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    screenshot: str | None = None
    depth: int = 0
    parent: str | None = None
    public: bool = False


class AppMap(BaseModel):
    target: str
    screens: list[ScreenInfo] = Field(default_factory=list)

    def modules(self) -> list[str]:
        seen: list[str] = []
        for s in self.screens:
            if s.module not in seen:
                seen.append(s.module)
        return seen

    def find_module(self, name: str) -> str | None:
        wanted = " ".join(name.split()).lower()
        return next((m for m in self.modules() if m.lower() == wanted), None)

    def screens_for(self, module: str) -> list[ScreenInfo]:
        canonical = self.find_module(module)
        return [s for s in self.screens if s.module == canonical] if canonical else []


class RunMeta(BaseModel):
    mode: Literal["explore", "deep"]
    target: str
    environment: Literal["dev", "production"]
    model: str
    started_at: str
    finished_at: str | None = None
    status: Literal["running", "paused", "completed", "interrupted"] = "running"
    module: str | None = None
    source_run: str | None = None
    note: str = ""
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_models.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/models.py tests/unit/test_models.py
git commit -m "feat: model data bersama (observation, action, test case, app map)"
```

---

### Task 4: Fingerprint layar

**Files:**
- Create: `qa_agent/orchestrator/fingerprint.py`
- Test: `tests/unit/test_fingerprint.py`

**Interfaces:**
- Consumes: `Element` (Task 3)
- Produces: `normalize_location(location: str) -> str`, `fingerprint(location: str, elements: list[Element]) -> str` dengan format `"<host><path-normalisasi>|<hash8>"`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_fingerprint.py`:

```python
from qa_agent.models import Element
from qa_agent.orchestrator.fingerprint import fingerprint, normalize_location


def els(*names):
    return [Element(index=i, role="link", name=n) for i, n in enumerate(names, 1)]


def test_numeric_ids_normalized():
    assert normalize_location("https://App.test/users/123/edit") == "app.test/users/:id/edit"


def test_uuid_and_long_hex_normalized():
    assert normalize_location("https://a.test/o/3f2a1b4c-1d2e-4f3a-9b8c-0123456789ab") == "a.test/o/:id"
    assert normalize_location("https://a.test/doc/5f8d0d55b54764421b7156c3") == "a.test/doc/:id"


def test_query_dropped_and_trailing_slash():
    assert normalize_location("https://a.test/users/?page=2") == "a.test/users"
    assert normalize_location("https://a.test/") == "a.test/"


def test_hash_route_kept_and_normalized():
    assert normalize_location("https://a.test/#/users/7?x=1") == "a.test/#/users/:id"


def test_non_url_passthrough():
    assert normalize_location("MainActivity") == "MainActivity"


def test_fingerprint_order_insensitive():
    assert fingerprint("https://a.test/x", els("A", "B")) == fingerprint("https://a.test/x", els("B", "A"))


def test_fingerprint_changes_with_elements():
    assert fingerprint("https://a.test/x", els("A")) != fingerprint("https://a.test/x", els("A", "B"))


def test_fingerprint_format():
    fp = fingerprint("https://a.test/users/9", els("Edit"))
    loc, digest = fp.split("|")
    assert loc == "a.test/users/:id" and len(digest) == 8
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_fingerprint.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/orchestrator/fingerprint.py`:

```python
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from qa_agent.models import Element

_ID_SEGMENT = re.compile(
    r"^(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,})$",
    re.IGNORECASE,
)


def _normalize_path(path: str) -> str:
    segments = [":id" if _ID_SEGMENT.match(s) else s for s in path.split("/")]
    return "/".join(segments).rstrip("/") or "/"


def normalize_location(location: str) -> str:
    """URL → host + path dengan segmen ID diganti ':id'. Selain URL dikembalikan apa adanya."""
    parts = urlsplit(location)
    if not parts.scheme or not parts.netloc:
        return location
    out = f"{parts.netloc.lower()}{_normalize_path(parts.path)}"
    if parts.fragment.startswith("/"):
        out += "#" + _normalize_path(parts.fragment.split("?")[0])
    return out


def fingerprint(location: str, elements: list[Element]) -> str:
    names = sorted({f"{e.role}:{' '.join(e.name.lower().split())}" for e in elements})
    digest = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:8]
    return f"{normalize_location(location)}|{digest}"
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_fingerprint.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/orchestrator/fingerprint.py tests/unit/test_fingerprint.py
git commit -m "feat: normalisasi URL dan fingerprint layar"
```

---

### Task 5: Safety Guard

**Files:**
- Create: `qa_agent/guard.py`
- Test: `tests/unit/test_guard.py`

**Interfaces:**
- Consumes: `Action`, `Element`, `GuardDecision` (Task 3)
- Produces:
  - `RISKY_KEYWORDS: tuple[str, ...]`, `LOGOUT_KEYWORDS: tuple[str, ...]`
  - `class Guard(environment: str, allowed_domains: Iterable[str], *, extra_keywords=(), login_endpoints=())`
  - `Guard.production -> bool`
  - `Guard.is_allowed_url(url: str) -> bool`
  - `Guard.keyword_risk(element: Element | None) -> Risk`
  - `Guard.check(action, element, *, explore=False, allow_logout=False, login=False) -> GuardDecision`
  - `Guard.should_block_request(method: str, url: str) -> bool`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_guard.py`:

```python
from qa_agent.guard import Guard
from qa_agent.models import Action, Element

DEV = Guard("dev", ["app.test"])
PROD = Guard("production", ["app.test"])


def el(name, role="button", context="", href=None):
    return Element(index=1, role=role, name=name, context=context, href=href)


def click(risk="low"):
    return Action(action="click", element=1, risk=risk)


def test_dev_allows_risky_click():
    assert DEV.check(click(), el("Hapus")).allowed


def test_production_blocks_keyword():
    d = PROD.check(click(), el("Hapus Pengguna"))
    assert not d.allowed and d.risk == "high" and "production" in d.reason


def test_production_keyword_in_form_context():
    assert not PROD.check(click(), el("OK", context="Konfirmasi Transfer")).allowed


def test_keyword_whole_word_only():
    assert PROD.check(click(), el("Unsaved draft list")).allowed
    assert PROD.check(click(), el("Updated at")).allowed


def test_ai_cannot_downgrade_risk():
    assert not PROD.check(click(risk="low"), el("Simpan")).allowed


def test_ai_high_risk_blocks_without_keyword():
    assert not PROD.check(click(risk="high"), el("Proses")).allowed
    assert DEV.check(click(risk="high"), el("Proses")).allowed


def test_typing_is_not_keyword_checked():
    action = Action(action="type", element=1, value="catatan")
    assert PROD.check(action, el("Catatan", role="input", context="Update Profil")).allowed


def test_logout_blocked_unless_allowed():
    assert not DEV.check(click(), el("Keluar")).allowed
    assert not DEV.check(click(), el("Log out")).allowed
    assert DEV.check(click(), el("Keluar"), allow_logout=True).allowed


def test_external_link_blocked_subdomain_allowed():
    assert not DEV.check(click(), el("Docs", role="link", href="https://evil.example/x")).allowed
    assert DEV.check(click(), el("API", role="link", href="https://api.app.test/x")).allowed


def test_javascript_link_treated_as_same_page():
    assert DEV.check(click(), el("Tab", role="link", href="javascript:void(0)")).allowed


def test_mailto_link_blocked():
    assert not DEV.check(click(), el("Email kami", role="link", href="mailto:a@b.c")).allowed


def test_navigate_domain_check():
    assert not DEV.check(Action(action="navigate", value="https://other.test/"), None).allowed
    assert DEV.check(Action(action="navigate", value="/users"), None).allowed
    assert not DEV.check(Action(action="navigate", value=None), None).allowed


def test_explore_is_navigation_only():
    assert not DEV.check(Action(action="type", element=1, value="x"), el("Cari", role="input"), explore=True).allowed
    assert not DEV.check(click(), el("Hapus"), explore=True).allowed
    assert DEV.check(click(), el("Pengguna", role="link"), explore=True).allowed


def test_login_flow_skips_keyword_rule():
    assert PROD.check(click(), el("Submit"), login=True).allowed


def test_extra_keywords():
    g = Guard("production", ["app.test"], extra_keywords=["Arsipkan"])
    assert not g.check(click(), el("Arsipkan")).allowed


def test_should_block_request_production_only():
    assert PROD.should_block_request("POST", "https://app.test/api/users")
    assert PROD.should_block_request("delete", "https://app.test/api/users/1")
    assert not PROD.should_block_request("GET", "https://app.test/api/users")
    assert not PROD.should_block_request("POST", "https://app.test/login")
    assert not PROD.should_block_request("POST", "https://app.test/api/auth/token")
    assert not DEV.should_block_request("POST", "https://app.test/api/users")


def test_custom_login_endpoints_replace_heuristic():
    g = Guard("production", ["app.test"], login_endpoints=["/api/v2/masuk"])
    assert not g.should_block_request("POST", "https://app.test/api/v2/masuk")
    assert g.should_block_request("POST", "https://app.test/login")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_guard.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/guard.py`:

```python
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlsplit

from qa_agent.models import Action, Element, GuardDecision, Risk

RISKY_KEYWORDS: tuple[str, ...] = (
    "hapus", "delete", "remove", "bayar", "pay", "checkout", "kirim", "send", "submit",
    "simpan", "save", "update", "approve", "setujui", "reject", "tolak", "transfer",
    "nonaktifkan", "deactivate", "reset", "konfirmasi", "confirm", "upload", "import", "broadcast",
)
LOGOUT_KEYWORDS: tuple[str, ...] = ("logout", "log out", "sign out", "signout", "keluar")
LOGIN_SEGMENTS = {"login", "signin", "sign-in", "auth", "token", "session", "sessions"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _has_word(text: str, words: Iterable[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) for w in words)


def _blocked(reason: str, risk: Risk = "high") -> GuardDecision:
    return GuardDecision(allowed=False, risk=risk, reason=reason)


class Guard:
    def __init__(
        self,
        environment: str,
        allowed_domains: Iterable[str],
        *,
        extra_keywords: Iterable[str] = (),
        login_endpoints: Iterable[str] = (),
    ) -> None:
        self.environment = environment
        self.allowed_domains = [d.lower() for d in allowed_domains if d]
        self.keywords = RISKY_KEYWORDS + tuple(k.lower() for k in extra_keywords)
        self.login_endpoints = [e.lower() for e in login_endpoints]

    @property
    def production(self) -> bool:
        return self.environment == "production"

    def is_allowed_url(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme == "javascript":
            return True
        if not parts.scheme and not parts.netloc:
            return True  # URL relatif
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.allowed_domains)

    def keyword_risk(self, element: Element | None) -> Risk:
        if element is None:
            return "low"
        text = f"{element.name} {element.context}".lower()
        return "high" if _has_word(text, self.keywords) else "low"

    def _is_logout(self, element: Element) -> bool:
        href_path = urlsplit(element.href or "").path.lower()
        return _has_word(element.name.lower(), LOGOUT_KEYWORDS) or "logout" in href_path

    def check(
        self,
        action: Action,
        element: Element | None,
        *,
        explore: bool = False,
        allow_logout: bool = False,
        login: bool = False,
    ) -> GuardDecision:
        kind = action.action
        if kind == "navigate":
            if not action.value or not self.is_allowed_url(action.value):
                return _blocked(f"URL di luar domain yang diizinkan: {action.value}")
            return GuardDecision(allowed=True, risk=action.risk)

        if kind in ("click", "select") and element is not None:
            if element.href and not self.is_allowed_url(element.href):
                return _blocked("Link mengarah ke luar domain yang diizinkan")
            if not allow_logout and self._is_logout(element):
                return _blocked("Aksi logout diblok (test case ini bukan tentang logout)", "medium")

        keyword = self.keyword_risk(element) if kind in ("click", "select") and not login else "low"
        risk: Risk = max(keyword, action.risk, key=_RISK_ORDER.__getitem__)

        if explore:
            if kind in ("type", "select"):
                return _blocked("Mode explore hanya navigasi: tidak mengisi form", "medium")
            if kind == "click" and risk != "low":
                return _blocked("Mode explore tidak mengklik elemen berisiko", risk)

        if self.production and risk == "high":
            return _blocked("Mode production: aksi berisiko tinggi (mengubah data) diblok")
        return GuardDecision(allowed=True, risk=risk)

    def should_block_request(self, method: str, url: str) -> bool:
        if not self.production or method.upper() in SAFE_METHODS:
            return False
        path = urlsplit(url).path.lower()
        if self.login_endpoints:
            return not any(ep in path for ep in self.login_endpoints)
        segments = {s for s in path.split("/") if s}
        return not (segments & LOGIN_SEGMENTS)
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_guard.py -v`
Expected: `17 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/guard.py tests/unit/test_guard.py
git commit -m "feat: safety guard (kata kunci, domain, logout, explore, filter request production)"
```

---

### Task 6: Parser jawaban AI

**Files:**
- Create: `qa_agent/agent/parser.py`
- Test: `tests/unit/test_parser.py`

**Interfaces:**
- Consumes: `Action` (Task 3)
- Produces: `class ActionParseError(ValueError)`, `extract_json(text: str | None) -> dict`, `parse_action(text: str | None, element_count: int) -> Action`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_parser.py`:

```python
import pytest

from qa_agent.agent.parser import ActionParseError, extract_json, parse_action


def test_plain_json():
    a = parse_action('{"action": "click", "element": 2, "thought": "buka menu"}', 5)
    assert a.action == "click" and a.element == 2


def test_think_block_and_fence_are_stripped():
    text = '<think>pertimbangan panjang {"x": 1}</think>\nBerikut jawabannya:\n```json\n{"action": "type", "element": 1, "value": "abc"}\n```'
    a = parse_action(text, 3)
    assert a.action == "type" and a.value == "abc"


def test_numbers_as_strings_are_coerced():
    a = parse_action('{"action": "TYPE", "element": "3", "value": 30}', 3)
    assert a.action == "type" and a.element == 3 and a.value == "30"


def test_status_case_insensitive():
    a = parse_action('{"action": "done", "status": "PASS", "actual": "ok"}', 0)
    assert a.status == "pass"


def test_empty_reply():
    with pytest.raises(ActionParseError, match="kosong"):
        parse_action("", 3)
    with pytest.raises(ActionParseError, match="kosong"):
        parse_action(None, 3)


def test_no_json():
    with pytest.raises(ActionParseError, match="Tidak ada objek JSON"):
        parse_action("Saya akan klik tombol login", 3)


def test_broken_json():
    with pytest.raises(ActionParseError, match="JSON tidak valid"):
        parse_action('{"action": "click", "element": }', 3)


def test_unknown_action():
    with pytest.raises(ActionParseError, match="action"):
        parse_action('{"action": "hover", "element": 1}', 3)


def test_element_required_and_in_range():
    with pytest.raises(ActionParseError, match="wajib menyertakan nomor"):
        parse_action('{"action": "click"}', 3)
    with pytest.raises(ActionParseError, match="Elemen 9 tidak ada"):
        parse_action('{"action": "click", "element": 9}', 3)


def test_value_required():
    with pytest.raises(ActionParseError, match="value"):
        parse_action('{"action": "type", "element": 1}', 3)


def test_done_requires_status():
    with pytest.raises(ActionParseError, match="status"):
        parse_action('{"action": "done", "actual": "x"}', 3)


def test_scroll_defaults_down():
    assert parse_action('{"action": "scroll", "value": "kiri"}', 0).value == "down"


def test_extract_json_for_plan_objects():
    assert extract_json('```\n{"test_cases": []}\n```') == {"test_cases": []}
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_parser.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/agent/parser.py`:

```python
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from qa_agent.models import Action


class ActionParseError(ValueError):
    """Jawaban AI tidak bisa diubah menjadi aksi yang valid."""


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
NEEDS_ELEMENT = {"click", "type", "select"}
NEEDS_VALUE = {"type", "select", "navigate"}


def extract_json(text: str | None) -> dict:
    if not text or not text.strip():
        raise ActionParseError("Jawaban AI kosong")
    cleaned = _THINK.sub("", text)
    fence = _FENCE.search(cleaned)
    candidate = fence.group(1) if fence else cleaned
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ActionParseError("Tidak ada objek JSON di jawaban AI")
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as e:
        raise ActionParseError(f"JSON tidak valid: {e.msg} (posisi {e.pos})") from e
    if not isinstance(data, dict):
        raise ActionParseError("JSON harus berupa objek {...}")
    return data


def _coerce(data: dict) -> dict:
    for key in ("action", "status"):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip().lower()
    element = data.get("element")
    if isinstance(element, str) and element.strip().isdigit():
        data["element"] = int(element.strip())
    for key in ("value", "actual", "reason", "thought", "expect"):
        if data.get(key) is not None and not isinstance(data[key], str):
            data[key] = str(data[key])
    return data


def parse_action(text: str | None, element_count: int) -> Action:
    data = _coerce(extract_json(text))
    try:
        action = Action.model_validate(data)
    except ValidationError as e:
        err = e.errors()[0]
        field = ".".join(str(p) for p in err["loc"]) or "?"
        raise ActionParseError(f"Field '{field}': {err['msg']}") from e

    if action.action in NEEDS_ELEMENT:
        if action.element is None:
            raise ActionParseError(f"Aksi '{action.action}' wajib menyertakan nomor 'element'")
        if not 1 <= action.element <= element_count:
            raise ActionParseError(f"Elemen {action.element} tidak ada (pilih 1-{element_count})")
    if action.action in NEEDS_VALUE and action.value is None:
        raise ActionParseError(f"Aksi '{action.action}' wajib menyertakan 'value'")
    if action.action == "done" and action.status is None:
        raise ActionParseError("Aksi 'done' wajib menyertakan 'status' pass atau fail")
    if action.action == "scroll" and action.value not in ("up", "down"):
        action.value = "down"
    return action
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_parser.py -v`
Expected: `13 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/agent/parser.py tests/unit/test_parser.py
git commit -m "feat: parser jawaban AI (toleran think/fence/tipe angka)"
```

---

### Task 7: Lapisan LLM (endpoint kantor, Claude, Fake)

**Files:**
- Create: `qa_agent/llm/base.py`, `qa_agent/llm/openai_compat.py`, `qa_agent/llm/anthropic_client.py`, `qa_agent/llm/fake.py`, `qa_agent/llm/factory.py`
- Test: `tests/unit/test_llm.py`

**Interfaces:**
- Consumes: `Config`, `ConfigError` (Task 2)
- Produces:
  - `Message(role: "user"|"assistant", text: str, images: list[bytes] = [])` (dataclass)
  - `LLMError(Exception)`, `LLMTransientError(LLMError)`, `LLMUnavailable(LLMError)`
  - `LLMClient` Protocol: atribut `model: str`, `chat(system: str, messages: list[Message]) -> str`
  - `with_retry(fn, *, delays=(2, 4, 8), sleep=time.sleep)`, `image_media_type(data: bytes) -> str`
  - `OpenAICompatClient(*, model, api_key, base_url, timeout=60, vision=True, sleep=time.sleep, client=None)`
  - `AnthropicClient(*, model, api_key, timeout=60, vision=True, max_tokens=2048, sleep=time.sleep, client=None)`
  - `FakeLLM(responses: list[str] | Callable[[str, list[Message]], str])` dengan atribut `calls: list[tuple[str, list[Message]]]`
  - `build_llm(cfg: Config) -> LLMClient`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_llm.py`:

```python
from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest

from qa_agent.config import Config, ConfigError
from qa_agent.llm.anthropic_client import AnthropicClient
from qa_agent.llm.base import LLMError, LLMUnavailable, Message, image_media_type, with_retry, LLMTransientError
from qa_agent.llm.factory import build_llm
from qa_agent.llm.fake import FakeLLM
from qa_agent.llm.openai_compat import OpenAICompatClient

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 10
JPEG = b"\xff\xd8\xff" + b"0" * 10
REQ = httpx.Request("POST", "http://ai.test/v1/chat/completions")


def openai_stub(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_with_retry_retries_then_succeeds():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise LLMTransientError("timeout")
        return "ok"

    assert with_retry(fn, sleep=sleeps.append) == "ok"
    assert sleeps == [2, 4]


def test_with_retry_gives_up_after_three_retries():
    sleeps = []

    def fn():
        raise LLMTransientError("503")

    with pytest.raises(LLMUnavailable, match="4 percobaan"):
        with_retry(fn, sleep=sleeps.append)
    assert sleeps == [2, 4, 8]


def test_image_media_type():
    assert image_media_type(PNG) == "image/png"
    assert image_media_type(JPEG) == "image/jpeg"


def test_openai_builds_vision_payload():
    seen = {}

    def create(**kw):
        seen.update(kw)
        return reply('{"action": "back"}')

    client = OpenAICompatClient(model="z-ai/glm-5.3-flash", api_key="k", base_url="http://ai.test/v1", client=openai_stub(create))
    out = client.chat("SYS", [Message("user", "layar", images=[PNG])])
    assert out == '{"action": "back"}'
    assert seen["model"] == "z-ai/glm-5.3-flash"
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}
    parts = seen["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "layar"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_text_only_when_vision_disabled():
    seen = {}

    def create(**kw):
        seen.update(kw)
        return reply("x")

    client = OpenAICompatClient(model="m", api_key="k", base_url="http://ai.test/v1", vision=False, client=openai_stub(create))
    client.chat("SYS", [Message("user", "layar", images=[PNG])])
    assert seen["messages"][1] == {"role": "user", "content": "layar"}


def test_openai_connection_error_is_retried():
    attempts = []

    def create(**kw):
        attempts.append(1)
        if len(attempts) == 1:
            raise openai.APIConnectionError(request=REQ)
        return reply("pulih")

    client = OpenAICompatClient(model="m", api_key="k", base_url="http://ai.test/v1", sleep=lambda s: None, client=openai_stub(create))
    assert client.chat("SYS", [Message("user", "hi")]) == "pulih"
    assert len(attempts) == 2


def test_openai_none_content_becomes_empty_string():
    client = OpenAICompatClient(model="m", api_key="k", base_url="http://ai.test/v1", client=openai_stub(lambda **kw: reply(None)))
    assert client.chat("SYS", [Message("user", "hi")]) == ""


def test_anthropic_payload_and_text_join():
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ha"), SimpleNamespace(type="text", text="lo")])

    stub = SimpleNamespace(messages=SimpleNamespace(create=create))
    client = AnthropicClient(model="claude-sonnet-5-5", api_key="k", client=stub)
    assert client.chat("SYS", [Message("user", "layar", images=[PNG])]) == "halo"
    assert seen["system"] == "SYS"
    blocks = seen["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[-1] == {"type": "text", "text": "layar"}


def test_anthropic_connection_error_exhausts_to_unavailable():
    def create(**kw):
        raise anthropic.APIConnectionError(request=REQ)

    stub = SimpleNamespace(messages=SimpleNamespace(create=create))
    client = AnthropicClient(model="m", api_key="k", sleep=lambda s: None, client=stub)
    with pytest.raises(LLMUnavailable):
        client.chat("SYS", [Message("user", "hi")])


def test_fake_llm_list_and_callable():
    fake = FakeLLM(["a", "b"])
    assert fake.chat("s", [Message("user", "1")]) == "a"
    assert fake.chat("s", [Message("user", "2")]) == "b"
    with pytest.raises(LLMError, match="kehabisan"):
        fake.chat("s", [Message("user", "3")])
    assert len(fake.calls) == 3
    echo = FakeLLM(lambda system, messages: messages[-1].text.upper())
    assert echo.chat("s", [Message("user", "halo")]) == "HALO"


def cfg(**llm):
    base = {"model": "m", "api_key_env": "LLM_TEST_KEY"}
    return Config.model_validate({
        "target": {"url": "http://app.test"},
        "accounts": [{"role": "a", "username_env": "U", "password_env": "P"}],
        "llm": {**base, **llm},
    })


def test_factory(monkeypatch):
    monkeypatch.setenv("LLM_TEST_KEY", "k")
    assert isinstance(build_llm(cfg(base_url="http://ai.test/v1")), OpenAICompatClient)
    assert isinstance(build_llm(cfg(provider="anthropic")), AnthropicClient)
    with pytest.raises(ConfigError, match="base_url"):
        build_llm(cfg())
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_llm.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'qa_agent.llm.anthropic_client'`

- [ ] **Step 3: Implementasi `base.py`**

`qa_agent/llm/base.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol, TypeVar


@dataclass
class Message:
    role: Literal["user", "assistant"]
    text: str
    images: list[bytes] = field(default_factory=list)


class LLMError(Exception):
    """Kesalahan dari endpoint AI yang tidak bisa diulang (mis. API key salah)."""


class LLMTransientError(LLMError):
    """Kesalahan sementara: timeout, 5xx, rate limit."""


class LLMUnavailable(LLMError):
    """Endpoint AI tetap gagal setelah semua retry."""


class LLMClient(Protocol):
    model: str

    def chat(self, system: str, messages: list[Message]) -> str: ...


T = TypeVar("T")
RETRY_DELAYS: tuple[int, ...] = (2, 4, 8)


def with_retry(fn: Callable[[], T], *, delays: tuple[int, ...] = RETRY_DELAYS, sleep: Callable[[float], None] = time.sleep) -> T:
    last: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            return fn()
        except LLMTransientError as e:
            last = e
            if attempt < len(delays):
                sleep(delays[attempt])
    raise LLMUnavailable(f"Endpoint AI tidak merespons setelah {len(delays) + 1} percobaan: {last}") from last


def image_media_type(data: bytes) -> str:
    return "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
```

- [ ] **Step 4: Implementasi `openai_compat.py`**

`qa_agent/llm/openai_compat.py`:

```python
from __future__ import annotations

import base64
import time
from typing import Any

import openai

from qa_agent.llm.base import LLMError, LLMTransientError, Message, image_media_type, with_retry


class OpenAICompatClient:
    """Endpoint yang kompatibel dengan OpenAI Chat Completions (AI kantor: GLM, DeepSeek, MiniMax)."""

    def __init__(self, *, model: str, api_key: str, base_url: str, timeout: int = 60, vision: bool = True,
                 sleep=time.sleep, client: Any = None) -> None:
        self.model = model
        self.vision = vision
        self._sleep = sleep
        self._client = client or openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)

    def build_messages(self, system: str, messages: list[Message]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.images and self.vision and m.role == "user":
                parts: list[dict] = [{"type": "text", "text": m.text}]
                for img in m.images:
                    url = f"data:{image_media_type(img)};base64,{base64.b64encode(img).decode()}"
                    parts.append({"type": "image_url", "image_url": {"url": url}})
                out.append({"role": m.role, "content": parts})
            else:
                out.append({"role": m.role, "content": m.text})
        return out

    def chat(self, system: str, messages: list[Message]) -> str:
        payload = self.build_messages(system, messages)

        def call() -> str:
            try:
                resp = self._client.chat.completions.create(model=self.model, messages=payload, temperature=0.2)
            except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as e:
                raise LLMTransientError(str(e)) from e
            except openai.APIStatusError as e:
                if e.status_code >= 500:
                    raise LLMTransientError(str(e)) from e
                raise LLMError(f"Endpoint AI menolak request ({e.status_code}): {e.message}") from e
            if not resp.choices:
                raise LLMTransientError("Respons AI tanpa choices")
            return resp.choices[0].message.content or ""

        return with_retry(call, sleep=self._sleep)
```

- [ ] **Step 5: Implementasi `anthropic_client.py`**

`qa_agent/llm/anthropic_client.py`:

```python
from __future__ import annotations

import base64
import time
from typing import Any

import anthropic

from qa_agent.llm.base import LLMError, LLMTransientError, Message, image_media_type, with_retry


class AnthropicClient:
    """Claude lewat Anthropic Messages API (provider alternatif)."""

    def __init__(self, *, model: str, api_key: str, timeout: int = 60, vision: bool = True, max_tokens: int = 2048,
                 sleep=time.sleep, client: Any = None) -> None:
        self.model = model
        self.vision = vision
        self.max_tokens = max_tokens
        self._sleep = sleep
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)

    def build_messages(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            blocks: list[dict] = []
            if m.images and self.vision and m.role == "user":
                for img in m.images:
                    blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": image_media_type(img), "data": base64.b64encode(img).decode()},
                    })
            blocks.append({"type": "text", "text": m.text})
            out.append({"role": m.role, "content": blocks})
        return out

    def chat(self, system: str, messages: list[Message]) -> str:
        payload = self.build_messages(messages)

        def call() -> str:
            try:
                resp = self._client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system, messages=payload)
            except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as e:
                raise LLMTransientError(str(e)) from e
            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    raise LLMTransientError(str(e)) from e
                raise LLMError(f"Claude menolak request ({e.status_code}): {e.message}") from e
            return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")

        return with_retry(call, sleep=self._sleep)
```

- [ ] **Step 6: Implementasi `fake.py` dan `factory.py`**

`qa_agent/llm/fake.py`:

```python
from __future__ import annotations

from typing import Callable

from qa_agent.llm.base import LLMError, Message

Responder = Callable[[str, list[Message]], str]


class FakeLLM:
    """AI palsu untuk test: daftar jawaban terskrip atau fungsi (system, messages) -> str."""

    model = "fake"

    def __init__(self, responses: list[str] | Responder) -> None:
        self._responder: Responder | None = responses if callable(responses) else None
        self._queue: list[str] = [] if callable(responses) else list(responses)
        self.calls: list[tuple[str, list[Message]]] = []

    def chat(self, system: str, messages: list[Message]) -> str:
        self.calls.append((system, list(messages)))
        if self._responder is not None:
            return self._responder(system, messages)
        if not self._queue:
            raise LLMError("FakeLLM kehabisan jawaban terskrip")
        return self._queue.pop(0)
```

`qa_agent/llm/factory.py`:

```python
from __future__ import annotations

from qa_agent.config import Config, ConfigError
from qa_agent.llm.anthropic_client import AnthropicClient
from qa_agent.llm.base import LLMClient
from qa_agent.llm.openai_compat import OpenAICompatClient


def build_llm(cfg: Config) -> LLMClient:
    llm = cfg.llm
    if llm.provider == "anthropic":
        return AnthropicClient(model=llm.model, api_key=cfg.api_key(), timeout=llm.timeout_seconds, vision=llm.vision)
    if not llm.base_url:
        raise ConfigError("llm.base_url wajib diisi untuk provider openai_compatible")
    return OpenAICompatClient(model=llm.model, api_key=cfg.api_key(), base_url=llm.base_url,
                              timeout=llm.timeout_seconds, vision=llm.vision)
```

- [ ] **Step 7: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_llm.py -v`
Expected: `11 passed`

- [ ] **Step 8: Commit**

```bash
git add qa_agent/llm tests/unit/test_llm.py
git commit -m "feat: klien LLM (OpenAI-compatible kantor, Claude, Fake) dengan retry"
```

---

### Task 8: Evidence Store & masking

**Files:**
- Create: `qa_agent/evidence.py`
- Test: `tests/unit/test_evidence.py`

**Interfaces:**
- Consumes: `AppMap`, `QaTestCase`, `RunMeta`, `StepRecord` (Task 3)
- Produces:
  - `SECRET_MASK = "••••••"`, `slugify(text, max_len=40) -> str`, `module_abbr(module: str) -> str`, `now_iso() -> str`
  - `Masker(secrets: Iterable[str] = ())` dengan `.mask(text: str | None) -> str | None` (juga memask placeholder `{{password}}`)
  - `RunStore(root: Path)`; `RunStore.create(runs_dir, mode, label, now=None) -> RunStore`
  - path: `screenshots_dir`, `steps_path`, `testcases_path`, `app_map_path`, `meta_path`, `review_path`, `report_xlsx`, `report_html`, `cases_xlsx`
  - `save_screenshot(name, data) -> str` (path relatif `screenshots/<name>.png`), `append_step(rec)`, `read_steps()`, `drop_steps(tc_id)`, `write_meta/read_meta`, `write_testcases/read_testcases`, `write_app_map/read_app_map -> AppMap | None`, `write_review(dict)/read_review() -> dict`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_evidence.py`:

```python
from datetime import datetime

from qa_agent.evidence import Masker, RunStore, SECRET_MASK, module_abbr, slugify
from qa_agent.models import AppMap, QaTestCase, RunMeta, ScreenInfo, StepRecord


def step(tc, n, **kw):
    return StepRecord(tc_id=tc, step_no=n, timestamp="2026-10-05T10:00:00", action="click", **kw)


def test_slugify():
    assert slugify("Manajemen Pengguna — Ä") == "manajemen-pengguna-a"
    assert slugify("app-dev.kantor.local:8080") == "app-dev-kantor-local-8080"
    assert slugify("!!!") == "run"


def test_module_abbr():
    assert module_abbr("Pengguna") == "PEN"
    assert module_abbr("Manajemen User") == "MU"
    assert module_abbr("Laporan Keuangan Bulanan Tahunan Detail") == "LKBT"
    assert module_abbr("—") == "TC"


def test_create_names_and_collision(tmp_path):
    runs = tmp_path / "folder dengan spasi" / "runs"
    now = datetime(2026, 10, 5, 14, 30)
    a = RunStore.create(runs, "deep", "Manajemen Pengguna", now=now)
    b = RunStore.create(runs, "deep", "Manajemen Pengguna", now=now)
    assert a.root.name == "2026-10-05_1430_deep_manajemen-pengguna"
    assert b.root.name == "2026-10-05_1430_deep_manajemen-pengguna-2"
    assert a.screenshots_dir.is_dir()


def test_screenshot_relative_path(tmp_path):
    store = RunStore(tmp_path / "run")
    rel = store.save_screenshot("TC-1_step-01", b"png")
    assert rel == "screenshots/TC-1_step-01.png"
    assert (store.root / rel).read_bytes() == b"png"


def test_steps_roundtrip_unicode_and_truncated_line(tmp_path):
    store = RunStore(tmp_path / "run ä")
    store.append_step(step("TC-1", 1, value="Nama 😀 — Ä"))
    store.append_step(step("TC-1", 2))
    with store.steps_path.open("a", encoding="utf-8") as f:
        f.write('{"tc_id": "TC-1", "step_no": 3, "time')  # baris terpotong saat crash
    steps = store.read_steps()
    assert [s.step_no for s in steps] == [1, 2]
    assert steps[0].value == "Nama 😀 — Ä"


def test_drop_steps(tmp_path):
    store = RunStore(tmp_path / "run")
    store.append_step(step("TC-1", 1))
    store.append_step(step("TC-2", 1))
    store.append_step(step("TC-1", 2))
    store.drop_steps("TC-1")
    assert [(s.tc_id, s.step_no) for s in store.read_steps()] == [("TC-2", 1)]


def test_json_roundtrips(tmp_path):
    store = RunStore(tmp_path / "run")
    assert store.read_testcases() == [] and store.read_app_map() is None and store.read_review() == {}
    cases = [QaTestCase(id="TC-PEN-001", module="Pengguna", title="Tambah — valid", expected="Tersimpan")]
    store.write_testcases(cases)
    assert store.read_testcases() == cases
    app_map = AppMap(target="http://a", screens=[ScreenInfo(fingerprint="f", url="http://a/", module="Dashboard", page_name="Beranda")])
    store.write_app_map(app_map)
    assert store.read_app_map() == app_map
    meta = RunMeta(mode="deep", target="http://a", environment="dev", model="m", started_at="2026-10-05T10:00:00")
    store.write_meta(meta)
    assert store.read_meta() == meta
    store.write_review({"TC-PEN-001": {"status_final": "Fail", "reviewer_note": "cek"}})
    assert store.read_review()["TC-PEN-001"]["status_final"] == "Fail"


def test_masker():
    m = Masker(["s3cret!", ""])
    assert m.mask("password s3cret! salah") == f"password {SECRET_MASK} salah"
    assert m.mask("isi {{password}}") == f"isi {SECRET_MASK}"
    assert m.mask("{{username}}") == "{{username}}"
    assert m.mask(None) is None
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_evidence.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/evidence.py`:

```python
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Iterable

from qa_agent.models import AppMap, QaTestCase, RunMeta, StepRecord

SECRET_MASK = "••••••"
_SECRET_PLACEHOLDERS = ("{{password}}",)


def slugify(text: str, max_len: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_len].strip("-") or "run"


def module_abbr(module: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", module).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", ascii_text)
    if not words:
        return "TC"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:4]).upper()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Masker:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def mask(self, text: str | None) -> str | None:
        if text is None:
            return None
        for secret in (*self._secrets, *_SECRET_PLACEHOLDERS):
            text = text.replace(secret, SECRET_MASK)
        return text


class RunStore:
    """Satu folder run: screenshot, steps.jsonl, testcases.json, app_map.json, run.json, laporan."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, runs_dir: Path, mode: str, label: str, now: datetime | None = None) -> "RunStore":
        now = now or datetime.now()
        base = f"{now:%Y-%m-%d_%H%M}_{mode}_{slugify(label)}"
        root = Path(runs_dir) / base
        n = 2
        while root.exists():
            root = Path(runs_dir) / f"{base}-{n}"
            n += 1
        return cls(root)

    @property
    def screenshots_dir(self) -> Path:
        return self.root / "screenshots"

    @property
    def steps_path(self) -> Path:
        return self.root / "steps.jsonl"

    @property
    def testcases_path(self) -> Path:
        return self.root / "testcases.json"

    @property
    def app_map_path(self) -> Path:
        return self.root / "app_map.json"

    @property
    def meta_path(self) -> Path:
        return self.root / "run.json"

    @property
    def review_path(self) -> Path:
        return self.root / "review.json"

    @property
    def report_xlsx(self) -> Path:
        return self.root / "report.xlsx"

    @property
    def report_html(self) -> Path:
        return self.root / "report.html"

    @property
    def cases_xlsx(self) -> Path:
        return self.root / "testcases.xlsx"

    def save_screenshot(self, name: str, data: bytes) -> str:
        (self.screenshots_dir / f"{name}.png").write_bytes(data)
        return f"screenshots/{name}.png"

    def append_step(self, record: StepRecord) -> None:
        with self.steps_path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
            f.flush()
            os.fsync(f.fileno())

    def read_steps(self) -> list[StepRecord]:
        if not self.steps_path.exists():
            return []
        steps: list[StepRecord] = []
        for line in self.steps_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                steps.append(StepRecord.model_validate_json(line))
            except ValueError:
                continue  # baris terpotong karena proses berhenti di tengah penulisan
        return steps

    def drop_steps(self, tc_id: str) -> None:
        if not self.steps_path.exists():
            return
        kept = [s for s in self.read_steps() if s.tc_id != tc_id]
        self._write_text(self.steps_path, "".join(s.model_dump_json() + "\n" for s in kept))

    def _write_text(self, path: Path, text: str) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _write_json(self, path: Path, data: object) -> None:
        self._write_text(path, json.dumps(data, ensure_ascii=False, indent=2))

    def write_meta(self, meta: RunMeta) -> None:
        self._write_json(self.meta_path, meta.model_dump(mode="json"))

    def read_meta(self) -> RunMeta:
        return RunMeta.model_validate_json(self.meta_path.read_text(encoding="utf-8"))

    def write_testcases(self, cases: list[QaTestCase]) -> None:
        self._write_json(self.testcases_path, [c.model_dump(mode="json") for c in cases])

    def read_testcases(self) -> list[QaTestCase]:
        if not self.testcases_path.exists():
            return []
        return [QaTestCase.model_validate(c) for c in json.loads(self.testcases_path.read_text(encoding="utf-8"))]

    def write_app_map(self, app_map: AppMap) -> None:
        self._write_json(self.app_map_path, app_map.model_dump(mode="json"))

    def read_app_map(self) -> AppMap | None:
        if not self.app_map_path.exists():
            return None
        return AppMap.model_validate_json(self.app_map_path.read_text(encoding="utf-8"))

    def write_review(self, review: dict) -> None:
        self._write_json(self.review_path, review)

    def read_review(self) -> dict:
        if not self.review_path.exists():
            return {}
        return json.loads(self.review_path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_evidence.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/evidence.py tests/unit/test_evidence.py
git commit -m "feat: evidence store per run + masking rahasia"
```

---

### Task 9: Imaging (Set-of-Mark, highlight, JPEG)

**Files:**
- Create: `qa_agent/imaging.py`
- Test: `tests/unit/test_imaging.py`

**Interfaces:**
- Consumes: `Element` (Task 3)
- Produces: `annotate(png: bytes, elements: list[Element]) -> bytes`, `highlight(png: bytes, bbox) -> bytes`, `to_jpeg(data: bytes, max_width=1280, quality=70) -> bytes`, `solid_png(color: tuple[int,int,int], size: tuple[int,int]) -> bytes`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_imaging.py`:

```python
from io import BytesIO

from PIL import Image

from qa_agent.imaging import annotate, highlight, solid_png, to_jpeg
from qa_agent.models import Element


def pixel(data, xy):
    return Image.open(BytesIO(data)).convert("RGB").getpixel(xy)


def test_solid_png():
    data = solid_png((255, 255, 255), (40, 30))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(BytesIO(data)).size == (40, 30)


def test_annotate_draws_box_and_keeps_size():
    base = solid_png((255, 255, 255), (200, 100))
    out = annotate(base, [Element(index=1, role="button", name="A", bbox=(50, 40, 60, 30)), Element(index=2, role="link", name="B", bbox=(0, 0, 0, 0))])
    assert Image.open(BytesIO(out)).size == (200, 100)
    assert pixel(out, (50, 55)) != (255, 255, 255)  # garis kiri kotak
    assert pixel(out, (80, 55)) == (255, 255, 255)  # isi kotak tetap


def test_highlight_red_border():
    out = highlight(solid_png((255, 255, 255), (100, 100)), (20, 20, 40, 40))
    r, g, b = pixel(out, (20, 40))
    assert r > 200 and g < 80 and b < 80


def test_to_jpeg_resizes_wide_images():
    out = to_jpeg(solid_png((0, 128, 0), (2000, 1000)))
    assert out[:3] == b"\xff\xd8\xff"
    assert Image.open(BytesIO(out)).size == (1280, 640)


def test_to_jpeg_keeps_small_images():
    assert Image.open(BytesIO(to_jpeg(solid_png((0, 0, 0), (300, 200))))).size == (300, 200)
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_imaging.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/imaging.py`:

```python
from __future__ import annotations

from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from qa_agent.models import Element

_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#0f8a9d", "#c2185b", "#9a6324"]


def _open(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGB")


def _png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def solid_png(color: tuple[int, int, int], size: tuple[int, int]) -> bytes:
    return _png(Image.new("RGB", size, color))


def annotate(png: bytes, elements: list[Element]) -> bytes:
    """Gambar kotak bernomor (Set-of-Mark) di setiap elemen, khusus untuk AI."""
    img = _open(png)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for el in elements:
        x, y, w, h = el.bbox
        if w <= 0 or h <= 0:
            continue
        color = _COLORS[el.index % len(_COLORS)]
        draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
        label = str(el.index)
        _, _, tw, th = draw.textbbox((0, 0), label, font=font)
        ly = max(0, y - th - 4)
        draw.rectangle([x, ly, x + tw + 4, ly + th + 4], fill=color)
        draw.text((x + 2, ly + 2), label, fill="white", font=font)
    return _png(img)


def highlight(png: bytes, bbox: Sequence[float]) -> bytes:
    """Kotak merah di elemen yang diklik/diisi, untuk evidence."""
    img = _open(png)
    x, y, w, h = bbox
    if w > 0 and h > 0:
        ImageDraw.Draw(img).rectangle([x - 2, y - 2, x + w + 2, y + h + 2], outline=(220, 20, 20), width=3)
    return _png(img)


def to_jpeg(data: bytes, max_width: int = 1280, quality: int = 70) -> bytes:
    img = _open(data)
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_imaging.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/imaging.py tests/unit/test_imaging.py
git commit -m "feat: anotasi Set-of-Mark, highlight evidence, konversi JPEG"
```

---

### Task 10: Aplikasi demo dengan bug buatan

Aplikasi Flask kecil yang menjadi target semua integration test dan evaluasi manual. Kredensial demo adalah nilai test milik proyek ini, bukan kredensial asli.

**Files:**
- Create: `tests/demo_app/__init__.py` (kosong), `tests/demo_app/app.py`, `tests/demo_app/__main__.py`
- Create: `tests/conftest.py`
- Test: `tests/unit/test_demo_app.py`

**Interfaces:**
- Produces:
  - `DEMO_USER = "admin@demo.local"`, `DEMO_PASSWORD = "rahasia123"`
  - `create_app() -> Flask`, `DemoState` (`users`, `writes: list[str]`, `reset()`)
  - `DemoServer(host="127.0.0.1", port=0)` dengan `.url`, `.state`, `.start()`, `.stop()`, `.serve_forever()`
  - fixture pytest `demo_server` (session) dan `demo` (state di-reset per test)
- Halaman: `/login` (Email, Password, tombol "Masuk"), `/` (Dashboard), `/users` (link "Tambah Pengguna", tombol "Ekspor", link "Edit", tombol "Hapus"), `/users/new` dan `/users/<id>/edit` (Nama, Email, Umur, tombol "Simpan", link "Batal"), `/reports` (tombol "Proses Ulang"), tombol nav "Keluar".
- Bug buatan:
  1. Nama yang mengandung apostrof memicu HTTP 500.
  2. Format email tidak divalidasi.
  3. Tombol "Ekspor" tidak melakukan apa-apa.
- Endpoint test: `GET /__test__/writes`, `POST /__test__/reset`. Semua request selain GET (kecuali `/login` dan `/__test__/*`) dicatat di `state.writes`.

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_demo_app.py`:

```python
import pytest

from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER, create_app


@pytest.fixture
def client():
    app = create_app()
    c = app.test_client()
    c.state = app.config["STATE"]
    return c


def login(client):
    return client.post("/login", data={"email": DEMO_USER, "password": DEMO_PASSWORD})


def test_requires_login(client):
    resp = client.get("/users")
    assert resp.status_code == 302 and "/login?next=/users" in resp.headers["Location"]


def test_login_not_counted_as_write(client):
    assert login(client).status_code == 302
    assert client.state.writes == []


def test_wrong_password_shows_alert(client):
    resp = client.post("/login", data={"email": DEMO_USER, "password": "salah"})
    assert "Email atau password salah" in resp.get_data(as_text=True)


def test_create_user_valid(client):
    login(client)
    resp = client.post("/users", data={"name": "Andi", "email": "andi@demo.local", "age": "22"})
    assert resp.status_code == 302
    assert len(client.state.users) == 3
    assert client.state.writes == ["POST /users"]


def test_bug_invalid_email_accepted(client):
    login(client)
    assert client.post("/users", data={"name": "Andi", "email": "bukan-email", "age": "22"}).status_code == 302


def test_bug_apostrophe_returns_500(client):
    login(client)
    assert client.post("/users", data={"name": "O'Brien", "email": "o@demo.local", "age": "40"}).status_code == 500


def test_empty_name_validation(client):
    login(client)
    resp = client.post("/users", data={"name": "", "email": "x@demo.local", "age": "22"})
    assert resp.status_code == 400 and "Nama wajib diisi" in resp.get_data(as_text=True)


def test_reports_rebuild_counted_and_reset(client):
    login(client)
    client.post("/reports/rebuild")
    assert client.get("/__test__/writes").get_json()["count"] == 1
    client.post("/__test__/reset")
    assert client.state.writes == [] and len(client.state.users) == 2
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_demo_app.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'tests.demo_app'`

- [ ] **Step 3: Implementasi aplikasi demo**

`tests/demo_app/app.py`:

```python
"""Aplikasi web demo dengan 3 bug buatan, target integration test & evaluasi QA Agent."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from functools import wraps

from flask import Flask, abort, jsonify, redirect, render_template_string, request, session
from werkzeug.serving import make_server

DEMO_USER = "admin@demo.local"
DEMO_PASSWORD = "rahasia123"

LAYOUT = """<!doctype html>
<html lang="id"><head><meta charset="utf-8"><title>{{ title }} - Demo QA</title></head>
<body>
{% if logged_in %}
<nav aria-label="Menu utama">
  <a href="/">Dashboard</a>
  <a href="/users">Pengguna</a>
  <a href="/reports">Laporan</a>
  <form method="post" action="/logout" style="display:inline"><button type="submit">Keluar</button></form>
</nav>
{% endif %}
<main>{{ body|safe }}</main>
</body></html>"""

LOGIN = """<h1>Masuk</h1>
<form method="post">
  {% if error %}<div role="alert" class="error">{{ error }}</div>{% endif %}
  <p><label for="email">Email</label> <input id="email" name="email" type="text"></p>
  <p><label for="password">Password</label> <input id="password" name="password" type="password"></p>
  <button type="submit">Masuk</button>
</form>"""

DASHBOARD = """<h1>Dashboard</h1><p>Selamat datang di aplikasi demo QA.</p>"""

USERS = """<h1>Daftar Pengguna</h1>
<p><a href="/users/new">Tambah Pengguna</a> <button type="button">Ekspor</button></p>
<table>
  <tr><th>Nama</th><th>Email</th><th>Umur</th><th>Aksi</th></tr>
  {% for uid, u in users.items() %}
  <tr>
    <td>{{ u.name }}</td><td>{{ u.email }}</td><td>{{ u.age }}</td>
    <td><a href="/users/{{ uid }}/edit">Edit</a>
      <form method="post" action="/users/{{ uid }}/delete" style="display:inline"><button type="submit">Hapus</button></form></td>
  </tr>
  {% endfor %}
</table>"""

USER_FORM = """<form method="post" action="{{ action }}">
  <h2>{{ heading }}</h2>
  {% if error %}<div role="alert" class="error">{{ error }}</div>{% endif %}
  <p><label for="name">Nama</label> <input id="name" name="name" value="{{ user.name }}"></p>
  <p><label for="email">Email</label> <input id="email" name="email" value="{{ user.email }}"></p>
  <p><label for="age">Umur</label> <input id="age" name="age" value="{{ user.age }}"></p>
  <button type="submit">Simpan</button>
  <a href="/users">Batal</a>
</form>"""

REPORTS = """<h1>Laporan</h1>
<p>Ringkasan aktivitas pengguna.</p>
{% if done %}<p>Laporan sedang diproses ulang.</p>{% endif %}
<form method="post" action="/reports/rebuild"><button type="submit">Proses Ulang</button></form>"""

EMPTY_USER = {"name": "", "email": "", "age": ""}


@dataclass
class DemoState:
    users: dict[int, dict[str, str]] = field(default_factory=dict)
    next_id: int = 1
    writes: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.users = {
            1: {"name": "Budi Santoso", "email": "budi@demo.local", "age": "30"},
            2: {"name": "Siti Aminah", "email": "siti@demo.local", "age": "27"},
        }
        self.next_id = 3
        self.writes = []


def _validate(form) -> str:
    name = form.get("name", "").strip()
    if "'" in name:
        raise RuntimeError("Bug buatan #1: apostrof memicu error server")
    if not name:
        return "Nama wajib diisi"
    if not form.get("age", "").strip().isdigit():
        return "Umur harus angka"
    return ""  # Bug buatan #2: format email tidak divalidasi


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "demo-secret-key"
    state = DemoState()
    state.reset()
    app.config["STATE"] = state

    def page(title: str, body: str, **ctx):
        return render_template_string(LAYOUT, title=title, body=render_template_string(body, **ctx), logged_in="user" in session)

    def login_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect(f"/login?next={request.path}")
            return fn(*args, **kwargs)
        return wrapper

    @app.before_request
    def track_writes():
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.path != "/login" and not request.path.startswith("/__test__"):
            state.writes.append(f"{request.method} {request.path}")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            if request.form.get("email") == DEMO_USER and request.form.get("password") == DEMO_PASSWORD:
                session["user"] = DEMO_USER
                nxt = request.args.get("next", "/")
                return redirect(nxt if nxt.startswith("/") else "/")
            error = "Email atau password salah"
        return page("Masuk", LOGIN, error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    @login_required
    def dashboard():
        return page("Dashboard", DASHBOARD)

    @app.get("/users")
    @login_required
    def users():
        return page("Pengguna", USERS, users=state.users)

    @app.get("/users/new")
    @login_required
    def new_user():
        return page("Tambah Pengguna", USER_FORM, action="/users", heading="Tambah Pengguna", user=EMPTY_USER, error="")

    @app.post("/users")
    @login_required
    def create_user():
        error = _validate(request.form)
        data = {k: request.form.get(k, "").strip() for k in ("name", "email", "age")}
        if error:
            return page("Tambah Pengguna", USER_FORM, action="/users", heading="Tambah Pengguna", user=data, error=error), 400
        state.users[state.next_id] = data
        state.next_id += 1
        return redirect("/users")

    @app.get("/users/<int:uid>/edit")
    @login_required
    def edit_user(uid: int):
        user = state.users.get(uid)
        if user is None:
            abort(404)
        return page("Edit Pengguna", USER_FORM, action=f"/users/{uid}", heading="Edit Pengguna", user=user, error="")

    @app.post("/users/<int:uid>")
    @login_required
    def update_user(uid: int):
        if uid not in state.users:
            abort(404)
        error = _validate(request.form)
        data = {k: request.form.get(k, "").strip() for k in ("name", "email", "age")}
        if error:
            return page("Edit Pengguna", USER_FORM, action=f"/users/{uid}", heading="Edit Pengguna", user=data, error=error), 400
        state.users[uid] = data
        return redirect("/users")

    @app.post("/users/<int:uid>/delete")
    @login_required
    def delete_user(uid: int):
        state.users.pop(uid, None)
        return redirect("/users")

    @app.get("/reports")
    @login_required
    def reports():
        return page("Laporan", REPORTS, done=request.args.get("done") == "1")

    @app.post("/reports/rebuild")
    @login_required
    def rebuild_reports():
        return redirect("/reports?done=1")

    @app.get("/__test__/writes")
    def test_writes():
        return jsonify(count=len(state.writes), requests=state.writes)

    @app.post("/__test__/reset")
    def test_reset():
        state.reset()
        return jsonify(ok=True)

    return app


class DemoServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.app = create_app()
        self._server = make_server(host, port, self.app, threaded=True)
        self.url = f"http://{host}:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def state(self) -> DemoState:
        return self.app.config["STATE"]

    def start(self) -> "DemoServer":
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def stop(self) -> None:
        self._server.shutdown()
```

`tests/demo_app/__main__.py`:

```python
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER, DemoServer


def main() -> None:
    server = DemoServer(port=5055)
    print(f"Aplikasi demo berjalan di {server.url}")
    print(f"Akun test: {DEMO_USER} / {DEMO_PASSWORD}")
    print("Tekan Ctrl+C untuk berhenti.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

`tests/conftest.py`:

```python
import pytest

from tests.demo_app.app import DemoServer


@pytest.fixture(scope="session")
def demo_server():
    server = DemoServer().start()
    yield server
    server.stop()


@pytest.fixture
def demo(demo_server):
    demo_server.state.reset()
    return demo_server
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_demo_app.py -v`
Expected: `8 passed` (log traceback `RuntimeError: Bug buatan #1` di stderr itu wajar)

- [ ] **Step 5: Commit**

```bash
git add tests/demo_app tests/conftest.py tests/unit/test_demo_app.py
git commit -m "test: aplikasi demo Flask dengan 3 bug buatan"
```

---

### Task 11: WebDriver — sesi, observasi, sinyal

**Files:**
- Create: `qa_agent/drivers/base.py`, `qa_agent/drivers/web_dom.py`, `qa_agent/drivers/web.py`
- Create: `tests/integration/helpers.py`
- Test: `tests/unit/test_web_dom.py`, `tests/integration/test_web_observe.py`

**Interfaces:**
- Consumes: `Element`, `Observation`, `Signal`, `Action`, `ActionResult` (Task 3), `fingerprint` (Task 4), `imaging.annotate/highlight` (Task 9)
- Produces:
  - `class DriverCrashed(Exception)`; `Driver` Protocol: `start()`, `stop()`, `new_session(auth_state: Path | None)`, `save_auth_state(path)`, `goto(location)`, property `current_url`, `observe() -> Observation`, `execute(action, element) -> ActionResult`, `screenshot(highlight: Element | None = None) -> bytes`, `set_credentials(username, password)`
  - `web_dom.EXTRACT_JS`, `web_dom.UI_ERROR_JS`, `web_dom.build_selector(raw: dict) -> str`, `web_dom.to_element(raw, frame_index, offset) -> Element`
  - `WebDriver(base_url, *, headless=False, viewport=(1366, 768), request_filter=None, max_elements=80, action_timeout_ms=15000, navigation_timeout_ms=30000)` dengan atribut `blocked_requests: list[str]` dan property `page` (Playwright Page, untuk test)
  - `execute()` dan `set_credentials()` diimplementasikan di Task 12

- [ ] **Step 1: Tulis unit test `web_dom` yang gagal**

`tests/unit/test_web_dom.py`:

```python
from qa_agent.drivers.web_dom import build_selector, to_element


def raw(**kw):
    base = {"index": 1, "role": "button", "name": "Simpan", "input_type": None, "value": None, "bbox": [10, 20, 30, 40],
            "testid": "", "testid_attr": "", "id": "", "href": None, "context": "", "css": "form > button", "tag": "button"}
    base.update(kw)
    return base


def test_testid_wins():
    assert build_selector(raw(testid="save-btn", testid_attr="data-testid", id="x")) == '[data-testid="save-btn"]'


def test_stable_id_used():
    assert build_selector(raw(id="email")) == '[id="email"]'


def test_auto_generated_id_skipped():
    assert build_selector(raw(id="input-12345")) == 'role=button[name="Simpan"]'
    assert build_selector(raw(id=":r3:")) == 'role=button[name="Simpan"]'


def test_role_mapping_and_quote_escape():
    assert build_selector(raw(role="input", name='Kata "kunci"')) == 'role=textbox[name="Kata \\"kunci\\""]'
    assert build_selector(raw(role="select", name="Kota")) == 'role=combobox[name="Kota"]'


def test_css_fallback():
    assert build_selector(raw(name="")) == "form > button"


def test_to_element_applies_frame_offset():
    e = to_element(raw(href="", input_type=""), 1, (100.0, 50.0))
    assert e.bbox == (110.0, 70.0, 30, 40)
    assert e.frame == 1 and e.href is None and e.input_type is None
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_web_dom.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi `drivers/base.py` dan `drivers/web_dom.py`**

`qa_agent/drivers/base.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from qa_agent.models import Action, ActionResult, Element, Observation


class DriverCrashed(Exception):
    """Browser/device tertutup atau tidak bisa dipakai lagi."""


class Driver(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def new_session(self, auth_state: Path | None = None) -> None: ...
    def save_auth_state(self, path: Path) -> None: ...
    def goto(self, location: str) -> None: ...
    @property
    def current_url(self) -> str: ...
    def observe(self) -> Observation: ...
    def execute(self, action: Action, element: Element | None) -> ActionResult: ...
    def screenshot(self, highlight: Element | None = None) -> bytes: ...
    def set_credentials(self, username: str, password: str) -> None: ...
```

`qa_agent/drivers/web_dom.py`:

```python
"""Ekstraksi elemen interaktif dari DOM (dijalankan di halaman lewat Playwright)."""
from __future__ import annotations

import re

from qa_agent.models import Element

EXTRACT_JS = r"""
([maxElements, startIndex]) => {
  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=tab], ' +
    '[role=menuitem], [role=checkbox], [role=radio], [role=combobox], [onclick], [contenteditable=""], [contenteditable=true]';
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const cssPath = (el) => {
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 6) {
      let s = el.tagName.toLowerCase();
      if (el.id && !/\d{3,}/.test(el.id)) { parts.unshift(s + '#' + CSS.escape(el.id)); break; }
      const p = el.parentElement;
      if (p) {
        const same = Array.from(p.children).filter(c => c.tagName === el.tagName);
        if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
      }
      parts.unshift(s);
      el = p;
    }
    return parts.join(' > ');
  };
  document.querySelectorAll('[data-qa-idx]').forEach(e => e.removeAttribute('data-qa-idx'));
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    if (out.length >= maxElements) break;
    if (el.disabled || el.closest('[aria-hidden=true]')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    let role = el.getAttribute('role');
    if (!role) {
      if (tag === 'a') role = 'link';
      else if (tag === 'select') role = 'select';
      else if (tag === 'textarea') role = 'textarea';
      else if (tag === 'input') role = ['submit', 'button', 'reset', 'image'].includes(type) ? 'button'
        : (['checkbox', 'radio'].includes(type) ? type : 'input');
      else role = 'button';
    }
    const labelFor = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
    const wrapLabel = el.closest('label');
    let name = el.getAttribute('aria-label') || (labelFor && labelFor.innerText) || '';
    if (!name && ['input', 'select', 'textarea'].includes(tag)) name = (wrapLabel && wrapLabel.innerText) || el.getAttribute('placeholder') || '';
    if (!name && tag === 'input' && ['submit', 'button', 'reset'].includes(type)) name = el.value;
    if (!name) name = el.innerText || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('name') || '';
    let value = null;
    if (tag === 'input' && ['checkbox', 'radio'].includes(type)) value = el.checked ? 'checked' : 'unchecked';
    else if (tag === 'input' && !['submit', 'button', 'reset', 'image'].includes(type)) value = type === 'password' ? (el.value ? '******' : '') : el.value;
    else if (tag === 'textarea') value = el.value;
    else if (tag === 'select') value = el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '';
    let context = '';
    const box = el.closest('form, dialog, [role=dialog], [role=alertdialog], fieldset');
    if (box) {
      const h = box.querySelector('h1, h2, h3, h4, legend');
      context = (h && h.innerText) || box.getAttribute('aria-label') || '';
      if (!context) {
        const prev = box.previousElementSibling;
        if (prev && /^H[1-4]$/.test(prev.tagName)) context = prev.innerText;
      }
    }
    const testidAttr = el.hasAttribute('data-testid') ? 'data-testid' : (el.hasAttribute('data-test') ? 'data-test' : '');
    const index = startIndex + out.length;
    el.setAttribute('data-qa-idx', String(index));
    out.push({
      index, role, name: clean(name), input_type: type || null, value,
      bbox: [r.x, r.y, r.width, r.height],
      testid: testidAttr ? el.getAttribute(testidAttr) : '', testid_attr: testidAttr, id: el.id || '',
      href: tag === 'a' ? el.href : null, context: clean(context), css: cssPath(el), tag,
    });
  }
  return out;
}
"""

UI_ERROR_JS = r"""
() => Array.from(document.querySelectorAll('[role=alert], .alert-danger, .alert-error, .error, .toast-error, .invalid-feedback, .text-danger'))
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())
  .filter(t => t)
  .slice(0, 5)
"""

_AUTO_ID = re.compile(r"\d{3,}|^:r|^(ember|ext-|mui-|react-|radix-|headlessui-)", re.IGNORECASE)
_PLAYWRIGHT_ROLE = {"input": "textbox", "textarea": "textbox", "select": "combobox"}


def _quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_selector(raw: dict) -> str:
    """Selector stabil untuk direkam (format replay). Eksekusi sekarang memakai data-qa-idx."""
    if raw.get("testid"):
        return f'[{raw["testid_attr"]}="{_quote(raw["testid"])}"]'
    element_id = raw.get("id") or ""
    if element_id and not _AUTO_ID.search(element_id):
        return f'[id="{_quote(element_id)}"]'
    name = raw.get("name") or ""
    if name:
        role = _PLAYWRIGHT_ROLE.get(raw["role"], raw["role"])
        return f'role={role}[name="{_quote(name)}"]'
    return raw.get("css") or raw.get("tag") or "*"


def to_element(raw: dict, frame_index: int, offset: tuple[float, float]) -> Element:
    x, y, w, h = raw["bbox"]
    ox, oy = offset
    return Element(
        index=raw["index"],
        role=raw["role"],
        name=raw.get("name") or "",
        input_type=raw.get("input_type") or None,
        value=raw.get("value"),
        bbox=(x + ox, y + oy, w, h),
        selector=build_selector(raw),
        href=raw.get("href") or None,
        context=raw.get("context") or "",
        frame=frame_index,
    )
```

- [ ] **Step 4: Jalankan unit test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_web_dom.py -v`
Expected: `6 passed`

- [ ] **Step 5: Tulis integration test observasi yang gagal**

`tests/integration/helpers.py`:

```python
from qa_agent.models import Element, Observation
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER


def find(obs: Observation, role: str, name: str) -> Element:
    for e in obs.elements:
        if e.role == role and e.name == name:
            return e
    raise AssertionError(f"{role} '{name}' tidak ada. Elemen: {[(e.role, e.name) for e in obs.elements]}")


def login_direct(driver) -> None:
    """Login lewat Playwright langsung (untuk test yang bukan tentang execute)."""
    driver.goto("/login")
    driver.page.fill("#email", DEMO_USER)
    driver.page.fill("#password", DEMO_PASSWORD)
    driver.page.click("button[type=submit]")
    driver.page.wait_for_load_state("domcontentloaded")
```

`tests/integration/test_web_observe.py`:

```python
from urllib.parse import urlsplit

import pytest

from qa_agent.drivers.base import DriverCrashed
from qa_agent.drivers.web import WebDriver
from tests.integration.helpers import find, login_direct

pytestmark = pytest.mark.browser


@pytest.fixture
def driver(demo):
    d = WebDriver(demo.url, headless=True)
    d.start()
    d.new_session(None)
    yield d
    d.stop()


def test_observe_login_page(driver, demo):
    driver.goto("/users")  # belum login → diarahkan ke /login
    obs = driver.observe()
    assert "/login" in obs.location and obs.is_login_screen
    email = find(obs, "input", "Email")
    password = find(obs, "input", "Password")
    button = find(obs, "button", "Masuk")
    assert password.input_type == "password"
    assert email.selector == '[id="email"]'
    assert button.selector == 'role=button[name="Masuk"]'
    assert button.context == "Masuk"
    assert [e.index for e in obs.elements] == list(range(1, len(obs.elements) + 1))
    assert obs.screenshot_annotated[:8] == b"\x89PNG\r\n\x1a\n"
    assert obs.fingerprint.startswith(f"{urlsplit(demo.url).netloc}/login|")


def test_users_page_elements(driver):
    login_direct(driver)
    driver.goto("/users")
    obs = driver.observe()
    names = [(e.role, e.name) for e in obs.elements]
    assert ("link", "Tambah Pengguna") in names
    assert ("button", "Ekspor") in names
    assert ("button", "Keluar") in names
    assert names.count(("link", "Edit")) == 2
    assert names.count(("button", "Hapus")) == 2
    edit = find(obs, "link", "Edit")
    assert edit.href.endswith("/users/1/edit")


def test_form_context_and_values(driver):
    login_direct(driver)
    driver.goto("/users/new")
    obs = driver.observe()
    assert find(obs, "button", "Simpan").context == "Tambah Pengguna"
    assert find(obs, "input", "Nama").value == ""


def test_http_500_signal(driver):
    login_direct(driver)
    driver.goto("/users/new")
    driver.observe()
    driver.page.fill("#name", "O'Brien")
    driver.page.fill("#age", "3")
    driver.page.click("text=Simpan")
    obs = driver.observe()
    errors = [s for s in obs.signals if s.kind == "http_error"]
    assert any(s.status == 500 and s.method == "POST" for s in errors)


def test_ui_error_signal(driver):
    login_direct(driver)
    driver.goto("/users/new")
    driver.observe()
    driver.page.fill("#age", "3")
    driver.page.click("text=Simpan")
    obs = driver.observe()
    assert any(s.kind == "ui_error" and "Nama wajib diisi" in s.message for s in obs.signals)
    assert any(s.kind == "http_error" and s.status == 400 for s in obs.signals)


def test_auth_state_roundtrip(driver, tmp_path):
    login_direct(driver)
    state = tmp_path / "auth" / "state.json"
    driver.save_auth_state(state)
    driver.new_session(state)
    driver.goto("/users")
    assert driver.current_url.endswith("/users")
    assert not driver.observe().is_login_screen


def test_screenshot_with_highlight(driver):
    driver.goto("/login")
    obs = driver.observe()
    png = driver.screenshot(highlight=find(obs, "button", "Masuk"))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_closed_driver_raises_crash(driver):
    driver.stop()
    with pytest.raises(DriverCrashed):
        driver.observe()
```

- [ ] **Step 6: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/integration/test_web_observe.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'qa_agent.drivers.web'`

- [ ] **Step 7: Implementasi `drivers/web.py` (tanpa execute)**

`qa_agent/drivers/web.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from qa_agent import imaging
from qa_agent.drivers.base import DriverCrashed
from qa_agent.drivers.web_dom import EXTRACT_JS, UI_ERROR_JS, to_element
from qa_agent.models import Action, ActionResult, Element, Observation, Signal
from qa_agent.orchestrator.fingerprint import fingerprint

TRACKED_RESOURCES = {"document", "xhr", "fetch"}
_FATAL_MARKERS = ("has been closed", "Target closed", "Browser closed")


def _first_line(e: Exception) -> str:
    lines = str(e).strip().splitlines()
    return (lines[0] if lines else type(e).__name__)[:300]


def _is_fatal(e: Exception) -> bool:
    return any(marker in str(e) for marker in _FATAL_MARKERS)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class WebDriver:
    """Driver web berbasis Playwright (sync API)."""

    def __init__(
        self,
        base_url: str,
        *,
        headless: bool = False,
        viewport: tuple[int, int] = (1366, 768),
        request_filter: Callable[[str, str], bool] | None = None,
        max_elements: int = 80,
        action_timeout_ms: int = 15_000,
        navigation_timeout_ms: int = 30_000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.viewport = viewport
        self.request_filter = request_filter
        self.max_elements = max_elements
        self.action_timeout_ms = action_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.blocked_requests: list[str] = []
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._frames: list[Any] = []
        self._signals: list[Signal] = []
        self._credentials: dict[str, str] = {}

    # ---------- siklus hidup ----------
    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)

    def stop(self) -> None:
        for closable in (self._context, self._browser):
            if closable is not None:
                try:
                    closable.close()
                except PlaywrightError:
                    pass
        if self._pw is not None:
            self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    def new_session(self, auth_state: Path | None = None) -> None:
        if self._browser is None:
            raise DriverCrashed("Browser belum dijalankan (panggil start())")
        if self._context is not None:
            try:
                self._context.close()
            except PlaywrightError:
                pass
        state = str(auth_state) if auth_state and Path(auth_state).exists() else None
        width, height = self.viewport
        self._context = self._browser.new_context(viewport={"width": width, "height": height}, storage_state=state)
        if self.request_filter is not None:
            self._context.route("**/*", self._route)
        page = self._context.new_page()
        page.set_default_timeout(self.action_timeout_ms)
        page.set_default_navigation_timeout(self.navigation_timeout_ms)
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("response", self._on_response)
        self._page = page
        self._signals = []
        self._frames = []

    def save_auth_state(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(path))

    @property
    def page(self) -> Any:
        if self._page is None:
            raise DriverCrashed("Sesi browser belum dibuat atau sudah ditutup")
        return self._page

    @property
    def current_url(self) -> str:
        return self.page.url

    # ---------- event ----------
    def _route(self, route: Any) -> None:
        request = route.request
        if self.request_filter is not None and self.request_filter(request.method, request.url):
            self.blocked_requests.append(f"{request.method} {request.url}")
            self._signals.append(Signal(kind="blocked_request", message="Request diblok mode production",
                                        method=request.method, url=request.url))
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def _on_console(self, msg: Any) -> None:
        if msg.type == "error":
            self._signals.append(Signal(kind="console_error", message=msg.text[:300]))

    def _on_page_error(self, error: Any) -> None:
        self._signals.append(Signal(kind="page_error", message=str(error)[:300]))

    def _on_response(self, response: Any) -> None:
        if response.status >= 400 and response.request.resource_type in TRACKED_RESOURCES:
            self._signals.append(Signal(kind="http_error", message=f"HTTP {response.status}", status=response.status,
                                        url=response.url, method=response.request.method))

    def _drain_signals(self) -> list[Signal]:
        signals, self._signals = self._signals, []
        return signals

    # ---------- navigasi & observasi ----------
    def goto(self, location: str) -> None:
        url = urljoin(self.base_url + "/", location)
        for attempt in range(2):  # timeout navigasi: coba 1× lagi (spec §9)
            try:
                self.page.goto(url, wait_until="domcontentloaded")
                break
            except PlaywrightTimeout:
                if attempt == 1:
                    raise
            except PlaywrightError as e:
                if _is_fatal(e):
                    raise DriverCrashed(_first_line(e)) from e
                raise
        self._settle()

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except PlaywrightTimeout:
            pass
        except PlaywrightError as e:
            if _is_fatal(e):
                raise DriverCrashed(_first_line(e)) from e

    def _scan_frames(self) -> list[tuple[Any, tuple[float, float]]]:
        main = self.page.main_frame
        frames: list[tuple[Any, tuple[float, float]]] = [(main, (0.0, 0.0))]
        origin = _origin(main.url)
        for child in main.child_frames:
            if _origin(child.url) != origin:
                continue  # iframe lintas domain tidak didukung
            try:
                box = child.frame_element().bounding_box()
            except PlaywrightError:
                continue
            if box:
                frames.append((child, (box["x"], box["y"])))
        return frames

    def _observe_once(self) -> Observation:
        self._settle()
        elements: list[Element] = []
        frames: list[Any] = []
        for frame, offset in self._scan_frames():
            remaining = self.max_elements - len(elements)
            if remaining <= 0:
                break
            raws = frame.evaluate(EXTRACT_JS, [remaining, len(elements) + 1])
            frame_index = len(frames)
            frames.append(frame)
            elements.extend(to_element(raw, frame_index, offset) for raw in raws)
        self._frames = frames
        ui_errors = self.page.evaluate(UI_ERROR_JS)
        png = self.page.screenshot()
        url = self.page.url
        signals = self._drain_signals() + [Signal(kind="ui_error", message=text) for text in ui_errors]
        return Observation(
            location=url,
            title=self.page.title(),
            elements=elements,
            signals=signals,
            screenshot_annotated=imaging.annotate(png, elements),
            fingerprint=fingerprint(url, elements),
        )

    def observe(self) -> Observation:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                return self._observe_once()
            except PlaywrightError as e:  # mis. "Execution context was destroyed" saat navigasi
                if _is_fatal(e):
                    raise DriverCrashed(_first_line(e)) from e
                last_error = e
                self._settle()
        assert last_error is not None
        raise last_error

    def screenshot(self, highlight: Element | None = None) -> bytes:
        try:
            png = self.page.screenshot()
        except PlaywrightError as e:
            if _is_fatal(e):
                raise DriverCrashed(_first_line(e)) from e
            raise
        return imaging.highlight(png, highlight.bbox) if highlight is not None else png
```

- [ ] **Step 8: Jalankan integration test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/integration/test_web_observe.py -v`
Expected: `8 passed`

- [ ] **Step 9: Commit**

```bash
git add qa_agent/drivers tests/unit/test_web_dom.py tests/integration/helpers.py tests/integration/test_web_observe.py
git commit -m "feat: WebDriver Playwright — sesi, observasi elemen, sinyal error"
```

---

### Task 12: WebDriver — eksekusi aksi, kredensial, blokir request production

**Files:**
- Modify: `qa_agent/drivers/web.py` (tambah method di class `WebDriver`)
- Test: `tests/integration/test_web_execute.py`

**Interfaces:**
- Consumes: `Guard.should_block_request` (Task 5), `WebDriver` (Task 11)
- Produces: `WebDriver.set_credentials(username, password)`, `WebDriver.execute(action, element) -> ActionResult` (`fatal=True` jika browser tertutup)

- [ ] **Step 1: Tulis test yang gagal**

`tests/integration/test_web_execute.py`:

```python
import pytest

from qa_agent.drivers.web import WebDriver
from qa_agent.guard import Guard
from qa_agent.models import Action
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER
from tests.integration.helpers import find

pytestmark = pytest.mark.browser


def make(demo, **kw):
    d = WebDriver(demo.url, headless=True, **kw)
    d.start()
    d.new_session(None)
    d.set_credentials(DEMO_USER, DEMO_PASSWORD)
    return d


def login(d):
    d.goto("/login")
    obs = d.observe()
    assert d.execute(Action(action="type", value="{{username}}"), find(obs, "input", "Email")).ok
    assert d.execute(Action(action="type", value="{{password}}"), find(obs, "input", "Password")).ok
    assert d.execute(Action(action="click"), find(obs, "button", "Masuk")).ok


@pytest.fixture
def driver(demo):
    d = make(demo)
    yield d
    d.stop()


def test_login_with_placeholders(driver):
    login(driver)
    obs = driver.observe()
    assert not obs.is_login_screen
    find(obs, "link", "Pengguna")


def test_password_value_not_exposed(driver):
    driver.goto("/login")
    obs = driver.observe()
    driver.execute(Action(action="type", value="{{password}}"), find(obs, "input", "Password"))
    after = driver.observe()
    assert find(after, "input", "Password").value == "******"
    assert DEMO_PASSWORD not in after.model_dump_json(exclude={"screenshot_annotated"})


def test_navigate_back_scroll_wait(driver):
    login(driver)
    assert driver.execute(Action(action="navigate", value="/reports"), None).ok
    assert driver.current_url.endswith("/reports")
    assert driver.execute(Action(action="back"), None).ok
    assert not driver.current_url.endswith("/reports")
    assert driver.execute(Action(action="scroll", value="down"), None).ok
    assert driver.execute(Action(action="wait", value="0.1"), None).ok


def test_click_requires_element(driver):
    result = driver.execute(Action(action="click"), None)
    assert not result.ok and "butuh elemen" in result.error


def test_stale_element_returns_error_not_crash(demo):
    d = make(demo, action_timeout_ms=1500)
    try:
        login(d)
        d.goto("/users")
        stale = find(d.observe(), "link", "Tambah Pengguna")
        d.goto("/reports")
        d.observe()  # data-qa-idx di halaman baru tidak memiliki elemen tadi
        stale = stale.model_copy(update={"index": 999})
        result = d.execute(Action(action="click"), stale)
        assert not result.ok and not result.fatal
    finally:
        d.stop()


def test_production_filter_blocks_writes_but_allows_login(demo):
    guard = Guard("production", ["127.0.0.1"])
    d = make(demo, request_filter=guard.should_block_request)
    try:
        login(d)
        assert not d.observe().is_login_screen  # POST /login diizinkan
        d.goto("/reports")
        result = d.execute(Action(action="click"), find(d.observe(), "button", "Proses Ulang"))
        assert not result.fatal  # navigasi yang dibatalkan boleh dilaporkan gagal, tapi browser tetap hidup
        assert demo.state.writes == []
        assert any("/reports/rebuild" in r for r in d.blocked_requests)
        assert any(s.kind == "blocked_request" for s in d.observe().signals)
    finally:
        d.stop()


def test_fatal_when_browser_closed(demo):
    d = make(demo)
    d.goto("/login")
    obs = d.observe()
    d._browser.close()
    result = d.execute(Action(action="click"), find(obs, "button", "Masuk"))
    assert not result.ok and result.fatal
    d.stop()
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/integration/test_web_execute.py -v`
Expected: FAIL dengan `AttributeError: 'WebDriver' object has no attribute 'set_credentials'`

- [ ] **Step 3: Implementasi — tambahkan method berikut ke class `WebDriver` di `qa_agent/drivers/web.py`** (di bawah `screenshot`)

```python
    # ---------- aksi ----------
    def set_credentials(self, username: str, password: str) -> None:
        self._credentials = {"{{username}}": username, "{{password}}": password}

    def _resolve(self, text: str | None) -> str:
        text = text or ""
        for placeholder, real in self._credentials.items():
            text = text.replace(placeholder, real)
        return text

    def _locator(self, element: Element) -> Any:
        return self._frames[element.frame].locator(f'[data-qa-idx="{element.index}"]').first

    def _select(self, locator: Any, value: str) -> None:
        try:
            locator.select_option(label=value, timeout=3000)
        except PlaywrightError:
            locator.select_option(value=value)

    def execute(self, action: Action, element: Element | None) -> ActionResult:
        kind = action.action
        if kind in ("click", "type", "select"):
            if element is None:
                return ActionResult(ok=False, error=f"Aksi {kind} butuh elemen")
            if element.frame >= len(self._frames):
                return ActionResult(ok=False, error="Elemen berasal dari observasi lama; observasi ulang")
        try:
            if kind == "click":
                self._locator(element).click()
            elif kind == "type":
                self._locator(element).fill(self._resolve(action.value))
            elif kind == "select":
                self._select(self._locator(element), action.value or "")
            elif kind == "scroll":
                self.page.mouse.wheel(0, -600 if action.value == "up" else 600)
            elif kind == "back":
                self.page.go_back(wait_until="domcontentloaded")
            elif kind == "navigate":
                self.goto(action.value or "/")
            elif kind == "wait":
                self.page.wait_for_timeout(min(float(action.value or 2), 10.0) * 1000)
            self._settle()
            return ActionResult(ok=True)
        except PlaywrightTimeout as e:
            return ActionResult(ok=False, error=f"Timeout: {_first_line(e)}")
        except PlaywrightError as e:
            return ActionResult(ok=False, error=_first_line(e), fatal=_is_fatal(e))
        except DriverCrashed as e:
            return ActionResult(ok=False, error=str(e), fatal=True)
        except ValueError as e:
            return ActionResult(ok=False, error=f"Nilai tidak valid: {e}")
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/integration/test_web_execute.py tests/integration/test_web_observe.py -v`
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/drivers/web.py tests/integration/test_web_execute.py
git commit -m "feat: WebDriver execute aksi, placeholder kredensial, blokir request production"
```

---

### Task 13: Humanize, prompt AI, deteksi loop

**Files:**
- Create: `qa_agent/report/humanize.py`, `qa_agent/agent/prompts.py`, `qa_agent/agent/loop_detect.py`
- Test: `tests/unit/test_humanize.py`, `tests/unit/test_prompts.py`, `tests/unit/test_loop_detect.py`

**Interfaces:**
- Consumes: `Element`, `Observation`, `Signal`, `ScreenInfo` (Task 3), `Message` (Task 7)
- Produces:
  - `humanize(action: str, element: dict | None, value: str | None) -> str`, `signal_text(signal: Signal) -> str`
  - `prompts.execute_system(platform: str, data_prefix: str) -> str` (diawali `"MODE: EXECUTE"`)
  - `prompts.step_message(goal, obs, history: list[str], notes: list[str], vision: bool) -> Message`
  - `prompts.retry_message(error: str) -> Message`
  - `prompts.observation_text(obs) -> str`, `prompts.format_element(e) -> str` (format baris `[3] input "Nama" value=""`)
  - `prompts.explore_system(known_modules: list[str]) -> str` (diawali `"MODE: EXPLORE_SCREEN"`), `prompts.explore_message(obs, vision) -> Message`
  - `prompts.plan_system(module, max_tcs, data_prefix, has_prd) -> str` (diawali `"MODE: PLAN"`), `prompts.plan_message(screens, prd_text) -> Message`
  - `LoopDetector(warn_at=3, block_at=4)` dengan `.record(fingerprint, action, target) -> "ok" | "warn" | "block"`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_humanize.py`:

```python
from qa_agent.models import Signal
from qa_agent.report.humanize import humanize, signal_text


def test_humanize_actions():
    btn = {"role": "button", "name": "Simpan"}
    field = {"role": "input", "name": "Email"}
    assert humanize("click", btn, None) == "Klik tombol 'Simpan'"
    assert humanize("type", field, "bukan-email") == "Isi field 'Email' dengan 'bukan-email'"
    assert humanize("type", field, "") == "Kosongkan field 'Email'"
    assert humanize("select", {"role": "select", "name": "Kota"}, "Bandung") == "Pilih 'Bandung' pada dropdown 'Kota'"
    assert humanize("scroll", None, "up") == "Gulir halaman ke atas"
    assert humanize("navigate", None, "/users") == "Buka halaman /users"
    assert humanize("blocked", None, "tombol tidak ada") == "Tidak bisa dilanjutkan: tombol tidak ada"
    assert humanize("click", {"role": "div", "name": ""}, None) == "Klik elemen 'tanpa nama'"


def test_signal_text():
    assert signal_text(Signal(kind="http_error", message="x", status=500, method="POST", url="http://a/users")) == "HTTP 500 POST http://a/users"
    assert signal_text(Signal(kind="page_error", message="TypeError: x")) == "Error JavaScript: TypeError: x"
    assert signal_text(Signal(kind="blocked_request", message="x", method="POST", url="http://a/r")) == "Request diblok: POST http://a/r"
```

`tests/unit/test_prompts.py`:

```python
from qa_agent.agent import prompts
from qa_agent.models import Element, Observation, ScreenInfo, Signal


def obs():
    return Observation(
        location="http://a/users/new", title="Tambah Pengguna",
        elements=[Element(index=1, role="input", name="Nama", value=""), Element(index=2, role="input", name="Password", input_type="password", value="******"),
                  Element(index=3, role="button", name="Simpan", context="Tambah Pengguna")],
        signals=[Signal(kind="http_error", message="HTTP 500", status=500, method="POST", url="http://a/users")],
        screenshot_annotated=b"\x89PNG",
    )


def test_execute_system_markers():
    s = prompts.execute_system("web", "QA-AUTO-20261005-1430")
    assert s.startswith("MODE: EXECUTE")
    assert "QA-AUTO-20261005-1430" in s and "{{username}}" in s and "{{password}}" in s
    assert "<<" not in s


def test_format_element():
    e = obs().elements
    assert prompts.format_element(e[0]) == '[1] input "Nama" value=""'
    assert prompts.format_element(e[1]) == '[2] input "Password" type=password value="******"'
    assert prompts.format_element(e[2]) == '[3] button "Simpan" (dalam: Tambah Pengguna)'


def test_step_message_sections_and_image():
    msg = prompts.step_message("Tambah pengguna", obs(), ["1. Klik link 'Tambah' → ok"], ["Aksi X diblok"], vision=True)
    assert "## Tujuan\nTambah pengguna" in msg.text
    assert "1. Klik link 'Tambah' → ok" in msg.text
    assert "## Catatan sistem\n- Aksi X diblok" in msg.text
    assert "- HTTP 500 POST http://a/users" in msg.text
    assert msg.images == [b"\x89PNG"]
    no_vision = prompts.step_message("x", obs(), [], [], vision=False)
    assert no_vision.images == [] and "(belum ada)" in no_vision.text and "Catatan sistem" not in no_vision.text


def test_explore_and_plan_prompts():
    assert prompts.explore_system(["Dashboard"]).startswith("MODE: EXPLORE_SCREEN")
    assert "Dashboard" in prompts.explore_system(["Dashboard"])
    plan = prompts.plan_system("Pengguna", 15, "QA-AUTO-X", has_prd=True)
    assert plan.startswith("MODE: PLAN") and "Pengguna" in plan and "15" in plan and "PRD" in plan
    screens = [ScreenInfo(fingerprint="f", url="http://a/users/new", module="Pengguna", page_name="Tambah Pengguna", purpose="Form tambah",
                          forms=[{"name": "Form pengguna", "fields": [{"label": "Nama", "type": "text"}]}], actions=["Simpan"])]
    msg = prompts.plan_message(screens, "PRD: email wajib valid")
    assert "Tambah Pengguna (http://a/users/new)" in msg.text and "Nama (text)" in msg.text and "## PRD" in msg.text
    assert "## PRD" not in prompts.plan_message(screens, None).text
```

`tests/unit/test_loop_detect.py`:

```python
from qa_agent.agent.loop_detect import LoopDetector


def test_warn_then_block():
    d = LoopDetector()
    assert [d.record("fp", "click", "#a") for _ in range(4)] == ["ok", "ok", "warn", "block"]


def test_different_targets_counted_separately():
    d = LoopDetector()
    for _ in range(2):
        d.record("fp", "click", "#a")
    assert d.record("fp", "click", "#b") == "ok"
    assert d.record("fp2", "click", "#a") == "ok"
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_humanize.py tests/unit/test_prompts.py tests/unit/test_loop_detect.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi `report/humanize.py`**

```python
from __future__ import annotations

from qa_agent.models import Signal

_ROLE_LABEL = {
    "button": "tombol", "link": "link", "input": "field", "textarea": "field", "select": "dropdown",
    "combobox": "dropdown", "checkbox": "checkbox", "radio": "pilihan", "tab": "tab", "menuitem": "menu",
}


def humanize(action: str, element: dict | None, value: str | None) -> str:
    """Kalimat langkah untuk manusia, dari template (bukan AI) agar selalu akurat."""
    element = element or {}
    name = element.get("name") or "tanpa nama"
    label = _ROLE_LABEL.get(element.get("role", ""), "elemen")
    if action == "click":
        return f"Klik {label} '{name}'"
    if action == "type":
        return f"Isi field '{name}' dengan '{value}'" if value else f"Kosongkan field '{name}'"
    if action == "select":
        return f"Pilih '{value}' pada {label} '{name}'"
    if action == "scroll":
        return "Gulir halaman ke atas" if value == "up" else "Gulir halaman ke bawah"
    if action == "back":
        return "Kembali ke halaman sebelumnya"
    if action == "navigate":
        return f"Buka halaman {value}"
    if action == "wait":
        return f"Tunggu {value or 2} detik"
    if action == "done":
        return "Verifikasi hasil akhir" + (f" ({value})" if value else "")
    if action == "blocked":
        return f"Tidak bisa dilanjutkan: {value}" if value else "Tidak bisa dilanjutkan"
    if action == "invalid":
        return "Jawaban AI tidak valid"
    return action


def signal_text(signal: Signal) -> str:
    if signal.kind == "http_error":
        return " ".join(p for p in (f"HTTP {signal.status}", signal.method, signal.url) if p)
    if signal.kind == "blocked_request":
        return f"Request diblok: {signal.method} {signal.url}"
    labels = {"console_error": "Console error", "page_error": "Error JavaScript", "ui_error": "Pesan error di layar"}
    return f"{labels.get(signal.kind, signal.kind)}: {signal.message}"
```

- [ ] **Step 4: Implementasi `agent/prompts.py`**

```python
from __future__ import annotations

from qa_agent.llm.base import Message
from qa_agent.models import Element, Observation, ScreenInfo
from qa_agent.report.humanize import signal_text

EXECUTE_SYSTEM = """MODE: EXECUTE
Kamu adalah QA automation engineer senior yang menguji aplikasi <<platform>> secara black-box (tanpa akses kode).
Setiap giliran kamu menerima tujuan, riwayat langkah, dan kondisi layar saat ini (screenshot bernomor + daftar elemen).
Pilih SATU aksi berikutnya.

Jawab HANYA dengan satu objek JSON, tanpa teks lain:
{"thought": "alasan singkat", "action": "<aksi>", "element": <nomor atau null>, "value": "<teks atau null>", "expect": "hasil yang kamu harapkan", "risk": "low|medium|high"}

Aksi yang tersedia:
- click (element wajib)
- type (element dan value wajib; value "" untuk mengosongkan field)
- select (element wajib, value = teks opsi)
- scroll (value "up" atau "down")
- back
- navigate (value = URL atau path di domain yang sama)
- wait (value = jumlah detik, maksimal 10)
- done (wajib "status": "pass" atau "fail", "actual": apa yang benar-benar terjadi, "severity": "Critical|Major|Minor" jika fail)
- blocked ("reason": kenapa tidak bisa dilanjutkan)

Aturan:
1. Pakai hanya nomor elemen dari daftar elemen layar saat ini.
2. Untuk kredensial tulis persis {{username}} dan {{password}}; sistem yang akan mengisinya.
3. Data baru yang kamu buat (nama, judul, dll.) diawali "<<data_prefix>>" kecuali test data menentukan lain.
4. risk "high" jika aksi menyimpan/mengubah/menghapus/mengirim data atau transaksi; "medium" jika membuka form/dialog yang bisa mengarah ke perubahan; "low" untuk navigasi dan membaca.
5. Nyatakan done segera setelah hasil bisa diverifikasi dari layar. Bandingkan dengan expected result secara jujur: fail jika berbeda.
6. Jika aksi diblok Safety Guard atau gagal berulang, cari jalan lain; jika tidak ada, nyatakan blocked.
7. Sinyal error (HTTP 5xx, error JavaScript) adalah bukti bug; sebutkan di actual.
"""

EXPLORE_SYSTEM = """MODE: EXPLORE_SCREEN
Kamu adalah QA engineer yang sedang memetakan fitur aplikasi. Analisis layar ini.
Jawab HANYA satu objek JSON:
{"module": "nama modul/fitur, singkat, Bahasa Indonesia, konsisten antar layar", "page_name": "nama halaman", "purpose": "fungsi halaman dalam 1 kalimat", "forms": [{"name": "nama form", "fields": [{"label": "label field", "type": "text|email|password|number|select|checkbox|date|file|textarea"}]}], "actions": ["aksi penting yang tersedia"], "nav_candidates": [nomor elemen yang membuka halaman atau menu lain]}
Aturan nav_candidates: hanya menu, link, tab, atau tombol yang berpindah halaman. JANGAN masukkan logout, hapus, simpan, kirim, atau aksi lain yang mengubah data.
Modul yang sudah ditemukan sejauh ini (pakai nama yang sama jika layar ini bagian dari modul tersebut): <<modules>>
"""

PLAN_SYSTEM = """MODE: PLAN
Kamu adalah QA engineer senior. Susun test case untuk modul "<<module>>" berdasarkan peta layar<<prd_hint>>.
Jawab HANYA satu objek JSON: {"test_cases": [ ... ]}
Format setiap test case:
{"title": "...", "page": "nama halaman", "type": "positif|negatif|validasi|boundary|navigasi", "priority": "High|Medium|Low", "precondition": "...", "test_data": "...", "steps": ["langkah 1", "langkah 2"], "expected": "...", "expected_source": "PRD|Inferensi AI", "start_url": "URL layar awal"}
Aturan:
1. Maksimal <<max>> test case. Campurkan tipe: positif, negatif, validasi field, boundary, navigasi.
2. expected_source "PRD" HANYA jika expected diambil langsung dari PRD; selain itu "Inferensi AI".
3. Langkah ditulis untuk manusia dalam Bahasa Indonesia, spesifik (sebut nama field/tombol).
4. Data baru diawali "<<data_prefix>>".
5. start_url diambil dari peta layar.
6. Jangan membuat test case login/logout kecuali modulnya memang autentikasi.
"""


def execute_system(platform: str, data_prefix: str) -> str:
    return EXECUTE_SYSTEM.replace("<<platform>>", platform).replace("<<data_prefix>>", data_prefix)


def explore_system(known_modules: list[str]) -> str:
    return EXPLORE_SYSTEM.replace("<<modules>>", ", ".join(known_modules) or "(belum ada)")


def plan_system(module: str, max_tcs: int, data_prefix: str, has_prd: bool) -> str:
    return (PLAN_SYSTEM.replace("<<module>>", module).replace("<<max>>", str(max_tcs))
            .replace("<<data_prefix>>", data_prefix).replace("<<prd_hint>>", " dan PRD" if has_prd else ""))


def format_element(e: Element) -> str:
    parts = [f'[{e.index}] {e.role} "{e.name}"']
    if e.input_type and e.input_type not in ("text", "submit", "button"):
        parts.append(f"type={e.input_type}")
    if e.value is not None:
        parts.append(f'value="{e.value}"')
    if e.context:
        parts.append(f"(dalam: {e.context})")
    return " ".join(parts)


def observation_text(obs: Observation) -> str:
    lines = [f"URL: {obs.location}", f"Judul: {obs.title}"]
    if obs.signals:
        lines.append("Sinyal:")
        lines.extend(f"- {signal_text(s)}" for s in obs.signals)
    lines.append("Elemen:")
    lines.extend([format_element(e) for e in obs.elements] or ["(tidak ada elemen interaktif)"])
    return "\n".join(lines)


def _images(obs: Observation, vision: bool) -> list[bytes]:
    return [obs.screenshot_annotated] if vision and obs.screenshot_annotated else []


def step_message(goal: str, obs: Observation, history: list[str], notes: list[str], vision: bool) -> Message:
    text = f"## Tujuan\n{goal}\n\n## Riwayat langkah terakhir\n" + ("\n".join(history) or "(belum ada)")
    if notes:
        text += "\n\n## Catatan sistem\n" + "\n".join(f"- {n}" for n in notes)
    text += "\n\n## Layar saat ini\n" + observation_text(obs)
    return Message(role="user", text=text, images=_images(obs, vision))


def retry_message(error: str) -> Message:
    return Message(role="user", text=f"Jawaban sebelumnya tidak valid: {error}. Ulangi dengan SATU objek JSON sesuai format.")


def explore_message(obs: Observation, vision: bool) -> Message:
    return Message(role="user", text="## Layar\n" + observation_text(obs), images=_images(obs, vision))


def plan_message(screens: list[ScreenInfo], prd_text: str | None) -> Message:
    lines = ["## Peta layar modul"]
    for s in screens:
        lines.append(f"- {s.page_name} ({s.url})")
        if s.purpose:
            lines.append(f"  Fungsi: {s.purpose}")
        for form in s.forms:
            fields = ", ".join(f"{f.get('label', '?')} ({f.get('type', '?')})" for f in form.get("fields", []))
            lines.append(f"  Form {form.get('name', '')}: {fields}")
        if s.actions:
            lines.append(f"  Aksi: {', '.join(s.actions)}")
    if prd_text:
        lines += ["", "## PRD", prd_text[:12000]]
    return Message(role="user", text="\n".join(lines))
```

- [ ] **Step 5: Implementasi `agent/loop_detect.py`**

```python
from __future__ import annotations

from collections import Counter
from typing import Literal


class LoopDetector:
    """Hitung kombinasi (layar, aksi, target). Ke-3 → peringatan, ke-4 → blocked."""

    def __init__(self, warn_at: int = 3, block_at: int = 4) -> None:
        self.warn_at = warn_at
        self.block_at = block_at
        self._counts: Counter[tuple[str, str, str]] = Counter()

    def record(self, fingerprint: str, action: str, target: str) -> Literal["ok", "warn", "block"]:
        key = (fingerprint, action, target)
        self._counts[key] += 1
        n = self._counts[key]
        if n >= self.block_at:
            return "block"
        if n >= self.warn_at:
            return "warn"
        return "ok"
```

- [ ] **Step 6: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_humanize.py tests/unit/test_prompts.py tests/unit/test_loop_detect.py -v`
Expected: `8 passed`

- [ ] **Step 7: Commit**

```bash
git add qa_agent/report/humanize.py qa_agent/agent/prompts.py qa_agent/agent/loop_detect.py tests/unit/test_humanize.py tests/unit/test_prompts.py tests/unit/test_loop_detect.py
git commit -m "feat: prompt AI (execute/explore/plan), humanize langkah, deteksi loop"
```

---

### Task 14: Agent Loop

**Files:**
- Create: `qa_agent/agent/loop.py`
- Create: `tests/fakes.py`
- Test: `tests/unit/test_agent_loop.py`

**Interfaces:**
- Consumes: `Driver`, `DriverCrashed` (Task 11), `LLMClient`, `Message` (Task 7), `Guard` (Task 5), `RunStore`, `Masker`, `now_iso` (Task 8), `parse_action`, `ActionParseError` (Task 6), `prompts`, `LoopDetector`, `humanize` (Task 13)
- Produces:
  - `LoopOutcome(final: "done"|"blocked", status: "pass"|"fail"|None, actual: str, reason: str, severity: str|None, steps: int, guard_blocks: int, signals: list[Signal], error_kind: ""|"max_steps"|"loop"|"interrupted"|"agent")`
  - `AgentLoop(*, driver, llm, guard, store, masker, data_prefix, platform="web", max_steps=25, vision=True, relogin: Callable[[str], None] | None = None, should_stop: Callable[[], bool] = lambda: False)`; atribut `relogin` boleh diganti setelah dibuat
  - `AgentLoop.run(tc_id: str, goal: str, *, allow_logout=False, login=False) -> LoopOutcome` (melempar `DriverCrashed` dan `LLMError`)
  - `find_same(obs, element) -> Element | None`
  - Test helper `tests/fakes.py`: `PNG`, `BASE`, `url(path)`, `el(index, role, name, **kw)`, `screen(path, *elements, title=None, signals=())`, `act(**kw) -> str`, `FakeDriver(screens, start, transitions=None, *, fail_first=0, fatal=False)` dengan atribut `current`, `executed`, `gotos`, `sessions`, `saved`

- [ ] **Step 1: Tulis helper test `tests/fakes.py`**

```python
"""Driver & data palsu untuk unit test (tanpa browser)."""
from __future__ import annotations

import json
from pathlib import Path

from qa_agent.imaging import solid_png
from qa_agent.models import Action, ActionResult, Element, Observation, Signal
from qa_agent.orchestrator.fingerprint import fingerprint

PNG = solid_png((255, 255, 255), (16, 12))
BASE = "http://app.test"


def url(path: str) -> str:
    return f"{BASE}/{path.lstrip('/')}"


def el(index: int, role: str, name: str, **kw) -> Element:
    kw.setdefault("bbox", (1.0, 1.0, 10.0, 5.0))
    kw.setdefault("selector", f"{role}:{name}")
    return Element(index=index, role=role, name=name, **kw)


def screen(path: str, *elements: Element, title: str | None = None, signals: tuple[Signal, ...] = ()) -> Observation:
    location = url(path)
    items = list(elements)
    return Observation(location=location, title=title or path, elements=items, signals=list(signals),
                       screenshot_annotated=PNG, fingerprint=fingerprint(location, items))


def act(**kw) -> str:
    return json.dumps(kw)


class FakeDriver:
    """Layar terskrip. transitions: {(lokasi_sekarang, nama_elemen_atau_aksi): lokasi_berikut}."""

    def __init__(self, screens: list[Observation], start: str, transitions: dict | None = None, *,
                 fail_first: int = 0, fatal: bool = False) -> None:
        self.screens = {s.location: s for s in screens}
        self.current = start
        self.transitions = transitions or {}
        self.fail_first = fail_first
        self.fatal = fatal
        self.executed: list[tuple[str, str | None, str | None]] = []
        self.gotos: list[str] = []
        self.sessions: list = []
        self.saved: list[Path] = []
        self.credentials: dict[str, str] = {}
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def new_session(self, auth_state=None) -> None:
        self.sessions.append(auth_state)

    def save_auth_state(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        self.saved.append(path)

    def goto(self, location: str) -> None:
        self.gotos.append(location)
        if location not in self.screens:
            raise RuntimeError(f"FakeDriver: layar {location} tidak ada")
        self.current = location

    @property
    def current_url(self) -> str:
        return self.current

    def set_credentials(self, username: str, password: str) -> None:
        self.credentials = {"{{username}}": username, "{{password}}": password}

    def observe(self) -> Observation:
        return self.screens[self.current].model_copy(deep=True)

    def screenshot(self, highlight=None) -> bytes:
        return PNG

    def execute(self, action: Action, element: Element | None) -> ActionResult:
        if self.fatal:
            return ActionResult(ok=False, error="Target closed", fatal=True)
        if self.fail_first > 0:
            self.fail_first -= 1
            return ActionResult(ok=False, error="Element is not attached to the DOM")
        value = action.value
        if value:
            for placeholder, real in self.credentials.items():
                value = value.replace(placeholder, real)
        name = element.name if element else None
        self.executed.append((action.action, name, value))
        nxt = self.transitions.get((self.current, name or action.action))
        if nxt:
            self.current = nxt
        return ActionResult(ok=True)
```

- [ ] **Step 2: Tulis test yang gagal**

`tests/unit/test_agent_loop.py`:

```python
import pytest

from qa_agent.agent.loop import AgentLoop
from qa_agent.drivers.base import DriverCrashed
from qa_agent.evidence import Masker, RunStore, SECRET_MASK
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from tests.fakes import FakeDriver, act, el, screen, url

LOGIN = screen("login", el(1, "input", "Email"), el(2, "input", "Password", input_type="password"), el(3, "button", "Masuk"))
HOME = screen("home", el(1, "link", "Pengguna", href=url("users")), el(2, "button", "Hapus"))
USERS = screen("users", el(1, "link", "Dashboard", href=url("home")))


def make(tmp_path, driver, replies, env="dev", **kw):
    store = RunStore(tmp_path / "run")
    llm = FakeLLM(replies)
    loop = AgentLoop(driver=driver, llm=llm, guard=Guard(env, ["app.test"]), store=store,
                     masker=Masker(["s3cret!"]), data_prefix="QA-AUTO-TEST", **kw)
    return loop, llm, store


def test_click_then_done_pass(tmp_path):
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")})
    loop, llm, store = make(tmp_path, driver, [act(action="click", element=1, thought="buka"),
                                              act(action="done", status="pass", actual="Daftar pengguna tampil")])
    out = loop.run("TC-1", "Buka halaman pengguna")
    assert (out.final, out.status, out.actual, out.steps) == ("done", "pass", "Daftar pengguna tampil", 2)
    steps = store.read_steps()
    assert [s.action for s in steps] == ["click", "done"]
    assert steps[0].element["name"] == "Pengguna"
    assert all((store.root / s.screenshot).exists() for s in steps)
    system, messages = llm.calls[0]
    assert system.startswith("MODE: EXECUTE") and "QA-AUTO-TEST" in system
    assert "Buka halaman pengguna" in messages[0].text and messages[0].images


def test_invalid_json_retried_then_recorded(tmp_path):
    driver = FakeDriver([HOME], url("home"))
    loop, llm, store = make(tmp_path, driver, ["bukan json", "masih bukan", act(action="done", status="pass", actual="ok")])
    out = loop.run("TC-1", "x")
    assert out.final == "done"
    assert len(llm.calls) == 3
    assert "tidak valid" in llm.calls[1][1][-1].text
    first = store.read_steps()[0]
    assert first.action == "invalid" and first.result.startswith("error")


def test_production_guard_block_is_reported_to_ai(tmp_path):
    driver = FakeDriver([HOME], url("home"))
    loop, llm, store = make(tmp_path, driver, [act(action="click", element=2), act(action="blocked", reason="aksi diblok")], env="production")
    out = loop.run("TC-1", "Hapus pengguna")
    assert out.final == "blocked" and out.guard_blocks == 1
    assert driver.executed == []
    assert "diblok Safety Guard" in llm.calls[1][1][0].text
    assert store.read_steps()[0].guard.startswith("blocked:")


def test_repeated_action_warns_then_blocks(tmp_path):
    driver = FakeDriver([HOME], url("home"))  # klik tidak mengubah layar
    loop, llm, _ = make(tmp_path, driver, [act(action="click", element=1)] * 4)
    out = loop.run("TC-1", "x")
    assert out.final == "blocked" and out.error_kind == "loop"
    assert "PERINGATAN" in llm.calls[3][1][0].text
    assert len(driver.executed) == 3


def test_max_steps(tmp_path):
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users"), (url("users"), "Dashboard"): url("home")})
    loop, _, _ = make(tmp_path, driver, [act(action="click", element=1), act(action="click", element=1)], max_steps=2)
    out = loop.run("TC-1", "x")
    assert out.final == "blocked" and out.error_kind == "max_steps" and out.steps == 2


def test_password_never_reaches_ai_or_logs(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"), {(url("login"), "Masuk"): url("home")})
    driver.set_credentials("qa@app.test", "s3cret!")
    loop, llm, store = make(tmp_path, driver, [
        act(action="type", element=1, value="{{username}}"),
        act(action="type", element=2, value="{{password}}"),
        act(action="click", element=3),
        act(action="done", status="pass", actual="masuk"),
    ])
    out = loop.run("LOGIN-1", "Login", login=True)
    assert out.status == "pass"
    assert ("type", "Password", "s3cret!") in driver.executed
    assert all("s3cret!" not in m.text for _, msgs in llm.calls for m in msgs)
    raw = store.steps_path.read_text(encoding="utf-8")
    assert "s3cret!" not in raw and SECRET_MASK in raw


def test_element_error_is_retried_once(tmp_path):
    driver = FakeDriver([HOME, USERS], url("home"), {(url("home"), "Pengguna"): url("users")}, fail_first=1)
    loop, _, store = make(tmp_path, driver, [act(action="click", element=1), act(action="done", status="pass", actual="ok")])
    loop.run("TC-1", "x")
    assert store.read_steps()[0].result == "ok"
    assert driver.executed == [("click", "Pengguna", None)]


def test_fatal_driver_error_raises(tmp_path):
    driver = FakeDriver([HOME], url("home"), fatal=True)
    loop, _, _ = make(tmp_path, driver, [act(action="click", element=1)])
    with pytest.raises(DriverCrashed):
        loop.run("TC-1", "x")


def test_stop_flag_interrupts(tmp_path):
    driver = FakeDriver([HOME], url("home"))
    loop, llm, _ = make(tmp_path, driver, [], should_stop=lambda: True)
    out = loop.run("TC-1", "x")
    assert out.error_kind == "interrupted" and llm.calls == []


def test_relogin_once_when_session_expires(tmp_path):
    driver = FakeDriver([HOME, LOGIN], url("home"), {(url("home"), "Pengguna"): url("login")})
    calls = []

    def relogin(return_to):
        calls.append(return_to)
        driver.current = url("home")

    loop, llm, _ = make(tmp_path, driver, [act(action="click", element=1), act(action="done", status="pass", actual="ok")], relogin=relogin)
    out = loop.run("TC-1", "x")
    assert calls == [url("home")]
    assert "Sesi login kedaluwarsa" in llm.calls[1][1][0].text
    assert out.status == "pass"


def test_relogin_not_repeated(tmp_path):
    driver = FakeDriver([HOME, LOGIN], url("home"), {(url("home"), "Pengguna"): url("login")})
    calls = []
    loop, _, _ = make(tmp_path, driver, [act(action="click", element=1), act(action="blocked", reason="tetap di login")], relogin=calls.append)
    out = loop.run("TC-1", "x")
    assert calls == [url("home")] and out.final == "blocked"
```

- [ ] **Step 3: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_agent_loop.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'qa_agent.agent.loop'`

- [ ] **Step 4: Implementasi**

`qa_agent/agent/loop.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from qa_agent.agent import prompts
from qa_agent.agent.loop_detect import LoopDetector
from qa_agent.agent.parser import ActionParseError, parse_action
from qa_agent.drivers.base import Driver, DriverCrashed
from qa_agent.evidence import Masker, RunStore, now_iso
from qa_agent.guard import Guard
from qa_agent.llm.base import LLMClient, Message
from qa_agent.models import Action, Element, Observation, Signal, StepRecord
from qa_agent.report.humanize import humanize

HISTORY_WINDOW = 8


@dataclass
class LoopOutcome:
    final: Literal["done", "blocked"]
    status: Literal["pass", "fail"] | None = None
    actual: str = ""
    reason: str = ""
    severity: str | None = None
    steps: int = 0
    guard_blocks: int = 0
    signals: list[Signal] = field(default_factory=list)
    error_kind: str = ""  # "", "max_steps", "loop", "interrupted", "agent"


def find_same(obs: Observation, element: Element) -> Element | None:
    for e in obs.elements:
        if e.selector and e.selector == element.selector:
            return e
    for e in obs.elements:
        if e.role == element.role and e.name == element.name:
            return e
    return None


def _element_dict(element: Element | None) -> dict[str, str] | None:
    if element is None:
        return None
    return {"role": element.role, "name": element.name, "selector": element.selector}


class AgentLoop:
    def __init__(
        self,
        *,
        driver: Driver,
        llm: LLMClient,
        guard: Guard,
        store: RunStore,
        masker: Masker,
        data_prefix: str,
        platform: str = "web",
        max_steps: int = 25,
        vision: bool = True,
        relogin: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.driver = driver
        self.llm = llm
        self.guard = guard
        self.store = store
        self.masker = masker
        self.data_prefix = data_prefix
        self.platform = platform
        self.max_steps = max_steps
        self.vision = vision
        self.relogin = relogin
        self.should_stop = should_stop

    def run(self, tc_id: str, goal: str, *, allow_logout: bool = False, login: bool = False) -> LoopOutcome:
        system = prompts.execute_system(self.platform, self.data_prefix)
        history: list[str] = []
        notes: list[str] = []
        signals: list[Signal] = []
        detector = LoopDetector()
        guard_blocks = 0
        relogged = False
        last_location = ""
        obs = self.driver.observe()

        for step_no in range(1, self.max_steps + 1):
            if self.should_stop():
                return LoopOutcome(final="blocked", reason="Dihentikan pengguna (Ctrl+C)", steps=step_no - 1,
                                   guard_blocks=guard_blocks, signals=signals, error_kind="interrupted")

            if self.relogin and not (login or allow_logout or relogged) and obs.is_login_screen and last_location:
                relogged = True
                self.relogin(last_location)
                obs = self.driver.observe()
                notes.append("Sesi login kedaluwarsa; sistem sudah login ulang dan kembali ke halaman terakhir. Lanjutkan tujuan.")

            signals.extend(obs.signals)
            message = prompts.step_message(goal, obs, history[-HISTORY_WINDOW:], notes, self.vision)
            notes = []
            try:
                action = self._decide(system, message, len(obs.elements))
            except ActionParseError as e:
                self._record(tc_id, step_no, obs, None, None, f"error: jawaban AI tidak valid ({e})")
                history.append(f"{step_no}. (jawaban AI tidak valid)")
                continue

            by_index = {e.index: e for e in obs.elements}
            element = by_index.get(action.element) if action.element is not None else None

            if action.action in ("done", "blocked"):
                shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", self.driver.screenshot())
                self._record(tc_id, step_no, obs, action, None, "ok", shot)
                if action.action == "done":
                    return LoopOutcome(final="done", status=action.status, actual=self.masker.mask(action.actual or "") or "",
                                       severity=action.severity, steps=step_no, guard_blocks=guard_blocks, signals=signals)
                return LoopOutcome(final="blocked", reason=self.masker.mask(action.reason or "AI menyatakan blocked") or "",
                                   actual=self.masker.mask(action.actual or "") or "", steps=step_no,
                                   guard_blocks=guard_blocks, signals=signals, error_kind="agent")

            target = element.selector if element is not None else (action.value or "")
            verdict = detector.record(obs.fingerprint, action.action, target)
            if verdict == "block":
                self._record(tc_id, step_no, obs, action, element, "error: langkah berulang tanpa kemajuan")
                return LoopOutcome(final="blocked", reason="Langkah yang sama diulang tanpa kemajuan", steps=step_no,
                                   guard_blocks=guard_blocks, signals=signals, error_kind="loop")
            if verdict == "warn":
                notes.append("PERINGATAN: aksi ini sudah dicoba berulang kali di layar yang sama. Pilih aksi lain atau nyatakan blocked.")

            description = humanize(action.action, _element_dict(element), self.masker.mask(action.value))
            decision = self.guard.check(action, element, allow_logout=allow_logout, login=login)
            if not decision.allowed:
                guard_blocks += 1
                shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", self.driver.screenshot(highlight=element))
                self._record(tc_id, step_no, obs, action, element, "skipped", shot, guard=f"blocked: {decision.reason}")
                notes.append(f"Aksi '{description}' diblok Safety Guard: {decision.reason}. Cari jalan lain atau nyatakan blocked.")
                history.append(f"{step_no}. {description} → DIBLOK")
                continue

            before = self.driver.screenshot(highlight=element) if action.action == "click" and element is not None else None
            result = self.driver.execute(action, element)
            if not result.ok and not result.fatal and element is not None:
                fresh = self.driver.observe()
                again = find_same(fresh, element)
                if again is not None:
                    element = again
                    result = self.driver.execute(action, again)
            if result.fatal:
                raise DriverCrashed(result.error or "Browser tertutup")

            after = before if before is not None else self.driver.screenshot(
                highlight=element if action.action in ("type", "select") else None)
            shot = self.store.save_screenshot(f"{tc_id}_step-{step_no:02d}", after)
            outcome_text = "ok" if result.ok else f"error: {result.error}"
            self._record(tc_id, step_no, obs, action, element, outcome_text, shot)
            history.append(f"{step_no}. {description} → {'ok' if result.ok else 'gagal: ' + (self.masker.mask(result.error) or '')}")
            last_location = obs.location
            obs = self.driver.observe()

        return LoopOutcome(final="blocked", reason=f"Batas {self.max_steps} langkah tercapai", steps=self.max_steps,
                           guard_blocks=guard_blocks, signals=signals, error_kind="max_steps")

    def _decide(self, system: str, message: Message, element_count: int) -> Action:
        reply = self.llm.chat(system, [message])
        try:
            return parse_action(reply, element_count)
        except ActionParseError as e:
            retry = [message, Message(role="assistant", text=reply or ""), prompts.retry_message(str(e))]
            return parse_action(self.llm.chat(system, retry), element_count)

    def _record(self, tc_id: str, step_no: int, obs: Observation, action: Action | None, element: Element | None,
                result: str, screenshot: str | None = None, guard: str = "allowed") -> None:
        if action is None:
            value = None
        elif action.action == "done":
            value = action.status
        elif action.action == "blocked":
            value = action.reason
        else:
            value = action.value
        self.store.append_step(StepRecord(
            tc_id=tc_id,
            step_no=step_no,
            timestamp=now_iso(),
            location=obs.location,
            fingerprint=obs.fingerprint,
            thought=self.masker.mask(action.thought) if action else "",
            action=action.action if action else "invalid",
            element=_element_dict(element),
            value=self.masker.mask(value),
            expect=action.expect if action else "",
            guard=guard,
            result=self.masker.mask(result) or "",
            signals=obs.signals,
            screenshot=screenshot,
        ))
```

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_agent_loop.py -v`
Expected: `11 passed`

- [ ] **Step 6: Commit**

```bash
git add qa_agent/agent/loop.py tests/fakes.py tests/unit/test_agent_loop.py
git commit -m "feat: agent loop observe-think-guard-act-verify-record"
```

---

### Task 15: Auth (login, simpan sesi, login ulang)

**Files:**
- Create: `qa_agent/orchestrator/auth.py`
- Test: `tests/unit/test_auth.py`

**Interfaces:**
- Consumes: `Driver` (Task 11), `LoopOutcome` (Task 14), `slugify` (Task 8)
- Produces:
  - `class LoginFailed(Exception)`, `login_goal(role: str) -> str`, `auth_state_path(project_dir: Path, target_url: str, role: str) -> Path` (→ `<project>/.qa-agent/auth/<host>-<role>.json`)
  - `AuthManager(driver, run_login: Callable[[str, str], LoopOutcome], state_path: Path, role: str)`
  - `AuthManager.login()`: driver harus sedang di halaman login. Melempar `LoginFailed`.
  - `AuthManager.start_authenticated(url: str)`: sesi baru dari state tersimpan, login jika diarahkan ke halaman login.
  - `AuthManager.relogin(return_to: str)`: login lalu kembali ke `return_to`.

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_auth.py`:

```python
import pytest

from qa_agent.agent.loop import LoopOutcome
from qa_agent.orchestrator.auth import AuthManager, LoginFailed, auth_state_path
from tests.fakes import FakeDriver, el, screen, url

LOGIN = screen("login", el(1, "input", "Email"), el(2, "input", "Password", input_type="password"), el(3, "button", "Masuk"))
HOME = screen("home", el(1, "link", "Pengguna"))
USERS = screen("users", el(1, "link", "Dashboard"))


def outcome(status="pass", final="done"):
    return LoopOutcome(final=final, status=status, actual="hasil login")


def test_auth_state_path(tmp_path):
    p = auth_state_path(tmp_path, "https://app-dev.kantor.local:8443", "Admin QA")
    assert p == tmp_path / ".qa-agent" / "auth" / "app-dev-kantor-local-8443-admin-qa.json"


def test_login_success_saves_state(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"))
    calls = []

    def run_login(tc_id, goal):
        calls.append((tc_id, goal))
        driver.current = url("home")
        return outcome()

    AuthManager(driver, run_login, tmp_path / "s.json", "admin").login()
    assert driver.saved == [tmp_path / "s.json"]
    tc_id, goal = calls[0]
    assert tc_id.startswith("LOGIN-") and "{{password}}" in goal and "'admin'" in goal


def test_login_ids_are_unique(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"))
    ids = []

    def run_login(tc_id, goal):
        ids.append(tc_id)
        driver.current = url("home")
        return outcome()

    auth = AuthManager(driver, run_login, tmp_path / "s.json", "admin")
    auth.login()
    driver.current = url("login")
    auth.login()
    assert len(set(ids)) == 2


def test_login_failure_raises(tmp_path):
    driver = FakeDriver([LOGIN], url("login"))
    auth = AuthManager(driver, lambda t, g: outcome("fail"), tmp_path / "s.json", "admin")
    with pytest.raises(LoginFailed, match="hasil login"):
        auth.login()
    assert driver.saved == []


def test_login_claimed_pass_but_form_still_shown(tmp_path):
    driver = FakeDriver([LOGIN], url("login"))
    auth = AuthManager(driver, lambda t, g: outcome(), tmp_path / "s.json", "admin")
    with pytest.raises(LoginFailed, match="masih tampil"):
        auth.login()


def test_start_authenticated_reuses_session(tmp_path):
    driver = FakeDriver([LOGIN, HOME], url("login"))
    auth = AuthManager(driver, lambda t, g: pytest.fail("tidak boleh login ulang"), tmp_path / "s.json", "admin")
    auth.start_authenticated(url("home"))
    assert driver.sessions == [tmp_path / "s.json"] and driver.current == url("home")


class RedirectDriver(FakeDriver):
    logged_in = False

    def goto(self, location):
        super().goto(location if self.logged_in else url("login"))


def test_start_authenticated_logs_in_when_redirected(tmp_path):
    driver = RedirectDriver([LOGIN, HOME], url("login"))

    def run_login(tc_id, goal):
        driver.logged_in = True
        driver.current = url("home")
        return outcome()

    AuthManager(driver, run_login, tmp_path / "s.json", "admin").start_authenticated(url("home"))
    assert driver.current == url("home") and driver.saved


def test_relogin_returns_to_page(tmp_path):
    driver = FakeDriver([LOGIN, HOME, USERS], url("login"))

    def run_login(tc_id, goal):
        driver.current = url("home")
        return outcome()

    AuthManager(driver, run_login, tmp_path / "s.json", "admin").relogin(url("users"))
    assert driver.current == url("users")
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_auth.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/orchestrator/auth.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from qa_agent.agent.loop import LoopOutcome
from qa_agent.drivers.base import Driver
from qa_agent.evidence import slugify

LOGIN_GOAL = (
    "Login ke aplikasi memakai akun peran '<<role>>'. Isi field username/email dengan {{username}} "
    "dan field password dengan {{password}}, lalu klik tombol login/masuk. Nyatakan done dengan status pass "
    "jika sudah berhasil masuk (form login hilang), atau status fail jika login ditolak."
)


class LoginFailed(Exception):
    """Login otomatis tidak berhasil."""


def login_goal(role: str) -> str:
    return LOGIN_GOAL.replace("<<role>>", role)


def auth_state_path(project_dir: Path, target_url: str, role: str) -> Path:
    host = urlsplit(target_url).netloc or target_url
    return Path(project_dir) / ".qa-agent" / "auth" / f"{slugify(host)}-{slugify(role)}.json"


class AuthManager:
    def __init__(self, driver: Driver, run_login: Callable[[str, str], LoopOutcome], state_path: Path, role: str) -> None:
        self.driver = driver
        self.run_login = run_login
        self.state_path = Path(state_path)
        self.role = role
        self._count = 0

    def _next_id(self) -> str:
        self._count += 1
        return f"LOGIN-{datetime.now():%H%M%S}-{self._count}"

    def login(self) -> None:
        """Driver harus sedang berada di halaman login."""
        outcome = self.run_login(self._next_id(), login_goal(self.role))
        if outcome.final != "done" or outcome.status != "pass":
            raise LoginFailed(outcome.actual or outcome.reason or "Login tidak berhasil")
        if self.driver.observe().is_login_screen:
            raise LoginFailed("AI menyatakan berhasil, tetapi form login masih tampil")
        self.driver.save_auth_state(self.state_path)

    def start_authenticated(self, url: str) -> None:
        self.driver.new_session(self.state_path)
        self.driver.goto(url)
        if self.driver.observe().is_login_screen:
            self.login()
            self.driver.goto(url)
            if self.driver.observe().is_login_screen:
                raise LoginFailed("Masih diarahkan ke halaman login setelah login berhasil")

    def relogin(self, return_to: str) -> None:
        self.login()
        self.driver.goto(return_to)
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_auth.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/orchestrator/auth.py tests/unit/test_auth.py
git commit -m "feat: auth manager (login AI, simpan storage_state, login ulang)"
```

---

### Task 16: Mode Explore

**Files:**
- Create: `qa_agent/orchestrator/explore.py`
- Test: `tests/unit/test_explore.py`

**Interfaces:**
- Consumes: `Driver`, `DriverCrashed`, `LLMClient`, `LLMError`, `Guard`, `RunStore`, `AuthManager`, `LoginFailed`, `prompts.explore_system/explore_message`, `extract_json`, `normalize_location`
- Produces:
  - `ScreenSummary(module, page_name, purpose, forms, actions, nav_candidates: list[int])`
  - `Explorer(*, driver, llm, guard, store, auth: AuthManager | None, start_url, max_screens=60, max_depth=5, max_minutes=45, vision=True, clock=time.monotonic, should_stop=lambda: False)`
  - `Explorer.run() -> AppMap`: menulis `app_map.json` + screenshot `explore_NNN` + step `tc_id="EXPLORE"` setiap kali menemukan layar baru

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_explore.py`:

```python
import itertools
import json
import re

from qa_agent.evidence import RunStore
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from qa_agent.orchestrator.explore import Explorer
from tests.fakes import BASE, FakeDriver, el, screen, url

LOGIN = screen("login", el(1, "input", "Email"), el(2, "input", "Password", input_type="password"), el(3, "button", "Masuk"))
HOME = screen("home", el(1, "link", "Pengguna", href=url("users")), el(2, "link", "Laporan", href=url("reports")),
              el(3, "button", "Keluar"), el(4, "link", "Bantuan", href="https://docs.other.test/"))
USERS = screen("users", el(1, "link", "Tambah Pengguna", href=url("users/new")), el(2, "link", "Edit", href=url("users/1/edit")),
               el(3, "link", "Edit", href=url("users/2/edit")), el(4, "button", "Hapus"), el(5, "button", "Ekspor"))
NEW = screen("users/new", el(1, "input", "Nama"), el(2, "button", "Simpan"))
EDIT1 = screen("users/1/edit", el(1, "input", "Nama"), el(2, "button", "Simpan"))
EDIT2 = screen("users/2/edit", el(1, "input", "Nama"), el(2, "button", "Simpan"))
REPORTS = screen("reports", el(1, "button", "Tab Arsip"))
ARCHIVE = screen("archive", el(1, "link", "Pengguna", href=url("users")))
ALL = [LOGIN, HOME, USERS, NEW, EDIT1, EDIT2, REPORTS, ARCHIVE]
TRANSITIONS = {(url("reports"), "Tab Arsip"): url("archive")}
MODULES = {"login": "Autentikasi", "home": "Dashboard", "users": "Pengguna", "reports": "Laporan", "archive": "laporan"}


def summarizer(system, messages):
    """AI 'nakal' yang memasukkan SEMUA elemen ke nav_candidates; guard harus menyaringnya."""
    assert system.startswith("MODE: EXPLORE_SCREEN")
    text = messages[0].text
    path = re.search(r"^URL: (\S+)", text, re.M).group(1).replace(BASE + "/", "")
    indices = [int(i) for i in re.findall(r"^\[(\d+)\]", text, re.M)]
    return json.dumps({"module": MODULES[path.split("/")[0]], "page_name": path, "purpose": f"Halaman {path}",
                       "nav_candidates": indices})


class StubAuth:
    def __init__(self, driver):
        self.driver = driver
        self.logins = 0

    def login(self):
        self.logins += 1
        self.driver.current = url("home")


def make(tmp_path, driver, llm=None, start="login", **kw):
    store = RunStore(tmp_path / "run")
    auth = StubAuth(driver)
    explorer = Explorer(driver=driver, llm=llm or FakeLLM(summarizer), guard=Guard("dev", ["app.test"]), store=store,
                        auth=auth, start_url=url(start), **kw)
    return explorer, store, auth


def test_explore_maps_app_and_respects_guard(tmp_path):
    driver = FakeDriver(ALL, url("login"), TRANSITIONS)
    explorer, store, auth = make(tmp_path, driver)
    app_map = explorer.run()
    paths = [s.url.replace(BASE + "/", "") for s in app_map.screens]
    assert paths[0] == "login" and app_map.screens[0].public and auth.logins == 1
    assert set(paths) == {"login", "home", "users", "reports", "users/new", "users/1/edit", "archive"}
    assert app_map.modules() == ["Autentikasi", "Dashboard", "Pengguna", "Laporan"]
    clicked = [name for (_, name, _) in driver.executed]
    assert "Hapus" not in clicked and "Keluar" not in clicked and "Simpan" not in clicked
    assert ("click", "Tab Arsip", None) in driver.executed
    assert not any(g.startswith("https://docs.other.test") for g in driver.gotos)
    assert store.read_app_map() == app_map
    assert (store.root / app_map.screens[0].screenshot).exists()
    assert [s.tc_id for s in store.read_steps()] == ["EXPLORE"] * len(paths)


def test_max_screens(tmp_path):
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("login"), TRANSITIONS), max_screens=3)
    assert len(explorer.run().screens) == 3


def test_time_limit(tmp_path):
    ticks = itertools.chain([0, 0], itertools.repeat(10_000))
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("login"), TRANSITIONS), clock=lambda: next(ticks))
    assert [s.url for s in explorer.run().screens] == [url("login"), url("home")]


def test_no_login_page(tmp_path):
    explorer, _, auth = make(tmp_path, FakeDriver(ALL, url("home"), TRANSITIONS), start="home", max_screens=2)
    app_map = explorer.run()
    assert auth.logins == 0 and not app_map.screens[0].public


def test_summary_fallback_follows_links(tmp_path):
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("home"), TRANSITIONS), llm=FakeLLM(lambda s, m: "bukan json"),
                          start="home", max_screens=2)
    app_map = explorer.run()
    assert app_map.screens[0].module == "Lainnya"
    assert app_map.screens[1].url == url("users")


def test_stop_flag(tmp_path):
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("home"), TRANSITIONS), start="home", should_stop=lambda: True)
    assert explorer.run().screens == []
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_explore.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/orchestrator/explore.py`:

```python
from __future__ import annotations

import time
from collections import deque
from typing import Callable
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from qa_agent.agent import prompts
from qa_agent.agent.parser import ActionParseError, extract_json
from qa_agent.drivers.base import Driver, DriverCrashed
from qa_agent.evidence import RunStore, now_iso
from qa_agent.guard import Guard
from qa_agent.llm.base import LLMClient, LLMError
from qa_agent.models import Action, AppMap, Observation, ScreenInfo, StepRecord
from qa_agent.orchestrator.auth import AuthManager, LoginFailed
from qa_agent.orchestrator.fingerprint import normalize_location

MAX_CLICK_PROBES = 10


class ScreenSummary(BaseModel):
    module: str = "Lainnya"
    page_name: str = ""
    purpose: str = ""
    forms: list[dict] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    nav_candidates: list[int] = Field(default_factory=list)


def _clean_href(href: str) -> str:
    """Buang anchor biasa (#bagian), pertahankan hash-route SPA (#/halaman)."""
    fragment = urlsplit(href).fragment
    if fragment and not fragment.startswith("/"):
        return href.split("#", 1)[0]
    return href


class Explorer:
    def __init__(
        self,
        *,
        driver: Driver,
        llm: LLMClient,
        guard: Guard,
        store: RunStore,
        auth: AuthManager | None,
        start_url: str,
        max_screens: int = 60,
        max_depth: int = 5,
        max_minutes: int = 45,
        vision: bool = True,
        clock: Callable[[], float] = time.monotonic,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.driver = driver
        self.llm = llm
        self.guard = guard
        self.store = store
        self.auth = auth
        self.start_url = start_url
        self.max_screens = max_screens
        self.max_depth = max_depth
        self.max_minutes = max_minutes
        self.vision = vision
        self.clock = clock
        self.should_stop = should_stop

    def run(self) -> AppMap:
        app_map = AppMap(target=self.start_url)
        deadline = self.clock() + self.max_minutes * 60
        if self.should_stop():
            return app_map
        self.driver.new_session(None)
        self.driver.goto(self.start_url)
        first = self.driver.observe()
        if first.is_login_screen:
            self._add_screen(app_map, first, depth=0, parent=None, public=True)
            if self.auth is None:
                raise LoginFailed("Aplikasi butuh login tetapi akun belum dikonfigurasi")
            self.auth.login()

        visited = {normalize_location(s.url) for s in app_map.screens}
        queue: deque[tuple[str, int, str | None]] = deque([(self.driver.current_url, 0, None)])
        while queue and not self._exhausted(app_map, deadline):
            target, depth, parent = queue.popleft()
            key = normalize_location(target)
            if key in visited or not self.guard.is_allowed_url(target):
                continue
            obs = self._open(target)
            visited.add(key)
            if obs is None:
                continue
            landed = normalize_location(obs.location)
            if landed != key and landed in visited:
                continue  # diarahkan ke layar yang sudah dicatat
            visited.add(landed)
            summary, info = self._add_screen(app_map, obs, depth, parent)
            if depth < self.max_depth:
                for next_url in self._discover(obs, summary, target):
                    if normalize_location(next_url) not in visited:
                        queue.append((next_url, depth + 1, info.fingerprint))
        return app_map

    def _exhausted(self, app_map: AppMap, deadline: float) -> bool:
        return len(app_map.screens) >= self.max_screens or self.clock() >= deadline or self.should_stop()

    def _open(self, target: str) -> Observation | None:
        try:
            self.driver.goto(target)
            obs = self.driver.observe()
            if obs.is_login_screen and self.auth is not None:
                self.auth.login()  # sesi kedaluwarsa
                self.driver.goto(target)
                obs = self.driver.observe()
                if obs.is_login_screen:
                    return None
            return obs
        except (LLMError, LoginFailed, DriverCrashed):
            raise
        except Exception as e:
            self.store.append_step(StepRecord(tc_id="EXPLORE", step_no=0, timestamp=now_iso(), location=target,
                                              action="navigate", value=target, result=f"error: {type(e).__name__}: {e}"))
            return None

    def _summarize(self, obs: Observation, known_modules: list[str]) -> ScreenSummary:
        system = prompts.explore_system(known_modules)
        message = prompts.explore_message(obs, self.vision)
        for _ in range(2):
            try:
                return ScreenSummary.model_validate(extract_json(self.llm.chat(system, [message])))
            except (ActionParseError, ValidationError):
                continue
        links = [e.index for e in obs.elements if e.role == "link"]
        return ScreenSummary(module="Lainnya", page_name=obs.title or obs.location, nav_candidates=links)

    def _add_screen(self, app_map: AppMap, obs: Observation, depth: int, parent: str | None,
                    public: bool = False) -> tuple[ScreenSummary, ScreenInfo]:
        summary = self._summarize(obs, app_map.modules())
        module = app_map.find_module(summary.module) or (" ".join(summary.module.split()) or "Lainnya")
        n = len(app_map.screens) + 1
        shot = self.store.save_screenshot(f"explore_{n:03d}", self.driver.screenshot())
        info = ScreenInfo(
            fingerprint=obs.fingerprint, url=obs.location, module=module,
            page_name=summary.page_name or obs.title or obs.location, purpose=summary.purpose,
            forms=summary.forms, actions=summary.actions, screenshot=shot, depth=depth, parent=parent, public=public,
        )
        app_map.screens.append(info)
        self.store.write_app_map(app_map)
        self.store.append_step(StepRecord(
            tc_id="EXPLORE", step_no=n, timestamp=now_iso(), location=obs.location, fingerprint=obs.fingerprint,
            thought=summary.purpose, action="navigate", value=obs.location, signals=obs.signals, screenshot=shot,
        ))
        return summary, info

    def _discover(self, obs: Observation, summary: ScreenSummary, current: str) -> list[str]:
        by_index = {e.index: e for e in obs.elements}
        found: list[str] = []
        probes: list[tuple[str, str]] = []
        for idx in summary.nav_candidates:
            element = by_index.get(idx)
            if element is None:
                continue
            if not self.guard.check(Action(action="click", element=idx), element, explore=True).allowed:
                continue
            if element.href and element.href.startswith(("http://", "https://")):
                found.append(_clean_href(element.href))
            else:
                probes.append((element.role, element.name))
        for role, name in probes[:MAX_CLICK_PROBES]:
            if self.should_stop():
                break
            target = self._click_probe(current, role, name)
            if target:
                found.append(target)
        return found

    def _click_probe(self, current: str, role: str, name: str) -> str | None:
        """Klik elemen tanpa href (tab/menu SPA) untuk melihat apakah pindah halaman."""
        try:
            self.driver.goto(current)
            obs = self.driver.observe()
            element = next((e for e in obs.elements if e.role == role and e.name == name), None)
            if element is None:
                return None
            before = normalize_location(self.driver.current_url)
            result = self.driver.execute(Action(action="click", element=element.index), element)
            after = self.driver.current_url
            if result.ok and normalize_location(after) != before and self.guard.is_allowed_url(after):
                return after
            return None
        except (LLMError, LoginFailed, DriverCrashed):
            raise
        except Exception:
            return None
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_explore.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/orchestrator/explore.py tests/unit/test_explore.py
git commit -m "feat: mode explore (BFS layar, ringkasan AI, inventaris fitur)"
```

---

### Task 17: Mode Deep — penyusunan test case & penilaian status

**Files:**
- Create: `qa_agent/orchestrator/deep.py` (bagian planner + judge, runner ditambahkan di Task 18)
- Test: `tests/unit/test_deep_plan.py`

**Interfaces:**
- Consumes: `AppMap`, `QaTestCase`, `ScreenInfo`, `Signal` (Task 3), `module_abbr` (Task 8), `prompts.plan_system/plan_message` (Task 13), `extract_json`, `ActionParseError` (Task 6), `LoopOutcome` (Task 14), `LOGOUT_KEYWORDS` (Task 5)
- Produces:
  - `class PlanError(Exception)`, `PlannedCase` (model jawaban AI)
  - `DeepPlanner(llm, *, data_prefix: str, max_tcs: int = 15)` dengan `.plan(app_map, module, prd_text=None) -> list[QaTestCase]`
  - `judge(outcome: LoopOutcome, tc: QaTestCase) -> tuple[str, str | None]` (status, severity)
  - `goal_for(tc: QaTestCase) -> str` (baris pertama: `"Jalankan test case <ID>: <judul>"`)
  - `is_logout_case(tc: QaTestCase) -> bool`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_deep_plan.py`:

```python
import json

import pytest

from qa_agent.agent.loop import LoopOutcome
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import AppMap, QaTestCase, ScreenInfo, Signal
from qa_agent.orchestrator.deep import DeepPlanner, PlanError, goal_for, is_logout_case, judge
from tests.fakes import url


def app_map():
    return AppMap(target=url(""), screens=[
        ScreenInfo(fingerprint="a", url=url("users"), module="Pengguna", page_name="Daftar Pengguna"),
        ScreenInfo(fingerprint="b", url=url("users/new"), module="Pengguna", page_name="Tambah Pengguna",
                   forms=[{"name": "Form", "fields": [{"label": "Nama", "type": "text"}]}]),
        ScreenInfo(fingerprint="c", url=url("reports"), module="Laporan", page_name="Laporan"),
    ])


CASE = {"title": "Tambah valid", "page": "Tambah Pengguna", "type": "Positif", "priority": "high",
        "steps": ["Isi form", "Klik Simpan"], "expected": "Tersimpan", "expected_source": "PRD",
        "start_url": "/users/new", "test_data": {"Nama": "QA-AUTO Budi"}}


def planner(replies, max_tcs=15):
    llm = FakeLLM(replies)
    return DeepPlanner(llm, data_prefix="QA-AUTO-X", max_tcs=max_tcs), llm


def test_plan_builds_ids_and_resolves_start():
    reply = {"test_cases": [CASE, {**CASE, "title": "Tanpa expected", "expected": None},
                            {**CASE, "title": "Validasi", "type": "validasi", "start_url": "", "page": "daftar pengguna"}]}
    p, llm = planner([json.dumps(reply)])
    cases = p.plan(app_map(), "Pengguna", prd_text="PRD: email wajib valid")
    assert [c.id for c in cases] == ["TC-PEN-001", "TC-PEN-002"]
    first, second = cases
    assert first.start_url == url("users/new") and first.type == "positif" and first.priority == "High"
    assert first.expected_source == "PRD"
    assert json.loads(first.test_data) == {"Nama": "QA-AUTO Budi"}
    assert second.title == "Validasi" and second.start_url == url("users")
    system, messages = llm.calls[0]
    assert system.startswith("MODE: PLAN") and "## PRD" in messages[0].text


def test_expected_source_forced_to_inference_without_prd():
    p, _ = planner([json.dumps({"test_cases": [CASE]})])
    assert p.plan(app_map(), "Pengguna")[0].expected_source == "Inferensi AI"


def test_module_name_tolerant_and_unknown_lists_modules():
    p, _ = planner([json.dumps({"test_cases": [CASE]})])
    assert p.plan(app_map(), "  pengguna ")[0].module == "Pengguna"
    unknown, _ = planner([])
    with pytest.raises(PlanError, match="Pengguna, Laporan"):
        unknown.plan(app_map(), "Transaksi")


def test_invalid_reply_retried_then_plan_error():
    p, llm = planner(["bukan json", '{"test_cases": "x"}'])
    with pytest.raises(PlanError, match="gagal"):
        p.plan(app_map(), "Pengguna")
    assert len(llm.calls) == 2 and "tidak valid" in llm.calls[1][1][-1].text


def test_max_tcs_truncates():
    p, _ = planner([json.dumps({"test_cases": [CASE] * 5})], max_tcs=3)
    assert len(p.plan(app_map(), "Pengguna")) == 3


def test_steps_string_is_split():
    p, _ = planner([json.dumps({"test_cases": [{**CASE, "steps": "1. Buka\n2. Klik"}]})])
    assert p.plan(app_map(), "Pengguna")[0].steps == ["1. Buka", "2. Klik"]


TC_AI = QaTestCase(id="T", module="M", title="t", expected="e")
TC_PRD = TC_AI.model_copy(update={"expected_source": "PRD"})
SIG500 = Signal(kind="http_error", message="HTTP 500", status=500)


@pytest.mark.parametrize("outcome, tc, expected", [
    (LoopOutcome(final="done", status="pass", signals=[SIG500]), TC_AI, ("Fail", "Major")),
    (LoopOutcome(final="done", status="pass", signals=[Signal(kind="page_error", message="x")]), TC_AI, ("Fail", "Major")),
    (LoopOutcome(final="done", status="pass", signals=[Signal(kind="http_error", message="x", status=404)]), TC_AI, ("Pass", None)),
    (LoopOutcome(final="done", status="fail", severity="Critical"), TC_PRD, ("Fail", "Critical")),
    (LoopOutcome(final="done", status="fail"), TC_AI, ("Perlu Review", "Minor")),
    (LoopOutcome(final="done", status="pass"), TC_AI, ("Pass", None)),
    (LoopOutcome(final="blocked", error_kind="loop"), TC_AI, ("Blocked", None)),
    (LoopOutcome(final="blocked", guard_blocks=1, error_kind="agent"), TC_AI, ("Skipped", None)),
])
def test_judge(outcome, tc, expected):
    assert judge(outcome, tc) == expected


def test_goal_and_logout_detection():
    tc = QaTestCase(id="TC-AUT-001", module="Autentikasi", title="Logout dari aplikasi", steps=["Klik Keluar"], expected="Kembali ke login")
    goal = goal_for(tc)
    assert goal.startswith("Jalankan test case TC-AUT-001: Logout dari aplikasi\n")
    assert "1. Klik Keluar" in goal and "Expected result: Kembali ke login" in goal
    assert is_logout_case(tc)
    assert not is_logout_case(TC_AI)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_deep_plan.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/orchestrator/deep.py`:

```python
from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError, field_validator

from qa_agent.agent import prompts
from qa_agent.agent.loop import LoopOutcome
from qa_agent.agent.parser import ActionParseError, extract_json
from qa_agent.evidence import module_abbr
from qa_agent.guard import LOGOUT_KEYWORDS
from qa_agent.llm.base import LLMClient, Message
from qa_agent.models import AppMap, QaTestCase, ScreenInfo, TcType


class PlanError(Exception):
    """Test case tidak bisa disusun."""


class PlannedCase(BaseModel):
    title: str
    page: str = ""
    type: TcType = "positif"
    priority: Literal["High", "Medium", "Low"] = "Medium"
    precondition: str = ""
    test_data: str = ""
    steps: list[str]
    expected: str
    expected_source: Literal["PRD", "Inferensi AI"] = "Inferensi AI"
    start_url: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _type_lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_capitalized(cls, v):
        return v.strip().capitalize() if isinstance(v, str) else v

    @field_validator("precondition", "test_data", "page", "start_url", mode="before")
    @classmethod
    def _as_text(cls, v):
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    @field_validator("steps", mode="before")
    @classmethod
    def _steps_as_list(cls, v):
        if isinstance(v, str):
            return [line.strip() for line in v.splitlines() if line.strip()]
        return v

    @field_validator("expected_source", mode="before")
    @classmethod
    def _source(cls, v):
        return "PRD" if isinstance(v, str) and v.strip().upper() == "PRD" else "Inferensi AI"


def _resolve_start(planned: PlannedCase, screens: list[ScreenInfo]) -> str:
    urls = [s.url for s in screens]
    if planned.start_url in urls:
        return planned.start_url
    if planned.start_url:
        wanted = urlsplit(planned.start_url).path or planned.start_url
        for u in urls:
            if urlsplit(u).path == wanted:
                return u
    page = planned.page.strip().lower()
    for s in screens:
        if page and s.page_name.strip().lower() == page:
            return s.url
    return screens[0].url


class DeepPlanner:
    def __init__(self, llm: LLMClient, *, data_prefix: str, max_tcs: int = 15) -> None:
        self.llm = llm
        self.data_prefix = data_prefix
        self.max_tcs = max_tcs

    def plan(self, app_map: AppMap, module: str, prd_text: str | None = None) -> list[QaTestCase]:
        canonical = app_map.find_module(module)
        if canonical is None:
            available = ", ".join(app_map.modules()) or "(kosong)"
            raise PlanError(f"Modul '{module.strip()}' tidak ditemukan di hasil explore. Modul yang tersedia: {available}")
        screens = app_map.screens_for(canonical)
        system = prompts.plan_system(canonical, self.max_tcs, self.data_prefix, bool(prd_text))
        first = prompts.plan_message(screens, prd_text)
        messages = [first]
        error = ""
        for _ in range(2):
            reply = self.llm.chat(system, messages)
            try:
                items = extract_json(reply).get("test_cases")
                if not isinstance(items, list):
                    raise ActionParseError("field 'test_cases' harus berupa list")
                cases = self._to_cases(items, canonical, screens, has_prd=bool(prd_text))
                if cases:
                    return cases
                error = "tidak ada test case yang valid"
            except ActionParseError as e:
                error = str(e)
            messages = [first, Message(role="assistant", text=reply or ""),
                        Message(role="user", text=f"Jawaban tidak valid: {error}. Ulangi sesuai format.")]
        raise PlanError(f"AI gagal menyusun test case: {error}")

    def _to_cases(self, items: list, module: str, screens: list[ScreenInfo], *, has_prd: bool) -> list[QaTestCase]:
        abbr = module_abbr(module)
        cases: list[QaTestCase] = []
        for item in items:
            if len(cases) >= self.max_tcs:
                break
            if not isinstance(item, dict):
                continue
            try:
                planned = PlannedCase.model_validate(item)
            except ValidationError:
                continue
            cases.append(QaTestCase(
                id=f"TC-{abbr}-{len(cases) + 1:03d}", module=module, page=planned.page, title=planned.title,
                type=planned.type, priority=planned.priority, precondition=planned.precondition,
                test_data=planned.test_data, steps=planned.steps, expected=planned.expected,
                expected_source=planned.expected_source if has_prd else "Inferensi AI",
                start_url=_resolve_start(planned, screens),
            ))
        return cases


def judge(outcome: LoopOutcome, tc: QaTestCase) -> tuple[str, str | None]:
    """Aturan status (spec §6.4). HTTP 5xx / error JavaScript selalu menang → Fail."""
    server_error = any(s.kind == "page_error" or (s.kind == "http_error" and (s.status or 0) >= 500) for s in outcome.signals)
    if server_error:
        return "Fail", outcome.severity or "Major"
    if outcome.final == "blocked":
        return ("Skipped" if outcome.guard_blocks > 0 else "Blocked"), None
    if outcome.status == "fail":
        return ("Fail" if tc.expected_source == "PRD" else "Perlu Review"), outcome.severity or "Minor"
    return "Pass", None


def goal_for(tc: QaTestCase) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(tc.steps, 1)) or "-"
    return (
        f"Jalankan test case {tc.id}: {tc.title}\n"
        f"Tipe: {tc.type}\n"
        f"Pre-condition: {tc.precondition or '-'}\n"
        f"Test data: {tc.test_data or '-'}\n"
        f"Langkah:\n{steps}\n"
        f"Expected result: {tc.expected}\n\n"
        "Ikuti langkah di atas di aplikasi. Setelah langkah terakhir, bandingkan kondisi layar dengan expected result, "
        "lalu nyatakan done (pass/fail) dengan actual yang menjelaskan apa yang terjadi."
    )


def is_logout_case(tc: QaTestCase) -> bool:
    text = " ".join([tc.title, *tc.steps]).lower()
    return any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text) for k in LOGOUT_KEYWORDS)
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_deep_plan.py -v`
Expected: `15 passed` (7 test biasa + 8 kasus parametrize `test_judge`)

- [ ] **Step 5: Commit**

```bash
git add qa_agent/orchestrator/deep.py tests/unit/test_deep_plan.py
git commit -m "feat: mode deep — penyusunan test case AI dan aturan status"
```

---

### Task 18: Mode Deep — eksekusi, resume, pemulihan error

**Files:**
- Modify: `qa_agent/orchestrator/deep.py` (tambah import + class `DeepRunner`)
- Test: `tests/unit/test_deep_runner.py`

**Interfaces:**
- Consumes: `AgentLoop` (Task 14), `AuthManager`, `LoginFailed` (Task 15), `RunStore.drop_steps/write_testcases` (Task 8), `judge`, `goal_for`, `is_logout_case` (Task 17), `LLMError` (Task 7)
- Produces: `DeepRunner(*, driver, loop, auth: AuthManager | None, store, should_stop=lambda: False)` dengan `.execute(cases, *, needs_auth: bool) -> list[QaTestCase]`
  - Melewati test case yang `status_ai`-nya sudah terisi (resume).
  - Melempar `LLMError` dan `LoginFailed` setelah menyimpan progres.
  - Error lain → `Blocked`, driver dipulihkan, lanjut ke test case berikutnya.

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_deep_runner.py`:

```python
import pytest

from qa_agent.agent.loop import LoopOutcome
from qa_agent.evidence import RunStore
from qa_agent.llm.base import LLMUnavailable
from qa_agent.models import QaTestCase, Signal, StepRecord
from qa_agent.orchestrator.auth import LoginFailed
from qa_agent.orchestrator.deep import DeepRunner
from tests.fakes import FakeDriver, el, screen, url

HOME = screen("home", el(1, "link", "Pengguna"))
PASS = LoopOutcome(final="done", status="pass", actual="berhasil")


class StubLoop:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []
        self.relogin = "belum diset"

    def run(self, tc_id, goal, *, allow_logout=False, login=False):
        self.calls.append((tc_id, allow_logout))
        result = self.outcomes[tc_id]
        if isinstance(result, Exception):
            raise result
        return result


class StubAuth:
    def __init__(self, fail=False):
        self.fail = fail
        self.started = []

    def start_authenticated(self, target):
        if self.fail:
            raise LoginFailed("password salah")
        self.started.append(target)

    def relogin(self, return_to):
        pass


def tc(n, **kw):
    kw.setdefault("title", f"Kasus {n}")
    return QaTestCase(id=f"TC-PEN-00{n}", module="Pengguna", expected="ok", start_url=url("home"), **kw)


def make(tmp_path, outcomes, auth=None, **kw):
    store = RunStore(tmp_path / "run")
    loop = StubLoop(outcomes)
    driver = FakeDriver([HOME], url("home"))
    auth = auth or StubAuth()
    runner = DeepRunner(driver=driver, loop=loop, auth=auth, store=store, **kw)
    return runner, loop, store, driver, auth


def test_executes_and_judges(tmp_path):
    outcomes = {
        "TC-PEN-001": PASS,
        "TC-PEN-002": LoopOutcome(final="done", status="fail", actual="tanpa validasi"),
        "TC-PEN-003": LoopOutcome(final="done", status="pass", signals=[Signal(kind="http_error", message="x", status=500)]),
    }
    runner, loop, store, _, auth = make(tmp_path, outcomes)
    cases = runner.execute([tc(1), tc(2), tc(3)], needs_auth=True)
    assert [c.status_ai for c in cases] == ["Pass", "Perlu Review", "Fail"]
    assert cases[1].actual == "tanpa validasi" and cases[2].severity == "Major"
    assert auth.started == [url("home")] * 3
    assert loop.relogin == auth.relogin
    assert [c.status_ai for c in store.read_testcases()] == ["Pass", "Perlu Review", "Fail"]


def test_resume_skips_finished(tmp_path):
    runner, loop, _, _, _ = make(tmp_path, {"TC-PEN-002": PASS})
    runner.execute([tc(1, status_ai="Pass"), tc(2)], needs_auth=True)
    assert [c[0] for c in loop.calls] == ["TC-PEN-002"]


def test_logout_case_allows_logout(tmp_path):
    runner, loop, _, _, _ = make(tmp_path, {"TC-PEN-001": PASS})
    runner.execute([tc(1, title="Logout dari aplikasi")], needs_auth=True)
    assert loop.calls == [("TC-PEN-001", True)]


def test_public_module_uses_clean_session(tmp_path):
    runner, loop, _, driver, auth = make(tmp_path, {"TC-PEN-001": PASS})
    runner.execute([tc(1)], needs_auth=False)
    assert driver.sessions == [None] and driver.gotos == [url("home")]
    assert auth.started == [] and loop.relogin is None


def test_unexpected_error_blocks_case_and_continues(tmp_path):
    runner, _, _, driver, _ = make(tmp_path, {"TC-PEN-001": RuntimeError("elemen hilang"), "TC-PEN-002": PASS})
    cases = runner.execute([tc(1), tc(2)], needs_auth=True)
    assert cases[0].status_ai == "Blocked" and "RuntimeError: elemen hilang" in cases[0].actual
    assert cases[1].status_ai == "Pass"
    assert None in driver.sessions  # driver dipulihkan dengan sesi baru


def test_llm_unavailable_saves_progress_and_raises(tmp_path):
    runner, _, store, _, _ = make(tmp_path, {"TC-PEN-001": PASS, "TC-PEN-002": LLMUnavailable("endpoint mati")})
    with pytest.raises(LLMUnavailable):
        runner.execute([tc(1), tc(2)], needs_auth=True)
    assert [c.status_ai for c in store.read_testcases()] == ["Pass", None]


def test_login_failed_raises(tmp_path):
    runner, loop, store, _, _ = make(tmp_path, {"TC-PEN-001": PASS}, auth=StubAuth(fail=True))
    with pytest.raises(LoginFailed):
        runner.execute([tc(1)], needs_auth=True)
    assert loop.calls == [] and store.read_testcases()[0].status_ai is None


def test_stop_flag(tmp_path):
    runner, loop, _, _, _ = make(tmp_path, {"TC-PEN-001": PASS}, should_stop=lambda: True)
    runner.execute([tc(1)], needs_auth=True)
    assert loop.calls == []


def test_interrupted_outcome_leaves_case_pending(tmp_path):
    outcomes = {"TC-PEN-001": LoopOutcome(final="blocked", error_kind="interrupted"), "TC-PEN-002": PASS}
    runner, loop, _, _, _ = make(tmp_path, outcomes)
    cases = runner.execute([tc(1), tc(2)], needs_auth=True)
    assert cases[0].status_ai is None and len(loop.calls) == 1


def test_old_steps_dropped_before_rerun(tmp_path):
    runner, _, store, _, _ = make(tmp_path, {"TC-PEN-001": PASS})
    store.append_step(StepRecord(tc_id="TC-PEN-001", step_no=1, timestamp="t", action="click"))
    store.append_step(StepRecord(tc_id="LOGIN-1", step_no=1, timestamp="t", action="click"))
    runner.execute([tc(1)], needs_auth=True)
    assert [s.tc_id for s in store.read_steps()] == ["LOGIN-1"]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_deep_runner.py -v`
Expected: FAIL dengan `ImportError: cannot import name 'DeepRunner'`

- [ ] **Step 3: Implementasi — tambahkan ke `qa_agent/orchestrator/deep.py`**

Tambahkan import berikut di bagian atas file (gabungkan dengan import yang sudah ada):

```python
from typing import Callable

from qa_agent.agent.loop import AgentLoop
from qa_agent.drivers.base import Driver
from qa_agent.evidence import RunStore
from qa_agent.llm.base import LLMError
from qa_agent.orchestrator.auth import AuthManager, LoginFailed
```

Tambahkan class di akhir file:

```python
class DeepRunner:
    def __init__(self, *, driver: Driver, loop: AgentLoop, auth: AuthManager | None, store: RunStore,
                 should_stop: Callable[[], bool] = lambda: False) -> None:
        self.driver = driver
        self.loop = loop
        self.auth = auth
        self.store = store
        self.should_stop = should_stop

    def execute(self, cases: list[QaTestCase], *, needs_auth: bool) -> list[QaTestCase]:
        self.loop.relogin = self.auth.relogin if (needs_auth and self.auth is not None) else None
        for tc in cases:
            if tc.status_ai is not None:
                continue  # sudah selesai (resume)
            if self.should_stop():
                break
            self.store.drop_steps(tc.id)
            try:
                self._prepare(tc, needs_auth)
                outcome = self.loop.run(tc.id, goal_for(tc), allow_logout=is_logout_case(tc))
                if outcome.error_kind == "interrupted":
                    break  # biarkan status kosong supaya dijalankan ulang saat resume
                tc.status_ai, tc.severity = judge(outcome, tc)
                tc.actual = outcome.actual or outcome.reason
                tc.ai_note = outcome.reason if outcome.final == "blocked" else ""
            except (LLMError, LoginFailed):
                self.store.write_testcases(cases)
                raise
            except Exception as e:  # satu test case gagal tidak menghentikan run
                tc.status_ai = "Blocked"
                tc.actual = f"Error sistem: {type(e).__name__}: {e}"
                self._recover()
            self.store.write_testcases(cases)
        return cases

    def _prepare(self, tc: QaTestCase, needs_auth: bool) -> None:
        start = tc.start_url or "/"
        if needs_auth and self.auth is not None:
            self.auth.start_authenticated(start)
        else:
            self.driver.new_session(None)
            self.driver.goto(start)

    def _recover(self) -> None:
        try:
            self.driver.new_session(None)
        except Exception:
            try:
                self.driver.stop()
            except Exception:
                pass
            self.driver.start()
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_deep_runner.py tests/unit/test_deep_plan.py -v`
Expected: `25 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/orchestrator/deep.py tests/unit/test_deep_runner.py
git commit -m "feat: eksekusi mode deep dengan resume, pemulihan error, dan pause saat AI mati"
```

---

### Task 19: Laporan Excel (report.xlsx, testcases.xlsx, baca hasil review)

**Files:**
- Create: `qa_agent/report/excel.py`
- Create: `tests/report_fixtures.py`
- Test: `tests/unit/test_excel.py`

**Interfaces:**
- Consumes: `RunMeta`, `QaTestCase`, `StepRecord`, `AppMap`, `STATUSES`, `TC_TYPES` (Task 3), `module_abbr` (Task 8), `humanize`, `signal_text` (Task 13)
- Produces:
  - `TC_HEADERS`, `PLAN_HEADERS` (daftar kolom), `class ReportLockedError(Exception)`
  - `write_report_xlsx(path, meta, cases, steps, app_map) -> None`. Sheet: "Ringkasan", lalu "Test Cases" + "Temuan" (jika ada test case), lalu "Inventaris Fitur" (jika ada app_map).
  - `write_cases_xlsx(path, cases) -> None`: untuk alur `--review`
  - `import_cases_xlsx(path) -> list[QaTestCase]`: melempar `ValueError("Baris N: ...")`
  - `read_review(path) -> dict[str, dict]`: `{tc_id: {"status_final": str|None, "reviewer_note": str}}`. Melempar `ValueError` jika ada status yang tidak dikenal.
  - Test helper `tests/report_fixtures.py`: `sample_run(root: Path) -> RunStore` (3 test case Pass / Perlu Review / Fail beserta steps, screenshot, dan app_map)

- [ ] **Step 1: Tulis fixture data laporan**

`tests/report_fixtures.py`:

```python
"""Data run contoh untuk test laporan."""
from __future__ import annotations

from pathlib import Path

from qa_agent.evidence import RunStore
from qa_agent.imaging import solid_png
from qa_agent.models import AppMap, QaTestCase, RunMeta, ScreenInfo, Signal, StepRecord


def sample_run(root: Path) -> RunStore:
    store = RunStore(root)
    store.write_meta(RunMeta(mode="deep", target="http://app.test", environment="dev", model="z-ai/glm-5.3-flash",
                             started_at="2026-10-05T14:30:00", finished_at="2026-10-05T14:42:30", status="completed",
                             module="Pengguna"))
    cases = [
        QaTestCase(id="TC-PEN-001", module="Pengguna", page="Tambah Pengguna", title="Tambah pengguna valid", type="positif",
                   priority="High", steps=["Buka form", "Isi data", "Klik Simpan"], expected="Pengguna tersimpan",
                   actual="Pengguna tersimpan", status_ai="Pass"),
        QaTestCase(id="TC-PEN-002", module="Pengguna", page="Tambah Pengguna", title="Validasi email <b>tebal</b>", type="validasi",
                   steps=["Isi email 'bukan-email'", "Klik Simpan"], expected="Muncul pesan validasi email",
                   actual="Tersimpan tanpa validasi", status_ai="Perlu Review", severity="Minor"),
        QaTestCase(id="TC-PEN-003", module="Pengguna", page="Tambah Pengguna", title="Nama dengan apostrof", type="boundary",
                   steps=["Isi nama O'Brien", "Klik Simpan"], expected="Tersimpan", expected_source="PRD",
                   actual="Server error 500", status_ai="Fail", severity="Major"),
    ]
    store.write_testcases(cases)
    for tc in cases:
        for n, (action, name, value) in enumerate([("type", "Nama", "Budi"), ("click", "Simpan", None), ("done", None, "pass")], 1):
            shot = store.save_screenshot(f"{tc.id}_step-{n:02d}", solid_png((200, 220, 240), (64, 48)))
            signals = []
            if tc.id == "TC-PEN-003" and action == "done":
                signals = [Signal(kind="http_error", message="HTTP 500", status=500, method="POST", url="http://app.test/users")]
            element = {"role": "button" if action == "click" else "input", "name": name, "selector": f"#{name}"} if name else None
            store.append_step(StepRecord(tc_id=tc.id, step_no=n, timestamp="2026-10-05T14:31:00", action=action,
                                         element=element, value=value, signals=signals, screenshot=shot))
    explore_shot = store.save_screenshot("explore_001", solid_png((10, 10, 10), (64, 48)))
    store.write_app_map(AppMap(target="http://app.test", screens=[
        ScreenInfo(fingerprint="app.test/users|x", url="http://app.test/users", module="Pengguna", page_name="Daftar Pengguna",
                   purpose="Melihat daftar pengguna", actions=["Tambah Pengguna"], screenshot=explore_shot,
                   forms=[{"name": "Cari", "fields": [{"label": "Kata kunci", "type": "text"}]}]),
    ]))
    return store
```

- [ ] **Step 2: Tulis test yang gagal**

`tests/unit/test_excel.py`:

```python
import pytest
from openpyxl import Workbook, load_workbook

from qa_agent.report.excel import (
    PLAN_HEADERS,
    TC_HEADERS,
    ReportLockedError,
    import_cases_xlsx,
    read_review,
    write_cases_xlsx,
    write_report_xlsx,
)
from tests.report_fixtures import sample_run


def build(tmp_path):
    store = sample_run(tmp_path / "run")
    write_report_xlsx(store.report_xlsx, store.read_meta(), store.read_testcases(), store.read_steps(), store.read_app_map())
    return store, load_workbook(store.report_xlsx)


def col(ws, header):
    headers = [c.value for c in ws[1]]
    return headers.index(header) + 1


def test_sheets_and_headers(tmp_path):
    _, wb = build(tmp_path)
    assert wb.sheetnames == ["Ringkasan", "Test Cases", "Temuan", "Inventaris Fitur"]
    assert [c.value for c in wb["Test Cases"][1]] == TC_HEADERS
    assert wb["Test Cases"].freeze_panes == "A2"


def test_test_case_rows_status_colors_and_links(tmp_path):
    _, wb = build(tmp_path)
    ws = wb["Test Cases"]
    assert ws.cell(2, 1).value == "TC-PEN-001"
    assert ws.cell(2, col(ws, "Langkah")).value == "1. Buka form\n2. Isi data\n3. Klik Simpan"
    status = ws.cell(2, col(ws, "Status AI"))
    assert status.value == "Pass" and status.fill.fgColor.rgb.endswith("C6EFCE")
    assert ws.cell(4, col(ws, "Status AI")).fill.fgColor.rgb.endswith("FFC7CE")
    evidence = ws.cell(2, col(ws, "Evidence"))
    assert evidence.hyperlink.target == "screenshots/TC-PEN-001_step-03.png"
    assert ws.cell(2, col(ws, "Laporan HTML")).hyperlink.target == "report.html#TC-PEN-001"
    assert any("Pass,Fail,Perlu Review,Blocked,Skipped" in (dv.formula1 or "") for dv in ws.data_validations.dataValidation)


def test_findings_only_fail_and_review(tmp_path):
    _, wb = build(tmp_path)
    ws = wb["Temuan"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert [r[1] for r in rows] == ["TC-PEN-002", "TC-PEN-003"]
    assert rows[0][0] == "BUG-001"
    assert "1. Isi field 'Nama' dengan 'Budi'" in rows[1][5]
    assert "HTTP 500 POST http://app.test/users" in rows[1][8]


def test_summary_counts(tmp_path):
    _, wb = build(tmp_path)
    values = {row[0]: row[1:] for row in wb["Ringkasan"].iter_rows(values_only=True) if row[0]}
    assert values["Target"][0] == "http://app.test"
    assert values["Durasi"][0] == "12 menit 30 detik"
    assert values["Pass"][:2] == (1, 1)
    assert values["Fail"][:2] == (1, 1)
    assert values["Pass rate"][0] == "33%"


def test_inventory_sheet(tmp_path):
    _, wb = build(tmp_path)
    row = next(wb["Inventaris Fitur"].iter_rows(min_row=2, values_only=True))
    assert row[:4] == ("Pengguna", "Daftar Pengguna", "http://app.test/users", "Melihat daftar pengguna")
    assert "Kata kunci (text)" in row[4]


def test_explore_only_report(tmp_path):
    store = sample_run(tmp_path / "run")
    write_report_xlsx(store.report_xlsx, store.read_meta(), [], [], store.read_app_map())
    assert load_workbook(store.report_xlsx).sheetnames == ["Ringkasan", "Inventaris Fitur"]


def test_read_review_roundtrip(tmp_path):
    store, wb = build(tmp_path)
    ws = wb["Test Cases"]
    ws.cell(3, col(ws, "Status Final")).value = "fail"
    ws.cell(3, col(ws, "Catatan Reviewer")).value = "Bug valid, lapor ke dev"
    wb.save(store.report_xlsx)
    review = read_review(store.report_xlsx)
    assert review["TC-PEN-002"] == {"status_final": "Fail", "reviewer_note": "Bug valid, lapor ke dev"}
    assert review["TC-PEN-001"] == {"status_final": None, "reviewer_note": ""}


def test_read_review_rejects_unknown_status(tmp_path):
    store, wb = build(tmp_path)
    ws = wb["Test Cases"]
    ws.cell(2, col(ws, "Status Final")).value = "Lulus"
    wb.save(store.report_xlsx)
    with pytest.raises(ValueError, match="Baris 2.*Lulus"):
        read_review(store.report_xlsx)


def test_cases_xlsx_roundtrip_and_new_row(tmp_path):
    store = sample_run(tmp_path / "run")
    write_cases_xlsx(store.cases_xlsx, store.read_testcases())
    wb = load_workbook(store.cases_xlsx)
    ws = wb["Test Cases"]
    assert [c.value for c in ws[1]] == PLAN_HEADERS
    ws.append([None, "Pengguna", "Daftar Pengguna", "Cari pengguna", "Navigasi", "Low", "", "", "1. Ketik nama\n2) Tekan cari",
               "Hasil muncul", "Inferensi AI", "http://app.test/users"])
    ws.delete_rows(2)  # reviewer menghapus TC-PEN-001
    wb.save(store.cases_xlsx)
    cases = import_cases_xlsx(store.cases_xlsx)
    assert [c.id for c in cases] == ["TC-PEN-002", "TC-PEN-003", "TC-PEN-004"]
    assert cases[2].steps == ["Ketik nama", "Tekan cari"] and cases[2].type == "navigasi"
    assert all(c.status_ai is None for c in cases)


def test_import_cases_reports_row_number(tmp_path):
    store = sample_run(tmp_path / "run")
    write_cases_xlsx(store.cases_xlsx, store.read_testcases())
    wb = load_workbook(store.cases_xlsx)
    wb["Test Cases"].cell(3, PLAN_HEADERS.index("Tipe") + 1).value = "acak"
    wb.save(store.cases_xlsx)
    with pytest.raises(ValueError, match="Baris 3"):
        import_cases_xlsx(store.cases_xlsx)


def test_locked_workbook_raises_friendly_error(tmp_path, monkeypatch):
    store = sample_run(tmp_path / "run")

    def locked(self, filename):
        raise PermissionError(13, "Permission denied", str(filename))

    monkeypatch.setattr(Workbook, "save", locked)
    with pytest.raises(ReportLockedError, match="Tutup"):
        write_report_xlsx(store.report_xlsx, store.read_meta(), store.read_testcases(), store.read_steps(), None)
```

- [ ] **Step 3: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_excel.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 4: Implementasi**

`qa_agent/report/excel.py`:

```python
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import ValidationError

from qa_agent.evidence import module_abbr
from qa_agent.models import STATUSES, TC_TYPES, AppMap, QaTestCase, RunMeta, StepRecord
from qa_agent.report.humanize import humanize, signal_text

TC_HEADERS = ["TC ID", "Modul", "Halaman", "Skenario", "Tipe", "Prioritas", "Pre-condition", "Test Data", "Langkah",
              "Expected Result", "Sumber Expected", "Actual Result", "Status AI", "Status Final", "Catatan Reviewer",
              "Evidence", "Laporan HTML"]
PLAN_HEADERS = ["TC ID", "Modul", "Halaman", "Skenario", "Tipe", "Prioritas", "Pre-condition", "Test Data", "Langkah",
                "Expected Result", "Sumber Expected", "URL Awal"]
FINDING_HEADERS = ["ID Temuan", "TC ID", "Judul", "Severity", "Status", "Langkah Reproduksi", "Expected", "Actual",
                   "Sinyal Teknis", "Evidence"]
INVENTORY_HEADERS = ["Modul", "Halaman", "URL", "Fungsi", "Form & Field", "Aksi", "Akses", "Screenshot"]

STATUS_FILL = {"Pass": "C6EFCE", "Fail": "FFC7CE", "Perlu Review": "FFEB9C", "Blocked": "D9D9D9", "Skipped": "D9D9D9"}
HEADER_FILL = PatternFill("solid", fgColor="305496")
WRAP = Alignment(wrap_text=True, vertical="top")
WIDE = {"Skenario": 36, "Langkah": 48, "Expected Result": 36, "Actual Result": 36, "Pre-condition": 24, "Test Data": 24,
        "Catatan Reviewer": 30, "Langkah Reproduksi": 48, "Expected": 32, "Actual": 32, "Sinyal Teknis": 40,
        "Judul": 36, "Fungsi": 36, "Form & Field": 40, "Aksi": 30, "URL": 36, "URL Awal": 36}


class ReportLockedError(Exception):
    """File laporan sedang dibuka aplikasi lain (biasanya Excel)."""


def _save(wb: Workbook, path: Path) -> None:
    try:
        wb.save(path)
    except PermissionError as e:
        raise ReportLockedError(f"Tidak bisa menulis {Path(path).name}. Tutup file itu di Excel lalu jalankan ulang perintahnya.") from e


def _header(ws: Worksheet, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = WRAP
    for i, name in enumerate(headers, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = WIDE.get(name, 16)
    ws.freeze_panes = "A2"


def steps_text(steps: list[str]) -> str:
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


def parse_steps(text: str | None) -> list[str]:
    lines = [re.sub(r"^\s*\d+\s*[.)]\s*", "", line).strip() for line in (text or "").splitlines()]
    return [line for line in lines if line]


def _steps_for(tc_id: str, steps: list[StepRecord]) -> list[StepRecord]:
    return [s for s in steps if s.tc_id == tc_id]


def _last_screenshot(records: list[StepRecord]) -> str | None:
    return next((r.screenshot for r in reversed(records) if r.screenshot), None)


def _duration(meta: RunMeta) -> str:
    if not meta.finished_at:
        return "-"
    seconds = int((datetime.fromisoformat(meta.finished_at) - datetime.fromisoformat(meta.started_at)).total_seconds())
    return f"{seconds // 60} menit {seconds % 60} detik"


def _write_summary(ws: Worksheet, meta: RunMeta, cases: list[QaTestCase]) -> None:
    rows = [("Target", meta.target), ("Mode", meta.mode), ("Modul", meta.module or "-"), ("Environment", meta.environment),
            ("Model AI", meta.model), ("Mulai", meta.started_at), ("Selesai", meta.finished_at or "-"),
            ("Durasi", _duration(meta)), ("Status run", meta.status)]
    if meta.note:
        rows.append(("Catatan", meta.note))
    for row in rows:
        ws.append(row)
    if cases:
        ws.append([])
        ws.append(["Status", "Jumlah (AI)", "Jumlah (Final)"])
        ai = Counter(c.status_ai for c in cases)
        final = Counter(c.effective_status for c in cases)
        for status in STATUSES:
            ws.append([status, ai.get(status, 0), final.get(status, 0)])
        ws.append(["Belum dijalankan", ai.get(None, 0), final.get(None, 0)])
        ws.append(["Total", len(cases), len(cases)])
        ws.append(["Pass rate", f"{round(100 * final.get('Pass', 0) / len(cases))}%"])
    for cell in ws["A"]:
        cell.font = Font(bold=True)
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 16


def _write_cases(ws: Worksheet, cases: list[QaTestCase], steps: list[StepRecord]) -> None:
    _header(ws, TC_HEADERS)
    for tc in cases:
        ws.append([tc.id, tc.module, tc.page, tc.title, tc.type, tc.priority, tc.precondition, tc.test_data,
                   steps_text(tc.steps), tc.expected, tc.expected_source, tc.actual, tc.status_ai or "",
                   tc.status_final or "", tc.reviewer_note, None, None])
        row = ws.max_row
        for cell in ws[row]:
            cell.alignment = WRAP
        if tc.status_ai:
            ws.cell(row, TC_HEADERS.index("Status AI") + 1).fill = PatternFill("solid", fgColor=STATUS_FILL[tc.status_ai])
        if tc.status_final:
            ws.cell(row, TC_HEADERS.index("Status Final") + 1).fill = PatternFill("solid", fgColor=STATUS_FILL[tc.status_final])
        shot = _last_screenshot(_steps_for(tc.id, steps))
        if shot:
            cell = ws.cell(row, TC_HEADERS.index("Evidence") + 1, "Lihat screenshot")
            cell.hyperlink = shot
            cell.style = "Hyperlink"
        html = ws.cell(row, TC_HEADERS.index("Laporan HTML") + 1, "Buka detail")
        html.hyperlink = f"report.html#{tc.id}"
        html.style = "Hyperlink"
    dv = DataValidation(type="list", formula1=f'"{",".join(STATUSES)}"', allow_blank=True)
    ws.add_data_validation(dv)
    column = ws.cell(1, TC_HEADERS.index("Status Final") + 1).column_letter
    dv.add(f"{column}2:{column}{max(ws.max_row, 2)}")


def _write_findings(ws: Worksheet, cases: list[QaTestCase], steps: list[StepRecord]) -> None:
    _header(ws, FINDING_HEADERS)
    n = 0
    for tc in cases:
        if tc.effective_status not in ("Fail", "Perlu Review"):
            continue
        n += 1
        records = _steps_for(tc.id, steps)
        repro = [humanize(r.action, r.element, r.value) for r in records if r.action not in ("done", "blocked", "invalid")]
        signals: list[str] = []
        for r in records:
            for s in r.signals:
                if s.kind in ("http_error", "page_error", "console_error") and signal_text(s) not in signals:
                    signals.append(signal_text(s))
        ws.append([f"BUG-{n:03d}", tc.id, tc.title, tc.severity or "", tc.effective_status, steps_text(repro),
                   tc.expected, tc.actual, "\n".join(signals[:5]), None])
        row = ws.max_row
        for cell in ws[row]:
            cell.alignment = WRAP
        shot = _last_screenshot(records)
        if shot:
            cell = ws.cell(row, len(FINDING_HEADERS), "Lihat screenshot")
            cell.hyperlink = shot
            cell.style = "Hyperlink"


def _write_inventory(ws: Worksheet, app_map: AppMap) -> None:
    _header(ws, INVENTORY_HEADERS)
    for s in app_map.screens:
        forms = "\n".join(
            f"{f.get('name', 'Form')}: " + ", ".join(f"{fd.get('label', '?')} ({fd.get('type', '?')})" for fd in f.get("fields", []))
            for f in s.forms)
        ws.append([s.module, s.page_name, s.url, s.purpose, forms, ", ".join(s.actions), "Publik" if s.public else "Login", None])
        row = ws.max_row
        for cell in ws[row]:
            cell.alignment = WRAP
        if s.screenshot:
            cell = ws.cell(row, len(INVENTORY_HEADERS), "Lihat screenshot")
            cell.hyperlink = s.screenshot
            cell.style = "Hyperlink"


def write_report_xlsx(path: Path, meta: RunMeta, cases: list[QaTestCase], steps: list[StepRecord], app_map: AppMap | None) -> None:
    wb = Workbook()
    summary = wb.active
    summary.title = "Ringkasan"
    _write_summary(summary, meta, cases)
    if cases:
        _write_cases(wb.create_sheet("Test Cases"), cases, steps)
        _write_findings(wb.create_sheet("Temuan"), cases, steps)
    if app_map and app_map.screens:
        _write_inventory(wb.create_sheet("Inventaris Fitur"), app_map)
    _save(wb, Path(path))


def write_cases_xlsx(path: Path, cases: list[QaTestCase]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Cases"
    _header(ws, PLAN_HEADERS)
    for tc in cases:
        ws.append([tc.id, tc.module, tc.page, tc.title, tc.type, tc.priority, tc.precondition, tc.test_data,
                   steps_text(tc.steps), tc.expected, tc.expected_source, tc.start_url])
        for cell in ws[ws.max_row]:
            cell.alignment = WRAP
    for header, options in (("Tipe", TC_TYPES), ("Prioritas", ("High", "Medium", "Low")), ("Sumber Expected", ("PRD", "Inferensi AI"))):
        dv = DataValidation(type="list", formula1=f'"{",".join(options)}"', allow_blank=True)
        ws.add_data_validation(dv)
        column = ws.cell(1, PLAN_HEADERS.index(header) + 1).column_letter
        dv.add(f"{column}2:{column}500")
    _save(wb, Path(path))


def _rows(path: Path) -> list[tuple[int, dict[str, object]]]:
    wb = load_workbook(path)
    if "Test Cases" not in wb.sheetnames:
        return []
    ws = wb["Test Cases"]
    headers = [c.value for c in ws[1]]
    out = []
    for row_no, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v in (None, "") for v in values):
            continue
        out.append((row_no, dict(zip(headers, values))))
    return out


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def import_cases_xlsx(path: Path) -> list[QaTestCase]:
    rows = _rows(path)
    cases: list[QaTestCase] = []
    used = {_text(r.get("TC ID")) for _, r in rows if _text(r.get("TC ID"))}
    for row_no, r in rows:
        tc_id = _text(r.get("TC ID"))
        module = _text(r.get("Modul"))
        if not tc_id:  # baris baru dari reviewer → nomor setelah nomor terbesar
            prefix = f"TC-{module_abbr(module)}-"
            numbers = [int(u[len(prefix):]) for u in used if u.startswith(prefix) and u[len(prefix):].isdigit()]
            tc_id = f"{prefix}{max(numbers, default=0) + 1:03d}"
            used.add(tc_id)
        try:
            cases.append(QaTestCase(
                id=tc_id, module=module, page=_text(r.get("Halaman")), title=_text(r.get("Skenario")),
                type=_text(r.get("Tipe")).lower() or "positif", priority=_text(r.get("Prioritas")).capitalize() or "Medium",
                precondition=_text(r.get("Pre-condition")), test_data=_text(r.get("Test Data")),
                steps=parse_steps(_text(r.get("Langkah"))), expected=_text(r.get("Expected Result")),
                expected_source="PRD" if _text(r.get("Sumber Expected")).upper() == "PRD" else "Inferensi AI",
                start_url=_text(r.get("URL Awal")),
            ))
        except ValidationError as e:
            err = e.errors()[0]
            raise ValueError(f"Baris {row_no}: kolom '{err['loc'][0]}' tidak valid ({err['msg']})") from e
    return cases


def read_review(path: Path) -> dict[str, dict]:
    canonical = {s.lower(): s for s in STATUSES}
    review: dict[str, dict] = {}
    for row_no, r in _rows(path):
        tc_id = _text(r.get("TC ID"))
        if not tc_id:
            continue
        raw = _text(r.get("Status Final"))
        status = canonical.get(raw.lower()) if raw else None
        if raw and status is None:
            raise ValueError(f"Baris {row_no}: Status Final '{raw}' tidak dikenal. Pilihan: {', '.join(STATUSES)}")
        review[tc_id] = {"status_final": status, "reviewer_note": _text(r.get("Catatan Reviewer"))}
    return review
```

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_excel.py -v`
Expected: `11 passed`

- [ ] **Step 6: Commit**

```bash
git add qa_agent/report/excel.py tests/report_fixtures.py tests/unit/test_excel.py
git commit -m "feat: laporan Excel (ringkasan, test case, temuan, inventaris) + baca hasil review"
```

---

### Task 20: Laporan HTML satu file

**Files:**
- Create: `qa_agent/report/html.py`, `qa_agent/report/templates/report.html.j2`
- Test: `tests/unit/test_html.py`

**Interfaces:**
- Consumes: `RunMeta`, `QaTestCase`, `StepRecord`, `AppMap`, `STATUSES` (Task 3), `to_jpeg` (Task 9), `humanize`, `signal_text` (Task 13), `tests/report_fixtures.sample_run` (Task 19)
- Produces: `write_report_html(path, run_root, meta, cases, steps, app_map) -> None`, `status_class(status) -> str` (`"Perlu Review"` → `"s-perlu-review"`, `None` → `"s-none"`)

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_html.py`:

```python
from qa_agent.report.html import status_class, write_report_html
from tests.report_fixtures import sample_run


def render(tmp_path, with_cases=True):
    store = sample_run(tmp_path / "run")
    cases = store.read_testcases() if with_cases else []
    steps = store.read_steps() if with_cases else []
    write_report_html(store.report_html, store.root, store.read_meta(), cases, steps, store.read_app_map())
    return store.report_html.read_text(encoding="utf-8")


def test_status_class():
    assert status_class("Perlu Review") == "s-perlu-review"
    assert status_class("Pass") == "s-pass"
    assert status_class(None) == "s-none"


def test_report_contains_cases_steps_and_images(tmp_path):
    html = render(tmp_path)
    assert html.startswith("<!doctype html>")
    assert 'id="TC-PEN-001"' in html and 'id="TC-PEN-003"' in html
    assert "Isi field &#39;Nama&#39; dengan &#39;Budi&#39;" in html
    assert "data:image/jpeg;base64," in html
    assert "HTTP 500 POST http://app.test/users" in html
    assert 'class="badge s-perlu-review"' in html


def test_findings_list_only_fail_and_review(tmp_path):
    html = render(tmp_path)
    findings = html.split('id="temuan"')[1].split("</section>")[0]
    assert "TC-PEN-002" in findings and "TC-PEN-003" in findings and "TC-PEN-001" not in findings


def test_user_text_is_escaped(tmp_path):
    html = render(tmp_path)
    assert "&lt;b&gt;tebal&lt;/b&gt;" in html and "<b>tebal</b>" not in html


def test_explore_only_report_shows_inventory(tmp_path):
    html = render(tmp_path, with_cases=False)
    assert "Inventaris Fitur" in html and "Daftar Pengguna" in html and 'id="temuan"' not in html
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_html.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi `report/html.py`**

```python
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from qa_agent.evidence import now_iso
from qa_agent.imaging import to_jpeg
from qa_agent.models import STATUSES, AppMap, QaTestCase, RunMeta, StepRecord
from qa_agent.report.humanize import humanize, signal_text


def status_class(status: str | None) -> str:
    return "s-" + (status or "none").lower().replace(" ", "-")


def _env() -> Environment:
    env = Environment(loader=PackageLoader("qa_agent.report", "templates"),
                      autoescape=select_autoescape(enabled_extensions=("html", "j2"), default=True))
    env.filters["status_class"] = status_class
    return env


def _image(run_root: Path, relative: str | None) -> str | None:
    if not relative:
        return None
    path = run_root / relative
    if not path.exists():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(to_jpeg(path.read_bytes())).decode()


def _step(run_root: Path, r: StepRecord) -> dict:
    return {
        "no": r.step_no,
        "text": humanize(r.action, r.element, r.value),
        "thought": r.thought,
        "guard": r.guard,
        "result": r.result,
        "signals": [signal_text(s) for s in r.signals],
        "image": _image(run_root, r.screenshot),
    }


def write_report_html(path: Path, run_root: Path, meta: RunMeta, cases: list[QaTestCase], steps: list[StepRecord],
                      app_map: AppMap | None) -> None:
    run_root = Path(run_root)
    by_tc: dict[str, list[StepRecord]] = defaultdict(list)
    for record in steps:
        by_tc[record.tc_id].append(record)
    case_items = [{"tc": tc, "status": tc.effective_status or "Belum dijalankan",
                   "steps": [_step(run_root, r) for r in by_tc.get(tc.id, [])]} for tc in cases]
    counts = Counter(item["status"] for item in case_items)
    inventory = [{"screen": s, "image": _image(run_root, s.screenshot)} for s in (app_map.screens if app_map else [])]
    html = _env().get_template("report.html.j2").render(
        meta=meta,
        statuses=STATUSES,
        counts=counts,
        total=len(cases),
        cases=case_items,
        findings=[c for c in case_items if c["status"] in ("Fail", "Perlu Review")],
        modules=sorted({tc.module for tc in cases}),
        inventory=inventory,
        generated_at=now_iso(),
    )
    Path(path).write_text(html, encoding="utf-8")
```

- [ ] **Step 4: Implementasi template `qa_agent/report/templates/report.html.j2`**

```html
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Laporan QA — {{ meta.module or meta.target }}</title>
<style>
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#5b6474; --line:#e3e6eb;
  --pass:#1e7b3a; --pass-bg:#d8f1df; --fail:#a4161a; --fail-bg:#fbdcdc; --review:#7a5200; --review-bg:#fff0c2;
  --neutral:#4a4f59; --neutral-bg:#e6e8ec; }
* { box-sizing:border-box; }
body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }
header { background:#1f2a44; color:#fff; padding:24px 32px; }
header h1 { margin:0 0 4px; font-size:22px; }
header .meta { color:#c9d1e3; font-size:14px; }
main { max-width:1200px; margin:0 auto; padding:24px 16px 64px; }
.counters { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:8px; }
.counter { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 16px; min-width:120px; }
.counter b { display:block; font-size:24px; }
.badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }
.s-pass { background:var(--pass-bg); color:var(--pass); }
.s-fail { background:var(--fail-bg); color:var(--fail); }
.s-perlu-review { background:var(--review-bg); color:var(--review); }
.s-blocked, .s-skipped, .s-none, .s-belum-dijalankan { background:var(--neutral-bg); color:var(--neutral); }
section h2 { font-size:18px; margin:32px 0 12px; }
.filters { display:flex; gap:16px; margin:12px 0; flex-wrap:wrap; font-size:14px; }
select { padding:6px 10px; border:1px solid var(--line); border-radius:6px; background:#fff; }
details.tc { background:var(--card); border:1px solid var(--line); border-radius:8px; margin-bottom:10px; }
details.tc > summary { cursor:pointer; padding:12px 16px; display:flex; gap:12px; align-items:center; list-style:none; }
details.tc > summary::-webkit-details-marker { display:none; }
.tc-body { padding:4px 16px 16px; border-top:1px solid var(--line); }
table.kv { border-collapse:collapse; width:100%; margin:12px 0; font-size:14px; }
table.kv th { text-align:left; width:180px; color:var(--muted); font-weight:500; vertical-align:top; padding:4px 8px 4px 0; }
table.kv td { padding:4px 0; white-space:pre-wrap; }
ol.steps { padding-left:20px; }
ol.steps li { margin-bottom:18px; }
.thought { color:var(--muted); font-size:13px; }
.warn { color:var(--fail); font-size:13px; }
.signals { font-family:ui-monospace,Consolas,monospace; font-size:12px; color:var(--fail); }
img.shot { max-width:100%; width:640px; border:1px solid var(--line); border-radius:6px; cursor:zoom-in; margin-top:6px; display:block; }
#lightbox { position:fixed; inset:0; background:rgba(0,0,0,.85); display:none; align-items:center; justify-content:center; z-index:10; cursor:zoom-out; }
#lightbox img { max-width:95vw; max-height:95vh; }
.inventory { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:12px; }
.inv-card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; font-size:14px; }
.inv-card small { color:var(--muted); word-break:break-all; }
footer { color:var(--muted); font-size:12px; margin-top:40px; }
@media print { header { background:none; color:#000; } header .meta { color:#333; } .filters { display:none; } details.tc { break-inside:avoid; } }
</style>
</head>
<body>
<header>
  <h1>Laporan QA{% if meta.module %} — {{ meta.module }}{% endif %}</h1>
  <div class="meta">{{ meta.target }} · mode {{ meta.mode }} · environment {{ meta.environment }} · model {{ meta.model }}<br>
    {{ meta.started_at }}{% if meta.finished_at %} s/d {{ meta.finished_at }}{% endif %} · status run: {{ meta.status }}{% if meta.note %} · {{ meta.note }}{% endif %}</div>
</header>
<main>
{% if cases %}
  <div class="counters">
    <div class="counter">Total<b>{{ total }}</b></div>
    {% for s in statuses %}<div class="counter"><span class="badge {{ s|status_class }}">{{ s }}</span><b>{{ counts.get(s, 0) }}</b></div>{% endfor %}
  </div>
  {% if findings %}
  <section id="temuan">
    <h2>Temuan ({{ findings|length }})</h2>
    <ul>
    {% for f in findings %}<li><a href="#{{ f.tc.id }}">{{ f.tc.id }}</a> — {{ f.tc.title }} <span class="badge {{ f.status|status_class }}">{{ f.status }}</span>{% if f.tc.severity %} · {{ f.tc.severity }}{% endif %}</li>{% endfor %}
    </ul>
  </section>
  {% endif %}
  <section>
    <h2>Test Case</h2>
    <div class="filters">
      <label>Status <select id="f-status"><option value="">Semua</option>{% for s in statuses %}<option>{{ s }}</option>{% endfor %}<option>Belum dijalankan</option></select></label>
      <label>Modul <select id="f-module"><option value="">Semua</option>{% for m in modules %}<option>{{ m }}</option>{% endfor %}</select></label>
    </div>
    {% for c in cases %}
    <details class="tc" id="{{ c.tc.id }}" data-status="{{ c.status }}" data-module="{{ c.tc.module }}">
      <summary><span class="badge {{ c.status|status_class }}">{{ c.status }}</span><b>{{ c.tc.id }}</b> {{ c.tc.title }}</summary>
      <div class="tc-body">
        <table class="kv">
          <tr><th>Modul / Halaman</th><td>{{ c.tc.module }} / {{ c.tc.page or "-" }}</td></tr>
          <tr><th>Tipe / Prioritas</th><td>{{ c.tc.type }} / {{ c.tc.priority }}</td></tr>
          <tr><th>Pre-condition</th><td>{{ c.tc.precondition or "-" }}</td></tr>
          <tr><th>Test data</th><td>{{ c.tc.test_data or "-" }}</td></tr>
          <tr><th>Langkah</th><td>{% for s in c.tc.steps %}{{ loop.index }}. {{ s }}
{% endfor %}</td></tr>
          <tr><th>Expected</th><td>{{ c.tc.expected }} ({{ c.tc.expected_source }})</td></tr>
          <tr><th>Actual</th><td>{{ c.tc.actual or "-" }}</td></tr>
          <tr><th>Status AI</th><td>{{ c.tc.status_ai or "-" }}{% if c.tc.severity %} · {{ c.tc.severity }}{% endif %}</td></tr>
          <tr><th>Status Final</th><td>{{ c.tc.status_final or "-" }}</td></tr>
          {% if c.tc.reviewer_note %}<tr><th>Catatan reviewer</th><td>{{ c.tc.reviewer_note }}</td></tr>{% endif %}
        </table>
        {% if c.steps %}
        <h3>Eksekusi</h3>
        <ol class="steps">
        {% for s in c.steps %}
          <li value="{{ s.no }}">
            <div>{{ s.text }}</div>
            {% if s.thought %}<div class="thought">AI: {{ s.thought }}</div>{% endif %}
            {% if s.guard != "allowed" %}<div class="warn">{{ s.guard }}</div>{% endif %}
            {% if s.result not in ("ok", "skipped") %}<div class="warn">{{ s.result }}</div>{% endif %}
            {% if s.signals %}<div class="signals">{% for sig in s.signals %}{{ sig }}<br>{% endfor %}</div>{% endif %}
            {% if s.image %}<img class="shot" src="{{ s.image }}" alt="Langkah {{ s.no }}" loading="lazy">{% endif %}
          </li>
        {% endfor %}
        </ol>
        {% endif %}
      </div>
    </details>
    {% endfor %}
  </section>
{% endif %}
{% if inventory %}
  <section>
    <h2>Inventaris Fitur</h2>
    <div class="inventory">
    {% for i in inventory %}
      <div class="inv-card"><b>{{ i.screen.module }}</b> — {{ i.screen.page_name }}{% if i.screen.public %} <span class="badge s-none">Publik</span>{% endif %}<br>
        <small>{{ i.screen.url }}</small>
        {% if i.screen.purpose %}<p>{{ i.screen.purpose }}</p>{% endif %}
        {% if i.image %}<img class="shot" src="{{ i.image }}" alt="{{ i.screen.page_name }}" loading="lazy">{% endif %}
      </div>
    {% endfor %}
    </div>
  </section>
{% endif %}
  <footer>Dibuat oleh QA Agent pada {{ generated_at }}. Klik screenshot untuk memperbesar. Cetak ke PDF lewat menu Print browser.</footer>
</main>
<div id="lightbox"><img alt=""></div>
<script>
(function () {
  var st = document.getElementById('f-status'), md = document.getElementById('f-module');
  function apply() {
    document.querySelectorAll('details.tc').forEach(function (d) {
      var ok = (!st.value || d.dataset.status === st.value) && (!md.value || d.dataset.module === md.value);
      d.style.display = ok ? '' : 'none';
    });
  }
  if (st) { st.addEventListener('change', apply); md.addEventListener('change', apply); }
  var lb = document.getElementById('lightbox'), lbImg = lb.querySelector('img');
  document.addEventListener('click', function (e) {
    if (e.target.classList && e.target.classList.contains('shot')) { lbImg.src = e.target.src; lb.style.display = 'flex'; }
    else if (e.target === lb || e.target === lbImg) { lb.style.display = 'none'; }
  });
  if (location.hash) {
    var target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (target && target.tagName === 'DETAILS') { target.open = true; target.scrollIntoView(); }
  }
})();
</script>
</body>
</html>
```

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_html.py -v`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add qa_agent/report/html.py qa_agent/report/templates/report.html.j2 tests/unit/test_html.py
git commit -m "feat: laporan HTML satu file dengan screenshot tertanam dan filter"
```

---

### Task 21: Build laporan + impor hasil review

**Files:**
- Create: `qa_agent/report/build.py`
- Test: `tests/unit/test_build.py`

**Interfaces:**
- Consumes: `RunStore` (Task 8), `write_report_xlsx`, `read_review`, `ReportLockedError` (Task 19), `write_report_html` (Task 20)
- Produces:
  - `apply_review(cases, review: dict) -> None`
  - `import_review(store) -> int`: baca Status Final dan Catatan Reviewer dari `report.xlsx`, simpan ke `review.json`, kembalikan jumlah baris yang direview
  - `build_reports(store) -> tuple[Path, Path]`: tulis ulang `report.xlsx` + `report.html` dari data run + `review.json`

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_build.py`:

```python
import pytest
from openpyxl import Workbook, load_workbook

from qa_agent.report.build import build_reports, import_review
from qa_agent.report.excel import TC_HEADERS, ReportLockedError
from tests.report_fixtures import sample_run


def test_build_then_review_roundtrip(tmp_path):
    store = sample_run(tmp_path / "run")
    xlsx, html = build_reports(store)
    assert xlsx.exists() and html.exists()

    wb = load_workbook(xlsx)
    ws = wb["Test Cases"]
    ws.cell(3, TC_HEADERS.index("Status Final") + 1).value = "Fail"
    ws.cell(3, TC_HEADERS.index("Catatan Reviewer") + 1).value = "Konfirmasi bug, email wajib valid"
    wb.save(xlsx)

    assert import_review(store) == 1
    assert store.read_review()["TC-PEN-002"]["status_final"] == "Fail"
    build_reports(store)

    ws = load_workbook(xlsx)["Test Cases"]
    assert ws.cell(3, TC_HEADERS.index("Status Final") + 1).value == "Fail"
    assert ws.cell(3, TC_HEADERS.index("Catatan Reviewer") + 1).value == "Konfirmasi bug, email wajib valid"
    text = html.read_text(encoding="utf-8")
    assert "Konfirmasi bug, email wajib valid" in text
    assert 'data-status="Fail"' in text and 'data-status="Perlu Review"' not in text


def test_import_review_without_report(tmp_path):
    store = sample_run(tmp_path / "run")
    assert import_review(store) == 0


def test_locked_report_propagates(tmp_path, monkeypatch):
    store = sample_run(tmp_path / "run")
    monkeypatch.setattr(Workbook, "save", lambda self, f: (_ for _ in ()).throw(PermissionError(13, "denied")))
    with pytest.raises(ReportLockedError):
        build_reports(store)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_build.py -v`
Expected: FAIL dengan `ModuleNotFoundError`

- [ ] **Step 3: Implementasi**

`qa_agent/report/build.py`:

```python
from __future__ import annotations

from pathlib import Path

from qa_agent.evidence import RunStore
from qa_agent.models import QaTestCase
from qa_agent.report.excel import read_review, write_report_xlsx
from qa_agent.report.html import write_report_html


def apply_review(cases: list[QaTestCase], review: dict) -> None:
    for tc in cases:
        entry = review.get(tc.id)
        if entry:
            tc.status_final = entry.get("status_final")
            tc.reviewer_note = entry.get("reviewer_note", "")


def import_review(store: RunStore) -> int:
    if not store.report_xlsx.exists():
        return 0
    review = read_review(store.report_xlsx)
    store.write_review(review)
    return sum(1 for r in review.values() if r["status_final"] or r["reviewer_note"])


def build_reports(store: RunStore) -> tuple[Path, Path]:
    meta = store.read_meta()
    cases = store.read_testcases()
    apply_review(cases, store.read_review())
    steps = store.read_steps()
    app_map = store.read_app_map()
    write_report_xlsx(store.report_xlsx, meta, cases, steps, app_map)
    write_report_html(store.report_html, store.root, meta, cases, steps, app_map)
    return store.report_xlsx, store.report_html
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_build.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add qa_agent/report/build.py tests/unit/test_build.py
git commit -m "feat: build ulang laporan dengan status final dari reviewer"
```

---

### Task 22: Runtime & CLI

**Files:**
- Create: `qa_agent/runtime.py`, `qa_agent/templates.py`, `qa_agent/cli.py`
- Test: `tests/unit/test_runtime.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: semua komponen sebelumnya
- Produces:
  - `StopFlag` (callable `() -> bool`, `.set()`, `.install()` untuk SIGINT)
  - `Runtime` dataclass (`cfg, store, environment, driver, llm, guard, masker, stop, loop, auth, data_prefix`)
  - `build_runtime(cfg, store, project_dir, *, environment, llm=None, now=None) -> Runtime`
  - `make_explorer(rt) -> Explorer`, `make_planner(rt) -> DeepPlanner`, `make_runner(rt) -> DeepRunner`
  - CLI `qa-agent` dengan perintah `init`, `check`, `explore`, `deep`, `run`, `report`. Exit code: 0 = selesai, 1 = input/config salah, 2 = run tidak selesai (paused/interrupted).

- [ ] **Step 1: Tulis test yang gagal**

`tests/unit/test_runtime.py`:

```python
import signal
from datetime import datetime

import pytest

from qa_agent.config import Config, ConfigError
from qa_agent.evidence import RunStore
from qa_agent.llm.fake import FakeLLM
from qa_agent.runtime import StopFlag, build_runtime


def cfg():
    return Config.model_validate({
        "target": {"url": "https://app-dev.kantor.local"},
        "accounts": [{"role": "admin", "username_env": "RT_USER", "password_env": "RT_PASS"}],
        "llm": {"base_url": "http://ai.test/v1", "model": "fake", "api_key_env": "RT_KEY"},
    })


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("RT_USER", "qa@kantor.local")
    monkeypatch.setenv("RT_PASS", "s3cret!")
    monkeypatch.setenv("RT_KEY", "k")


def test_build_runtime_dev(tmp_path, env):
    rt = build_runtime(cfg(), RunStore(tmp_path / "run"), tmp_path, environment="dev", llm=FakeLLM([]), now=datetime(2026, 10, 5, 14, 30))
    assert rt.data_prefix == "QA-AUTO-20261005-1430"
    assert rt.driver.request_filter is None
    assert rt.auth.state_path == tmp_path / ".qa-agent" / "auth" / "app-dev-kantor-local-admin.json"
    assert rt.masker.mask("s3cret!") == "••••••"
    assert rt.loop.relogin is None and rt.loop.max_steps == 25


def test_build_runtime_production_installs_request_filter(tmp_path, env):
    rt = build_runtime(cfg(), RunStore(tmp_path / "run"), tmp_path, environment="production", llm=FakeLLM([]))
    assert rt.driver.request_filter("POST", "https://app-dev.kantor.local/api/users") is True
    assert rt.driver.request_filter("POST", "https://app-dev.kantor.local/login") is False


def test_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_USER", "")
    with pytest.raises(ConfigError, match="RT_USER"):
        build_runtime(cfg(), RunStore(tmp_path / "run"), tmp_path, environment="dev", llm=FakeLLM([]))


def test_stop_flag_install():
    original = signal.getsignal(signal.SIGINT)
    try:
        flag = StopFlag()
        assert flag() is False
        flag.install()
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)  # simulasi Ctrl+C pertama
        assert flag() is True
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    finally:
        signal.signal(signal.SIGINT, original)
```

`tests/unit/test_cli.py`:

```python
import pytest
from typer.testing import CliRunner

from qa_agent import cli
from qa_agent.cli import app
from qa_agent.evidence import RunStore
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import RunMeta
from qa_agent.templates import CONFIG_TEMPLATE
from tests.report_fixtures import sample_run

runner = CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "qa-agent.yaml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(cli, "_check_browser", lambda: (True, ""))
    monkeypatch.setattr(cli, "_check_target", lambda url: (True, url))
    return tmp_path


@pytest.fixture
def secrets(monkeypatch):
    monkeypatch.setenv("QA_ADMIN_USER", "qa@kantor.local")
    monkeypatch.setenv("QA_ADMIN_PASS", "s3cret!")
    monkeypatch.setenv("OFFICE_AI_KEY", "k")


def test_init_creates_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / "qa-agent.yaml").exists() and (tmp_path / ".env.example").exists()
    assert "LEWATI" in runner.invoke(app, ["init"]).output


def test_check_invalid_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "qa-agent.yaml").write_text("target: {}", encoding="utf-8")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1 and "[GAGAL] Config" in result.output


def test_check_reports_missing_secrets(project, monkeypatch):
    for name in ("QA_ADMIN_USER", "QA_ADMIN_PASS", "OFFICE_AI_KEY"):
        monkeypatch.setenv(name, "")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "[GAGAL] Kredensial akun" in result.output and "QA_ADMIN_USER" in result.output
    assert "[GAGAL] API key AI" in result.output


def test_check_all_ok_with_fake_llm(project, secrets, monkeypatch):
    monkeypatch.setattr(cli, "build_llm", lambda cfg: FakeLLM(["OK", "Merah"]))
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "[OK] Endpoint AI (teks)" in result.output and "[OK] Endpoint AI (gambar)" in result.output


def test_check_vision_wrong_answer_fails(project, secrets, monkeypatch):
    monkeypatch.setattr(cli, "build_llm", lambda cfg: FakeLLM(["OK", "saya tidak bisa melihat gambar"]))
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1 and "[GAGAL] Endpoint AI (gambar)" in result.output


def test_report_rebuilds(project):
    store = sample_run(project / "runs" / "contoh")
    result = runner.invoke(app, ["report", "--run", str(store.root)])
    assert result.exit_code == 0, result.output
    assert store.report_xlsx.exists() and store.report_html.exists()


def test_report_rejects_non_run_folder(project):
    (project / "kosong").mkdir()
    result = runner.invoke(app, ["report", "--run", str(project / "kosong")])
    assert result.exit_code == 1 and "bukan folder run" in result.output


def test_deep_unknown_module_lists_modules(project, secrets):
    store = sample_run(project / "runs" / "explore")
    result = runner.invoke(app, ["deep", "--from", str(store.root), "--module", "Transaksi"])
    assert result.exit_code == 1 and "Pengguna" in result.output


def test_deep_rejects_pdf_prd(project, secrets):
    store = sample_run(project / "runs" / "explore")
    (project / "prd.pdf").write_bytes(b"%PDF")
    result = runner.invoke(app, ["deep", "--from", str(store.root), "--module", "Pengguna", "--prd", "prd.pdf"])
    assert result.exit_code == 1 and ".md atau .txt" in result.output


def test_run_rejects_explore_run(project, secrets):
    store = RunStore(project / "runs" / "x")
    store.write_meta(RunMeta(mode="explore", target="http://a", environment="dev", model="m", started_at="2026-10-05T10:00:00"))
    result = runner.invoke(app, ["run", "--run", str(store.root)])
    assert result.exit_code == 1 and "mode deep" in result.output


def test_invalid_env_option(project, secrets):
    result = runner.invoke(app, ["explore", "--env", "staging"])
    assert result.exit_code == 1 and "dev' atau 'production" in result.output
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `.venv/Scripts/python -m pytest tests/unit/test_runtime.py tests/unit/test_cli.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'qa_agent.runtime'`

- [ ] **Step 3: Implementasi `runtime.py`**

```python
from __future__ import annotations

import signal
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from qa_agent.agent.loop import AgentLoop
from qa_agent.config import Config
from qa_agent.drivers.web import WebDriver
from qa_agent.evidence import Masker, RunStore
from qa_agent.guard import Guard
from qa_agent.llm.base import LLMClient
from qa_agent.llm.factory import build_llm
from qa_agent.orchestrator.auth import AuthManager, auth_state_path
from qa_agent.orchestrator.deep import DeepPlanner, DeepRunner
from qa_agent.orchestrator.explore import Explorer


class StopFlag:
    """Ctrl+C pertama: selesaikan langkah berjalan lalu berhenti. Ctrl+C kedua: keluar paksa."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def __call__(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        self._event.set()

    def install(self) -> None:
        def handler(signum, frame):
            self.set()
            signal.signal(signal.SIGINT, signal.default_int_handler)
            print("\nCtrl+C diterima: menyelesaikan langkah berjalan lalu menulis laporan. "
                  "Tekan Ctrl+C lagi untuk keluar paksa.", file=sys.stderr)

        signal.signal(signal.SIGINT, handler)


@dataclass
class Runtime:
    cfg: Config
    store: RunStore
    environment: str
    driver: WebDriver
    llm: LLMClient
    guard: Guard
    masker: Masker
    stop: StopFlag
    loop: AgentLoop
    auth: AuthManager
    data_prefix: str


def build_runtime(cfg: Config, store: RunStore, project_dir: Path, *, environment: str,
                  llm: LLMClient | None = None, now: datetime | None = None) -> Runtime:
    guard = Guard(environment, cfg.domains(), extra_keywords=cfg.guard.extra_risky_keywords,
                  login_endpoints=cfg.target.login_endpoints)
    creds = cfg.credentials()
    masker = Masker([creds.password])
    driver = WebDriver(cfg.target.url, headless=cfg.browser.headless, viewport=cfg.browser.size,
                       request_filter=guard.should_block_request if guard.production else None)
    driver.set_credentials(creds.username, creds.password)
    stop = StopFlag()
    data_prefix = f"QA-AUTO-{(now or datetime.now()):%Y%m%d-%H%M}"
    llm = llm or build_llm(cfg)
    common = dict(driver=driver, llm=llm, guard=guard, store=store, masker=masker, data_prefix=data_prefix,
                  max_steps=cfg.limits.max_steps_per_tc, vision=cfg.llm.vision, should_stop=stop)
    login_loop = AgentLoop(**common)
    auth = AuthManager(driver, lambda tc_id, goal: login_loop.run(tc_id, goal, login=True),
                       auth_state_path(project_dir, cfg.target.url, creds.role), creds.role)
    return Runtime(cfg=cfg, store=store, environment=environment, driver=driver, llm=llm, guard=guard, masker=masker,
                   stop=stop, loop=AgentLoop(**common), auth=auth, data_prefix=data_prefix)


def make_explorer(rt: Runtime) -> Explorer:
    limits = rt.cfg.limits
    return Explorer(driver=rt.driver, llm=rt.llm, guard=rt.guard, store=rt.store, auth=rt.auth,
                    start_url=rt.cfg.target.url, max_screens=limits.explore_max_screens,
                    max_depth=limits.explore_max_depth, max_minutes=limits.explore_max_minutes,
                    vision=rt.cfg.llm.vision, should_stop=rt.stop)


def make_planner(rt: Runtime) -> DeepPlanner:
    return DeepPlanner(rt.llm, data_prefix=rt.data_prefix, max_tcs=rt.cfg.limits.deep_max_tcs)


def make_runner(rt: Runtime) -> DeepRunner:
    return DeepRunner(driver=rt.driver, loop=rt.loop, auth=rt.auth, store=rt.store, should_stop=rt.stop)
```

- [ ] **Step 4: Implementasi `templates.py`**

```python
CONFIG_TEMPLATE = """# Konfigurasi QA Agent. Rahasia (API key, password) diisi di file .env, BUKAN di sini.
target:
  platform: web
  url: https://app-dev.kantor.local          # URL aplikasi yang dites
  allowed_domains: []                         # kosong = domain dari url
  login_endpoints: []                         # kosong = heuristik (login/auth/signin/token/session)
environment: dev                              # dev | production (bisa di-override: --env production)
accounts:
  - role: admin
    username_env: QA_ADMIN_USER
    password_env: QA_ADMIN_PASS
llm:
  provider: openai_compatible                 # openai_compatible (AI kantor) | anthropic (Claude)
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
  headless: false                             # false = browser terlihat, kamu bisa menonton agent bekerja
  viewport: 1366x768
"""

ENV_TEMPLATE = """# Salin file ini menjadi .env lalu isi nilainya. File .env TIDAK BOLEH di-commit.
OFFICE_AI_KEY=
# ANTHROPIC_API_KEY=
QA_ADMIN_USER=
QA_ADMIN_PASS=
"""
```

- [ ] **Step 5: Implementasi `cli.py`**

```python
from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, NoReturn, Optional
from urllib.parse import urlsplit

import typer

from qa_agent.config import Config, ConfigError, load_config
from qa_agent.evidence import RunStore, now_iso
from qa_agent.imaging import solid_png
from qa_agent.llm.base import LLMError, Message
from qa_agent.llm.factory import build_llm
from qa_agent.models import STATUSES, AppMap, QaTestCase, RunMeta
from qa_agent.orchestrator.auth import LoginFailed
from qa_agent.orchestrator.deep import PlanError
from qa_agent.report.build import build_reports, import_review
from qa_agent.report.excel import ReportLockedError, import_cases_xlsx, write_cases_xlsx
from qa_agent.runtime import Runtime, build_runtime, make_explorer, make_planner, make_runner
from qa_agent.templates import CONFIG_TEMPLATE, ENV_TEMPLATE

app = typer.Typer(help="QA Agent — AI QA automation untuk aplikasi web.", no_args_is_help=True, add_completion=False)
CONFIG_HELP = "File konfigurasi"


def _fail(message: str) -> NoReturn:
    typer.echo(f"[GAGAL] {message}", err=True)
    raise typer.Exit(1)


def _load(config: Path) -> Config:
    try:
        return load_config(config)
    except ConfigError as e:
        _fail(str(e))


def _environment(option: str | None, cfg: Config) -> str:
    env = option or cfg.environment
    if env not in ("dev", "production"):
        _fail("--env harus 'dev' atau 'production'")
    return env


def _project_dir(config: Path) -> Path:
    return config.resolve().parent


def _runtime(cfg: Config, store: RunStore, config: Path, environment: str) -> Runtime:
    try:
        return build_runtime(cfg, store, _project_dir(config), environment=environment)
    except ConfigError as e:
        _fail(str(e))


def _write_reports(store: RunStore) -> None:
    try:
        xlsx, html = build_reports(store)
    except ReportLockedError as e:
        typer.echo(f"[GAGAL] {e}", err=True)
        return
    typer.echo(f"Laporan Excel : {xlsx}")
    typer.echo(f"Laporan HTML  : {html}")


def _finish(store: RunStore, meta: RunMeta, status: str, note: str = "") -> None:
    meta.status = status  # type: ignore[assignment]
    meta.finished_at = now_iso()
    meta.note = note
    store.write_meta(meta)
    _write_reports(store)


def _run_guarded(rt: Runtime, meta: RunMeta, body: Callable[[], object]) -> str:
    rt.stop.install()
    status, note = "completed", ""
    try:
        rt.driver.start()
        body()
        if rt.stop():
            status, note = "interrupted", "Dihentikan dengan Ctrl+C"
    except LLMError as e:
        status, note = "paused", f"Endpoint AI bermasalah: {e}"
    except LoginFailed as e:
        status, note = "paused", f"Login gagal: {e}"
    except KeyboardInterrupt:
        status, note = "interrupted", "Dihentikan paksa"
    except Exception as e:  # jangan sampai laporan tidak ditulis
        status, note = "interrupted", f"Error tak terduga: {type(e).__name__}: {e}"
    finally:
        try:
            rt.driver.stop()
        except Exception:
            pass
        _finish(rt.store, meta, status, note)
    typer.echo(f"Status run: {status}" + (f" — {note}" if note else ""))
    return status


def _check_browser() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True, ""
    except Exception as e:
        return False, f"jalankan: python -m playwright install chromium ({type(e).__name__})"


def _check_target(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return True, f"{url} (HTTP {resp.status})"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"{url} (HTTP {e.code})"
    except Exception as e:
        return False, f"{url}: {e}"


@app.command()
def init(force: bool = typer.Option(False, "--force", help="Timpa file yang sudah ada")) -> None:
    """Buat qa-agent.yaml dan .env.example di folder ini."""
    for name, content in (("qa-agent.yaml", CONFIG_TEMPLATE), (".env.example", ENV_TEMPLATE)):
        path = Path(name)
        if path.exists() and not force:
            typer.echo(f"[LEWATI] {name} sudah ada (pakai --force untuk menimpa)")
            continue
        path.write_text(content, encoding="utf-8")
        typer.echo(f"[OK] {name} dibuat")
    typer.echo("Berikutnya: salin .env.example menjadi .env, isi nilainya, lalu jalankan 'qa-agent check'.")


@app.command()
def check(config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP)) -> None:
    """Cek config, kredensial, endpoint AI (teks & gambar), browser, dan target."""
    ok = True

    def line(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        typer.echo(f"[{'OK' if passed else 'GAGAL'}] {name}" + (f" — {detail}" if detail else ""))

    try:
        cfg = load_config(config)
    except ConfigError as e:
        line("Config", False, str(e))
        raise typer.Exit(1)
    line("Config", True, str(config))

    secrets_ok = True
    for label, getter in (("Kredensial akun", cfg.credentials), ("API key AI", cfg.api_key)):
        try:
            getter()
            line(label, True)
        except ConfigError as e:
            line(label, False, str(e))
            secrets_ok = False

    if secrets_ok:
        llm = build_llm(cfg)
        try:
            reply = llm.chat("Jawab sangat singkat.", [Message(role="user", text="Balas dengan satu kata: OK")])
            line("Endpoint AI (teks)", bool(reply.strip()), f"{cfg.llm.model}: {reply.strip()[:40]}")
        except LLMError as e:
            line("Endpoint AI (teks)", False, str(e))
        if cfg.llm.vision:
            try:
                reply = llm.chat("Jawab dengan satu kata.", [Message(
                    role="user", text="Apa warna gambar ini? Jawab: merah, hijau, atau biru.",
                    images=[solid_png((220, 20, 20), (64, 64))])])
                line("Endpoint AI (gambar)", any(w in reply.lower() for w in ("merah", "red")), reply.strip()[:40] or "(kosong)")
            except LLMError as e:
                line("Endpoint AI (gambar)", False, str(e))

    line("Browser Chromium", *_check_browser())
    line("Target", *_check_target(cfg.target.url))
    if not ok:
        raise typer.Exit(1)


@app.command()
def explore(
    config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP),
    env: Optional[str] = typer.Option(None, "--env", help="dev | production"),
) -> None:
    """Petakan seluruh aplikasi (hanya navigasi) menjadi inventaris fitur."""
    cfg = _load(config)
    environment = _environment(env, cfg)
    store = RunStore.create(_project_dir(config) / "runs", "explore", urlsplit(cfg.target.url).netloc)
    rt = _runtime(cfg, store, config, environment)
    meta = RunMeta(mode="explore", target=cfg.target.url, environment=environment, model=cfg.llm.model, started_at=now_iso())
    store.write_meta(meta)
    typer.echo(f"Folder run: {store.root}")
    status = _run_guarded(rt, meta, make_explorer(rt).run)
    app_map = store.read_app_map()
    if app_map:
        typer.echo(f"Ditemukan {len(app_map.screens)} layar dalam {len(app_map.modules())} modul: {', '.join(app_map.modules())}")
    if status != "completed":
        raise typer.Exit(2)


def _read_prd(prd: Path | None) -> str | None:
    if prd is None:
        return None
    if prd.suffix.lower() not in (".md", ".txt"):
        _fail("PRD harus berupa file .md atau .txt (salin isi PDF/Word ke file teks dulu)")
    if not prd.exists():
        _fail(f"File PRD {prd} tidak ditemukan")
    return prd.read_text(encoding="utf-8")


def _execute(rt: Runtime, meta: RunMeta, app_map: AppMap, cases: list[QaTestCase]) -> None:
    needs_auth = not all(s.public for s in app_map.screens_for(meta.module or ""))
    typer.echo(f"Menjalankan {sum(1 for c in cases if c.status_ai is None)} test case...")
    meta.status = "running"
    rt.store.write_meta(meta)
    status = _run_guarded(rt, meta, lambda: make_runner(rt).execute(cases, needs_auth=needs_auth))
    counts = {s: sum(1 for c in cases if c.status_ai == s) for s in STATUSES}
    typer.echo("Hasil: " + ", ".join(f"{s} {n}" for s, n in counts.items() if n))
    if status == "paused":
        typer.echo(f'Lanjutkan dengan: qa-agent run --run "{rt.store.root}" --resume')
    if status != "completed":
        raise typer.Exit(2)


@app.command()
def deep(
    from_run: Path = typer.Option(..., "--from", help="Folder run hasil explore"),
    module: str = typer.Option(..., "--module", help="Nama modul dari hasil explore"),
    prd: Optional[Path] = typer.Option(None, "--prd", help="File PRD .md/.txt (opsional)"),
    review: bool = typer.Option(False, "--review", help="Berhenti setelah test case disusun untuk direview"),
    config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP),
    env: Optional[str] = typer.Option(None, "--env", help="dev | production"),
) -> None:
    """Susun test case untuk satu modul lalu jalankan."""
    cfg = _load(config)
    environment = _environment(env, cfg)
    if not (from_run / "app_map.json").exists():
        _fail(f"{from_run} bukan folder run explore (app_map.json tidak ada)")
    app_map = RunStore(from_run).read_app_map()
    assert app_map is not None
    canonical = app_map.find_module(module)
    if canonical is None:
        _fail(f"Modul '{module.strip()}' tidak ditemukan. Modul yang tersedia: {', '.join(app_map.modules())}")
    prd_text = _read_prd(prd)

    store = RunStore.create(_project_dir(config) / "runs", "deep", canonical)
    store.write_app_map(app_map)
    rt = _runtime(cfg, store, config, environment)
    meta = RunMeta(mode="deep", target=cfg.target.url, environment=environment, model=cfg.llm.model,
                   started_at=now_iso(), module=canonical, source_run=str(from_run))
    store.write_meta(meta)
    typer.echo(f"Folder run: {store.root}")
    typer.echo(f"Menyusun test case untuk modul '{canonical}'...")
    try:
        cases = make_planner(rt).plan(app_map, canonical, prd_text)
    except (PlanError, LLMError) as e:
        _finish(store, meta, "paused", str(e))
        _fail(str(e))
    store.write_testcases(cases)
    typer.echo(f"{len(cases)} test case disusun.")

    if review:
        try:
            write_cases_xlsx(store.cases_xlsx, cases)
        except ReportLockedError as e:
            _fail(str(e))
        _finish(store, meta, "paused", "Menunggu review test case")
        typer.echo(f"Review & edit test case di: {store.cases_xlsx}")
        typer.echo(f'Lalu jalankan: qa-agent run --run "{store.root}"')
        return
    _execute(rt, meta, app_map, cases)


@app.command("run")
def run_command(
    run_dir: Path = typer.Option(..., "--run", help="Folder run mode deep"),
    resume: bool = typer.Option(False, "--resume", help="Lanjutkan test case yang belum selesai"),
    config: Path = typer.Option(Path("qa-agent.yaml"), "--config", "-c", help=CONFIG_HELP),
) -> None:
    """Jalankan test case hasil review, atau lanjutkan run yang terhenti."""
    cfg = _load(config)
    if not (run_dir / "run.json").exists():
        _fail(f"{run_dir} bukan folder run (run.json tidak ada)")
    store = RunStore(run_dir)
    meta = store.read_meta()
    if meta.mode != "deep":
        _fail("Hanya run mode deep yang bisa dijalankan atau dilanjutkan")
    app_map = store.read_app_map() or AppMap(target=meta.target)

    if resume:
        cases = store.read_testcases()
    elif store.cases_xlsx.exists():
        try:
            cases = import_cases_xlsx(store.cases_xlsx)
        except ValueError as e:
            _fail(f"{store.cases_xlsx.name}: {e}")
    else:
        cases = store.read_testcases()
    if not resume:
        for c in cases:
            c.status_ai, c.actual, c.ai_note, c.severity = None, "", "", None
    if not cases:
        _fail("Tidak ada test case untuk dijalankan")
    store.write_testcases(cases)
    rt = _runtime(cfg, store, config, meta.environment)
    _execute(rt, meta, app_map, cases)


@app.command()
def report(run_dir: Path = typer.Option(..., "--run", help="Folder run")) -> None:
    """Buat ulang laporan memakai Status Final dan Catatan Reviewer dari report.xlsx."""
    if not (run_dir / "run.json").exists():
        _fail(f"{run_dir} bukan folder run (run.json tidak ada)")
    store = RunStore(run_dir)
    try:
        n = import_review(store)
        xlsx, html = build_reports(store)
    except ValueError as e:
        _fail(f"report.xlsx: {e}")
    except ReportLockedError as e:
        _fail(str(e))
    typer.echo(f"{n} baris review diimpor.")
    typer.echo(f"Laporan Excel : {xlsx}")
    typer.echo(f"Laporan HTML  : {html}")
```

- [ ] **Step 6: Jalankan test, pastikan lulus**

Run: `.venv/Scripts/python -m pytest tests/unit/test_runtime.py tests/unit/test_cli.py -v`
Expected: `15 passed`

- [ ] **Step 7: Cek entry point**

Run: `.venv/Scripts/qa-agent --help`
Expected: daftar perintah `init`, `check`, `explore`, `deep`, `run`, `report`

- [ ] **Step 8: Commit**

```bash
git add qa_agent/runtime.py qa_agent/templates.py qa_agent/cli.py tests/unit/test_runtime.py tests/unit/test_cli.py
git commit -m "feat: CLI qa-agent (init, check, explore, deep, run, report) dengan Ctrl+C aman"
```

---

### Task 23: Test end-to-end terhadap aplikasi demo (browser asli + AI palsu)

Membuktikan seluruh rantai bekerja di browser sungguhan: explore → plan → execute → laporan. Juga memastikan mode production memblok semua penulisan data. AI diganti `DemoBrain`, yaitu AI palsu yang mengenal aplikasi demo, sehingga test bersifat deterministik dan gratis.

**Files:**
- Create: `tests/integration/brain.py`
- Test: `tests/integration/test_e2e_demo.py`

**Interfaces:**
- Consumes: `build_runtime`, `make_explorer`, `make_planner`, `make_runner` (Task 22), `build_reports` (Task 21), `FakeLLM` (Task 7), fixture `demo` (Task 10)
- Produces: `DemoBrain()` (callable untuk `FakeLLM`)

- [ ] **Step 1: Tulis `tests/integration/brain.py`**

```python
"""AI palsu yang 'paham' aplikasi demo, untuk test end-to-end tanpa endpoint AI sungguhan."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

SCRIPTS: dict[str, list[tuple]] = {
    "Login ke aplikasi": [
        ("type", "input", "Email", "{{username}}"), ("type", "input", "Password", "{{password}}"),
        ("click", "button", "Masuk", None), ("done", "pass", "Berhasil masuk ke dashboard"),
    ],
    "Tambah pengguna dengan data valid": [
        ("type", "input", "Nama", "QA-AUTO Valid"), ("type", "input", "Email", "valid@demo.local"),
        ("type", "input", "Umur", "30"), ("click", "button", "Simpan", None), ("done", "pass", "Pengguna baru muncul di daftar"),
    ],
    "Validasi format email": [
        ("type", "input", "Nama", "QA-AUTO Email"), ("type", "input", "Email", "bukan-email"),
        ("type", "input", "Umur", "25"), ("click", "button", "Simpan", None), ("done", "fail", "Data tersimpan tanpa pesan validasi email"),
    ],
    "Nama dengan apostrof": [
        ("type", "input", "Nama", "O'Brien"), ("type", "input", "Email", "obrien@demo.local"),
        ("type", "input", "Umur", "40"), ("click", "button", "Simpan", None), ("done", "pass", "Pengguna tersimpan"),
    ],
    "Proses ulang laporan": [
        ("click", "button", "Proses Ulang", None), ("done", "pass", "Laporan diproses ulang"),
    ],
}
HIGH_RISK = {"Simpan"}

PLAN = {"test_cases": [
    {"title": "Tambah pengguna dengan data valid", "page": "Tambah Pengguna", "type": "positif", "priority": "High",
     "steps": ["Isi Nama, Email, Umur dengan data valid", "Klik Simpan"], "expected": "Pengguna baru muncul di daftar",
     "expected_source": "Inferensi AI", "start_url": "/users/new", "test_data": "Nama: QA-AUTO Valid; Email: valid@demo.local; Umur: 30"},
    {"title": "Validasi format email", "page": "Tambah Pengguna", "type": "validasi", "priority": "High",
     "steps": ["Isi Email dengan 'bukan-email'", "Klik Simpan"], "expected": "Muncul pesan validasi format email",
     "expected_source": "Inferensi AI", "start_url": "/users/new", "test_data": "Email: bukan-email"},
    {"title": "Nama dengan apostrof", "page": "Tambah Pengguna", "type": "boundary", "priority": "Medium",
     "steps": ["Isi Nama dengan O'Brien", "Klik Simpan"], "expected": "Pengguna tersimpan",
     "expected_source": "Inferensi AI", "start_url": "/users/new", "test_data": "Nama: O'Brien"},
]}


def _module_for(path: str) -> str:
    if path.startswith("/login"):
        return "Autentikasi"
    if path.startswith("/users"):
        return "Pengguna"
    if path.startswith("/reports"):
        return "Laporan"
    return "Dashboard"


def _index(text: str, role: str, name: str) -> int | None:
    match = re.search(rf'^\[(\d+)\] {re.escape(role)} "{re.escape(name)}"', text, re.M)
    return int(match.group(1)) if match else None


class DemoBrain:
    def __init__(self) -> None:
        self.progress: dict[str, int] = {}

    def __call__(self, system, messages) -> str:
        text = messages[0].text
        if system.startswith("MODE: EXPLORE_SCREEN"):
            return self._explore(text)
        if system.startswith("MODE: PLAN"):
            return json.dumps(PLAN)
        return self._execute(text)

    def _explore(self, text: str) -> str:
        path = urlsplit(re.search(r"^URL: (\S+)", text, re.M).group(1)).path or "/"
        links = [int(i) for i in re.findall(r"^\[(\d+)\] link ", text, re.M)]
        return json.dumps({"module": _module_for(path), "page_name": path, "purpose": f"Halaman {path}", "nav_candidates": links})

    def _execute(self, text: str) -> str:
        goal = text.split("## Tujuan\n", 1)[1].split("\n", 1)[0]
        key = next(k for k in SCRIPTS if k in goal)
        history_head = text.split("## Riwayat langkah terakhir\n", 1)[1].split("\n", 1)[0]
        if history_head == "(belum ada)":
            self.progress[key] = 0
        if "diblok Safety Guard" in text:
            return json.dumps({"action": "blocked", "reason": "Aksi diblok mode production"})
        step = self.progress.get(key, 0)
        self.progress[key] = step + 1
        item = SCRIPTS[key][min(step, len(SCRIPTS[key]) - 1)]
        if item[0] == "done":
            status, actual = item[1], item[2]
            if "HTTP 5" in text:
                status, actual = "fail", "Server error 500 setelah klik Simpan"
            return json.dumps({"action": "done", "status": status, "actual": actual,
                               "severity": "Major" if status == "fail" else None})
        kind, role, name, value = item
        idx = _index(text, role, name)
        if idx is None:
            return json.dumps({"action": "blocked", "reason": f"{role} '{name}' tidak ditemukan"})
        return json.dumps({"action": kind, "element": idx, "value": value,
                           "risk": "high" if name in HIGH_RISK else "low", "thought": f"{kind} {name}"})
```

- [ ] **Step 2: Tulis test end-to-end**

`tests/integration/test_e2e_demo.py`:

```python
import pytest
from openpyxl import load_workbook

from qa_agent.config import Config
from qa_agent.evidence import RunStore, now_iso
from qa_agent.llm.fake import FakeLLM
from qa_agent.models import QaTestCase, RunMeta
from qa_agent.report.build import build_reports
from qa_agent.runtime import build_runtime, make_explorer, make_planner, make_runner
from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER
from tests.integration.brain import DemoBrain

pytestmark = pytest.mark.browser


@pytest.fixture
def cfg(demo, monkeypatch):
    monkeypatch.setenv("DEMO_USER", DEMO_USER)
    monkeypatch.setenv("DEMO_PASS", DEMO_PASSWORD)
    monkeypatch.setenv("DEMO_AI_KEY", "tidak-dipakai")
    return Config.model_validate({
        "target": {"url": demo.url},
        "accounts": [{"role": "admin", "username_env": "DEMO_USER", "password_env": "DEMO_PASS"}],
        "llm": {"base_url": "http://tidak-dipakai.test/v1", "model": "demo-brain", "api_key_env": "DEMO_AI_KEY"},
        "browser": {"headless": True},
        "limits": {"explore_max_minutes": 5},
    })


def meta(mode, target, module=None, environment="dev"):
    return RunMeta(mode=mode, target=target, environment=environment, model="demo-brain", started_at=now_iso(), module=module)


def run_explore(tmp_path, cfg):
    store = RunStore(tmp_path / "explore")
    store.write_meta(meta("explore", cfg.target.url))
    rt = build_runtime(cfg, store, tmp_path, environment="dev", llm=FakeLLM(DemoBrain()))
    rt.driver.start()
    try:
        app_map = make_explorer(rt).run()
    finally:
        rt.driver.stop()
    return app_map, store


def test_explore_demo_app(tmp_path, cfg, demo):
    app_map, store = run_explore(tmp_path, cfg)
    assert app_map.modules() == ["Autentikasi", "Dashboard", "Pengguna", "Laporan"]
    assert app_map.screens[0].public and "/login" in app_map.screens[0].url
    assert sum(1 for s in app_map.screens if s.url.endswith("/edit")) == 1
    assert demo.state.writes == []  # explore tidak pernah submit/hapus/logout
    assert len(demo.state.users) == 2
    xlsx, html = build_reports(store)
    assert "Inventaris Fitur" in load_workbook(xlsx).sheetnames
    assert (tmp_path / ".qa-agent" / "auth").is_dir()
    assert not list(store.root.rglob("*storage*"))  # sesi login tidak disimpan di folder run


def test_deep_dev_finds_seeded_bugs(tmp_path, cfg, demo):
    app_map, _ = run_explore(tmp_path, cfg)
    store = RunStore(tmp_path / "deep")
    store.write_app_map(app_map)
    store.write_meta(meta("deep", cfg.target.url, module="Pengguna"))
    rt = build_runtime(cfg, store, tmp_path, environment="dev", llm=FakeLLM(DemoBrain()))
    cases = make_planner(rt).plan(app_map, "pengguna")
    store.write_testcases(cases)
    rt.driver.start()
    try:
        make_runner(rt).execute(cases, needs_auth=True)
    finally:
        rt.driver.stop()

    assert [c.id for c in cases] == ["TC-PEN-001", "TC-PEN-002", "TC-PEN-003"]
    assert [c.status_ai for c in cases] == ["Pass", "Perlu Review", "Fail"]
    assert len(demo.state.users) == 4  # valid + email tidak valid tersimpan (bug #2); apostrof gagal (bug #1)

    xlsx, html = build_reports(store)
    findings = [row[1] for row in load_workbook(xlsx)["Temuan"].iter_rows(min_row=2, values_only=True)]
    assert findings == ["TC-PEN-002", "TC-PEN-003"]
    assert "HTTP 500 POST" in html.read_text(encoding="utf-8")
    assert DEMO_PASSWORD not in store.steps_path.read_text(encoding="utf-8")


def test_production_mode_blocks_all_writes(tmp_path, cfg, demo):
    store = RunStore(tmp_path / "prod")
    store.write_meta(meta("deep", cfg.target.url, module="Pengguna", environment="production"))
    rt = build_runtime(cfg, store, tmp_path, environment="production", llm=FakeLLM(DemoBrain()))
    cases = [
        QaTestCase(id="TC-PEN-001", module="Pengguna", title="Tambah pengguna dengan data valid",
                   steps=["Isi form", "Klik Simpan"], expected="Tersimpan", start_url=f"{demo.url}/users/new"),
        QaTestCase(id="TC-LAP-001", module="Laporan", title="Proses ulang laporan",
                   steps=["Klik Proses Ulang"], expected="Laporan diproses", start_url=f"{demo.url}/reports"),
    ]
    rt.driver.start()
    try:
        make_runner(rt).execute(cases, needs_auth=True)
    finally:
        rt.driver.stop()

    assert cases[0].status_ai == "Skipped"           # dicegah oleh aturan kata kunci "Simpan"
    assert demo.state.writes == []                    # tidak ada satu pun request pengubah data yang lolos
    assert len(demo.state.users) == 2
    assert any("/reports/rebuild" in r for r in rt.driver.blocked_requests)  # dicegah di level jaringan
```

- [ ] **Step 3: Jalankan test end-to-end**

Run: `.venv/Scripts/python -m pytest tests/integration/test_e2e_demo.py -v`
Expected: `3 passed` (sekitar 30–90 detik)

Jika ada yang gagal, gunakan superpowers:systematic-debugging. Buka `report.html` di folder `tmp_path` test (jalankan dengan `--basetemp=.pytest-tmp` agar mudah ditemukan) untuk melihat langkah dan screenshot yang diambil agent.

- [ ] **Step 4: Jalankan seluruh test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: semua test lulus (test bermarker `llm` dilewati)

- [ ] **Step 5: Commit**

```bash
git add tests/integration/brain.py tests/integration/test_e2e_demo.py
git commit -m "test: end-to-end explore/deep/production terhadap aplikasi demo"
```

---

### Task 24: Dokumentasi, contoh config, dan evaluasi dengan GLM asli

**Files:**
- Create: `README.md`, `examples/demo-app.yaml`, `docs/evaluation.md`

**Interfaces:**
- Consumes: CLI (Task 22), aplikasi demo (`python -m tests.demo_app`, Task 10)
- Produces: panduan pemakaian dan checklist evaluasi untuk kriteria sukses spec §1

- [ ] **Step 1: Tulis `examples/demo-app.yaml`**

```yaml
# Config untuk evaluasi terhadap aplikasi demo lokal (python -m tests.demo_app).
# Akun demo (DEMO_USER / DEMO_PASS) adalah nilai test milik proyek ini: admin@demo.local / rahasia123.
target:
  platform: web
  url: http://127.0.0.1:5055
environment: dev
accounts:
  - role: admin
    username_env: DEMO_USER
    password_env: DEMO_PASS
llm:
  provider: openai_compatible
  base_url: http://192.168.151.121/v1
  model: z-ai/glm-5.3-flash
  api_key_env: OFFICE_AI_KEY
  vision: true
limits:
  explore_max_minutes: 15
browser:
  headless: false
```

- [ ] **Step 2: Tulis `README.md`**

````markdown
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

`--env production` memblok aksi berisiko (hapus, simpan, kirim, bayar, dan sejenisnya) **dan** membatalkan semua request POST/PUT/PATCH/DELETE kecuali login. Jika endpoint login aplikasi tidak mengandung kata login/auth/signin/token/session, isi `target.login_endpoints` di config. Gunakan mode ini hanya jika benar-benar perlu.

## Jika ada masalah

- **AI kantor mati di tengah run:** status run menjadi `paused`. Lanjutkan dengan `qa-agent run --run <folder> --resume`.
- **Ctrl+C:** tekan sekali untuk berhenti dengan rapi (laporan parsial tetap ditulis), dua kali untuk keluar paksa.
- **"Tutup file itu di Excel":** tutup `report.xlsx` lalu jalankan `qa-agent report --run <folder>`.
- **Ganti model:** ubah `llm.model` di config. Untuk Claude: `provider: anthropic`, `model: claude-sonnet-5-5`, `api_key_env: ANTHROPIC_API_KEY`.

## Keterbatasan

Saat ini hanya untuk web. Belum mendukung OTP/2FA/CAPTCHA, elemen canvas, shadow DOM tertutup, iframe lintas domain, PRD selain `.md`/`.txt`, maupun template Excel kustom. Screenshot di laporan bisa berisi data aplikasi, jadi perlakukan laporan sebagai dokumen internal.

## Pengembangan

- Test: `.venv/Scripts/python -m pytest` (otomatis menjalankan aplikasi demo + Chromium headless)
- Aplikasi demo manual: `.venv/Scripts/python -m tests.demo_app` → http://127.0.0.1:5055
````

- [ ] **Step 3: Tulis `docs/evaluation.md`**

```markdown
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
```

- [ ] **Step 4: Verifikasi akhir**

Run: `.venv/Scripts/python -m pytest -v`
Expected: semua test lulus

Run: `.venv/Scripts/qa-agent --help`
Expected: 6 perintah tampil dalam Bahasa Indonesia

- [ ] **Step 5: Commit**

```bash
git add README.md examples/demo-app.yaml docs/evaluation.md
git commit -m "docs: README, config demo, dan panduan evaluasi dengan GLM"
```

- [ ] **Step 6: Evaluasi manual dengan GLM (LANGKAH OLEH PENGGUNA)**

Minta pengguna menjalankan `docs/evaluation.md` dengan API key kantor, lalu mengisi kolom Hasil. Hasil evaluasi ini menentukan apakah GLM cukup andal, atau perlu prompt tuning/model lain, sebelum lanjut ke sub-proyek Android.
