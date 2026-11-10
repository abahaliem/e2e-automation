"""Data uji per aplikasi ({{data:nama}}) dan persiapan HTTP sebelum run / test case.

- Penanda {{data:nama}} di test case diganti nilai tersedia berikutnya saat test case mulai; nilai lalu ditandai
  terpakai. Penanda yang sama dalam satu test case memakai nilai yang sama.
- Persiapan HTTP (mis. endpoint internal pembuat WO uji) dijalankan sebelum run atau sebelum setiap test case;
  nilai dari respons JSON bisa langsung masuk ke kumpulan data (capture: wo_id = data.id).
- Header persiapan (biasanya berisi token) disimpan di penyimpanan rahasia, tidak di database.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable

from qa_agent.models import QaTestCase
from qa_agent.server.secrets import SecretStore
from qa_agent.server.store import HookRow, Store

PLACEHOLDER = re.compile(r"\{\{data:([A-Za-z0-9_.-]{1,40})\}\}")
SET_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_FIELDS = ("title", "precondition", "test_data", "expected")
HttpFn = Callable[[str, str, dict, bytes | None, float], tuple[int, bytes]]


class HookError(Exception):
    """Persiapan HTTP gagal."""


def hook_secret_key(hook_id: int) -> str:
    return f"hook:{hook_id}:headers"


def placeholders(tc: QaTestCase) -> list[str]:
    found: list[str] = []
    for text in [*(getattr(tc, f) or "" for f in _FIELDS), *tc.steps]:
        for name in PLACEHOLDER.findall(text):
            if name not in found:
                found.append(name)
    return found


def _sub(text: str, values: dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def apply_values(tc: QaTestCase, values: dict[str, str]) -> None:
    for f in _FIELDS:
        setattr(tc, f, _sub(getattr(tc, f) or "", values))
    tc.steps = [_sub(s, values) for s in tc.steps]


def extract(data, path: str) -> str | None:
    """Ambil nilai dari JSON lewat path bertitik (data.items.0.id)."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    if cur is None or isinstance(cur, (dict, list)):
        return None
    return str(cur)


def data_hint(sets: dict[str, list[str]]) -> str:
    """Bagian prompt penyusun test case: kumpulan data uji yang tersedia untuk aplikasi ini."""
    if not sets:
        return ""
    lines = ["## Data uji tersedia",
             "Untuk data yang harus sudah ada di aplikasi (mis. nomor work order), tulis penanda {{data:nama}} di "
             "langkah/test data, jangan mengarang nilai. Sistem mengisi nilai yang belum terpakai saat test case mulai."]
    for name, values in sets.items():
        sample = ", ".join(values[:3]) if values else "(habis)"
        lines.append(f"- {{{{data:{name}}}}}: {len(values)} nilai tersedia, contoh {sample}")
    return "\n".join(lines)


def _default_http(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL dari Admin/QA
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HookError(f"tidak bisa menghubungi {url}: {getattr(e, 'reason', e)}") from e


def run_hook(store: Store, secrets: SecretStore, hook: HookRow, *, used_by: str, http: HttpFn | None = None,
             timeout: float = 30) -> dict[str, str]:
    """Jalankan satu persiapan HTTP. Nilai capture ditambahkan ke data uji dan dikembalikan."""
    http = http or _default_http
    taken: dict[str, str] = {}

    def resolve(text: str) -> str:
        # Penanda di persiapan dibaca saja (mis. ID teknisi untuk membuat WO), tidak ditandai terpakai
        for name in PLACEHOLDER.findall(text):
            if name not in taken:
                value = store.peek_test_data(hook.app_id, name)
                if value is None:
                    raise HookError(f"Persiapan '{hook.name}': data uji '{name}' belum diisi")
                taken[name] = value
        return _sub(text, taken)

    url, body = resolve(hook.url), resolve(hook.body or "")
    headers = json.loads(secrets.get(hook_secret_key(hook.id)) or "{}")
    if body and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = "application/json"
    status, raw = http(hook.method, url, headers, body.encode("utf-8") if body else None, timeout)
    if not 200 <= status < 300:
        raise HookError(f"Persiapan '{hook.name}' gagal: HTTP {status}")
    captured: dict[str, str] = {}
    if hook.capture:
        try:
            data = json.loads(raw.decode("utf-8") or "null")
        except ValueError as e:
            raise HookError(f"Persiapan '{hook.name}': respons bukan JSON") from e
        for name, path in hook.capture.items():
            value = extract(data, path)
            if value is None:
                raise HookError(f"Persiapan '{hook.name}': '{path}' tidak ada di respons")
            store.add_test_data(hook.app_id, name, [value])
            captured[name] = value
    return captured


class DataPreparer:
    """Dipanggil DeepRunner sebelum tiap test case: persiapan HTTP 'case', lalu isi penanda {{data:...}}.

    Mengembalikan pesan masalah (test case jadi Blocked) atau None bila siap.
    """

    def __init__(self, store: Store, secrets: SecretStore, *, app_id: int, run_id: int, http: HttpFn | None = None,
                 run_hooks: bool = True) -> None:
        self.store, self.secrets, self.app_id, self.run_id = store, secrets, app_id, run_id
        self.http, self.run_hooks = http, run_hooks

    def before_run(self) -> None:
        """Persiapan 'run' (sekali sebelum test case pertama). HookError → run dijeda."""
        if self.run_hooks:
            for hook in self.store.list_hooks(self.app_id, when="run", active_only=True):
                run_hook(self.store, self.secrets, hook, used_by=f"Run #{self.run_id}", http=self.http)

    def __call__(self, tc: QaTestCase) -> str | None:
        keys = placeholders(tc)
        if self.run_hooks and keys:
            try:
                for hook in self.store.list_hooks(self.app_id, when="case", active_only=True):
                    run_hook(self.store, self.secrets, hook, used_by=f"Run #{self.run_id} · {tc.id}", http=self.http)
            except HookError as e:
                return str(e)
        values: dict[str, str] = {}
        for key in keys:
            value = self.store.take_test_data(self.app_id, key, f"Run #{self.run_id} · {tc.id}")
            if value is None:
                for name, used in values.items():  # kembalikan nilai yang sudah diambil untuk test case ini
                    self.store.release_test_data(self.app_id, name, used)
                return f"Data uji '{key}' habis. Tambahkan nilai baru di Aplikasi > Data uji, lalu jalankan ulang"
            values[key] = value
        if values:
            apply_values(tc, values)
        return None
