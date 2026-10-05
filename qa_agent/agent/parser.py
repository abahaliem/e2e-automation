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


def extract_json(text: str | None) -> dict:
    if not text or not text.strip():
        raise ActionParseError("Jawaban AI kosong")
    cleaned = _THINK.sub("", text)
    fence = _FENCE.search(cleaned)
    candidate = fence.group(1) if fence else cleaned
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ActionParseError("Tidak ada objek JSON di jawaban AI")
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as e:
        raise ActionParseError(f"JSON tidak valid: {e.msg} (posisi {e.pos})") from e
    if not isinstance(data, dict):
        raise ActionParseError("JSON harus berupa objek {...}")
    return data


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
    data = _coerce(extract_json(text))
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
