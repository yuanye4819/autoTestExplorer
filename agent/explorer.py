"""
Web 探索器 — 基于 Playwright 执行页面操作，驱动探索流程
"""
from __future__ import annotations

import asyncio
import base64
import time
from typing import Optional, Callable

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config import settings
from models.schemas import (
    ExploreStep, StepAction, StepStatus, ElementLocator,
    ExplorationTask, PageSnapshot,
)
from agent.analyzer import analyze_page, build_locator, find_login_form


class WebExplorer:
    """
    Web 探索器：管理浏览器生命周期，执行页面操作，收集页面快照。
    每一步操作都记录为 ExploreStep。
    """

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._on_step: Optional[Callable] = None     # 步骤回调 (用于 WebSocket 推送)
        self._on_log: Optional[Callable] = None
        self._current_screenshot: Optional[str] = None
        self._steps: list[ExploreStep] = []
        self._captcha_needed: bool = False

    async def start(self):
        """启动浏览器"""
        pw = await async_playwright().start()
        self._pw = pw
        self.browser = await pw.chromium.launch(
            headless=settings.BROWSER_HEADLESS,
            slow_mo=settings.BROWSER_SLOW_MO,
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(settings.BROWSER_TIMEOUT)

    async def stop(self):
        """Close browser - log errors per step instead of swallowing"""
        import logging
        _log = logging.getLogger("autotest")
        if self.context:
            try:
                await self.context.close()
            except Exception as e:
                _log.warning(f"Error closing browser context: {e}")
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                _log.warning(f"Error closing browser: {e}")
        if hasattr(self, "_pw") and self._pw:
            try:
                await self._pw.stop()
            except Exception as e:
                _log.warning(f"Error stopping playwright: {e}")

    def on_step(self, callback: Callable):
        """设置步骤回调"""
        self._on_step = callback

    def on_log(self, callback: Callable):
        """设置日志回调"""
        self._on_log = callback

    async def _log(self, message: str):
        if self._on_log:
            await self._on_log(message)

    async def _emit_step(self, step: ExploreStep):
        self._steps.append(step)
        if self._on_step:
            await self._on_step(step)

    async def take_screenshot(self) -> str:
        """截取当前页面并返回 base64"""
        if self.page:
            data = await self.page.screenshot(type="png", full_page=False)
            self._current_screenshot = base64.b64encode(data).decode()
            return self._current_screenshot
        return ""

    # ── 核心操作 ────────────────────────────────────

    async def navigate(self, url: str, description: str = "") -> ExploreStep:
        """导航到指定 URL"""
        start = time.time()
        step = ExploreStep(index=len(self._steps), action=StepAction.NAVIGATE,
                           description=description or f"导航到 {url}", value=url)
        step.status = StepStatus.RUNNING
        await self._emit_step(step)

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # 等待动态内容
            step.status = StepStatus.SUCCESS
            await self._log(f"✓ 成功导航到 {url}")
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            await self._log(f"✗ 导航失败: {e}")

        step.duration_ms = int((time.time() - start) * 1000)
        step.screenshot_b64 = await self.take_screenshot()
        await self._emit_step(step)
        return step

    async def click_element(self, locator: ElementLocator, description: str = "") -> ExploreStep:
        """点击元素"""
        start = time.time()
        step = ExploreStep(index=len(self._steps), action=StepAction.CLICK,
                           description=description or f"点击 {locator.selector}",
                           locator=locator)
        step.status = StepStatus.RUNNING
        await self._emit_step(step)

        try:
            element = await self._find_element(locator)
            await element.click()
            await asyncio.sleep(1)
            step.status = StepStatus.SUCCESS
            await self._log(f"✓ 点击成功: {locator.selector}")
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            await self._log(f"✗ 点击失败: {e}")

        step.duration_ms = int((time.time() - start) * 1000)
        step.screenshot_b64 = await self.take_screenshot()
        await self._emit_step(step)
        return step

    async def fill_input(self, locator: ElementLocator, value: str, description: str = "") -> ExploreStep:
        """在输入框/下拉框中填入内容，自动识别 select 元素"""
        start = time.time()
        step = ExploreStep(index=len(self._steps), action=StepAction.FILL,
                           description=description or f"在 {locator.selector} 输入 '{value}'",
                           locator=locator, value=value)
        step.status = StepStatus.RUNNING
        await self._emit_step(step)

        try:
            element = await self._find_element(locator)
            tag = await element.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                step.action = StepAction.SELECT
                step.description = description or f"在 {locator.selector} 选择 '{value}'"
                await element.select_option(value)
                await self._log(f"✓ 选择成功(自动检测): {locator.selector} ← '{value}'")
            else:
                await element.fill(value)
                await self._log(f"✓ 输入成功: {locator.selector} ← '{value}'")
            step.status = StepStatus.SUCCESS
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            await self._log(f"✗ 操作失败: {e}")

        step.duration_ms = int((time.time() - start) * 1000)
        step.screenshot_b64 = await self.take_screenshot()
        await self._emit_step(step)
        return step

    async def select_option(self, locator: ElementLocator, value: str, description: str = "") -> ExploreStep:
        """在下拉框中选中选项"""
        start = time.time()
        step = ExploreStep(index=len(self._steps), action=StepAction.SELECT,
                           description=description or f"在 {locator.selector} 选择 '{value}'",
                           locator=locator, value=value)
        step.status = StepStatus.RUNNING
        await self._emit_step(step)

        try:
            element = await self._find_element(locator)
            await element.select_option(value)
            step.status = StepStatus.SUCCESS
            await self._log(f"✓ 选择成功: {locator.selector} ← '{value}'")
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            await self._log(f"✗ 选择失败: {e}")

        step.duration_ms = int((time.time() - start) * 1000)
        step.screenshot_b64 = await self.take_screenshot()
        await self._emit_step(step)
        return step

    async def assert_visible(self, locator: ElementLocator, description: str = "") -> ExploreStep:
        """断言元素可见"""
        start = time.time()
        step = ExploreStep(index=len(self._steps), action=StepAction.ASSERT_VISIBLE,
                           description=description or f"验证 {locator.selector} 可见",
                           locator=locator)
        step.status = StepStatus.RUNNING
        await self._emit_step(step)

        try:
            element = await self._find_element(locator)
            visible = await element.is_visible()
            if visible:
                step.status = StepStatus.SUCCESS
                await self._log(f"✓ 验证通过: {locator.selector} 可见")
            else:
                step.status = StepStatus.FAILED
                step.error = "元素不可见"
                await self._log(f"✗ 验证失败: {locator.selector} 不可见")
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            await self._log(f"✗ 验证失败: {e}")

        step.duration_ms = int((time.time() - start) * 1000)
        step.screenshot_b64 = await self.take_screenshot()
        await self._emit_step(step)
        return step

    async def assert_text(self, text: str, description: str = "") -> ExploreStep:
        """断言页面包含指定文本"""
        start = time.time()
        step = ExploreStep(index=len(self._steps), action=StepAction.ASSERT_TEXT,
                           description=description or f"验证页面包含 '{text}'",
                           value=text)
        step.status = StepStatus.RUNNING
        await self._emit_step(step)

        try:
            content = await self.page.content()
            if text in content:
                step.status = StepStatus.SUCCESS
                await self._log(f"✓ 验证通过: 页面包含 '{text}'")
            else:
                step.status = StepStatus.FAILED
                step.error = f"页面不包含文本: {text}"
                await self._log(f"✗ 验证失败: 页面不包含 '{text}'")
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)

        step.duration_ms = int((time.time() - start) * 1000)
        step.screenshot_b64 = await self.take_screenshot()
        await self._emit_step(step)
        return step

    async def get_snapshot(self) -> PageSnapshot:
        """获取当前页面快照"""
        snapshot = await analyze_page(self.page)
        snapshot.screenshot_b64 = await self.take_screenshot()
        return snapshot

    async def try_auto_login(self, username: str, password: str) -> bool:
        """
        尝试自动登录：检测登录表单并填入凭据
        返回 True 如果成功识别并提交了登录表单
        """
        snapshot = await self.get_snapshot()
        elements = snapshot.interactive_elements
        login_form = find_login_form(elements)

        if not login_form:
            await self._log("ℹ 未检测到登录表单，跳过自动登录")
            return False

        await self._log("🔍 检测到登录表单，尝试自动登录...")

        uf = login_form["username_field"]
        pf = login_form["password_field"]
        sb = login_form["submit_button"]

        try:
            # 填入用户名
            uloc = build_locator(uf)
            await self.fill_input(uloc, username, f"填入用户名 '{username}'")

            # 填入密码
            ploc = build_locator(pf)
            await self.fill_input(ploc, password, "填入密码")

            # CAPTCHA check
            captcha = await self.detect_captcha()
            if captcha is not None:
                await self._log("CAPTCHA detected, trying OCR...")
                captcha_text = ""
                if captcha:
                    captcha_text = await self.solve_captcha_ocr(captcha)
                if captcha_text:
                    await self.fill_captcha(captcha_text)
                    await self._log("OCR solved: " + captcha_text)
                else:
                    await self._log("OCR failed, manual input needed")
                    self._captcha_needed = True
                    return False

            # 点击登录
            if sb:
                bloc = build_locator(sb)
                await self.click_element(bloc, "点击登录按钮")

            await asyncio.sleep(2)
            await self._log("✓ 自动登录完成")
            return True
        except Exception as e:
            await self._log(f"✗ 自动登录失败: {e}")
            return False

    # ── 验证码处理 ─────────────────────────────────

    async def detect_captcha(self) -> str | None:
        """检测页面上是否存在验证码输入框，返回验证码图片的 base64 或 None"""
        captcha_keywords = ["captcha", "验证码", "verification code", "vercode", "code"]
        snapshot = await self.get_snapshot()
        for el in snapshot.interactive_elements:
            combined = (el.get("name", "") + el.get("label", "") + el.get("placeholder", "") + el.get("id", "")).lower()
            if any(kw in combined for kw in captcha_keywords):
                # Found a captcha input — try to find the captcha image nearby
                try:
                    # Look for img elements near the captcha input
                    img = await self.page.locator('img[src*="captcha"], img[src*="code"], img[src*="verify"]').first
                    if await img.count() > 0:
                        return await img.screenshot(type="png")
                except Exception:
                    pass
                # Fallback: return empty string (captcha exists but no image found)
                return ""
        return None

    async def solve_captcha_ocr(self, image_b64: str) -> str:
        """Try OCR via Tesseract, fallback to AI."""
        try:
            import pytesseract
            from PIL import Image
            import io, base64
            img_data = base64.b64decode(image_b64)
            import os as _os
            if _os.path.exists(r"D:\Tesseract-OCR\tesseract.exe"):
                pytesseract.pytesseract.tesseract_cmd = r"D:\Tesseract-OCR\tesseract.exe"
            img = Image.open(io.BytesIO(img_data))
            text = pytesseract.image_to_string(
                img, config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
            ).strip()
            if text:
                return text
        except Exception:
            pass
        # AI fallback
        try:
            from services.ai_client import call_ai
            text = call_ai(
                prompt="Read this CAPTCHA text, return only the characters",
                system="You are OCR. Output only the text.", max_tokens=20, timeout=10)
            return text.strip() if text else ""
        except Exception:
            return ""

    async def fill_captcha(self, value: str) -> bool:
        """Fill the detected captcha input with the given value."""
        snapshot = await self.get_snapshot()
        captcha_keywords = ["captcha", "验证码", "vercode"]
        for el in snapshot.interactive_elements:
            combined = (el.get("name", "") + el.get("label", "") + el.get("placeholder", "") + el.get("id", "")).lower()
            if any(kw in combined for kw in captcha_keywords):
                loc = build_locator(el)
                await self.fill_input(loc, value, f"输入验证码 '{value}'")
                return True
        return False

    # ── 内部方法 ────────────────────────────────────

    async def _find_element(self, locator: ElementLocator):
        """根据定位器查找元素，按优先级尝试多种策略"""
        strategies = []

        if locator.test_id:
            strategies.append(self.page.get_by_test_id(locator.test_id))
        if locator.label:
            strategies.append(self.page.get_by_label(locator.label))
        if locator.placeholder:
            strategies.append(self.page.get_by_placeholder(locator.placeholder))
        if locator.role and locator.name:
            strategies.append(self.page.get_by_role(locator.role, name=locator.name))
        if locator.text:
            strategies.append(self.page.get_by_text(locator.text))
        if locator.css:
            strategies.append(self.page.locator(locator.css))
        if locator.xpath:
            strategies.append(self.page.locator(f"xpath={locator.xpath}"))

        # 逐个尝试
        last_error = None
        for element in strategies:
            try:
                count = await element.count()
                if count > 0:
                    return element.first
            except Exception as e:
                last_error = e
                continue

        raise Exception(f"未找到元素: {locator.selector} — {last_error}")

    @property
    def steps(self) -> list[ExploreStep]:
        return self._steps
