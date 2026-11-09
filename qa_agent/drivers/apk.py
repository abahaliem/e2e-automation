"""Membaca paket & versi dari file APK (AndroidManifest.xml biner) tanpa aapt."""
from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

RES_STRING_POOL = 0x0001
RES_XML_START_ELEMENT = 0x0102
UTF8_FLAG = 0x100
NO_INDEX = 0xFFFFFFFF
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11


class ApkError(Exception):
    """File bukan APK yang bisa dibaca."""


@dataclass
class ApkInfo:
    package: str
    version_name: str | None
    version_code: int | None
    size_bytes: int


def _read_len_utf8(data: bytes, pos: int) -> tuple[int, int]:
    n = data[pos]
    if n & 0x80:
        return ((n & 0x7F) << 8) | data[pos + 1], pos + 2
    return n, pos + 1


def _string_pool(data: bytes, start: int) -> list[str]:
    _, header_size, _size, count, _styles, flags, strings_start, _ = struct.unpack_from("<HHIIIIII", data, start)
    offsets = struct.unpack_from(f"<{count}I", data, start + header_size)
    base = start + strings_start
    utf8 = bool(flags & UTF8_FLAG)
    out: list[str] = []
    for off in offsets:
        pos = base + off
        if utf8:
            _, pos = _read_len_utf8(data, pos)  # panjang utf-16 (diabaikan)
            n, pos = _read_len_utf8(data, pos)
            out.append(data[pos:pos + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, pos)[0]
                pos += 2
            out.append(data[pos:pos + 2 * n].decode("utf-16-le", "replace"))
    return out


def parse_manifest(data: bytes) -> dict[str, object]:
    """Atribut elemen <manifest> pertama: package, versionName, versionCode."""
    if len(data) < 8 or struct.unpack_from("<H", data, 0)[0] != 0x0003:
        raise ApkError("AndroidManifest.xml tidak berformat biner Android")
    pos = struct.unpack_from("<H", data, 2)[0]
    strings: list[str] = []
    while pos + 8 <= len(data):
        ctype, header_size, size = struct.unpack_from("<HHI", data, pos)
        if size <= 0:
            break
        if ctype == RES_STRING_POOL:
            strings = _string_pool(data, pos)
        elif ctype == RES_XML_START_ELEMENT:
            ext = pos + header_size
            _ns, name_idx, attr_start, attr_size, attr_count = struct.unpack_from("<IIHHH", data, ext)
            if strings and strings[name_idx] == "manifest":
                attrs: dict[str, object] = {}
                for i in range(attr_count):
                    a = ext + attr_start + i * attr_size
                    _ans, aname, raw, _sz, _r0, dtype, value = struct.unpack_from("<IIIHBBI", data, a)
                    key = strings[aname] if aname < len(strings) else ""
                    if raw != NO_INDEX and raw < len(strings):
                        attrs[key] = strings[raw]
                    elif dtype == TYPE_STRING and value < len(strings):
                        attrs[key] = strings[value]
                    elif dtype in (TYPE_INT_DEC, TYPE_INT_HEX):
                        attrs[key] = value
                return attrs
        pos += size
    raise ApkError("Elemen <manifest> tidak ditemukan")


def read_apk_info(path: Path | str) -> ApkInfo:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            try:
                manifest = z.read("AndroidManifest.xml")
            except KeyError as e:
                raise ApkError("AndroidManifest.xml tidak ada di dalam file") from e
    except zipfile.BadZipFile as e:
        raise ApkError("Ini bukan file APK yang valid") from e
    try:
        attrs = parse_manifest(manifest)
    except (struct.error, IndexError) as e:
        raise ApkError(f"AndroidManifest.xml tidak bisa dibaca: {e}") from e
    package = attrs.get("package")
    if not isinstance(package, str) or not package:
        raise ApkError("Nama paket tidak ditemukan di AndroidManifest.xml")
    version_name = attrs.get("versionName")
    version_code = attrs.get("versionCode")
    return ApkInfo(package=package,
                   version_name=version_name if isinstance(version_name, str) and version_name else None,
                   version_code=version_code if isinstance(version_code, int) else None,
                   size_bytes=path.stat().st_size)
