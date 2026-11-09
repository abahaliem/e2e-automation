"""Pengaturan server dashboard: folder data, alamat, dan batas run paralel."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_data_dir() -> Path:
    """Folder data default: %USERPROFILE%\\QA Agent."""
    return Path.home() / "QA Agent"


@dataclass
class ServerSettings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8787
    max_parallel: int = 2
    auth_required: bool = False  # mode server: wajib login (sub-proyek 4)
    secure_cookies: bool = False  # cookie sesi hanya lewat HTTPS (di belakang reverse proxy)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "qa-agent.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def auth_dir(self) -> Path:
        return self.data_dir / "auth"

    @property
    def browsers_dir(self) -> Path:
        return self.data_dir / "browsers"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.runs_dir, self.auth_dir):
            d.mkdir(parents=True, exist_ok=True)


def configure_playwright_browsers(settings: "ServerSettings") -> str | None:
    r"""Pakai browser di folder data (mis. %USERPROFILE%\QA Agent\browsers) bila ada.

    Proses yang dijalankan dari aplikasi Windows terpaket (mis. terminal di aplikasi desktop) melihat AppData
    yang divirtualisasi, sehingga browser Playwright di AppData\Local\ms-playwright tidak terlihat.
    Folder di bawah profil pengguna tidak terkena virtualisasi itu. Variabel yang diatur pengguna tetap dihormati.
    """
    current = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if current:
        return current
    d = settings.browsers_dir
    if d.is_dir() and any(d.iterdir()):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(d)
        return str(d)
    return None


def configure_adb(settings: "ServerSettings") -> str | None:
    r"""Bila ada `<data>\platform-tools\adb(.exe)`, tambahkan ke PATH supaya adb ditemukan tanpa instalasi sistem."""
    folder = settings.data_dir / "platform-tools"
    exe = folder / ("adb.exe" if os.name == "nt" else "adb")
    if not exe.is_file():
        return None
    path = os.environ.get("PATH", "")
    if str(folder) not in path.split(os.pathsep):
        os.environ["PATH"] = str(folder) + os.pathsep + path
    return str(exe)
