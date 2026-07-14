"""Shared Playwright locator generation for script and page-object generators."""
from models.schemas import ElementLocator


def _esc(s: str) -> str:
    """Escape value for safe use inside Playwright string literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def generate_playwright_locator(locator: ElementLocator) -> str:
    """Convert ElementLocator to Playwright locator code string."""
    if locator.test_id:
        return f'page.get_by_test_id("{_esc(locator.test_id)}")'
    if locator.label:
        return f'page.get_by_label("{_esc(locator.label)}")'
    if locator.placeholder:
        return f'page.get_by_placeholder("{_esc(locator.placeholder)}")'
    if locator.role and locator.name:
        return f'page.get_by_role("{_esc(locator.role)}", name="{_esc(locator.name)}")'
    if locator.text:
        return f'page.get_by_text("{_esc(locator.text)}")'
    if locator.css:
        return f'page.locator("{_esc(locator.css)}")'
    if locator.xpath:
        return f'page.locator("xpath={_esc(locator.xpath)}")'
    return 'page.locator("body")'


def is_password_field(locator: ElementLocator) -> bool:
    """Check if this locator targets a password input."""
    if not locator:
        return False
    keywords = ["password", "pass", "pwd", "密码"]
    combined = (locator.name or "") + " " + (locator.label or "") + " " + (locator.placeholder or "") + " " + (locator.selector or "")
    return any(kw in combined.lower() for kw in keywords)
