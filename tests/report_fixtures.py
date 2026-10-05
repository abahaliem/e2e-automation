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
