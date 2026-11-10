"""Pengaturan > Laporan: nama perusahaan/instansi dan template Excel kantor."""
from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from qa_agent.models import STATUSES
from qa_agent.report.excel import read_template_info, status_from_vocab, template_sheets
from qa_agent.server.api import deps
from qa_agent.server.reporting import (AUTO_FIELDS, KEY_COMPANY, KEY_LOGO, KEY_LOGO_NAME, KEY_TEMPLATE,
                                       KEY_TEMPLATE_FIELDS, KEY_TEMPLATE_NAME, KEY_TEMPLATE_SHEET, excel_template,
                                       logo_path, template_fields, templates_dir)

router = APIRouter(prefix="/api/settings", tags=["settings"])
MAX_TEMPLATE_BYTES = 5 * 1024 * 1024


class ReportPatch(BaseModel):
    company_name: str | None = Field(default=None, max_length=120)
    # isian kepala template kantor per label, mis. {"Developer": "Deni", "Segment": "Biznet Home"}
    template_fields: dict[str, str] | None = None
    template_sheet: str | None = Field(default=None, max_length=100)  # "" = pilih otomatis


def _out(request: Request) -> dict:
    store, settings = deps.store(request), deps.settings(request)
    path = excel_template(store, settings)
    template = None
    if path is not None:
        try:
            info = read_template_info(path, sheet=store.get_setting(KEY_TEMPLATE_SHEET))
            values = template_fields(store)
            template = {
                "name": store.get_setting(KEY_TEMPLATE_NAME) or path.name,
                "sheet": info.sheet, "sheets": template_sheets(path),
                "sheet_chosen": bool(store.get_setting(KEY_TEMPLATE_SHEET)),
                "header_row": info.header_row, "capacity": info.capacity,
                "columns": [{"header": h, "maps_to": m} for h, m in zip(info.headers, info.columns) if h is not None],
                "status_options": info.status_options,
                "status_map": {s: status_from_vocab(s, info.status_options) for s in STATUSES} if info.status_options else {},
                "fields": [{"label": f.label, "key": f.key, "auto": f.key in AUTO_FIELDS,
                            "value": values.get(f.label, "")} for f in info.fields],
            }
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
    import json

    store = deps.store(request)
    if body.company_name is not None:
        store.set_setting(KEY_COMPANY, body.company_name.strip() or None)
    if body.template_fields is not None:
        clean = {k.strip()[:80]: v.strip()[:300] for k, v in body.template_fields.items() if k.strip() and v.strip()}
        store.set_setting(KEY_TEMPLATE_FIELDS, json.dumps(clean) if clean else None)
    if body.template_sheet is not None:
        store.set_setting(KEY_TEMPLATE_SHEET, body.template_sheet.strip() or None)
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
        read_template_info(target)
    except ValueError as e:
        target.unlink(missing_ok=True)
        return invalid(str(e))
    store = deps.store(request)
    old = excel_template(store, deps.settings(request))
    store.set_setting(KEY_TEMPLATE, target.name)
    store.set_setting(KEY_TEMPLATE_NAME, filename)
    store.set_setting(KEY_TEMPLATE_SHEET, None)  # template baru: sheet dipilih otomatis lagi
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
