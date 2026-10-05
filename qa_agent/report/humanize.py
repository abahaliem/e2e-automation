from __future__ import annotations

from qa_agent.models import Signal

_ROLE_LABEL = {
    "button": "tombol", "link": "link", "input": "field", "textarea": "field", "select": "dropdown",
    "combobox": "dropdown", "checkbox": "checkbox", "radio": "pilihan", "tab": "tab", "menuitem": "menu",
}


def humanize(action: str, element: dict | None, value: str | None) -> str:
    """Kalimat langkah untuk manusia, dari template (bukan AI) agar selalu akurat."""
    element = element or {}
    name = element.get("name") or "tanpa nama"
    label = _ROLE_LABEL.get(element.get("role", ""), "elemen")
    if action == "click":
        return f"Klik {label} '{name}'"
    if action == "type":
        return f"Isi field '{name}' dengan '{value}'" if value else f"Kosongkan field '{name}'"
    if action == "select":
        return f"Pilih '{value}' pada {label} '{name}'"
    if action == "scroll":
        return "Gulir halaman ke atas" if value == "up" else "Gulir halaman ke bawah"
    if action == "back":
        return "Kembali ke halaman sebelumnya"
    if action == "navigate":
        return f"Buka halaman {value}"
    if action == "wait":
        return f"Tunggu {value or 2} detik"
    if action == "done":
        return "Verifikasi hasil akhir" + (f" ({value})" if value else "")
    if action == "blocked":
        return f"Tidak bisa dilanjutkan: {value}" if value else "Tidak bisa dilanjutkan"
    if action == "invalid":
        return "Jawaban AI tidak valid"
    return action


def signal_text(signal: Signal) -> str:
    if signal.kind == "http_error":
        return " ".join(p for p in (f"HTTP {signal.status}", signal.method, signal.url) if p)
    if signal.kind == "blocked_request":
        return f"Request diblok: {signal.method} {signal.url}"
    labels = {"console_error": "Console error", "page_error": "Error JavaScript", "ui_error": "Pesan error di layar"}
    return f"{labels.get(signal.kind, signal.kind)}: {signal.message}"
