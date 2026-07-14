"""
页面分析器 — 提取 DOM 结构、可交互元素、页面语义信息
"""
from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import Page

from models.schemas import ElementLocator, PageSnapshot


async def analyze_page(page: Page) -> PageSnapshot:
    """
    分析当前页面，提取完整的结构快照：
    - URL / 标题
    - 所有可交互元素（按钮、链接、输入框等）
    - 页面可见文本摘要
    """
    url = page.url
    title = await page.title()

    # 提取可交互元素
    elements = await page.evaluate("""() => {
        const interactiveSelectors = [
            'button', 'a[href]', 'input', 'textarea', 'select',
            '[role="button"]', '[role="link"]', '[role="textbox"]',
            '[role="checkbox"]', '[role="combobox"]', '[role="radio"]',
            '[onclick]', '[tabindex]:not([tabindex="-1"])',
            'label', 'form'
        ];

        const seen = new Set();
        const results = [];

        // Helper: get semantic parent path
        function getParentPath(el) {
            const parts = [];
            let cur = el.parentElement;
            while (cur && cur !== document.body && parts.length < 4) {
                const t = cur.tagName.toLowerCase();
                const id = cur.id ? '#' + cur.id : '';
                const cls = cur.className && typeof cur.className === 'string'
                    ? '.' + cur.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
                if (['form','section','nav','header','main','footer','article','aside','div','fieldset'].includes(t)) {
                    parts.unshift(t + id + cls);
                }
                cur = cur.parentElement;
            }
            return parts.join(' > ') || 'body';
        }

        // Helper: find containing section
        function getSection(el) {
            const s = el.closest('section,nav,header,main,footer,article,aside,[role="region"],[role="navigation"]');
            if (s) {
                const label = s.getAttribute('aria-label') || s.getAttribute('aria-labelledby')
                    || (s.querySelector('h1,h2,h3,h4')?.textContent?.trim())
                    || s.id || s.className?.split(/\\s+/)[0] || s.tagName.toLowerCase();
                return label.substring(0, 40);
            }
            return '';
        }

        for (const sel of interactiveSelectors) {
            document.querySelectorAll(sel).forEach((el, idx) => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                const style = window.getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none') return;

                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') || (
                    tag === 'button' ? 'button' :
                    tag === 'a' ? 'link' :
                    (tag === 'input' && el.type === 'checkbox') ? 'checkbox' :
                    (tag === 'input' && (el.type === 'text' || el.type === 'password' || el.type === 'email')) ? 'textbox' :
                    tag === 'textarea' ? 'textbox' :
                    tag === 'select' ? 'combobox' : ''
                );
                const name = el.getAttribute('aria-label') || el.getAttribute('title') ||
                    el.textContent?.trim().substring(0, 80) || '';
                const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || el.getAttribute('data-action') || '';

                let dataAttr = '';
                if (!testId && el.attributes) {
                    for (const attr of el.attributes) {
                        if (attr.name.startsWith('data-') && attr.name !== 'data-testid' && attr.name !== 'data-test') {
                            dataAttr = attr.name + '=' + attr.value;
                            break;
                        }
                    }
                }

                // Label detection (improved: also check aria-labelledby)
                let labelText = '';
                const labelledBy = el.getAttribute('aria-labelledby');
                if (labelledBy) {
                    const lbl = document.getElementById(labelledBy);
                    if (lbl) labelText = lbl.textContent.trim();
                }
                if (!labelText && el.id) {
                    const label = document.querySelector('label[for="' + el.id + '"]');
                    if (label) labelText = label.textContent.trim();
                }
                if (!labelText && el.closest('label')) {
                    labelText = el.closest('label').textContent.replace(el.textContent || '', '').trim();
                }
                if (!labelText && (tag === 'input' || tag === 'textarea' || tag === 'select')) {
                    const parentLabel = el.parentElement?.closest('label');
                    if (parentLabel) labelText = parentLabel.textContent.replace(el.textContent || '', '').trim();
                }

                const placeholder = el.getAttribute('placeholder') || '';
                const cssClass = (el.className && typeof el.className === 'string') ? el.className : '';
                const elId = el.id || '';
                const href = el.getAttribute('href') || '';
                const inputType = el.getAttribute('type') || '';
                const value = (tag === 'input' || tag === 'textarea') ? (el.value || '') : (tag === 'select' ? (el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '') : '');
                const required = el.hasAttribute('required') || el.getAttribute('aria-required') === 'true';
                const disabled = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true';
                const parentPath = getParentPath(el);
                const section = getSection(el);

                const uid = tag + '|' + name.substring(0, 30) + '|' + elId + '|' + idx;
                if (seen.has(uid)) return;
                seen.add(uid);

                results.push({
                    tag, role, name, label: labelText, placeholder,
                    id: elId, css: cssClass, href, type: inputType,
                    testId, dataAttr, value,
                    visible: true, required, disabled,
                    parentPath, section,
                });
            });
        }
        return results.slice(0, 100);
    }""")

    # 提取页面可见文本
    body_text = await page.evaluate("""() => {
        const body = document.body;
        if (!body) return '';
        return body.innerText?.substring(0, 3000) || '';
    }""")

    snapshot = PageSnapshot(
        url=url,
        title=title,
        interactive_elements=elements,
        body_text=body_text,
    )
    return snapshot


