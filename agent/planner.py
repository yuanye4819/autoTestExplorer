"""
Agent 规划器 — 基于页面分析结果决定下一步操作
支持启发式探索 + DeepSeek/OpenAI 兼容 API 推理增强
"""
from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from config import settings
from models.schemas import ExploreStep, StepAction, ElementLocator, PageSnapshot
from agent.analyzer import build_locator


class ActionPlan:
    """单步操作计划"""
    def __init__(
        self,
        action: StepAction,
        description: str,
        reasoning: str,
        locator: Optional[ElementLocator] = None,
        value: Optional[str] = None,
    ):
        self.action = action
        self.description = description
        self.reasoning = reasoning
        self.locator = locator
        self.value = value


class AgentPlanner:
    """智能规划器：启发式 + DeepSeek AI 双模式"""

    def __init__(self):
        self._explored_urls: set[str] = set()
        self._action_history: list[str] = []
        self._visited_pages: dict[str, int] = {}  # URL -> remaining link count
        self._ai_available: bool | None = None  # None = 未检测
        self._last_error: str = ""

    def reset(self):
        self._explored_urls.clear()
        self._action_history.clear()
        self._visited_pages.clear()

    @property
    def ai_status(self) -> str:
        """返回 AI 状态描述"""
        if self._ai_available is None:
            return "未检测"
        if self._ai_available:
            return f"已连接 ({settings.AI_MODEL})"
        return f"未连接 — {self._last_error or '未配置 API Key'}"

    def configure_ai(self, api_key: str, api_base: str = "", model: str = ""):
        """运行时更新 AI 配置（用于桌面应用动态配置）"""
        if api_key:
            settings.AI_API_KEY = api_key
        if api_base:
            settings.AI_API_BASE = api_base
        if model:
            settings.AI_MODEL = model
        self._ai_available = None  # 重新检测

    async def plan_next_action(
        self,
        snapshot: PageSnapshot,
        task_requirements: str,
        previous_steps: list[ExploreStep],
        step_index: int,
        max_steps: int,
    ) -> ActionPlan:
        """优先 AI 推理，不可用则回退启发式"""
        elements = snapshot.interactive_elements

        if settings.AI_API_KEY:
            try:
                plan = await self._ai_plan(snapshot, task_requirements, previous_steps, step_index, max_steps)
                self._ai_available = True
                return plan
            except Exception as e:
                self._last_error = str(e)[:100]
                self._ai_available = False

        return self._heuristic_plan(snapshot, task_requirements, previous_steps, step_index, max_steps, elements)

    # ── 启发式策略 ──────────────────────────────

    def _heuristic_plan(
        self, snapshot: PageSnapshot, task_requirements: str,
        previous_steps: list[ExploreStep], step_index: int, max_steps: int,
        elements: list[dict],
    ) -> ActionPlan:
        require_lower = task_requirements.lower()
        current_url = snapshot.url

        # Track page visit
        total_links = sum(1 for e in elements if e["tag"] == "a" and e.get("href"))
        self._visited_pages[current_url] = total_links

        # Phase 1: Form discovery (first 3 steps only)
        if step_index <= 2:
            forms = [e for e in elements if e["tag"] in ("input", "textarea", "select", "form")]
            if forms and any(kw in require_lower for kw in ("login", "sign", "register", "login", "form", "submit")):
                first_input = forms[0]
                loc = build_locator(first_input)
                action = StepAction.SELECT if first_input.get("tag") == "select" else StepAction.FILL
                return ActionPlan(
                    action=action, description="fill form field" if action == StepAction.FILL else "select dropdown",
                    reasoning="form detected, prioritize form interaction", locator=loc, value="test",
                )

        # Phase 2: Explore interactive elements on current page
        buttons = [e for e in elements if e["role"] in ("button", "link") or e["tag"] in ("button", "a")]
        buttons.sort(key=lambda b: len(b.get("name", "") or ""), reverse=True)

        unexplored_btns = []
        unexplored_links = []
        for btn in buttons:
            name = btn.get("name", "") or btn.get("href", "")[:60]
            if not name:
                continue
            action_key = "click:" + name
            if action_key in self._action_history:
                continue
            dangerous = ("delete", "remove", "logout", "sign out")
            if any(d in name.lower() for d in dangerous):
                continue
            if btn["tag"] == "a" and btn.get("href"):
                unexplored_links.append((btn, action_key))
            else:
                unexplored_btns.append((btn, action_key))

        # Prioritize links to new pages (deeper exploration)
        if unexplored_links and step_index < max_steps * 0.8:
            btn, key = unexplored_links[0]
            href = btn.get("href", "")
            if href not in self._explored_urls:
                self._explored_urls.add(href)
                self._action_history.append(key)
                name = btn.get("name", "") or href
                return ActionPlan(
                    action=StepAction.CLICK, description="navigate to: " + name[:60],
                    reasoning="exploring link to extend coverage: " + href[:50],
                    locator=build_locator(btn),
                )
            else:
                self._action_history.append(key)

        # Then click other buttons
        if unexplored_btns:
            btn, key = unexplored_btns[0]
            self._action_history.append(key)
            return ActionPlan(
                action=StepAction.CLICK, description="click: " + (btn.get("name", "") or "element")[:60],
                reasoning="exploring interactive button", locator=build_locator(btn),
            )

        # Phase 3: Verify if exploration is sufficient
        progress = step_index / max(max_steps, 1)
        if progress > 0.5:
            key_elements = [e for e in elements if e.get("name") and len(e["name"]) > 3]
            if key_elements:
                el = key_elements[0]
                return ActionPlan(
                    action=StepAction.ASSERT_VISIBLE,
                    description="verify: " + el["name"][:50] + " visible",
                    reasoning="validating key element after exploration",
                    locator=build_locator(el),
                )

        return ActionPlan(action=StepAction.WAIT, description="waiting for page", reasoning="no more elements to explore")

    # ── DeepSeek AI 推理 ─────────────────────────

    async def _ai_plan(
        self, snapshot: PageSnapshot, task_requirements: str,
        previous_steps: list[ExploreStep], step_index: int, max_steps: int,
    ) -> ActionPlan:
        """调用 DeepSeek/OpenAI 兼容 API"""

        # 精简元素列表（含结构信息辅助 AI 理解页面布局）
        el_list = []
        for i, el in enumerate(snapshot.interactive_elements[:25]):
            item = {"i": i}
            for k in ("tag", "role", "name", "label", "placeholder", "id", "href", "type",
                       "parentPath", "section"):
                v = el.get(k)
                if v:
                    item[k] = str(v)[:80]
            if el.get("required"):
                item["req"] = True
            if el.get("disabled"):
                item["dis"] = True
            el_list.append(item)

        prev_list = [
            {"i": s.index, "a": s.action.value, "d": s.description[:60], "ok": s.status.value == "success"}
            for s in previous_steps[-8:]
        ]

        prompt = f"""你是 Web 测试专家。根据当前页面选择最优的下一步操作。

【测试目标】{task_requirements}

【当前页面】{snapshot.url} | {snapshot.title}
页面文本摘要: {snapshot.body_text[:800]}

【可交互元素】
{json.dumps(el_list, ensure_ascii=False)}

【已完成步骤】
{json.dumps(prev_list, ensure_ascii=False)}

【进度】{step_index + 1}/{max_steps}

返回合法 JSON（只返回 JSON，不要其他文字）:
{{"action":"click|fill|navigate|assert_visible|assert_text|wait","target_i":目标元素序号或-1,"value":"输入值","reason":"选择原因"}}

规则：优先测试目标功能，避免重复，勿做删除/登出等危险操作。"""

        for attempt in range(2):
            try:
                plan_data = await self._call_api(prompt)
                return self._parse_plan(plan_data, snapshot)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                if attempt == 1:
                    raise
                # 重试：让 prompt 更严格
                prompt += "\n\n【重要】必须返回纯 JSON，不要 markdown 代码块。只返回 JSON 对象。"

    async def _call_api(self, prompt: str) -> dict:
        """调用 AI API，返回解析后的 JSON"""
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{settings.AI_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.AI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.AI_MODEL,
                    "messages": [
                        {"role": "system", "content": "你是 Web 自动化测试专家。只输出 JSON，不输出解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": settings.AI_TEMPERATURE,
                    "max_tokens": settings.AI_MAX_TOKENS,
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(f"API 返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        # 提取 JSON — DeepSeek 有时包在 ```json 中
        json_str = content
        for marker in ("```json", "```"):
            if marker in content:
                parts = content.split(marker)
                if len(parts) >= 2:
                    inner = parts[1]
                    if "```" in inner:
                        inner = inner.split("```")[0]
                    json_str = inner.strip()
                    break

        # 尝试从文本中提取 JSON 对象
        if not json_str.startswith("{"):
            m = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]+"[^{}]*\}', json_str)
            if m:
                json_str = m.group()

        return json.loads(json_str)

    def _parse_plan(self, data: dict, snapshot: PageSnapshot) -> ActionPlan:
        """将 API 返回的 JSON 转换为 ActionPlan"""
        action = StepAction(data["action"])
        target_i = data.get("target_i", -1)
        value = data.get("value", "")
        reason = data.get("reason", "")

        # 匹配元素
        locator = None
        elements = snapshot.interactive_elements

        if isinstance(target_i, int) and 0 <= target_i < len(elements):
            locator = build_locator(elements[target_i])
        elif target_i is not None and target_i != -1:
            # 按名称模糊匹配
            target_str = str(target_i).lower()
            for el in elements:
                name = (el.get("name") or "").lower()
                label = (el.get("label") or "").lower()
                if target_str in name or target_str in label:
                    locator = build_locator(el)
                    break

        # 描述
        action_cn = {
            "click": "点击", "fill": "填写", "navigate": "导航",
            "assert_visible": "验证可见", "assert_text": "验证文本",
            "wait": "等待", "select": "选择", "check": "勾选",
        }
        desc_parts = [action_cn.get(action.value, action.value)]
        if locator:
            el_name = locator.name or locator.label or locator.placeholder or locator.selector
            if el_name:
                desc_parts.append(f"'{el_name[:40]}'")
        if value and action in (StepAction.FILL, StepAction.NAVIGATE):
            desc_parts.append(f"「{value[:30]}」")
        description = "".join(desc_parts)

        return ActionPlan(
            action=action,
            description=description,
            reasoning=reason,
            locator=locator,
            value=value if value else None,
        )
