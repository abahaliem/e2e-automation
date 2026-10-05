from qa_agent.agent import prompts
from qa_agent.models import Element, Observation, ScreenInfo, Signal


def obs():
    return Observation(
        location="http://a/users/new", title="Tambah Pengguna",
        elements=[Element(index=1, role="input", name="Nama", value=""), Element(index=2, role="input", name="Password", input_type="password", value="******"),
                  Element(index=3, role="button", name="Simpan", context="Tambah Pengguna")],
        signals=[Signal(kind="http_error", message="HTTP 500", status=500, method="POST", url="http://a/users")],
        screenshot_annotated=b"\x89PNG",
    )


def test_execute_system_markers():
    s = prompts.execute_system("web", "QA-AUTO-20261005-1430")
    assert s.startswith("MODE: EXECUTE")
    assert "QA-AUTO-20261005-1430" in s and "{{username}}" in s and "{{password}}" in s
    assert "<<" not in s


def test_format_element():
    e = obs().elements
    assert prompts.format_element(e[0]) == '[1] input "Nama" value=""'
    assert prompts.format_element(e[1]) == '[2] input "Password" type=password value="******"'
    assert prompts.format_element(e[2]) == '[3] button "Simpan" (dalam: Tambah Pengguna)'


def test_step_message_sections_and_image():
    msg = prompts.step_message("Tambah pengguna", obs(), ["1. Klik link 'Tambah' → ok"], ["Aksi X diblok"], vision=True)
    assert "## Tujuan\nTambah pengguna" in msg.text
    assert "1. Klik link 'Tambah' → ok" in msg.text
    assert "## Catatan sistem\n- Aksi X diblok" in msg.text
    assert "- HTTP 500 POST http://a/users" in msg.text
    assert msg.images == [b"\x89PNG"]
    no_vision = prompts.step_message("x", obs(), [], [], vision=False)
    assert no_vision.images == [] and "(belum ada)" in no_vision.text and "Catatan sistem" not in no_vision.text


def test_explore_and_plan_prompts():
    assert prompts.explore_system(["Dashboard"]).startswith("MODE: EXPLORE_SCREEN")
    assert "Dashboard" in prompts.explore_system(["Dashboard"])
    plan = prompts.plan_system("Pengguna", 15, "QA-AUTO-X", has_prd=True)
    assert plan.startswith("MODE: PLAN") and "Pengguna" in plan and "15" in plan and "PRD" in plan
    screens = [ScreenInfo(fingerprint="f", url="http://a/users/new", module="Pengguna", page_name="Tambah Pengguna", purpose="Form tambah",
                          forms=[{"name": "Form pengguna", "fields": [{"label": "Nama", "type": "text"}]}], actions=["Simpan"])]
    msg = prompts.plan_message(screens, "PRD: email wajib valid")
    assert "Tambah Pengguna (http://a/users/new)" in msg.text and "Nama (text)" in msg.text and "## PRD" in msg.text
    assert "## PRD" not in prompts.plan_message(screens, None).text