def build_locator(element: dict) -> ElementLocator:
    """
    优先级: data-* > id > label > placeholder > role+name > text > css
    """
    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    loc = ElementLocator(strategy="auto")
    tag = element.get("tag", "")
    el_id = element.get("id", "")
    css_class = element.get("css", "")
    name = element.get("name", "").strip()
    role = element.get("role", "")
    label = element.get("label", "").strip()
    placeholder = element.get("placeholder", "").strip()
    test_id = element.get("testId", "").strip()
    data_attr = element.get("dataAttr", "").strip()

    if test_id:
        loc.strategy = "testid"
        loc.test_id = test_id
        loc.selector = '[data-testid="' + _esc(test_id) + '"]'
    elif data_attr:
        loc.strategy = "css"
        loc.css = "[" + data_attr + "]"
        loc.selector = "[" + data_attr + "]"
    elif el_id:
        loc.strategy = "css"
        loc.css = "#" + _esc(el_id)
        loc.selector = "#" + _esc(el_id)
    elif label:
        loc.strategy = "label"
        loc.label = label
        loc.selector = 'getByLabel("' + _esc(label) + '")'
    elif placeholder:
        loc.strategy = "placeholder"
        loc.placeholder = placeholder
        loc.selector = 'getByPlaceholder("' + _esc(placeholder) + '")'
    elif role and name:
        loc.strategy = "role"
        loc.role = role
        loc.name = name
        loc.selector = 'getByRole("' + _esc(role) + '", name="' + _esc(name) + '")'
    elif name:
        loc.strategy = "text"
        loc.text = name[:60]
        loc.selector = 'getByText("' + _esc(name[:60]) + '")'
    else:
        css = tag
        if css_class:
            css += "." + ".".join(css_class.split()[:2])
        loc.strategy = "css"
        loc.css = css
        loc.selector = css

    return loc

def find_login_form(elements: list[dict]) -> Optional[dict]:
    """
    在元素列表中识别登录表单，返回 {username_field, password_field, submit_button}
    """
    inputs = [e for e in elements if e["tag"] in ("input", "textarea")]
    buttons = [e for e in elements if e["tag"] == "button" or e["role"] == "button"]

    username_field = None
    password_field = None
    submit_button = None

    for inp in inputs:
        input_type = inp.get("type", "")
        name_lower = inp.get("name", "").lower()
        label_lower = inp.get("label", "").lower()
        placeholder_lower = inp.get("placeholder", "").lower()
        combined = f"{name_lower} {label_lower} {placeholder_lower} {input_type}"

        if not username_field and any(kw in combined for kw in ("user", "username", "email", "account", "登录", "用户名", "账号", "邮箱")):
            username_field = inp
        if not password_field and any(kw in combined for kw in ("password", "pass", "pwd", "密码")):
            password_field = inp

    for btn in buttons:
        btn_name = btn.get("name", "").lower()
        if any(kw in btn_name for kw in ("login", "sign in", "log in", "登录", "登入", "submit", "提交")):
            submit_button = btn
            break

    if not submit_button and buttons:
        # 取表单中最后一个 button
        submit_button = buttons[-1]

    if username_field and password_field:
        return {
            "username_field": username_field,
            "password_field": password_field,
            "submit_button": submit_button,
        }
    return None
