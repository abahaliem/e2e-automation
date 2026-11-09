from __future__ import annotations

from qa_agent.llm.base import Message
from qa_agent.models import Element, Observation, ScreenInfo
from qa_agent.report.humanize import signal_text

EXECUTE_SYSTEM = """MODE: EXECUTE
Kamu adalah QA automation engineer senior yang menguji aplikasi <<platform>> secara black-box (tanpa akses kode).
Setiap giliran kamu menerima tujuan, riwayat langkah, dan kondisi layar saat ini (screenshot bernomor + daftar elemen).
Pilih SATU aksi berikutnya.

Jawab HANYA dengan satu objek JSON, tanpa teks lain:
{"thought": "alasan singkat", "action": "<aksi>", "element": <nomor atau null>, "value": "<teks atau null>", "expect": "hasil yang kamu harapkan", "risk": "low|medium|high"}

Aksi yang tersedia:
- click (element wajib)
- type (element dan value wajib; value "" untuk mengosongkan field)
- select (element wajib, value = teks opsi)
- scroll (value "up" atau "down")
- back
- navigate (value = URL atau path di domain yang sama)
- wait (value = jumlah detik, maksimal 10)
- done (wajib "status": "pass" atau "fail", "actual": apa yang benar-benar terjadi, "severity": "Critical|Major|Minor" jika fail)
- blocked ("reason": kenapa tidak bisa dilanjutkan)

Aturan:
1. Pakai hanya nomor elemen dari daftar elemen layar saat ini.
2. Untuk kredensial tulis persis {{username}} dan {{password}}; sistem yang akan mengisinya.
3. Data baru yang kamu buat (nama, judul, dll.) diawali "<<data_prefix>>" kecuali test data menentukan lain.
4. risk "high" jika aksi menyimpan/mengubah/menghapus/mengirim data atau transaksi; "medium" jika membuka form/dialog yang bisa mengarah ke perubahan; "low" untuk navigasi dan membaca.
5. Nyatakan done segera setelah hasil bisa diverifikasi dari layar. Bandingkan dengan expected result secara jujur: fail jika berbeda.
6. Jika aksi diblok Safety Guard atau gagal berulang, cari jalan lain; jika tidak ada, nyatakan blocked.
7. Sinyal error (HTTP 5xx, error JavaScript) adalah bukti bug; sebutkan di actual.
"""

EXPLORE_SYSTEM = """MODE: EXPLORE_SCREEN
Kamu adalah QA engineer yang sedang memetakan fitur aplikasi. Analisis layar ini.
Jawab HANYA satu objek JSON:
{"module": "nama modul/fitur, singkat, Bahasa Indonesia, konsisten antar layar", "page_name": "nama halaman", "purpose": "fungsi halaman dalam 1 kalimat", "forms": [{"name": "nama form", "fields": [{"label": "label field", "type": "text|email|password|number|select|checkbox|date|file|textarea"}]}], "actions": ["aksi penting yang tersedia"], "nav_candidates": [nomor elemen yang membuka halaman atau menu lain]}
Aturan nav_candidates: hanya menu, link, tab, atau tombol yang berpindah halaman. JANGAN masukkan logout, hapus, simpan, kirim, atau aksi lain yang mengubah data.
Modul yang sudah ditemukan sejauh ini (pakai nama yang sama jika layar ini bagian dari modul tersebut): <<modules>>
"""

PLAN_SYSTEM = """MODE: PLAN
Kamu adalah QA engineer senior. Susun test case untuk modul "<<module>>" berdasarkan peta layar<<prd_hint>>.
Jawab HANYA satu objek JSON: {"test_cases": [ ... ]}
Format setiap test case:
{"title": "...", "page": "nama halaman", "type": "positif|negatif|validasi|boundary|navigasi", "priority": "High|Medium|Low", "precondition": "...", "test_data": "...", "steps": ["langkah 1", "langkah 2"], "expected": "...", "expected_source": "PRD|Inferensi AI", "start_url": "URL layar awal"}
Aturan:
1. Maksimal <<max>> test case. Campurkan tipe: positif, negatif, validasi field, boundary, navigasi.
2. expected_source "PRD" HANYA jika expected diambil langsung dari PRD; selain itu "Inferensi AI".
3. Langkah ditulis untuk manusia dalam Bahasa Indonesia, spesifik (sebut nama field/tombol).
4. Data baru diawali "<<data_prefix>>".
5. start_url diambil dari peta layar.
6. Jangan membuat test case login/logout kecuali modulnya memang autentikasi.
"""


