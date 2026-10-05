from qa_agent.drivers.web_dom import build_selector, to_element


def raw(**kw):
    base = {"index": 1, "role": "button", "name": "Simpan", "input_type": None, "value": None, "bbox": [10, 20, 30, 40],
            "testid": "", "testid_attr": "", "id": "", "href": None, "context": "", "css": "form > button", "tag": "button"}
    base.update(kw)
    return base


def test_testid_wins():
    assert build_selector(raw(testid="save-btn", testid_attr="data-testid", id="x")) == '[data-testid="save-btn"]'


def test_stable_id_used():
    assert build_selector(raw(id="email")) == '[id="email"]'


def test_auto_generated_id_skipped():
    assert build_selector(raw(id="input-12345")) == 'role=button[name="Simpan"]'
    assert build_selector(raw(id=":r3:")) == 'role=button[name="Simpan"]'


def test_role_mapping_and_quote_escape():
    assert build_selector(raw(role="input", name='Kata "kunci"')) == 'role=textbox[name="Kata \\"kunci\\""]'
    assert build_selector(raw(role="select", name="Kota")) == 'role=combobox[name="Kota"]'


def test_css_fallback():
    assert build_selector(raw(name="")) == "form > button"


def test_to_element_applies_frame_offset():
    e = to_element(raw(href="", input_type=""), 1, (100.0, 50.0))
    assert e.bbox == (110.0, 70.0, 30, 40)
    assert e.frame == 1 and e.href is None and e.input_type is None
