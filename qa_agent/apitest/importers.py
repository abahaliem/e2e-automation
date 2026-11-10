"""Impor test case API dari Postman collection (v2.x) dan OpenAPI/Swagger (JSON/YAML)."""
from __future__ import annotations

import json
import re

import yaml

from qa_agent.apitest.engine import ApiCase, Assertion

METHODS = ("get", "post", "put", "patch", "delete")


def _load(text: str):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError(f"File tidak bisa dibaca sebagai JSON/YAML: {e}") from e


def from_postman(text: str) -> list[ApiCase]:
    data = _load(text)
    if not isinstance(data, dict) or "item" not in data:
        raise ValueError("Bukan Postman collection (tidak ada 'item')")
    cases: list[ApiCase] = []

    def walk(items, prefix=""):
        for it in items or []:
            name = f"{prefix}{it.get('name', 'Request')}"
            if "item" in it:
                walk(it["item"], f"{name} / ")
                continue
            req = it.get("request") or {}
            if isinstance(req, str):
                req = {"method": "GET", "url": req}
            url = req.get("url", "")
            if isinstance(url, dict):
                url = url.get("raw") or ""
            headers = {h["key"]: h.get("value", "") for h in req.get("header") or [] if h.get("key") and not h.get("disabled")}
            body = ""
            if (req.get("body") or {}).get("mode") == "raw":
                body = req["body"].get("raw") or ""
            cases.append(ApiCase(name=name, method=(req.get("method") or "GET").upper(), url=url, headers=headers,
                                 body=body, assertions=[Assertion(kind="status", op="eq", expected="2xx")]))

    walk(data["item"])
    if not cases:
        raise ValueError("Collection tidak berisi request")
    return cases


def _example(schema: dict, spec: dict, depth: int = 0):
    if depth > 4 or not isinstance(schema, dict):
        return "string"
    if "$ref" in schema:
        ref = schema["$ref"].split("/")
        node = spec
        for part in ref[1:]:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return _example(node, spec, depth + 1)
    if "example" in schema:
        return schema["example"]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: _example(v, spec, depth + 1) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [_example(schema.get("items") or {}, spec, depth + 1)]
    if "enum" in schema:
        return schema["enum"][0]
    return {"integer": 0, "number": 0, "boolean": False}.get(t, "string")


def _operations(spec: dict):
    if not isinstance(spec, dict) or not ("openapi" in spec or "swagger" in spec) or "paths" not in spec:
        raise ValueError("Bukan spesifikasi OpenAPI/Swagger (tidak ada 'openapi'/'swagger' dan 'paths')")
    for path, ops in (spec.get("paths") or {}).items():
        for method in METHODS:
            if isinstance(ops, dict) and method in ops:
                yield path, method.upper(), ops[method] or {}


def _body_schema(op: dict) -> dict | None:
    content = ((op.get("requestBody") or {}).get("content") or {})
    media = content.get("application/json") or next(iter(content.values()), None)
    if media:
        return media.get("schema") or {}
    for p in op.get("parameters") or []:  # Swagger 2: body parameter
        if p.get("in") == "body":
            return p.get("schema") or {}
    return None


def from_openapi(text: str) -> list[ApiCase]:
    spec = _load(text)
    cases = []
    for path, method, op in _operations(spec):
        url = "{{base_url}}" + re.sub(r"\{(\w+)\}", r"{{\1}}", path)
        schema = _body_schema(op)
        body = json.dumps(_example(schema, spec), ensure_ascii=False) if schema else ""
        ok = sorted(c for c in (op.get("responses") or {}) if str(c).startswith("2")) or ["2xx"]
        cases.append(ApiCase(name=op.get("summary") or op.get("operationId") or f"{method} {path}", method=method,
                             url=url, body=body, assertions=[Assertion(kind="status", op="eq", expected=str(ok[0]))]))
    if not cases:
        raise ValueError("Spesifikasi tidak berisi endpoint")
    return cases


def openapi_base_url(text: str) -> str:
    spec = _load(text)
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        return servers[0].get("url", "")
    if spec.get("host"):
        return f"{(spec.get('schemes') or ['https'])[0]}://{spec['host']}{spec.get('basePath', '')}"
    return ""


def openapi_summary(text: str, limit: int = 60) -> str:
    """Ringkasan endpoint untuk prompt AI: method, path, field body (* = wajib), kode respons."""
    spec = _load(text)
    lines = []
    for path, method, op in list(_operations(spec))[:limit]:
        schema = _body_schema(op) or {}
        if "$ref" in schema:
            node = spec
            for part in schema["$ref"].split("/")[1:]:
                node = node.get(part, {})
            schema = node
        required = set(schema.get("required") or [])
        fields = ", ".join(f"{k}{'*' if k in required else ''}:{(v or {}).get('type', '?')}"
                           for k, v in (schema.get("properties") or {}).items())
        params = ", ".join(f"{p.get('name')}({p.get('in')})" for p in op.get("parameters") or [] if p.get("in") != "body")
        codes = ", ".join(str(c) for c in (op.get("responses") or {}))
        lines.append(f"- {method} {path}: {op.get('summary') or op.get('operationId') or ''}"
                     f"{' | body: ' + fields if fields else ''}{' | param: ' + params if params else ''} | respons: {codes}")
    return "\n".join(lines)
