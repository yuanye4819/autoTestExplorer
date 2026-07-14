"""
Agent 编排器 — 将探索器与规划器组合为完整的探索 Agent
驱动整个探索循环：分析 → 规划 → 执行 → 记录
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from config import settings
from models.schemas import (
    ExplorationTask, ExploreStep, TaskStatus, TaskResult,
    StepAction, StepStatus, WSMessage,
)
from agent.explorer import WebExplorer
from agent.planner import AgentPlanner


class ExplorationAgent:
    """
    探索 Agent 编排器：
    1. 接收 ExplorationTask
    2. 启动浏览器
    3. 循环执行：获取快照 → 规划下一步 → 执行 → 记录
    4. 生成最终的 TaskResult
    """

    def __init__(self):
        self.explorer = WebExplorer()
        self.planner = AgentPlanner()
        self._ws_callbacks: list[Callable] = []     # WebSocket 推送回调列表

    async def add_ws_callback(self, callback: Callable):
        """注册 WebSocket 消息回调"""
        self._ws_callbacks.append(callback)

    async def _push(self, msg_type: str, task_id: str, data: dict):
        """向所有 WebSocket 客户端推送消息"""
        msg = WSMessage(type=msg_type, task_id=task_id, data=data)
        for cb in self._ws_callbacks:
            try:
                await cb(msg.model_dump(mode="json"))
            except Exception:
                pass

    async def explore(self, task: ExplorationTask) -> TaskResult:
        """
        执行完整的探索流程，返回 TaskResult
        """
        result = TaskResult(task=task, status=TaskStatus.EXPLORING)
        self.planner.reset()

        await self._push("status", task.id, {"status": "starting", "message": "正在启动浏览器..."})

        try:
            # 1. 启动浏览器
            await self.explorer.start()

            # 设置回调
            async def on_step(step: ExploreStep):
                await self._push("step_update", task.id, step.model_dump(mode="json"))

            async def on_log(message: str):
                await self._push("log", task.id, {"message": message})

            self.explorer.on_step(on_step)
            self.explorer.on_log(on_log)

            # 2. 导航到目标 URL
            await self._push("status", task.id, {"status": "navigating", "message": f"正在导航到 {task.target_url}..."})
            await self.explorer.navigate(task.target_url, f"打开目标应用: {task.target_url}")

            # 3. 自动登录（如果提供了凭据）
            if task.username and task.password:
                await self._push("status", task.id, {"status": "logging_in", "message": "正在尝试自动登录..."})
                await self.explorer.try_auto_login(task.username, task.password)

            # 4. 探索循环
            max_steps = min(task.max_steps, settings.AGENT_MAX_STEPS)
            for i in range(max_steps):
                await self._push("status", task.id, {
                    "status": "exploring",
                    "message": f"探索中... 步骤 {i+1}/{max_steps}",
                    "step": i + 1,
                    "max_steps": max_steps,
                })

                # 获取页面快照
                snapshot = await self.explorer.get_snapshot()
                await self._push("snapshot", task.id, {
                    "url": snapshot.url,
                    "title": snapshot.title,
                    "element_count": len(snapshot.interactive_elements),
                    "screenshot": snapshot.screenshot_b64,
                })

                # 规划下一步
                plan = await self.planner.plan_next_action(
                    snapshot=snapshot,
                    task_requirements=task.requirements,
                    previous_steps=self.explorer.steps,
                    step_index=i,
                    max_steps=max_steps,
                )

                await self._push("reasoning", task.id, {
                    "action": plan.action.value,
                    "description": plan.description,
                    "reasoning": plan.reasoning,
                })

                # 执行操作
                step = await self._execute_plan(plan)

                # 检查是否应该结束探索
                if self._should_stop_exploration(step, i, max_steps):
                    await self._push("log", task.id, {"message": "探索目标已达成，结束探索"})
                    break

                await asyncio.sleep(settings.AGENT_STEP_DELAY)

            # 5. 收集结果
            result.steps = self.explorer.steps
            result.status = TaskStatus.GENERATING

            await self._push("status", task.id, {"status": "exploration_done", "message": f"探索完成，共 {len(result.steps)} 步"})

        except Exception as e:
            result.status = TaskStatus.FAILED
            await self._push("error", task.id, {"message": str(e)})
        finally:
            await self.explorer.stop()

        return result

    async def _execute_plan(self, plan) -> ExploreStep:
        """执行单个操作计划"""
        action = plan.action

        if action == StepAction.NAVIGATE:
            return await self.explorer.navigate(plan.value or "", plan.description)
        elif action == StepAction.CLICK:
            return await self.explorer.click_element(plan.locator, plan.description)
        elif action == StepAction.FILL:
            return await self.explorer.fill_input(plan.locator, plan.value or "", plan.description)
        elif action == StepAction.SELECT:
            return await self.explorer.select_option(plan.locator, plan.value or "", plan.description)
        elif action == StepAction.ASSERT_VISIBLE:
            return await self.explorer.assert_visible(plan.locator, plan.description)
        elif action == StepAction.ASSERT_TEXT:
            return await self.explorer.assert_text(plan.value or "", plan.description)
        elif action == StepAction.WAIT:
            await asyncio.sleep(2)
            # 创建一个简单的等待步骤
            from datetime import datetime
            step = ExploreStep(
                index=len(self.explorer.steps),
                action=StepAction.WAIT,
                description=plan.description or "等待页面加载",
                reasoning=plan.reasoning,
                status=StepStatus.SUCCESS,
            )
            self.explorer._steps.append(step)
            return step
        else:
            # 默认等待
            await asyncio.sleep(1)
            from datetime import datetime
            step = ExploreStep(
                index=len(self.explorer.steps),
                action=StepAction.WAIT,
                description=f"未知操作: {action}",
                status=StepStatus.SKIPPED,
            )
            self.explorer._steps.append(step)
            return step

    def _should_stop_exploration(self, last_step: ExploreStep, step_index: int, max_steps: int) -> bool:
        """
        判断是否应该提前结束探索：
        - 连续 3 次失败
        - 已达到最大步数 80%
        - 大部分步骤是断言（说明探索已充分）
        """
        if step_index >= max_steps:
            return True

        # 连续失败检查
        recent = self.explorer.steps[-3:]
        if len(recent) >= 3 and all(s.status == StepStatus.FAILED for s in recent):
            return True

        # 如果最近 3 步都是断言，说明探索已完成
        if len(recent) >= 3 and all(s.action in (StepAction.ASSERT_VISIBLE, StepAction.ASSERT_TEXT) for s in recent):
            return True

        return False
