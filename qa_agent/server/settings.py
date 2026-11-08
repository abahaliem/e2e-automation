"""Pengaturan server dashboard: folder data, alamat, dan batas run paralel."""
from __future__ import annotations

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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "qa-agent.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def auth_dir(self) -> Path:
        return self.data_dir / "auth"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.runs_dir, self.auth_dir):
            d.mkdir(parents=True, exist_ok=True)
