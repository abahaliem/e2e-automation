import json
import re

import pytest
from fastapi.testclient import TestClient

from qa_agent.drivers.adb import AdbError, AdbNotFound, DeviceInfo
from qa_agent.llm.fake import FakeLLM
from qa_agent.server.app import create_app
from qa_agent.server.secrets import MemorySecretStore
from qa_agent.server.settings import ServerSettings
from tests.android_fakes import HOME_XML, USERS_XML, FakeAdb
from tests.server.conftest import Brains, wait_for


class DeviceAdb:
    """Adb tiruan untuk API perangkat."""

    def __init__(self, serial=None, state=None):
        self.serial = serial
        self.state = state if state is not None else {"packages": ["com.demo.app"], "installed": [], "fail": None}

    def devices(self):
        return [DeviceInfo("R58M123", "device", "SM A546E"), DeviceInfo("ZY22", "unauthorized")]

    def android_version(self):
        return "14"

    def packages(self, third_party=True):
        if self.serial == "ZY22":
            raise AdbError("error: device unauthorized")
        return sorted(self.state["packages"])

    def package_versions(self):
        return {p: ("3.8.1" if p == "com.demo.app" else None) for p in self.packages()}

    def screencap(self):
        from tests.android_fakes import PNG
        return PNG

    def install(self, path):
        if self.state["fail"]:
            raise AdbError(self.state["fail"])
        self.state["installed"].append(path)
        self.state["packages"].append("com.baru.app")


@pytest.fixture
def ctx(tmp_path):
    state = {"packages": ["com.demo.app"], "installed": [], "fail": None}
    brains = Brains()
    app = create_app(ServerSettings(data_dir=tmp_path / "data"), secrets=MemorySecretStore(), llm_factory=brains,
                     adb_factory=lambda serial=None: DeviceAdb(serial, state))
    with TestClient(app) as client:
        yield client, state, app, brains


def test_list_devices(ctx):
    client, *_ = ctx
    body = client.get("/api/devices").json()
    assert body["devices"][0] == {"serial": "R58M123", "state": "device", "model": "SM A546E", "emulator": False,
                                  "android_version": "14"}
    assert body["devices"][1]["state"] == "unauthorized" and body["devices"][1]["android_version"] is None


def test_adb_missing_503(tmp_path):
    def missing(serial=None):
        class A:
            def devices(self):
                raise AdbNotFound("adb tidak ditemukan")
        return A()

    app = create_app(ServerSettings(data_dir=tmp_path / "d"), secrets=MemorySecretStore(), adb_factory=missing)
    with TestClient(app) as client:
        r = client.get("/api/devices")
        assert r.status_code == 503 and r.json()["adb_missing"] is True


def test_packages_and_unauthorized(ctx):
    client, *_ = ctx
    body = client.get("/api/devices/R58M123/packages").json()
    assert body["packages"] == ["com.demo.app"]
    assert body["apps"] == [{"package": "com.demo.app", "version": "3.8.1"}]
    r = client.get("/api/devices/ZY22/packages")
    assert r.status_code == 409 and "unauthorized" in r.json()["detail"]


