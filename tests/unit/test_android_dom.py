from qa_agent.drivers.android_dom import parse_ui, screen_key
from tests.android_fakes import LOGIN_XML, hierarchy, node


def by_name(elements):
    return {e.name: e for e in elements}


def test_login_screen_elements():
    els = parse_ui(LOGIN_XML)
    names = by_name(els)
    assert [e.index for e in els] == list(range(1, len(els) + 1))
    email = names["Email"]
    assert email.role == "input" and email.bbox == (100.0, 400.0, 880.0, 120.0)
    assert email.selector == "com.demo.app:id/email"
    password = next(e for e in els if e.input_type == "password")
    assert password.role == "input" and password.name == "Password"
    assert names["MASUK"].role == "button"
    assert names["Masuk ke Demo"].role == "text"


def test_clickable_container_takes_child_text_and_children_not_duplicated():
    xml = hierarchy(node("android.widget.LinearLayout", rid="com.demo.app:id/row", bounds="[0,300][1080,420]",
                         children=node("android.widget.TextView", text="Pengaturan Akun", clickable=False,
                                       bounds="[40,320][600,400]")))
    els = parse_ui(xml)
    assert [(e.role, e.name) for e in els] == [("button", "Pengaturan Akun")]


def test_roles_and_state():
    xml = hierarchy(
        node("android.widget.CheckBox", text="Ingat saya", checkable=True, checked=True, bounds="[0,0][300,80]"),
        node("androidx.appcompat.widget.SwitchCompat", text="Notifikasi", checkable=True, bounds="[0,100][300,180]"),
        node("android.widget.Spinner", desc="Pilih kota", bounds="[0,200][300,280]"),
        node("android.widget.ImageButton", desc="Kembali", bounds="[0,300][100,380]"),
        node("android.widget.Button", text="Kirim", enabled=False, bounds="[0,400][300,480]"),
    )
    els = by_name(parse_ui(xml))
    assert els["Ingat saya"].role == "checkbox" and els["Ingat saya"].value == "on"
    assert els["Notifikasi"].role == "switch" and els["Notifikasi"].value == "off"
    assert els["Pilih kota"].role == "select"
    assert els["Kembali"].role == "button"
    assert els["Kirim"].context == "nonaktif"


def test_invisible_and_empty_nodes_skipped():
    xml = hierarchy(
        node("android.widget.Button", text="Nol", bounds="[0,0][0,0]"),
        node("android.widget.Button", text="Di luar layar", bounds="[0,3000][300,3100]"),
        node("android.view.View", text="", desc="", clickable=False, bounds="[0,0][100,100]"),
        node("android.widget.Button", text="Tampil", bounds="[0,0][300,100]"),
    )
    assert [e.name for e in parse_ui(xml, screen=(1080, 2400))] == ["Tampil"]


def test_password_value_masked():
    xml = hierarchy(node("android.widget.EditText", text="••••••", rid="x:id/pass", password=True))
    el = parse_ui(xml)[0]
    assert el.value == "******" and el.input_type == "password"


def test_limit_prefers_interactive():
    texts = [node("android.widget.TextView", text=f"Info {i}", clickable=False, bounds=f"[0,{i*10}][100,{i*10+9}]")
             for i in range(30)]
    xml = hierarchy(*texts, node("android.widget.Button", text="Simpan", bounds="[0,2000][300,2100]"))
    els = parse_ui(xml, max_elements=10)
    assert len(els) == 10 and any(e.name == "Simpan" for e in els)


def test_screen_key_stable_for_dynamic_text_but_differs_per_screen():
    a = parse_ui(hierarchy(node("android.widget.TextView", text="12:01", clickable=False),
                           node("android.widget.Button", text="Bayar", rid="x:id/pay")))
    b = parse_ui(hierarchy(node("android.widget.TextView", text="12:02", clickable=False),
                           node("android.widget.Button", text="Bayar", rid="x:id/pay")))
    c = parse_ui(hierarchy(node("android.widget.Button", text="Batal", rid="x:id/cancel")))
    assert screen_key(a) == screen_key(b) != screen_key(c)
    assert len(screen_key(a)) == 8
