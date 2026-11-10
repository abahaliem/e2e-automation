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

    def redact(self, text: str | None) -> str | None:
        """Rahasia asli → penanda {{password}} (untuk skrip yang diputar ulang: nilai tetap bisa diisi sistem)."""
        if text is None:
            return None
        for secret in self._secrets:
            text = text.replace(secret, "{{password}}")
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

    # ---------- skrip regresi (langkah test case Pass, diputar ulang tanpa AI) ----------
    @property
    def scripts_path(self) -> Path:
        return self.root / "scripts.json"

    def write_scripts(self, scripts: dict) -> None:
        self._write_json(self.scripts_path, {k: v.model_dump(mode="json") for k, v in scripts.items()})

    def read_scripts(self) -> dict:
        from qa_agent.agent.script import TestScript

        if not self.scripts_path.exists():
            return {}
        data = json.loads(self.scripts_path.read_text(encoding="utf-8"))
        return {k: TestScript.model_validate(v) for k, v in data.items()}

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
