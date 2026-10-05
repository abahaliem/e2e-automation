import itertools
import json
import re

from qa_agent.evidence import RunStore
from qa_agent.guard import Guard
from qa_agent.llm.fake import FakeLLM
from qa_agent.orchestrator.explore import Explorer
from tests.fakes import BASE, FakeDriver, el, screen, url

LOGIN = screen("login", el(1, "input", "Email"), el(2, "input", "Password", input_type="password"), el(3, "button", "Masuk"))
HOME = screen("home", el(1, "link", "Pengguna", href=url("users")), el(2, "link", "Laporan", href=url("reports")),
              el(3, "button", "Keluar"), el(4, "link", "Bantuan", href="https://docs.other.test/"))
USERS = screen("users", el(1, "link", "Tambah Pengguna", href=url("users/new")), el(2, "link", "Edit", href=url("users/1/edit")),
               el(3, "link", "Edit", href=url("users/2/edit")), el(4, "button", "Hapus"), el(5, "button", "Ekspor"))
NEW = screen("users/new", el(1, "input", "Nama"), el(2, "button", "Simpan"))
EDIT1 = screen("users/1/edit", el(1, "input", "Nama"), el(2, "button", "Simpan"))
EDIT2 = screen("users/2/edit", el(1, "input", "Nama"), el(2, "button", "Simpan"))
REPORTS = screen("reports", el(1, "button", "Tab Arsip"))
ARCHIVE = screen("archive", el(1, "link", "Pengguna", href=url("users")))
ALL = [LOGIN, HOME, USERS, NEW, EDIT1, EDIT2, REPORTS, ARCHIVE]
TRANSITIONS = {(url("reports"), "Tab Arsip"): url("archive")}
MODULES = {"login": "Autentikasi", "home": "Dashboard", "users": "Pengguna", "reports": "Laporan", "archive": "laporan"}


def summarizer(system, messages):
    """AI 'nakal' yang memasukkan SEMUA elemen ke nav_candidates; guard harus menyaringnya."""
    assert system.startswith("MODE: EXPLORE_SCREEN")
    text = messages[0].text
    path = re.search(r"^URL: (\S+)", text, re.M).group(1).replace(BASE + "/", "")
    indices = [int(i) for i in re.findall(r"^\[(\d+)\]", text, re.M)]
    return json.dumps({"module": MODULES[path.split("/")[0]], "page_name": path, "purpose": f"Halaman {path}",
                       "nav_candidates": indices})


class StubAuth:
    def __init__(self, driver):
        self.driver = driver
        self.logins = 0

    def login(self):
        self.logins += 1
        self.driver.current = url("home")


def make(tmp_path, driver, llm=None, start="login", **kw):
    store = RunStore(tmp_path / "run")
    auth = StubAuth(driver)
    explorer = Explorer(driver=driver, llm=llm or FakeLLM(summarizer), guard=Guard("dev", ["app.test"]), store=store,
                        auth=auth, start_url=url(start), **kw)
    return explorer, store, auth


def test_explore_maps_app_and_respects_guard(tmp_path):
    driver = FakeDriver(ALL, url("login"), TRANSITIONS)
    explorer, store, auth = make(tmp_path, driver)
    app_map = explorer.run()
    paths = [s.url.replace(BASE + "/", "") for s in app_map.screens]
    assert paths[0] == "login" and app_map.screens[0].public and auth.logins == 1
    assert set(paths) == {"login", "home", "users", "reports", "users/new", "users/1/edit", "archive"}
    assert app_map.modules() == ["Autentikasi", "Dashboard", "Pengguna", "Laporan"]
    clicked = [name for (_, name, _) in driver.executed]
    assert "Hapus" not in clicked and "Keluar" not in clicked and "Simpan" not in clicked
    assert ("click", "Tab Arsip", None) in driver.executed
    assert not any(g.startswith("https://docs.other.test") for g in driver.gotos)
    assert store.read_app_map() == app_map
    assert (store.root / app_map.screens[0].screenshot).exists()
    assert [s.tc_id for s in store.read_steps()] == ["EXPLORE"] * len(paths)


def test_max_screens(tmp_path):
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("login"), TRANSITIONS), max_screens=3)
    assert len(explorer.run().screens) == 3


def test_time_limit(tmp_path):
    ticks = itertools.chain([0, 0], itertools.repeat(10_000))
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("login"), TRANSITIONS), clock=lambda: next(ticks))
    assert [s.url for s in explorer.run().screens] == [url("login"), url("home")]


def test_no_login_page(tmp_path):
    explorer, _, auth = make(tmp_path, FakeDriver(ALL, url("home"), TRANSITIONS), start="home", max_screens=2)
    app_map = explorer.run()
    assert auth.logins == 0 and not app_map.screens[0].public


def test_summary_fallback_follows_links(tmp_path):
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("home"), TRANSITIONS), llm=FakeLLM(lambda s, m: "bukan json"),
                          start="home", max_screens=2)
    app_map = explorer.run()
    assert app_map.screens[0].module == "Lainnya"
    assert app_map.screens[1].url == url("users")


def test_stop_flag(tmp_path):
    explorer, _, _ = make(tmp_path, FakeDriver(ALL, url("home"), TRANSITIONS), start="home", should_stop=lambda: True)
    assert explorer.run().screens == []
