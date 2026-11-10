"""Pengaturan > Laporan: nama perusahaan/instansi dan template Excel kantor."""
from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from qa_agent.report.excel import _template_sheet
from qa_agent.server.api import deps
from qa_agent.server.reporting import (KEY_COMPANY, KEY_LOGO, KEY_LOGO_NAME, KEY_TEMPLATE, KEY_TEMPLATE_NAME,
                                       excel_template, logo_path, templates_dir)

router = APIRouter(prefix="/api/settings", tags=["settings"])
MAX_TEMPLATE_BYTES = 5 * 1024 * 1024


class ReportPatch(BaseModel):
    company_name: str = Field(default="", max_length=120)


def _out(request: Request) -> dict:
    store, settings = deps.store(request), deps.settings(request)
    path = excel_template(store, settings)
    template = None
    if path is not None:
        try:
            _, ws, columns = _template_sheet(path)
            headers = [c.value for c in ws[1]]
            template = {"name": store.get_setting(KEY_TEMPLATE_NAME) or path.name,
                        "columns": [{"header": h, "maps_to": m} for h, m in zip(headers, columns) if h is not None]}
        except ValueError:
            template = None
    logo = logo_path(store, settings)
    logo_out = None
    if logo is not None:
        logo_out = {"name": store.get_setting(KEY_LOGO_NAME) or logo.name,
                    "url": f"/api/settings/report/logo?v={int(logo.stat().st_mtime)}"}
    return {"company_name": store.get_setting(KEY_COMPANY) or "", "excel_template": template, "logo": logo_out}


@router.get("/report")
def get_report_settings(request: Request) -> dict:
    return _out(request)


@router.patch("/report")
def patch_report_settings(body: ReportPatch, request: Request) -> dict:
    deps.store(request).set_setting(KEY_COMPANY, body.company_name.strip() or None)
    return _out(request)


@router.post("/report/template")
async def upload_template(request: Request, filename: str = "template.xlsx"):
    def invalid(message: str) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": message, "field_errors": {"file": message}})

    if not filename.lower().endswith(".xlsx"):
        return invalid("Template harus berupa file Excel .xlsx")
    data = await request.body()
    if not data or len(data) > MAX_TEMPLATE_BYTES:
        return invalid("File template kosong atau lebih dari 5 MB")
    folder = templates_dir(deps.settings(request))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"excel-{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
    target.write_bytes(data)
    try:
        _template_sheet(target)
    except ValueError as e:
        target.unlink(missing_ok=True)
        return invalid(str(e))
    store = deps.store(request)
    old = excel_template(store, deps.settings(request))
    store.set_setting(KEY_TEMPLATE, target.name)
    store.set_setting(KEY_TEMPLATE_NAME, filename)
    if old is not None and old != target:
        old.unlink(missing_ok=True)
    return _out(request)


MAX_LOGO_BYTES = 2 * 1024 * 1024
LOGO_BOX = (800, 300)  # cukup tajam untuk kepala dokumen A4


@router.post("/report/logo")
async def upload_logo(request: Request, filename: str = "logo.png"):
    """Logo perusahaan untuk kepala laporan PDF. Disimpan ulang sebagai PNG (format & ukuran aman)."""
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    def invalid(message: str) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": message, "field_errors": {"logo": message}})

    if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return invalid("Logo harus berupa gambar PNG, JPG, atau WEBP")
    data = await request.body()
    if not data or len(data) > MAX_LOGO_BYTES:
        return invalid("File logo kosong atau lebih dari 2 MB")
    try:
        with Image.open(BytesIO(data)) as img:
            img.load()
            if img.format not in ("PNG", "JPEG", "WEBP"):
                return invalid("Logo harus berupa gambar PNG, JPG, atau WEBP")
            logo = img.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return invalid("File bukan gambar yang bisa dibaca")
    logo.thumbnail(LOGO_BOX)
    folder = templates_dir(deps.settings(request))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"logo-{time.strftime('%Y%m%d-%H%M%S')}.png"
    logo.save(target, "PNG")
    store = deps.store(request)
    old = logo_path(store, deps.settings(request))
    store.set_setting(KEY_LOGO, target.name)
    store.set_setting(KEY_LOGO_NAME, filename)
    if old is not None and old != target:
        old.unlink(missing_ok=True)
    return _out(request)


@router.get("/report/logo")
def get_logo(request: Request):
    from fastapi.responses import FileResponse

    path = logo_path(deps.store(request), deps.settings(request))
    if path is None:
        raise deps.not_found("Logo")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.delete("/report/logo", status_code=204)
def delete_logo(request: Request) -> Response:
    store = deps.store(request)
    path = logo_path(store, deps.settings(request))
    store.set_setting(KEY_LOGO, None)
    store.set_setting(KEY_LOGO_NAME, None)
    if path is not None:
        path.unlink(missing_ok=True)
    return Response(status_code=204)


@router.delete("/report/template", status_code=204)
def delete_template(request: Request) -> Response:
    store = deps.store(request)
    path = excel_template(store, deps.settings(request))
    store.set_setting(KEY_TEMPLATE, None)
    store.set_setting(KEY_TEMPLATE_NAME, None)
    if path is not None:
        path.unlink(missing_ok=True)
    return Response(status_code=204)
