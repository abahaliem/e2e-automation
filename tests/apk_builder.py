"""Membuat APK tiruan (zip + AndroidManifest.xml biner) untuk test pembaca APK."""
from __future__ import annotations

import io
import struct
import zipfile

ANDROID_NS = "http://schemas.android.com/apk/res/android"


def _string_pool(strings: list[str]) -> bytes:
    data = b""
    offsets = []
    for s in strings:
        offsets.append(len(data))
        enc = s.encode("utf-16-le")
        data += struct.pack("<H", len(s)) + enc + b"\x00\x00"
    while len(data) % 4:
        data += b"\x00"
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    size = strings_start + len(data)
    head = struct.pack("<HHIIIIII", 0x0001, header_size, size, len(strings), 0, 0, strings_start, 0)
    return head + b"".join(struct.pack("<I", o) for o in offsets) + data


def _attr(ns: int, name: int, raw: int, dtype: int, data: int) -> bytes:
    return struct.pack("<IIIHBBI", ns, name, raw, 8, 0, dtype, data)


def manifest_xml(package: str, version_name: str | None, version_code: int = 1) -> bytes:
    strings = ["manifest", "package", "versionName", "versionCode", ANDROID_NS, package, version_name or ""]
    pool = _string_pool(strings)
    attrs = [
        _attr(0xFFFFFFFF, 1, 5, 0x03, 5),  # package="..."
        _attr(4, 3, 0xFFFFFFFF, 0x10, version_code),  # android:versionCode=int
    ]
    if version_name is not None:
        attrs.append(_attr(4, 2, 6, 0x03, 6))  # android:versionName="..."
    body = struct.pack("<IIIIHHHHHH", 1, 0xFFFFFFFF, 0xFFFFFFFF, 0, 20, 20, len(attrs), 0, 0, 0) + b"".join(attrs)
    start = struct.pack("<HHI", 0x0102, 16, 16 + len(body)) + body
    end_body = struct.pack("<IIII", 1, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    end = struct.pack("<HHI", 0x0103, 16, 16 + len(end_body)) + end_body
    content = pool + start + end
    return struct.pack("<HHI", 0x0003, 8, 8 + len(content)) + content


def make_apk(package: str = "id.kantor.hrmobile", version_name: str | None = "3.9.0") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml", manifest_xml(package, version_name))
        z.writestr("classes.dex", b"dex\n035\x00" + b"\x00" * 64)
    return buf.getvalue()
