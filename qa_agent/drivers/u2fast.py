"""Jalur cepat Android lewat uiautomator2: mesin UiAutomator tetap hidup di HP (file u2.jar di /data/local/tmp,
tanpa memasang aplikasi), jadi baca elemen layar ~0,2 detik dan screenshot ~0,3 detik, dibanding `uiautomator dump`
~3 detik yang menyalakan ulang UiAutomator tiap kali.

Hasil bacaan disamakan dengan `uiautomator dump`: jendela sistem (status bar, tombol navigasi, keyboard) dibuang.
"""
from __future__ import annotations

import os
import re
import threading
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Any

# Jendela yang tidak muncul di `uiautomator dump` biasa dan hanya membingungkan AI
_SYSTEM_WINDOW = re.compile(r"^com\.android\.systemui$|inputmethod|keyboard|swiftkey|\.ime$|gboard", re.IGNORECASE)


def strip_system_windows(xml: str) -> str:
    """Buang jendela status bar / navigasi / keyboard dari hasil dump uiautomator2."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return xml
    for child in list(root):
        if _SYSTEM_WINDOW.search(child.get("package", "")):
            root.remove(child)
    return ET.tostring(root, encoding="unicode")


def enabled() -> bool:
    return os.environ.get("QA_AGENT_ANDROID_FAST", "1").strip().lower() not in ("0", "false", "no", "off")


class FastDevice:
    """Sambungan uiautomator2 yang dibuat sekali lalu dipakai ulang (thread-safe)."""

    def __init__(self, serial: str | None, adb_path: str | None = None) -> None:
        self.serial = serial
        self.adb_path = adb_path
        self._dev: Any = None
        self._lock = threading.Lock()
        self.failures = 0

    def _device(self) -> Any:
        if self._dev is None:
            if self.adb_path and os.path.isfile(self.adb_path):
                os.environ.setdefault("ADBUTILS_ADB_PATH", self.adb_path)
            import uiautomator2 as u2

            self._dev = u2.connect(self.serial) if self.serial else u2.connect()
        return self._dev

    def dump(self) -> str:
        with self._lock:
            xml = self._device().dump_hierarchy()
        return strip_system_windows(xml)

    def screenshot_png(self) -> bytes:
        with self._lock:
            img = self._device().screenshot()
        buf = BytesIO()
        img.convert("RGB").save(buf, "PNG", compress_level=1)
        return buf.getvalue()

    def stop(self) -> None:
        """Matikan UiAutomator milik uiautomator2 supaya `uiautomator dump` biasa bisa dipakai lagi."""
        with self._lock:
            if self._dev is not None:
                try:
                    self._dev.stop_uiautomator()
                except Exception:  # noqa: BLE001
                    pass
            self._dev = None
