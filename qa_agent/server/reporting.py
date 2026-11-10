"""Pengaturan laporan (Pengaturan > Laporan) dan pembangunan laporan yang memakainya."""
from __future__ import annotations

from pathlib import Path

from qa_agent.evidence import RunStore
from qa_agent.report.build import build_reports
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import Store

KEY_COMPANY = "report.company"
KEY_TEMPLATE = "report.excel_template"  # nama file di <data>/templates
KEY_TEMPLATE_NAME = "report.excel_template_name"  # nama asli file


def templates_dir(settings: ServerSettings) -> Path:
    return settings.data_dir / "templates"


def excel_template(store: Store, settings: ServerSettings) -> Path | None:
    name = store.get_setting(KEY_TEMPLATE)
    if not name:
        return None
    path = templates_dir(settings) / name
    return path if path.is_file() else None


def company_name(store: Store) -> str:
    return store.get_setting(KEY_COMPANY) or ""


KEY_LOGO = "report.logo"  # nama file PNG di <data>/templates
KEY_LOGO_NAME = "report.logo_name"  # nama asli file


def logo_path(store: Store, settings: ServerSettings) -> Path | None:
    name = store.get_setting(KEY_LOGO)
    if not name:
        return None
    path = templates_dir(settings) / name
    return path if path.is_file() else None


def logo_data_uri(store: Store, settings: ServerSettings) -> str | None:
    """Logo perusahaan untuk kepala dokumen PDF (disematkan supaya PDF berdiri sendiri)."""
    import base64

    path = logo_path(store, settings)
    if path is None:
        return None
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


KEY_TEMPLATE_FIELDS = "report.template_fields"  # JSON {label isian kepala template: nilai}
KEY_TEMPLATE_SHEET = "report.template_sheet"  # sheet template yang dipakai (kosong = dipilih otomatis)
AUTO_FIELDS = {"project", "date", "platform", "environment"}  # diisi otomatis dari run


def template_fields(store: Store) -> dict[str, str]:
    import json

    try:
        return json.loads(store.get_setting(KEY_TEMPLATE_FIELDS) or "{}")
    except ValueError:
        return {}


def report_context(rs: RunStore, store: Store) -> dict[str, str]:
    """Nilai otomatis template kantor: nama aplikasi (Project) dan peran akun test (User Role)."""
    row = store.run_by_folder(str(rs.root))
    if row is None:
        return {}
    context: dict[str, str] = {}
    app = store.get_app(row.app_id)
    if app is not None:
        context["Project"] = app.name
    account = store.get_account(row.account_id) if row.account_id else None
    if account is not None:
        context["Peran"] = account.role
    return context


def build_run_reports(rs: RunStore, store: Store, settings: ServerSettings, *, import_excel: bool = True):
    """build_reports dengan template Excel kantor (tata letak bebas) bila sudah diatur."""
    return build_reports(rs, import_excel=import_excel, template=excel_template(store, settings),
                         fields=template_fields(store), context=report_context(rs, store),
                         sheet=store.get_setting(KEY_TEMPLATE_SHEET))
