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
