"""
BDD Feature 文件生成器 — 将探索步骤转换为 Gherkin 格式
"""
from __future__ import annotations

import re
from datetime import datetime

from models.schemas import ExploreStep, StepAction, ExplorationTask


def _sanitize_name(text: str) -> str:
    """将文本转换为合法的 Gherkin 名称"""
    # 移除特殊字符，保留中英文和数字
    cleaned = re.sub(r'[^\w\u4e00-\u9fff\s]', '', text)
    return cleaned.strip()[:80]


def _extract_scenario_name(steps: list[ExploreStep], requirements: str) -> str:
    """从需求和步骤中提取有意义的 Scenario 名称"""
    if requirements:
        return _sanitize_name(requirements)[:60]
    # 取第一步的描述作为场景名
    for s in steps:
        if s.description:
            name = s.description.replace("导航到", "").replace("打开", "").strip()
            return f"探索 {name}"[:60]
    return "自动探索场景"


def _steps_to_scenarios(steps: list[ExploreStep]) -> list[dict]:
    """
    将探索步骤分组为 BDD Scenario 列表。
    每个 Scenario 有 name、given、when、then 列表。
    """
    scenarios = []
    current = {"name": "", "given": [], "when": [], "then": []}
    last_was_navigation = False

    for step in steps:
        if step.status.value == "failed":
            continue

        action = step.action
        desc = step.description or ""

        # 导航操作 → 新的 Given 或新 Scenario 的开始
        if action == StepAction.NAVIGATE:
            if current["when"] or current["then"]:
                # 保存当前场景
                if current["when"]:
                    scenarios.append(current)
                current = {"name": "", "given": [], "when": [], "then": []}
            url = step.value or ""
            current["given"].append(f'打开页面 "{url}"')
            current["name"] = current["name"] or _sanitize_name(desc)
            last_was_navigation = True
            continue

        # 输入操作 → When
        if action in (StepAction.FILL, StepAction.SELECT, StepAction.CHECK):
            what = desc
            if step.locator:
                if step.locator.label:
                    what = f'在 "{step.locator.label}" 输入'
                elif step.locator.placeholder:
                    what = f'在 "{step.locator.placeholder}" 输入'
            if step.value:
                val = step.value
                # 密码字段脱敏
                if "password" in what.lower() or "密码" in what:
                    val = "***"
                what += f' "{val}"'
            current["when"].append(what)

        # 点击操作 → When
        elif action == StepAction.CLICK:
            what = desc
            if step.locator:
                elem_name = step.locator.name or step.locator.label or step.locator.text or "元素"
                what = f'点击 "{elem_name}"'
            current["when"].append(what)

        # 断言操作 → Then
        elif action in (StepAction.ASSERT_VISIBLE, StepAction.ASSERT_TEXT, StepAction.ASSERT_URL):
            what = desc
            if action == StepAction.ASSERT_VISIBLE and step.locator:
                elem_name = step.locator.name or step.locator.label or step.locator.text or "目标元素"
                what = f'页面应显示 "{elem_name}"'
            elif action == StepAction.ASSERT_TEXT:
                what = f'页面应包含文本 "{step.value}"'
            current["then"].append(what)

        last_was_navigation = False

    # 保存最后一个场景
    if current["when"] or current["then"]:
        scenarios.append(current)

    # 如果没有场景，创建一个默认的
    if not scenarios:
        all_then = []
        for s in steps:
            if s.status.value == "success":
                all_then.append(s.description)
        scenarios.append({
            "name": "页面可用性验证",
            "given": ["打开目标页面"],
            "when": ["访问页面"],
            "then": all_then[:5] or ["页面成功加载"],
        })

    return scenarios


def generate_feature_file(task: ExplorationTask, steps: list[ExploreStep]) -> str:
    """
    根据探索任务和步骤生成 BDD Feature 文件 (Gherkin 格式)
    """
    feature_name = _sanitize_name(task.requirements) if task.requirements else "Web 应用自动探索测试"
    scenarios = _steps_to_scenarios(steps)

    lines = []
    lines.append(f"# 由 AI Agent 自动生成的 BDD Feature 文件")
    lines.append(f"# 目标 URL: {task.target_url}")
    lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# 探索步骤数: {len(steps)}")
    lines.append("")
    lines.append(f"Feature: {feature_name}")
    lines.append("")
    lines.append(f"  作为测试工程师")
    lines.append(f"  我希望验证 Web 应用的核心功能")
    lines.append(f"  以确保应用按预期工作")
    lines.append("")

    for i, scenario in enumerate(scenarios):
        name = scenario["name"] or f"场景 {i+1}"
        lines.append(f"  Scenario: {name}")

        for g in scenario["given"]:
            lines.append(f"    Given {g}")

        for w in scenario["when"]:
            lines.append(f"    When {w}")

        for t in scenario["then"]:
            lines.append(f"    Then {t}")

        lines.append("")

    return "\n".join(lines)
