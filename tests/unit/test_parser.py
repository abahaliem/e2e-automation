import pytest

from qa_agent.agent.parser import ActionParseError, extract_json, parse_action


def test_plain_json():
    a = parse_action('{"action": "click", "element": 2, "thought": "buka menu"}', 5)
    assert a.action == "click" and a.element == 2


def test_think_block_and_fence_are_stripped():
    text = '<think>pertimbangan panjang {"x": 1}</think>\nBerikut jawabannya:\n```json\n{"action": "type", "element": 1, "value": "abc"}\n```'
    a = parse_action(text, 3)
    assert a.action == "type" and a.value == "abc"


def test_numbers_as_strings_are_coerced():
    a = parse_action('{"action": "TYPE", "element": "3", "value": 30}', 3)
    assert a.action == "type" and a.element == 3 and a.value == "30"


def test_status_case_insensitive():
    a = parse_action('{"action": "done", "status": "PASS", "actual": "ok"}', 0)
    assert a.status == "pass"


def test_empty_reply():
    with pytest.raises(ActionParseError, match="kosong"):
        parse_action("", 3)
    with pytest.raises(ActionParseError, match="kosong"):
        parse_action(None, 3)


def test_no_json():
    with pytest.raises(ActionParseError, match="Tidak ada objek JSON"):
        parse_action("Saya akan klik tombol login", 3)


def test_broken_json():
    with pytest.raises(ActionParseError, match="JSON tidak valid"):
        parse_action('{"action": "click", "element": }', 3)


def test_unknown_action():
    with pytest.raises(ActionParseError, match="action"):
        parse_action('{"action": "hover", "element": 1}', 3)


def test_element_required_and_in_range():
    with pytest.raises(ActionParseError, match="wajib menyertakan nomor"):
        parse_action('{"action": "click"}', 3)
    with pytest.raises(ActionParseError, match="Elemen 9 tidak ada"):
        parse_action('{"action": "click", "element": 9}', 3)


def test_value_required():
    with pytest.raises(ActionParseError, match="value"):
        parse_action('{"action": "type", "element": 1}', 3)


def test_done_requires_status():
    with pytest.raises(ActionParseError, match="status"):
        parse_action('{"action": "done", "actual": "x"}', 3)


def test_scroll_defaults_down():
    assert parse_action('{"action": "scroll", "value": "kiri"}', 0).value == "down"


def test_extract_json_for_plan_objects():
    assert extract_json('```\n{"test_cases": []}\n```') == {"test_cases": []}


def test_dangling_think_close_with_braces_in_reasoning():
    # Review #9: endpoint yang mem-prefill <think> hanya mengirim penutupnya
    a = parse_action('Isi {{username}} dulu, lalu {"x"}</think>\n{"action": "wait", "value": "1"}', 0)
    assert a.action == "wait"


def test_multiple_json_objects_takes_last_with_action():
    a = parse_action('Contoh: {"contoh": 1}\nJawaban: {"action": "back"}', 0)
    assert a.action == "back"
