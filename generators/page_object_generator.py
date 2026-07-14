"""
Page Object 代码生成器 — 根据探索过程中收集的元素定位信息生成 Page Object 类
"""
from __future__ import annotations

from models.schemas import ExploreStep, StepAction, ElementLocator


from generators._locator_utils import generate_playwright_locator

def _generate_method_name(action: StepAction, description: str, locator: ElementLocator = None) -> str:
    """生成语义化的方法名"""
    import re

    if locator and locator.name:
        base = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', locator.name[:30]).strip('_').lower()
        if base:
            if action == StepAction.CLICK:
                return f"click_{base}"
            elif action == StepAction.FILL:
                return f"fill_{base}"
            elif action == StepAction.ASSERT_VISIBLE:
                return f"verify_{base}_visible"

    # 回退：从描述生成
    desc_clean = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', description[:30]).strip('_').lower()
    return desc_clean or f"action_{action.value}"


def generate_page_object(steps: list[ExploreStep], page_name: str = "BasePage") -> str:
    """
    根据探索步骤生成 Page Object 类。
    收集所有唯一元素定位器，生成属性，并生成对应的操作方法。
    """
    # 收集所有唯一的定位器
    seen_selectors = set()
    unique_elements: list[tuple[str, ElementLocator, StepAction]] = []

    for step in steps:
        if not step.locator or step.status.value == "failed":
            continue
        selector_key = step.locator.selector or step.locator.name or step.locator.label or ""
        if selector_key in seen_selectors:
            continue
        seen_selectors.add(selector_key)
        unique_elements.append((selector_key, step.locator, step.action))

    lines = []
    lines.append('"""')
    lines.append(f'Page Object: {page_name}')
    lines.append(f'由 AI Agent 自动生成')
    lines.append(f'包含 {len(unique_elements)} 个元素定位器')
    lines.append('"""')
    lines.append('')
    lines.append('from playwright.sync_api import Page, expect')
    lines.append('')
    lines.append('')
    lines.append(f'class {page_name}:')
    lines.append(f'    """自动生成的 Page Object 类"""')
    lines.append('')

    # 构造函数
    lines.append(f'    def __init__(self, page: Page):')
    lines.append(f'        self.page = page')
    lines.append('')

    # 元素定位器作为属性
    element_props = []
    for key, loc, action in unique_elements:
        prop_name = _generate_method_name(action, key, loc)
        # 避免以数字开头
        if prop_name and prop_name[0].isdigit():
            prop_name = "el_" + prop_name
        # 避免重复属性名
        count = 1
        original = prop_name
        while prop_name in element_props:
            prop_name = f"{original}_{count}"
            count += 1
        element_props.append(prop_name)

        loc_code = generate_playwright_locator(loc)
        lines.append(f'    @property')
        lines.append(f'    def {prop_name}(self):')
        comment = loc.name or loc.label or loc.placeholder or loc.selector
        if comment:
            lines.append(f'        """{comment}"""')
        lines.append(f'        return {loc_code}')
        lines.append('')

    # 操作方法
    for key, loc, action in unique_elements:
        prop_name = _generate_method_name(action, key, loc)
        if prop_name and prop_name[0].isdigit():
            prop_name = "el_" + prop_name

        if action == StepAction.FILL:
            lines.append(f'    def {prop_name}(self, value: str):')
            comment = loc.name or loc.label or "输入框"
            lines.append(f'        """在 {comment} 中输入文本"""')
            lines.append(f'        self.{prop_name}.fill(value)')
            lines.append('')
        elif action == StepAction.CLICK:
            lines.append(f'    def {prop_name}(self):')
            comment = loc.name or loc.label or "按钮"
            lines.append(f'        """点击 {comment}"""')
            lines.append(f'        self.{prop_name}.click()')
            lines.append('')
        elif action in (StepAction.ASSERT_VISIBLE,):
            lines.append(f'    def {prop_name}(self):')
            comment = loc.name or loc.label or "元素"
            lines.append(f'        """验证 {comment} 可见"""')
            lines.append(f'        expect(self.{prop_name}).to_be_visible()')
            lines.append('')

    return '\n'.join(lines)
