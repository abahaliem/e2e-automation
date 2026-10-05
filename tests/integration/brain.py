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
