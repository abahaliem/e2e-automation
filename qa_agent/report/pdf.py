"""Cetak report.html menjadi PDF lewat Chromium (Playwright)."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


def html_to_pdf(html_path: Path, pdf_path: Path) -> Path:
    """Harus dipanggil dari thread tanpa event loop asyncio (Playwright sync API)."""
    html_path, pdf_path = Path(html_path), Path(pdf_path)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            page.emulate_media(media="print")
            page.pdf(path=str(pdf_path), format="A4", print_background=True,
                     margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        finally:
            browser.close()
    return pdf_path
