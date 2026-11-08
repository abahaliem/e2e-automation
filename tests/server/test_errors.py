from qa_agent.server.runs import friendly_error


def test_missing_browser_message():
    raw = Exception(
        "BrowserType.launch: Executable doesn't exist at C:\\x\\chrome-headless-shell.exe\n"
        "╔════════╗\n║ Looks like Playwright was just installed or updated. ║\n║ playwright install ║\n╚════════╝"
    )
    msg = friendly_error(raw)
    assert "Browser Chromium untuk testing tidak ditemukan" in msg
    assert "playwright install chromium" in msg
    assert "╔" not in msg and "║" not in msg


def test_other_error_is_single_line_without_box_chars():
    msg = friendly_error(ValueError("baris satu\n║ kotak ║\nbaris dua"))
    assert msg.startswith("Error tak terduga: ValueError: baris satu")
    assert "\n" not in msg and "║" not in msg
