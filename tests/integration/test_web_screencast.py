import io

import pytest
from PIL import Image

from qa_agent.drivers.web import WebDriver
from tests.integration.helpers import login_direct

pytestmark = pytest.mark.browser

ANIMATE = """() => {
  const d = document.createElement('div');
  d.id = 'anim';
  d.style.cssText = 'width:80px;height:80px;background:#2560e8;position:fixed;top:0;left:0';
  document.body.appendChild(d);
  let i = 0;
  setInterval(() => { d.style.left = ((i += 7) % 900) + 'px'; }, 30);
}"""


def pump(driver, ms):
    driver.page.wait_for_timeout(ms)


def test_screencast_frames_flow_and_stop(demo):
    frames: list[tuple[bytes, dict]] = []
    d = WebDriver(demo.url, headless=True, viewport=(1600, 900))
    d.start()
    try:
        d.set_frame_sink(lambda jpeg, meta: frames.append((jpeg, meta)))
        d.new_session(None)
        login_direct(d)
        d.page.evaluate(ANIMATE)
        pump(d, 500)
        assert frames == []  # belum ada penonton
        d.set_streaming(True)
        pump(d, 3000)
        assert len(frames) >= 2
        jpeg, meta = frames[-1]
        assert jpeg[:2] == b"\xff\xd8"
        assert Image.open(io.BytesIO(jpeg)).width <= 1280
        assert meta["width"] == 1600 and meta["height"] == 900
        assert len(frames) <= 3 * 8  # dibatasi sekitar 6 fps

        # sesi browser baru (per test case): screencast dipasang ulang otomatis
        d.new_session(None)
        login_direct(d)
        d.page.evaluate(ANIMATE)
        before = len(frames)
        pump(d, 1500)
        assert len(frames) > before

        d.set_streaming(False)
        pump(d, 300)
        stopped_at = len(frames)
        pump(d, 1000)
        assert len(frames) == stopped_at
    finally:
        d.stop()
