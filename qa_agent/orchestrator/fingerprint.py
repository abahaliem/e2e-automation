from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from qa_agent.models import Element

_ID_SEGMENT = re.compile(
    r"^(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,})$",
    re.IGNORECASE,
)


def _normalize_path(path: str) -> str:
    segments = [":id" if _ID_SEGMENT.match(s) else s for s in path.split("/")]
    return "/".join(segments).rstrip("/") or "/"


def normalize_location(location: str) -> str:
    """URL → host + path dengan segmen ID diganti ':id'. Selain URL dikembalikan apa adanya."""
    parts = urlsplit(location)
    if parts.scheme == "android":
        return location  # kunci layar di fragment adalah identitas layar (aplikasi satu-activity)
    if not parts.scheme or not parts.netloc:
        return location
    out = f"{parts.netloc.lower()}{_normalize_path(parts.path)}"
    if parts.fragment.startswith("/"):
        out += "#" + _normalize_path(parts.fragment.split("?")[0])
    return out


def fingerprint(location: str, elements: list[Element]) -> str:
    names = sorted({f"{e.role}:{' '.join(e.name.lower().split())}" for e in elements})
    digest = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:8]
    return f"{normalize_location(location)}|{digest}"
