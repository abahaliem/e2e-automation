"""Cetak HTML laporan menjadi PDF lewat Chromium (Playwright)."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

FOOTER = ('<div style="width:100%;font-size:7.5pt;color:#858a96;padding:0 14mm;display:flex;justify-content:flex-end;'
          'font-family:Segoe UI,Arial,sans-serif">Halaman&nbsp;<span class="pageNumber"></span>&nbsp;dari&nbsp;'
          '<span class="totalPages"></span></div>')


def html_to_pdf(html_path: Path, pdf_path: Path, *, page_numbers: bool = False) -> Path:
    """Harus dipanggil dari thread tanpa event loop asyncio (Playwright sync API).

    `page_numbers`: kaki halaman "Halaman X dari Y" (mockup 08); margin diambil dari @page di HTML.
    """
    html_path, pdf_path = Path(html_path), Path(pdf_path)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            page.emulate_media(media="print")
            if page_numbers:
                page.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True,
                         display_header_footer=True, header_template="<div></div>", footer_template=FOOTER,
                         margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
            else:
                page.pdf(path=str(pdf_path), format="A4", print_background=True,
                         margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        finally:
            browser.close()
    return pdf_path
