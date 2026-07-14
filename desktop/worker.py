"""Exploration worker thread — extracted from desktop_app.py."""
from __future__ import annotations

import asyncio
import queue
import threading

from models.schemas import ExplorationTask, ExploreStep, TaskStatus
from agent.agent import ExplorationAgent


class ExplorationWorker(threading.Thread):
    """Runs the async exploration agent in a background thread.
    Communicates results back via a thread-safe queue."""

    def __init__(self, task: ExplorationTask, ui_queue: queue.Queue):
        super().__init__(daemon=True)
        self.task = task
        self.ui_queue = ui_queue
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            agent = ExplorationAgent()

            async def on_step(step: ExploreStep):
                self.ui_queue.put(("step", step))

            async def on_log(message: str):
                self.ui_queue.put(("log", message))

            async def on_snapshot(url, title, screenshot_b64, element_count):
                self.ui_queue.put(("snapshot", {
                    "url": url, "title": title,
                    "screenshot": screenshot_b64, "element_count": element_count,
                }))

            async def on_reasoning(action, description, reasoning):
                self.ui_queue.put(("reasoning", {
                    "action": action, "description": description, "reasoning": reasoning,
                }))

            async def on_status(status, message, step=None, max_steps=None):
                self.ui_queue.put(("status", {
                    "status": status, "message": message,
                    "step": step, "max_steps": max_steps,
                }))

            loop.run_until_complete(self._run_exploration(agent, on_step, on_log,
                on_snapshot, on_reasoning, on_status))
        except Exception:
            import traceback
            self.ui_queue.put(("error", traceback.format_exc()))
        finally:
            loop.close()

    async def _run_exploration(self, agent, on_step, on_log, on_snapshot, on_reasoning, on_status):
        # Direct callback assignment (not method calls)
        agent.explorer._on_step = on_step
        agent.explorer._on_log = on_log

        # Run exploration
        result = await agent.explore(self.task)

        # Generation phase (mirrors _run_exploration in services/exploration.py)
        if result.steps and result.status.value != "failed":
            from generators.feature_generator import generate_feature_file
            from generators.script_generator import generate_test_script
            from generators.page_object_generator import generate_page_object
            from services.exploration import _derive_page_name

            result.feature_content = generate_feature_file(self.task, result.steps)
            result.test_script = generate_test_script(self.task, result.steps)
            result.page_object_code = generate_page_object(result.steps, _derive_page_name(self.task.target_url))

            self.ui_queue.put(("log", f"Generated: Feature ({len(result.feature_content)} chars), Script ({len(result.test_script)} chars), PageObject ({len(result.page_object_code)} chars)"))

        self.ui_queue.put(("done", result))
