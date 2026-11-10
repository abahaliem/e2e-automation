"""Mesin API testing: kirim request berurutan, cek assertion, simpan nilai ke variabel untuk request berikutnya.

Variabel ditulis {{nama}} di URL/header/body (mis. {{base_url}}, {{token}} hasil login). Rahasia (password, token
dari header rahasia) disamarkan di hasil supaya aman masuk laporan.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import httpx

VAR = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
MASK = "••••••"


@dataclass
class Assertion:
    kind: str  # status | json | time | body | header
    op: str = "eq"  # eq | ne | contains | exists | not_exists | lt | gt | type
    expected: str = ""
    path: str = ""  # json: data.items[0].id ; header: nama header


@dataclass
class ApiCase:
    name: str
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    assertions: list[Assertion] = field(default_factory=list)
    capture: dict[str, str] = field(default_factory=dict)  # nama variabel → json path


def substitute(text: str, variables: dict) -> str:
    return VAR.sub(lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0), text or "")


def json_path(data, path: str) -> tuple[bool, object]:
    """'data.items[0].id' / '$.data.id' → (ada?, nilai)."""
    path = (path or "").strip()
    if path.startswith("$"):
        path = path[1:].lstrip(".")
    cur = data
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            i = int(part[1:-1])
            if not isinstance(cur, list) or i >= len(cur):
                return False, None
            cur = cur[i]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _type_name(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return {str: "string", list: "array", dict: "object", type(None): "null"}.get(type(value), type(value).__name__)


def _text(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _compare(op: str, actual, expected: str) -> bool:
    if op == "exists":
        return actual is not _MISSING
    if op == "not_exists":
        return actual is _MISSING
    if actual is _MISSING:
        return False
    if op == "type":
        return _type_name(actual) == expected.strip().lower()
    a = _text(actual)
    if op == "contains":
        return expected in a
    if op in ("lt", "gt"):
        try:
            return float(a) < float(expected) if op == "lt" else float(a) > float(expected)
        except ValueError:
            return False
    equal = a == expected or (a.lower() in ("true", "false") and a.lower() == expected.strip().lower())
    return equal if op == "eq" else not equal


_MISSING = object()


def describe(a: Assertion) -> str:
    target = {"status": "Status", "time": "Waktu respons (ms)", "body": "Body", "json": f"JSON {a.path}",
              "header": f"Header {a.path}"}.get(a.kind, a.kind)
    op = {"eq": "=", "ne": "≠", "contains": "mengandung", "exists": "ada", "not_exists": "tidak ada", "lt": "<",
          "gt": ">", "type": "bertipe"}.get(a.op, a.op)
    return f"{target} {op} {a.expected}".strip()


def check(a: Assertion, resp: dict) -> dict:
    """Satu assertion terhadap respons {status, json, text, ms, headers}."""
    if a.kind == "status":
        actual = resp["status"]
        exp = a.expected.strip().lower()
        if re.fullmatch(r"[1-5]xx", exp):
            passed = str(actual).startswith(exp[0])
        elif "," in exp:
            passed = str(actual) in [x.strip() for x in exp.split(",")]
        else:
            passed = _compare(a.op, actual, a.expected)
    elif a.kind == "time":
        actual = round(resp["ms"])
        passed = _compare(a.op or "lt", actual, a.expected)
    elif a.kind == "body":
        actual = resp["text"][:200]
        passed = _compare(a.op or "contains", resp["text"], a.expected)
    elif a.kind == "header":
        actual = resp["headers"].get(a.path.lower(), _MISSING)
        passed = _compare(a.op, actual, a.expected)
        actual = None if actual is _MISSING else actual
    elif a.kind == "json":
        found, value = json_path(resp["json"], a.path) if resp["json"] is not None else (False, None)
        actual = value if found else _MISSING
        passed = _compare(a.op, actual, a.expected)
        actual = None if actual is _MISSING else actual
    else:
        return {"description": describe(a), "passed": False, "actual": f"Jenis cek tidak dikenal: {a.kind}"}
    return {"description": describe(a), "passed": bool(passed), "actual": _text(actual)[:300]}


def _mask(text: str, secrets: list[str]) -> str:
    for s in sorted({s for s in secrets if s and len(s) >= 3}, key=len, reverse=True):
        text = text.replace(s, MASK)
    return text


def run_suite(cases: list[ApiCase], *, variables: dict | None = None, secret_headers: dict[str, str] | None = None,
              secrets: list[str] | None = None, timeout_s: float = 30, stop=None, on_case=None) -> dict:
    """Jalankan test case berurutan. Nilai capture masuk ke variabel untuk test case berikutnya."""
    variables = dict(variables or {})
    secret_values = list(secrets or []) + list((secret_headers or {}).values())
    results = []
    with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
        for case in cases:
            if stop is not None and stop.is_set():
                break
            url = substitute(case.url, variables)
            headers = {k: substitute(v, variables) for k, v in case.headers.items()}
            headers = {**headers, **(secret_headers or {})}
            body = substitute(case.body, variables) if case.body else ""
            if body and not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = "application/json"
            entry: dict = {"name": case.name, "request": {"method": case.method, "url": url, "body": body[:2000]},
                           "assertions": [], "error": "", "passed": False}
            t0 = time.monotonic()
            try:
                r = client.request(case.method, url, headers=headers, content=body.encode("utf-8") if body else None)
                ms = (time.monotonic() - t0) * 1000
                try:
                    data = r.json()
                except ValueError:
                    data = None
                resp = {"status": r.status_code, "json": data, "text": r.text, "ms": ms,
                        "headers": {k.lower(): v for k, v in r.headers.items()}}
                entry.update(status=r.status_code, ms=round(ms, 1), response=r.text[:2000])
                entry["assertions"] = [check(a, resp) for a in case.assertions] or [
                    check(Assertion(kind="status", op="eq", expected="2xx"), resp)]
                entry["passed"] = all(x["passed"] for x in entry["assertions"])
                for name, path in case.capture.items():
                    found, value = json_path(data, path) if data is not None else (False, None)
                    if found:
                        variables[name] = value
                        if any(k in name.lower() for k in ("token", "secret", "password")):
                            secret_values.append(_text(value))
                    else:
                        entry["error"] = f"Nilai '{path}' untuk variabel {{{{{name}}}}} tidak ada di respons"
                        entry["passed"] = False
            except httpx.HTTPError as e:
                entry.update(error=f"{type(e).__name__}: {e}", ms=round((time.monotonic() - t0) * 1000, 1))
            # samarkan rahasia di seluruh hasil test case
            results.append(json.loads(_mask(json.dumps(entry, ensure_ascii=False), secret_values)))
            if on_case:
                on_case(results[-1])
    errors = sum(1 for r in results if r["error"] and "status" not in r)
    passed = sum(1 for r in results if r["passed"])
    shown_vars = {k: (MASK if any(s in k.lower() for s in ("token", "secret", "password")) else v)
                  for k, v in variables.items() if k not in ("password",)}
    return {"cases": results, "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed - errors,
                                          "errors": errors},
            "variables": json.loads(_mask(json.dumps(shown_vars, ensure_ascii=False, default=str), secret_values)),
            "stopped": bool(stop is not None and stop.is_set())}
