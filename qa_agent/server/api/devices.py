"""Perangkat Android (adb): daftar HP, aplikasi terpasang, upload & pasang APK."""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from qa_agent.drivers.adb import AdbError, AdbNotFound
from qa_agent.server.api import deps

router = APIRouter(prefix="/api", tags=["devices"])
MAX_APK_BYTES = 300 * 1024 * 1024
ADB_MISSING = ("adb (Android platform-tools) belum terpasang di laptop ini. Unduh platform-tools dari "
               "developer.android.com, lalu ekstrak ke folder platform-tools di folder data QA Agent "
               "atau tambahkan ke PATH, kemudian jalankan ulang qa-agent serve.")


def _adb(request: Request, serial: str | None = None):
    return request.app.state.adb_factory(serial)


def _missing() -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": ADB_MISSING, "adb_missing": True})


@router.get("/devices")
def list_devices(request: Request):
    try:
        devices = _adb(request).devices()
    except AdbNotFound:
        return _missing()
    except AdbError as e:
        raise HTTPException(status_code=409, detail=f"adb bermasalah: {e}")
    out = []
    for d in devices:
        version = None
        if d.state == "device":
            try:
                version = _adb(request, d.serial).android_version() or None
            except AdbError:
                version = None
        out.append({"serial": d.serial, "state": d.state, "model": d.model, "emulator": d.emulator,
                    "android_version": version})
    return {"devices": out}


_HOST = r"[A-Za-z0-9.-]{1,253}|\[[0-9A-Fa-f:]+\]"
_ADDRESS = re.compile(rf"^(?:{_HOST})(?::\d{{1,5}})?$")


class ConnectIn(BaseModel):
    address: str = Field(max_length=270)
    pair_address: str | None = Field(default=None, max_length=270)
    pair_code: str | None = Field(default=None, max_length=12)


@router.post("/devices/connect")
def connect_device(body: ConnectIn, request: Request):
    """Sambungkan HP lewat jaringan (Wireless debugging / HP di server): opsional `adb pair`, lalu `adb connect`."""
    address = body.address.strip()
    pair_address = (body.pair_address or "").strip()
    code = (body.pair_code or "").strip()
    for field, value in (("address", address), ("pair_address", pair_address)):
        if value and not _ADDRESS.match(value):
            return JSONResponse(status_code=422, content={"detail": "Alamat harus berbentuk IP:port, mis. 192.168.1.20:5555",
                                                          "field_errors": {field: "Format IP:port tidak valid"}})
    if not address:
        return JSONResponse(status_code=422, content={"detail": "Isi alamat IP:port HP",
                                                      "field_errors": {"address": "Wajib diisi"}})
    if code and not code.isdigit():
        return JSONResponse(status_code=422, content={"detail": "Kode pairing berupa angka",
                                                      "field_errors": {"pair_code": "Kode pairing berupa angka"}})
    if ":" not in address.rsplit("]", 1)[-1]:
        address += ":5555"
    adb = _adb(request)
    try:
        if pair_address and code:
            adb.pair(pair_address, code)
        message = adb.connect(address)
    except AdbNotFound:
        return _missing()
    except AdbError as e:
        raise HTTPException(status_code=409, detail=f"Gagal tersambung: {e}")
    return {"address": address, "message": message}


@router.get("/devices/{serial}/packages")
def device_packages(serial: str, request: Request):
    adb = _adb(request, serial)
    try:
        try:
            versions = adb.package_versions()
        except AdbError as e:
            if "unauthorized" in str(e) or "not found" in str(e) or "offline" in str(e):
                raise
            versions = {p: None for p in adb.packages(third_party=True)}
    except AdbNotFound:
        return _missing()
    except AdbError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"packages": list(versions), "apps": [{"package": p, "version": v} for p, v in versions.items()]}


@router.get("/devices/{serial}/screen")
def device_screen(serial: str, request: Request):
    """Pratinjau layar HP (JPEG kecil) untuk panel Layar HP di Run baru."""
    from qa_agent.imaging import to_jpeg

    try:
        jpeg = to_jpeg(_adb(request, serial).screencap(), max_width=480, quality=60)
    except AdbNotFound:
        return _missing()
    except AdbError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return Response(content=jpeg, media_type="image/jpeg", headers={"cache-control": "no-store"})


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": message, "field_errors": {"file": message}})


async def _save_upload(request: Request, filename: str):
    """Simpan unggahan APK ke <data>/apks. Mengembalikan Path atau JSONResponse error."""
    if not filename.lower().endswith(".apk"):
        return _invalid("File harus berformat .apk")
    folder = deps.settings(request).data_dir / "apks"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "aplikasi.apk"
    target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}"
    size = 0
    with target.open("wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_APK_BYTES:
                f.close()
                target.unlink(missing_ok=True)
                return _invalid("APK lebih dari 300 MB")
            f.write(chunk)
    if size == 0:
        target.unlink(missing_ok=True)
        return _invalid("File APK kosong")
    return target


@router.post("/devices/{serial}/apk")
async def upload_apk(serial: str, request: Request, filename: str = "aplikasi.apk"):
    """Mockup 02b: unggah APK, baca paket & versinya. Dipasang saat run dimulai."""
    from qa_agent.drivers.apk import ApkError, read_apk_info

    target = await _save_upload(request, filename)
    if isinstance(target, JSONResponse):
        return target
    try:
        info = read_apk_info(target)
    except ApkError as e:
        target.unlink(missing_ok=True)
        return _invalid(f"File APK tidak bisa dibaca: {e}")
    installed = None
    try:
        installed = _adb(request, serial).package_versions().get(info.package)
    except AdbError:
        installed = None
    return {"file": target.name, "package": info.package, "version": info.version_name,
            "version_code": info.version_code, "size_bytes": info.size_bytes, "installed_version": installed}


@router.post("/devices/{serial}/install")
async def install_apk(serial: str, request: Request, filename: str = "aplikasi.apk"):
    target = await _save_upload(request, filename)
    if isinstance(target, JSONResponse):
        return target
    adb = _adb(request, serial)
    try:
        before = set(adb.packages(third_party=True))
        adb.install(str(target))
        after = adb.packages(third_party=True)
    except AdbNotFound:
        return _missing()
    except AdbError as e:
        raise HTTPException(status_code=409, detail=str(e))
    new = sorted(set(after) - before)
    package = new[0] if len(new) == 1 else None
    message = "" if package else "APK terpasang. Pilih paket aplikasinya dari daftar."
    return {"package": package, "packages": after, "message": message, "file": target.name}
