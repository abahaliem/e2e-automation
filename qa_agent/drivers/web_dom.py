"""Ekstraksi elemen interaktif dari DOM (dijalankan di halaman lewat Playwright)."""
from __future__ import annotations

import re

from qa_agent.models import Element

EXTRACT_JS = r"""
([maxElements, startIndex]) => {
  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=tab], ' +
    '[role=menuitem], [role=checkbox], [role=radio], [role=combobox], [onclick], [contenteditable=""], [contenteditable=true]';
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const cssPath = (el) => {
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 6) {
      let s = el.tagName.toLowerCase();
      if (el.id && !/\d{3,}/.test(el.id)) { parts.unshift(s + '#' + CSS.escape(el.id)); break; }
      const p = el.parentElement;
      if (p) {
        const same = Array.from(p.children).filter(c => c.tagName === el.tagName);
        if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
      }
      parts.unshift(s);
      el = p;
    }
    return parts.join(' > ');
  };
  document.querySelectorAll('[data-qa-idx]').forEach(e => e.removeAttribute('data-qa-idx'));
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    if (out.length >= maxElements) break;
    if (el.disabled || el.closest('[aria-hidden=true]')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    let role = el.getAttribute('role');
    if (!role) {
      if (tag === 'a') role = 'link';
      else if (tag === 'select') role = 'select';
      else if (tag === 'textarea') role = 'textarea';
      else if (tag === 'input') role = ['submit', 'button', 'reset', 'image'].includes(type) ? 'button'
        : (['checkbox', 'radio'].includes(type) ? type : 'input');
      else role = 'button';
    }
    const labelFor = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
    const wrapLabel = el.closest('label');
    let name = el.getAttribute('aria-label') || (labelFor && labelFor.innerText) || '';
    if (!name && ['input', 'select', 'textarea'].includes(tag)) name = (wrapLabel && wrapLabel.innerText) || el.getAttribute('placeholder') || '';
    if (!name && tag === 'input' && ['submit', 'button', 'reset'].includes(type)) name = el.value;
    if (!name) name = el.innerText || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('name') || '';
    let value = null;
    if (tag === 'input' && ['checkbox', 'radio'].includes(type)) value = el.checked ? 'checked' : 'unchecked';
    else if (tag === 'input' && !['submit', 'button', 'reset', 'image'].includes(type)) value = type === 'password' ? (el.value ? '******' : '') : el.value;
    else if (tag === 'textarea') value = el.value;
    else if (tag === 'select') value = el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '';
    let context = '';
    const box = el.closest('form, dialog, [role=dialog], [role=alertdialog], fieldset');
    if (box) {
      const h = box.querySelector('h1, h2, h3, h4, legend');
      context = (h && h.innerText) || box.getAttribute('aria-label') || '';
      if (!context) {
        const prev = box.previousElementSibling;
        if (prev && /^H[1-4]$/.test(prev.tagName)) context = prev.innerText;
      }
    }
    const testidAttr = el.hasAttribute('data-testid') ? 'data-testid' : (el.hasAttribute('data-test') ? 'data-test' : '');
    const index = startIndex + out.length;
    el.setAttribute('data-qa-idx', String(index));
    out.push({
      index, role, name: clean(name), input_type: type || null, value,
      bbox: [r.x, r.y, r.width, r.height],
      testid: testidAttr ? el.getAttribute(testidAttr) : '', testid_attr: testidAttr, id: el.id || '',
      href: tag === 'a' ? el.href : null, context: clean(context), css: cssPath(el), tag,
    });
  }
  return out;
}
"""

UI_ERROR_JS = r"""
() => Array.from(document.querySelectorAll('[role=alert], .alert-danger, .alert-error, .error, .toast-error, .invalid-feedback, .text-danger'))
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())
  .filter(t => t)
  .slice(0, 5)
"""

_AUTO_ID = re.compile(r"\d{3,}|^:r|^(ember|ext-|mui-|react-|radix-|headlessui-)", re.IGNORECASE)
_PLAYWRIGHT_ROLE = {"input": "textbox", "textarea": "textbox", "select": "combobox"}


def _quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_selector(raw: dict) -> str:
    """Selector stabil untuk direkam (format replay). Eksekusi sekarang memakai data-qa-idx."""
    if raw.get("testid"):
        return f'[{raw["testid_attr"]}="{_quote(raw["testid"])}"]'
    element_id = raw.get("id") or ""
    if element_id and not _AUTO_ID.search(element_id):
        return f'[id="{_quote(element_id)}"]'
    name = raw.get("name") or ""
    if name:
        role = _PLAYWRIGHT_ROLE.get(raw["role"], raw["role"])
        return f'role={role}[name="{_quote(name)}"]'
    return raw.get("css") or raw.get("tag") or "*"


def to_element(raw: dict, frame_index: int, offset: tuple[float, float]) -> Element:
    x, y, w, h = raw["bbox"]
    ox, oy = offset
    return Element(
        index=raw["index"],
        role=raw["role"],
        name=raw.get("name") or "",
        input_type=raw.get("input_type") or None,
        value=raw.get("value"),
        bbox=(x + ox, y + oy, w, h),
        selector=build_selector(raw),
        href=raw.get("href") or None,
        context=raw.get("context") or "",
        frame=frame_index,
    )
