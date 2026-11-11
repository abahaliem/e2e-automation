"""XML `uiautomator dump` → daftar `Element` (setara EXTRACT_JS untuk web)."""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET

from qa_agent.models import Element

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_ROLE_BY_CLASS = (
    (("EditText", "AutoCompleteTextView", "TextInputEditText"), "input"),
    (("CheckBox",), "checkbox"),
    (("RadioButton",), "radio"),
    (("Switch", "ToggleButton"), "switch"),
    (("Spinner",), "select"),
    (("SeekBar", "Slider"), "slider"),
    (("TabView", "Tab"), "tab"),
    (("Button", "FloatingActionButton", "Chip"), "button"),
)
INTERACTIVE = {"input", "checkbox", "radio", "switch", "select", "slider", "tab", "button"}


def _bounds(raw: str) -> tuple[float, float, float, float] | None:
    m = _BOUNDS.match(raw or "")
    if not m:
        return None
    x1, y1, x2, y2 = (int(v) for v in m.groups())
    return float(x1), float(y1), float(x2 - x1), float(y2 - y1)


def _flag(node: ET.Element, name: str) -> bool:
    return node.get(name) == "true"


def _role(node: ET.Element) -> str:
    cls = (node.get("class") or "").rsplit(".", 1)[-1]
    for keys, role in _ROLE_BY_CLASS:
        if any(k in cls for k in keys):
            return role
    if _flag(node, "checkable"):
        return "checkbox"
    if _flag(node, "clickable") or _flag(node, "long-clickable"):
        return "button"
    return "text"


def _rid_label(rid: str) -> str:
    tail = rid.split("/", 1)[-1] if rid else ""
    return " ".join(tail.replace("_", " ").split()).capitalize() if tail else ""


def _descendant_texts(node: ET.Element) -> list[ET.Element]:
    return [n for n in node.iter("node") if n is not node and ((n.get("text") or "").strip() or (n.get("content-desc") or "").strip())]


def parse_ui(xml: str, max_elements: int = 80, screen: tuple[int, int] | None = None) -> list[Element]:
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    consumed: set[int] = set()
    found: list[tuple[int, bool, Element]] = []  # (urutan, interaktif, elemen)
    order = 0
    unnamed_inputs = 0
    for node in root.iter("node"):
        order += 1
        if id(node) in consumed:
            continue
        bbox = _bounds(node.get("bounds", ""))
        if bbox is None or bbox[2] <= 0 or bbox[3] <= 0:
            continue
        if screen and (bbox[0] >= screen[0] or bbox[1] >= screen[1] or bbox[0] + bbox[2] <= 0 or bbox[1] + bbox[3] <= 0):
            continue
        role = _role(node)
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        rid = node.get("resource-id") or ""
        password = _flag(node, "password")
        if role == "input":
            name = (node.get("hint") or "").strip() or desc or _rid_label(rid) or ("" if password else text)
            if not name:
                # Flutter: label hanya tergambar di layar. Beri nama yang bisa dibedakan, AI melihat labelnya di gambar.
                if password:
                    name = "Password"
                else:
                    unnamed_inputs += 1
                    name = f"Isian {unnamed_inputs}"
            value = "******" if password and text else (text or None)
        else:
            name = text or desc
            value = None
            if not name and role in INTERACTIVE:
                children = _descendant_texts(node)
                name = " ".join(((c.get("text") or c.get("content-desc") or "").strip()) for c in children[:2]).strip()
                consumed.update(id(c) for c in children)
            if not name and role in INTERACTIVE:
                name = _rid_label(rid)
        if not name and role not in INTERACTIVE:
            continue
        if role in ("checkbox", "switch", "radio"):
            value = "on" if _flag(node, "checked") else "off"
        element = Element(
            index=0, role=role, name=" ".join(name.split())[:120], value=value,
            input_type="password" if password else None, bbox=bbox,
            selector=rid or f"{node.get('class')}:{name}:{node.get('bounds')}",
            context="nonaktif" if node.get("enabled") == "false" else "",
        )
        found.append((order, role in INTERACTIVE, element))

    if len(found) > max_elements:
        interactive = [f for f in found if f[1]][:max_elements]
        rest = [f for f in found if not f[1]][: max_elements - len(interactive)]
        found = sorted(interactive + rest, key=lambda f: f[0])
    elements = [f[2] for f in found]
    for i, el in enumerate(elements, 1):
        el.index = i
    return elements


def screen_parts(elements: list[Element]) -> set[str]:
    """Penanda elemen interaktif sebuah layar (dasar screen_key dan pembanding kemiripan layar)."""
    return {f"{e.role}:{e.selector if ':id/' in e.selector else e.name.lower()}" for e in elements
            if e.role in INTERACTIVE}


def screen_key(elements: list[Element]) -> str:
    """Identitas layar dari struktur elemen interaktif (teks dinamis seperti jam diabaikan)."""
    return hashlib.sha1("\n".join(sorted(screen_parts(elements))).encode("utf-8")).hexdigest()[:8]


def similarity(a: set[str], b: set[str]) -> float:
    """Kemiripan dua layar (Jaccard). Layar daftar yang isinya berubah (nomor order, jam) tetap mirip."""
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)
