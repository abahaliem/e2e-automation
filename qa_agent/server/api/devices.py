"""Perangkat Android (adb): daftar HP, aplikasi terpasang, upload & pasang APK."""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

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


@router.get("/devices/{serial}/packages")
def device_packages(serial: str, request: Request):
    try:
        return {"packages": _adb(request, serial).packages(third_party=True)}
    except AdbNotFound:
        return _missing()
    except AdbError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/devices/{serial}/install")
async def install_apk(serial: str, request: Request, filename: str = "aplikasi.apk"):
    if not filename.lower().endswith(".apk"):
        return JSONResponse(status_code=422, content={"detail": "File harus berformat .apk",
                                                      "field_errors": {"file": "File harus berformat .apk"}})
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
                return JSONResponse(status_code=422, content={"detail": "APK lebih dari 300 MB", "field_errors": {}})
            f.write(chunk)
    if size == 0:
        target.unlink(missing_ok=True)
        return JSONResponse(status_code=422, content={"detail": "File APK kosong", "field_errors": {}})
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
