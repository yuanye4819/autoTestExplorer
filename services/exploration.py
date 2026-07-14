"""Exploration orchestration — drives the full explore -> generate -> save pipeline."""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime
from urllib.parse import urlparse

from config import settings
from models.schemas import (
    ExplorationTask, TaskResult, TaskStatus, WSMessage,
)
from generators.feature_generator import generate_feature_file
from generators.script_generator import generate_test_script
from generators.page_object_generator import generate_page_object

logger = logging.getLogger("autotest")



def _update_output_manifest(task_id: str, result):
    """Append a summary entry to output/_manifest.json for browsing history."""
    import json
    from datetime import datetime

    manifest_path = settings.OUTPUT_DIR / "_manifest.json"
    entries = []
    if manifest_path.exists():
        try:
            entries = json.loads(manifest_path.read_text("utf-8"))
        except Exception:
            entries = []

    entries.append({
        "id": task_id,
        "url": result.task.target_url,
        "requirements": result.task.requirements,
        "status": result.status.value,
        "steps": len(result.steps),
        "created_at": result.created_at.isoformat() if result.created_at else "",
        "completed_at": datetime.now().isoformat(),
    })

    # Keep last 100 entries
    manifest_path.write_text(json.dumps(entries[-100:], ensure_ascii=False, indent=2), "utf-8")


def _derive_page_name(url: str) -> str:
    """Derive a safe Page Object class name from a URL."""
    import re as _re

    def _safe_name(part: str) -> str:
        cleaned = _re.sub(r"[^a-zA-Z0-9_]", "_", part)
        if cleaned and cleaned[0].isdigit():
            cleaned = "p_" + cleaned
        return cleaned.strip("_") or "page"

    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "").split(".")[0]
    path = parsed.path.strip("/").replace("/", "_").replace("-", "_")
    host_safe = _safe_name(host).capitalize()
    if path:
        path_safe = _safe_name(path).capitalize()
        return f"{host_safe}_{path_safe}Page"
    return f"{host_safe}Page"


def _broadcast_error(task_id: str, message: str):
    """Push an error message to all connected WebSocket clients."""
    from state import ws_connections

    if task_id in ws_connections:
        msg = WSMessage(type="error", task_id=task_id, data={"message": message})
        for ws in ws_connections[task_id]:
            try:
                asyncio.create_task(ws.send_json(msg.model_dump(mode="json")))
            except Exception:
                pass


async def _guarded_exploration(task_id: str):
    """Run exploration with concurrency semaphore gating."""
    from state import _task_semaphore

    async with _task_semaphore:
        await _run_exploration(task_id)


async def _run_exploration(task_id: str):
    """Complete exploration -> generate -> save pipeline for a single task."""
    from state import tasks_store, agent
    from services.db import _db_save_task

    result = tasks_store.get(task_id)
    if not result:
        return

    try:
        # Phase 1: Explore (with timeout guard)
        result.status = TaskStatus.EXPLORING
        logger.info(f"[{task_id}] Starting exploration of {result.task.target_url}")
        explored = await asyncio.wait_for(
            agent.explore(result.task),
            timeout=settings.BROWSER_TIMEOUT / 1000 * 3,
        )
        result.steps = explored.steps

        if result.status == TaskStatus.FAILED:
            logger.warning(f"[{task_id}] Exploration failed")
            return

        if not result.steps:
            logger.warning(f"[{task_id}] Exploration produced 0 steps — target may be unreachable")

        # Phase 2: Generate Feature file
        result.status = TaskStatus.GENERATING
        result.feature_content = generate_feature_file(result.task, result.steps)
        logger.info(f"[{task_id}] Feature file generated ({len(result.feature_content)} chars)")

        # Phase 3: Generate Page Object
        result.page_object_code = generate_page_object(
            result.steps,
            page_name=_derive_page_name(result.task.target_url),
        )
        logger.info(f"[{task_id}] Page Object generated ({len(result.page_object_code)} chars)")

        # Phase 4: Generate test script
        result.test_script = generate_test_script(result.task, result.steps)
        logger.info(f"[{task_id}] Test script generated ({len(result.test_script)} chars)")

        # Save to disk
        task_dir = settings.OUTPUT_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "test.feature").write_text(result.feature_content, encoding="utf-8")
        (task_dir / "test_generated.py").write_text(result.test_script, encoding="utf-8")
        (task_dir / "page_object.py").write_text(result.page_object_code, encoding="utf-8")
        logger.info(f"[{task_id}] Files saved to {task_dir}")

        # Write manifest
        _update_output_manifest(task_id, result)

        # Phase 5: Mark complete
        result.status = TaskStatus.COMPLETED
        result.completed_at = datetime.now()
        _db_save_task(result)
        logger.info(f"[{task_id}] Task completed successfully")

    except asyncio.TimeoutError:
        result.status = TaskStatus.FAILED
        error_msg = "Exploration timed out — target may be unreachable or too slow"
        logger.error(f"[{task_id}] {error_msg}")
        _db_save_task(result)
        _broadcast_error(task_id, error_msg)
    except Exception as e:
        result.status = TaskStatus.FAILED
        result.completed_at = datetime.now()
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"[{task_id}] {error_msg}")
        logger.error(traceback.format_exc())
        _db_save_task(result)
        _broadcast_error(task_id, error_msg)