ANDROID_NOTE = """
Catatan aplikasi Android:
- back = menekan tombol Kembali di HP (juga untuk menutup keyboard layar atau dialog).
- navigate tidak tersedia; berpindah layar dengan click, back, atau scroll.
- Daftar panjang: scroll "down" untuk melihat elemen di bawahnya.
- Dialog "tidak merespons" / "telah berhenti" dari Android adalah bukti bug (crash/ANR); sebutkan di actual.
"""


def execute_system(platform: str, data_prefix: str, skills: str = "") -> str:
    text = EXECUTE_SYSTEM.replace("<<platform>>", platform).replace("<<data_prefix>>", data_prefix)
    if platform == "android":
        text += ANDROID_NOTE
    return text + ("\n" + skills if skills else "")


def explore_system(known_modules: list[str]) -> str:
    return EXPLORE_SYSTEM.replace("<<modules>>", ", ".join(known_modules) or "(belum ada)")


def plan_system(module: str, max_tcs: int, data_prefix: str, has_prd: bool, skills: str = "") -> str:
    text = (PLAN_SYSTEM.replace("<<module>>", module).replace("<<max>>", str(max_tcs))
            .replace("<<data_prefix>>", data_prefix).replace("<<prd_hint>>", " dan PRD" if has_prd else ""))
    return text + ("\n" + skills if skills else "")


def format_element(e: Element) -> str:
    parts = [f'[{e.index}] {e.role} "{e.name}"']
    if e.input_type and e.input_type not in ("text", "submit", "button"):
        parts.append(f"type={e.input_type}")
    if e.value is not None:
        parts.append(f'value="{e.value}"')
    if e.context:
        parts.append(f"(dalam: {e.context})")
    return " ".join(parts)


def observation_text(obs: Observation) -> str:
    lines = [f"URL: {obs.location}", f"Judul: {obs.title}"]
    if obs.signals:
        lines.append("Sinyal:")
        lines.extend(f"- {signal_text(s)}" for s in obs.signals)
    lines.append("Elemen:")
    lines.extend([format_element(e) for e in obs.elements] or ["(tidak ada elemen interaktif)"])
    return "\n".join(lines)


def _images(obs: Observation, vision: bool) -> list[bytes]:
    return [obs.screenshot_annotated] if vision and obs.screenshot_annotated else []


def step_message(goal: str, obs: Observation, history: list[str], notes: list[str], vision: bool,
                 hints: list[str] | None = None) -> Message:
    text = f"## Tujuan\n{goal}\n\n## Riwayat langkah terakhir\n" + ("\n".join(history) or "(belum ada)")
    if hints:
        text += ("\n\n## Arahan QA\n" + "\n".join(f"- {h}" for h in hints)
                 + "\n(Arahan dari QA manusia yang memantau. Ikuti selama tidak melanggar aturan keamanan.)")
    if notes:
        text += "\n\n## Catatan sistem\n" + "\n".join(f"- {n}" for n in notes)
    text += "\n\n## Layar saat ini\n" + observation_text(obs)
    return Message(role="user", text=text, images=_images(obs, vision))


def retry_message(error: str) -> Message:
    return Message(role="user", text=f"Jawaban sebelumnya tidak valid: {error}. Ulangi dengan SATU objek JSON sesuai format.")


def explore_message(obs: Observation, vision: bool) -> Message:
    return Message(role="user", text="## Layar\n" + observation_text(obs), images=_images(obs, vision))


def plan_message(screens: list[ScreenInfo], prd_text: str | None) -> Message:
    lines = ["## Peta layar modul"]
    for s in screens:
        lines.append(f"- {s.page_name} ({s.url})")
        if s.purpose:
            lines.append(f"  Fungsi: {s.purpose}")
        for form in s.forms:
            fields = ", ".join(f"{f.get('label', '?')} ({f.get('type', '?')})" for f in form.get("fields", []))
            lines.append(f"  Form {form.get('name', '')}: {fields}")
        if s.actions:
            lines.append(f"  Aksi: {', '.join(s.actions)}")
    if prd_text:
        lines += ["", "## PRD", prd_text[:12000]]
    return Message(role="user", text="\n".join(lines))
