import pytest

from qa_agent.drivers.apk import ApkError, read_apk_info
from tests.apk_builder import make_apk


def test_reads_package_and_version(tmp_path):
    path = tmp_path / "hr-mobile-3.9.0-debug.apk"
    path.write_bytes(make_apk("id.kantor.hrmobile", "3.9.0"))
    info = read_apk_info(path)
    assert info.package == "id.kantor.hrmobile"
    assert info.version_name == "3.9.0"
    assert info.version_code == 1
    assert info.size_bytes == path.stat().st_size


def test_missing_version_name(tmp_path):
    path = tmp_path / "x.apk"
    path.write_bytes(make_apk("com.demo.app", None))
    info = read_apk_info(path)
    assert info.package == "com.demo.app" and info.version_name is None


def test_not_an_apk(tmp_path):
    path = tmp_path / "x.apk"
    path.write_bytes(b"bukan zip")
    with pytest.raises(ApkError, match="bukan file APK"):
        read_apk_info(path)
    import zipfile

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "x")
    with pytest.raises(ApkError, match="AndroidManifest"):
        read_apk_info(path)