def test_install_apk_detects_new_package(ctx):
    client, state, app, _ = ctx
    r = client.post("/api/devices/R58M123/install?filename=Demo%20App.apk", content=b"PK\x03\x04apk",
                    headers={"content-type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    assert r.json()["package"] == "com.baru.app"
    saved = state["installed"][0]
    assert saved.endswith(".apk") and "apks" in saved
    # pasang ulang: tidak ada paket baru â†’ pengguna memilih dari daftar
    r = client.post("/api/devices/R58M123/install?filename=demo.apk", content=b"PK\x03\x04apk")
    assert r.json()["package"] is None and "com.demo.app" in r.json()["packages"]


def test_install_rejects_non_apk_and_reports_failure(ctx):
    client, state, *_ = ctx
    r = client.post("/api/devices/R58M123/install?filename=virus.exe", content=b"MZ")
    assert r.status_code == 422
    state["fail"] = "Gagal memasang APK: INSTALL_FAILED_VERSION_DOWNGRADE"
    r = client.post("/api/devices/R58M123/install?filename=demo.apk", content=b"PK\x03\x04")
    assert r.status_code == 409 and "VERSION_DOWNGRADE" in r.json()["detail"]


def test_android_app_validation(ctx):
    client, *_ = ctx
    ok = client.post("/api/apps", json={"name": "Demo HP", "platform": "android", "url": "android://com.demo.app"})
    assert ok.status_code == 201 and ok.json()["platform"] == "android"
    bad = client.post("/api/apps", json={"name": "X", "platform": "android", "url": "https://web.test"})
    assert bad.status_code == 422 and "url" in bad.json()["field_errors"]


def test_android_run_requires_device(ctx):
    client, *_ = ctx
    client.post("/api/profiles", json={"name": "P", "base_url": "http://x/v1", "model": "m", "api_key": "k"})
    app = client.post("/api/apps", json={"name": "Demo HP", "platform": "android", "url": "android://com.demo.app"}).json()
    r = client.post("/api/runs", json={"app_id": app["id"], "mode": "explore"})
    assert r.status_code == 422 and "perangkat" in r.json()["detail"]


def brain(system, messages):
    text = messages[0].text
    if system.startswith("MODE: EXPLORE_SCREEN"):
        links = [int(i) for i in re.findall(r'^\[(\d+)\] button "Pengguna"', text, re.M)]
        module = "Pengguna" if "Daftar Pengguna" in text else "Beranda"
        return json.dumps({"module": module, "page_name": module, "purpose": "x", "nav_candidates": links})
    if system.startswith("MODE: PLAN"):
        return json.dumps({"test_cases": [{"title": "Daftar pengguna tampil", "steps": ["Buka Pengguna"],
                                           "expected": "Daftar tampil"}]})
    assert "Catatan aplikasi Android" in system
    return json.dumps({"action": "done", "status": "pass", "actual": "Daftar pengguna tampil"})


def test_android_explore_and_deep_run(ctx, monkeypatch):
    client, _, app_obj, brains = ctx
    fake = FakeAdb({"HOME": HOME_XML, "USERS": USERS_XML}, "HOME", {("HOME", (0, 300, 1080, 420)): "USERS"})
    serials = []
    monkeypatch.setattr("qa_agent.drivers.adb.Adb", lambda serial=None, **kw: serials.append(serial) or fake)
    import qa_agent.drivers.android as android_mod
    original = android_mod.AndroidDriver.__init__

    def fast_init(self, adb, package, **kw):
        original(self, adb, package, sleep=lambda s: None, **{k: v for k, v in kw.items() if k != "sleep"})

    monkeypatch.setattr(android_mod.AndroidDriver, "__init__", fast_init)
    brains.make = lambda profile: FakeLLM(brain)

    client.post("/api/profiles", json={"name": "P", "base_url": "http://x/v1", "model": "m", "api_key": "k"})
    app = client.post("/api/apps", json={"name": "Demo HP", "platform": "android", "url": "android://com.demo.app"}).json()
    run = client.post("/api/runs", json={"app_id": app["id"], "mode": "explore", "device_serial": "R58M123"}).json()
    assert run["device_serial"] == "R58M123"
    wait_for(lambda: client.get(f"/api/runs/{run['id']}").json()["status"] in ("completed", "interrupted", "paused"))
    done = client.get(f"/api/runs/{run['id']}").json()
    assert done["status"] == "completed", done["note"]
    assert serials and serials[0] == "R58M123"
    assert client.get(f"/api/apps/{app['id']}/modules").json()["modules"] == ["Beranda", "Pengguna"]

    deep = client.post("/api/runs", json={"app_id": app["id"], "mode": "deep", "module": "Pengguna",
                                          "device_serial": "R58M123"}).json()
    wait_for(lambda: client.get(f"/api/runs/{deep['id']}").json()["status"] in ("completed", "interrupted", "paused"))
    result = client.get(f"/api/runs/{deep['id']}").json()
    assert result["status"] == "completed", result["note"]
    cases = client.get(f"/api/runs/{deep['id']}/cases").json()
    assert [c["status_ai"] for c in cases] == ["Pass"]
    assert fake.current == "USERS"  # run modul dibuka di layar awal test case lewat jalur hasil explore


def test_device_screen_preview(ctx):
    client, *_ = ctx
    r = client.get("/api/devices/R58M123/screen")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert r.headers["cache-control"] == "no-store"