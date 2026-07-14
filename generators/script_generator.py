"""
自动化测试脚本生成器 — 将探索步骤转换为可执行的 Playwright Python 测试脚本
"""
from __future__ import annotations

import re
from datetime import datetime

from models.schemas import ExploreStep, StepAction, ElementLocator, ExplorationTask


def _generate_playwright_locator(locator: ElementLocator) -> str:
    """将 ElementLocator 转换为 Playwright 定位代码"""
    if locator.test_id:
        return f'page.get_by_test_id("{locator.test_id}")'
    if locator.label:
        return f'page.get_by_label("{locator.label}")'
    if locator.placeholder:
        return f'page.get_by_placeholder("{locator.placeholder}")'
    if locator.role and locator.name:
        return f'page.get_by_role("{locator.role}", name="{locator.name}")'
    if locator.text:
        return f'page.get_by_text("{locator.text}")'
    if locator.css:
        return f'page.locator("{locator.css}")'
    if locator.xpath:
        return f'page.locator("xpath={locator.xpath}")'
    return 'page.locator("body")'


def _is_password_field(step: ExploreStep) -> bool:
    if not step.locator:
        return False
    keywords = ["password", "pass", "pwd", "密码"]
    combined = (step.locator.name or "") + " " + (step.locator.label or "") + " " + (step.locator.placeholder or "") + " " + (step.locator.selector or "")
    combined = combined.lower()
    return any(kw in combined for kw in keywords)


def _escape_py_string(s: str) -> str:
    """转义 Python 字符串中的特殊字符"""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _step_to_pytest_code(step: ExploreStep, indent: str = "    ") -> list[str]:
    """
    将单个探索步骤转换为 pytest 代码行列表
    """
    lines = []
    action = step.action
    desc = _escape_py_string(step.description or "")

    if step.status.value == "failed":
        lines.append(f"{indent}# [失败] {desc}")
        return lines

    lines.append(f"{indent}# {desc}")

    if action == StepAction.NAVIGATE:
        url = step.value or ""
        lines.append(f'{indent}page.goto("{url}", wait_until="domcontentloaded", timeout=30000)')
        lines.append(f'{indent}page.wait_for_load_state("networkidle", timeout=15000)')
        lines.append(f'{indent}page.wait_for_timeout(1000)')

    elif action == StepAction.CLICK:
        if step.locator:
            loc_code = _generate_playwright_locator(step.locator)
            lines.append(f"{indent}{loc_code}.wait_for(state='visible', timeout=10000)")
            lines.append(f"{indent}{loc_code}.click()")

    elif action == StepAction.FILL:
        if step.locator:
            loc_code = _generate_playwright_locator(step.locator)
            lines.append(f"{indent}{loc_code}.wait_for(state='visible', timeout=10000)")
            value = _escape_py_string(step.value or "")
            # 密码字段脱敏：生成环境变量引用
            if _is_password_field(step):
                lines.append(f'{indent}{loc_code}.fill(os.environ.get("TEST_PASSWORD", ""))')
                lines.append(f"{indent}# 密码字段 — 请设置环境变量 TEST_PASSWORD")
            else:
                lines.append(f'{indent}{loc_code}.fill("{value}")')

    elif action == StepAction.SELECT:
        if step.locator:
            loc_code = _generate_playwright_locator(step.locator)
            value = _escape_py_string(step.value or "")
            lines.append(f'{indent}{loc_code}.select_option("{value}")')

    elif action == StepAction.CHECK:
        if step.locator:
            loc_code = _generate_playwright_locator(step.locator)
            lines.append(f"{indent}{loc_code}.check()")

    elif action == StepAction.HOVER:
        if step.locator:
            loc_code = _generate_playwright_locator(step.locator)
            lines.append(f"{indent}{loc_code}.hover()")

    elif action == StepAction.ASSERT_VISIBLE:
        if step.locator:
            loc_code = _generate_playwright_locator(step.locator)
            lines.append(f"{indent}{loc_code}.wait_for(state='visible', timeout=10000)")
            lines.append(f"{indent}expect({loc_code}).to_be_visible()")

    elif action == StepAction.ASSERT_TEXT:
        text = _escape_py_string(step.value or desc)
        lines.append(f'{indent}expect(page.locator("body")).to_contain_text("{text}")')

    elif action == StepAction.ASSERT_URL:
        url = step.value or ""
        lines.append(f'{indent}expect(page).to_have_url("{url}")')

    elif action == StepAction.WAIT:
        lines.append(f"{indent}page.wait_for_timeout(3000)")

    elif action == StepAction.SCREENSHOT:
        name = re.sub(r'[^a-zA-Z0-9_]', '_', desc)[:40]
        lines.append(f'{indent}page.screenshot(path="screenshots/{name}.png")')

    return lines


