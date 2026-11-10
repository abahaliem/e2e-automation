"""Skill QA: pengetahuan tambahan untuk AI (mockup 06).

Skill bawaan "QA Engineer profesional" selalu aktif; skill tambahan diunggah pengguna (.md/.txt/.docx/.pdf)
dan teksnya disisipkan ke prompt sesuai tahap pemakaian.
"""
from __future__ import annotations

import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

STAGES = {
    "plan": "Menyusun test case",
    "execute": "Menjalankan test",
    "judge": "Menilai hasil",
    "report": "Menulis laporan",
}
# Tahap → prompt yang memakainya
PLAN_STAGES = ("plan", "report")
EXECUTE_STAGES = ("execute", "judge")
ALLOWED = (".md", ".txt", ".docx", ".pdf")
MAX_BYTES = 10 * 1024 * 1024
MAX_STAGE_CHARS = 60_000  # batas teks skill per prompt
CONTEXT_TOKENS = 128_000
CHARS_PER_PAGE = 3000


class SkillError(Exception):
    """File skill tidak bisa dipakai."""


@dataclass(frozen=True)
class BuiltinSkill:
    name: str
    description: str
    topics: tuple[str, ...]
    content: str


BUILTIN_SKILL = BuiltinSkill(
    name="QA Engineer profesional",
    description="Cara berpikir dasar agent saat merancang, menjalankan, dan menilai pengujian.",
    topics=(
        "Equivalence Partitioning dan Boundary Value",
        "Decision Table dan State Transition",
        "Pengujian negatif dan error guessing",
        "Test case: pre-condition, langkah, expected",
        "Severity dan prioritas bug",
        "Laporan bug yang bisa direproduksi",
    ),
    content="""Kamu bekerja seperti QA engineer profesional.
1. Equivalence Partitioning & Boundary Value: bagi input menjadi kelas valid/tidak valid; uji nilai batas (min, min-1, max, max+1, kosong, sangat panjang, karakter khusus seperti apostrof dan emoji).
2. Decision Table & State Transition: untuk aturan bisnis dengan beberapa kondisi, uji kombinasi penting; untuk alur berstatus (draft, diajukan, disetujui), uji transisi valid dan yang seharusnya ditolak.
3. Pengujian negatif & error guessing: coba input salah format, field wajib dikosongkan, klik ganda, kembali di tengah proses, data duplikat; pesan error harus jelas dan data tidak boleh tersimpan.
4. Test case yang baik punya Pre-condition, Langkah yang spesifik (sebut nama field/tombol), Test data, dan Expected result yang bisa diverifikasi dari layar.
5. Severity: Critical = fitur utama tidak bisa dipakai/data rusak/keamanan; Major = fungsi penting salah tanpa jalan lain; Minor = tampilan/teks/validasi ringan. Prioritas mengikuti dampak ke pengguna.
6. Laporan bug yang bisa direproduksi: langkah reproduksi berurutan, expected vs actual, bukti teknis (HTTP status, error JavaScript, crash), dan screenshot.
Nilai hasil dengan jujur: bandingkan kondisi layar dengan expected; jangan menyatakan pass bila tidak terbukti.""",
)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _docx(path: Path) -> tuple[str, int | None]:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
            pages = None
            if "docProps/app.xml" in z.namelist():
                m = re.search(rb"<Pages>(\d+)</Pages>", z.read("docProps/app.xml"))
                pages = int(m.group(1)) if m else None
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise SkillError(f"File .docx tidak bisa dibaca: {e}") from e
    paragraphs = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p")]
    return "\n".join(p for p in paragraphs if p.strip()), pages


def _pdf(path: Path) -> tuple[str, int]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "").strip() for page in reader.pages)
        return text, len(reader.pages)
    except (PdfReadError, ValueError, KeyError) as e:
        raise SkillError(f"File .pdf tidak bisa dibaca: {e}") from e


def extract_text(path: Path | str) -> tuple[str, int]:
    """(teks, jumlah halaman) dari file skill."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in ALLOWED:
        raise SkillError("Skill harus berupa file .md, .txt, .docx, atau .pdf")
    if suffix in (".md", ".txt"):
        text, pages = _decode(path.read_bytes()), None
    elif suffix == ".docx":
        text, pages = _docx(path)
    else:
        text, pages = _pdf(path)
    text = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()
    if not text:
        raise SkillError("Tidak ada teks yang bisa dibaca dari file ini (PDF hasil scan belum didukung)")
    return text, pages or max(1, math.ceil(len(text) / CHARS_PER_PAGE))


def skill_section(extra: list[tuple[str, str]], limit: int = MAX_STAGE_CHARS) -> str:
    """Bagian prompt '## Skill QA': skill bawaan + skill tambahan (nama, teks), dipotong bila terlalu panjang."""
    parts = [f"### {BUILTIN_SKILL.name} (bawaan)\n{BUILTIN_SKILL.content}"]
    used = len(parts[0])
    for name, text in extra:
        block = f"### {name}\n{text}"
        if used + len(block) > limit:
            block = block[: max(0, limit - used)] + "\n[...dipotong karena terlalu panjang]"
        parts.append(block)
        used += len(block)
        if used >= limit:
            break
    return ("## Skill QA\nIkuti pengetahuan dan standar berikut saat bekerja. Aturan keamanan sistem tetap berlaku.\n\n"
            + "\n\n".join(parts))


def capacity_percent(total_chars: int, context_tokens: int = CONTEXT_TOKENS) -> int:
    """Perkiraan porsi konteks model yang terpakai skill (≈ 4 karakter per token)."""
    return min(100, round(100 * (total_chars / 4) / context_tokens))
