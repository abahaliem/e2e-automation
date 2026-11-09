import io
import zipfile

import pytest

from qa_agent.agent import prompts
from qa_agent.skills import BUILTIN_SKILL, SkillError, extract_text, skill_section


def make_docx(paragraphs: list[str], pages: int | None = 3) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
        if pages:
            z.writestr("docProps/app.xml", f'<Properties xmlns="x"><Pages>{pages}</Pages></Properties>')
    return buf.getvalue()


def make_pdf(lines: list[str]) -> bytes:
    """PDF minimal satu halaman berisi teks (tanpa library tambahan)."""
    content = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({ln}) Tj 0 -16 Td" for ln in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_extract_md_and_txt(tmp_path):
    md = tmp_path / "checklist.md"
    md.write_text("# Checklist Regresi\n- Cek login\n- Cek logout\n", encoding="utf-8")
    text, pages = extract_text(md)
    assert "Cek login" in text and pages == 1
    txt = tmp_path / "glosarium.txt"
    txt.write_bytes("Karyawan = pegawai tetap; café".encode("cp1252"))
    text, _ = extract_text(txt)
    assert "pegawai tetap" in text


def test_extract_docx(tmp_path):
    path = tmp_path / "standar-test-case.docx"
    path.write_bytes(make_docx(["Standar Test Case Kantor", "ID memakai format TC-MODUL-001"], pages=4))
    text, pages = extract_text(path)
    assert text.splitlines() == ["Standar Test Case Kantor", "ID memakai format TC-MODUL-001"]
    assert pages == 4


def test_extract_pdf(tmp_path):
    path = tmp_path / "aturan-cuti.pdf"
    path.write_bytes(make_pdf(["Aturan Bisnis Cuti", "Cuti tahunan maksimal 12 hari"]))
    text, pages = extract_text(path)
    assert "Cuti tahunan maksimal 12 hari" in text and pages == 1


def test_extract_rejects_empty_and_unknown(tmp_path):
    empty = tmp_path / "kosong.md"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(SkillError, match="Tidak ada teks"):
        extract_text(empty)
    with pytest.raises(SkillError, match=".md, .txt, .docx, atau .pdf"):
        extract_text(tmp_path / "x.xlsx")


def test_builtin_skill_covers_mockup_topics():
    for topic in ("Equivalence Partitioning", "Boundary Value", "Decision Table", "State Transition",
                  "error guessing", "Pre-condition", "Severity", "reproduksi"):
        assert topic.lower() in BUILTIN_SKILL.content.lower()
    assert len(BUILTIN_SKILL.topics) == 6


def test_skill_section_and_prompts():
    section = skill_section([("Standar Test Case Kantor", "ID memakai TC-MODUL-001")])
    assert section.startswith("## Skill QA")
    assert "QA Engineer profesional" in section and "### Standar Test Case Kantor" in section
    plan = prompts.plan_system("Pengguna", 10, "QA-AUTO", False, skills=section)
    execute = prompts.execute_system("web", "QA-AUTO", skills=section)
    assert "ID memakai TC-MODUL-001" in plan and "ID memakai TC-MODUL-001" in execute
    assert "## Skill QA" not in prompts.plan_system("Pengguna", 10, "QA-AUTO", False)
