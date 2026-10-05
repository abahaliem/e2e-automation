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


def extract_json(text: str | None, required_key: str | None = None) -> dict:
    """Ambil objek JSON dari jawaban AI.

    Blok <think> dibuang (termasuk penutup </think> tanpa pembuka), lalu semua objek JSON tingkat atas dipindai.
    Jika `required_key` diberikan, dipilih objek terakhir yang memiliki key itu.
    """
    if not text or not text.strip():
        raise ActionParseError("Jawaban AI kosong")
    cleaned = _THINK.sub("", text)
    close = cleaned.lower().rfind("</think>")
    if close != -1:
        cleaned = cleaned[close + len("</think>"):]
    fence = _FENCE.search(cleaned)
    candidate = fence.group(1) if fence else cleaned
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    last_error: json.JSONDecodeError | None = None
    i = candidate.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(candidate, i)
        except json.JSONDecodeError as e:
            last_error = e
            i = candidate.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        i = candidate.find("{", end)
    if not objects:
        if last_error is not None:
            raise ActionParseError(f"JSON tidak valid: {last_error.msg} (posisi {last_error.pos})")
        raise ActionParseError("Tidak ada objek JSON di jawaban AI")
    if required_key:
        matching = [o for o in objects if required_key in o]
        if matching:
            return matching[-1]
    return objects[-1]


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
    data = _coerce(extract_json(text, "action"))
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