def _group_steps_into_tests(steps: list[ExploreStep]) -> list[dict]:
    """
    将步骤按导航操作分组，每组生成一个测试函数
    """
    tests = []
    current = {"steps": [], "description": "自动生成的测试"}

    for step in steps:
        if step.status.value == "failed":
            continue

        if step.action == StepAction.NAVIGATE and current["steps"]:
            # 开始新的测试函数
            if current["steps"]:
                tests.append(current)
            current = {"steps": [], "description": step.description or "导航测试"}
            current["steps"].append(step)
        else:
            current["steps"].append(step)

    if current["steps"]:
        tests.append(current)

    # 合并空测试
    if not tests:
        tests.append({"steps": steps, "description": "页面探索测试"})

    return tests


def generate_test_script(task: ExplorationTask, steps: list[ExploreStep]) -> str:
    tests = _group_steps_into_tests(steps)
    total_ok = sum(1 for s in steps if s.status.value == "success")

    lines = []
    lines.append('"""')
    lines.append("AI Agent 自动生成的测试脚本")
    lines.append("目标网址: " + task.target_url)
    lines.append("测试要求: " + task.requirements)
    lines.append("步骤数: " + str(len(steps)) + "  |  成功: " + str(total_ok))
    lines.append("场景数: " + str(len(tests)))
    lines.append("")
    lines.append("运行方式:")
    lines.append("  pytest <file> -v")
    lines.append("  pytest <file> -v --headed  (有头模式)")
    lines.append('"""')
    lines.append("")
    lines.append("import os")
    lines.append("import pytest")
    lines.append("from playwright.sync_api import Page, expect")
    lines.append("")

    lines.append("# 配置")
    lines.append("")
    lines.append("@pytest.fixture(scope='session')")
    lines.append("def browser_context_args(browser_context_args):")
    lines.append("    return {**browser_context_args, 'viewport': {'width':1440,'height':900}, 'locale':'zh-CN'}")
    lines.append("")
    lines.append("@pytest.fixture(autouse=True)")
    lines.append("def _setup(page: Page):")
    lines.append("    page.set_default_timeout(15000)")
    lines.append("")

    lines.append("# 测试场景")
    lines.append("")

    for i, test_group in enumerate(tests):
        test_steps = test_group["steps"]
        desc = test_group["description"]
        func_name = re.sub(r'[^a-zA-Z0-9_]', '_', desc)[:50].strip('_').lower()
        if not func_name or func_name[0].isdigit():
            func_name = "test_scenario_" + str(i + 1)
        else:
            func_name = "test_" + func_name

        given_steps = [s for s in test_steps if s.action == StepAction.NAVIGATE]
        when_steps = [s for s in test_steps if s.action in (StepAction.CLICK, StepAction.FILL, StepAction.SELECT, StepAction.CHECK, StepAction.HOVER)]
        then_steps = [s for s in test_steps if s.action in (StepAction.ASSERT_VISIBLE, StepAction.ASSERT_TEXT, StepAction.ASSERT_URL)]

        lines.append("def " + func_name + "(page: Page):")
        lines.append('    """')
        lines.append("    " + desc)
        for s in given_steps:
            lines.append("    Given  " + (s.description or "")[:80])
        for s in when_steps:
            lines.append("    When   " + (s.description or "")[:80])
        for s in then_steps:
            lines.append("    Then   " + (s.description or "")[:80])
        lines.append('    """')

        for s in given_steps:
            lines.append("    # GIVEN")
            for cl in _step_to_pytest_code(s):
                lines.append(cl)
        if given_steps:
            lines.append("")

        for s in when_steps:
            lines.append("    # WHEN")
            for cl in _step_to_pytest_code(s):
                lines.append(cl)
        if when_steps:
            lines.append("")

        for s in then_steps:
            lines.append("    # THEN")
            for cl in _step_to_pytest_code(s):
                lines.append(cl)

        other_steps = [s for s in test_steps if s not in given_steps + when_steps + then_steps]
        for s in other_steps:
            for cl in _step_to_pytest_code(s):
                lines.append(cl)

        lines.append("")

    return chr(10).join(lines)
