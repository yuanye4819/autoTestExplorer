"""REST API routes for task management."""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException

from config import settings
from models.schemas import (
    ExplorationTask, TaskResult, TaskStatus, TaskSummary,
    CreateTaskRequest, WSMessage,
)
from state import tasks_store, ws_connections, agent, test_runner
from services.exploration import _guarded_exploration
from services.db import save_task

router = APIRouter()


@router.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.post("/api/tasks", response_model=TaskSummary)
async def create_task(req: CreateTaskRequest):
    """Create a new exploration task."""
    active_count = sum(1 for r in tasks_store.values() if r.status in (TaskStatus.EXPLORING, TaskStatus.PENDING))
    if active_count >= settings.MAX_CONCURRENT_TASKS:
        raise HTTPException(status_code=429, detail=f"Max concurrent tasks ({settings.MAX_CONCURRENT_TASKS}) reached")

    task = ExplorationTask(
        target_url=req.target_url,
        requirements=req.requirements,
        username=req.username or None,
        password=req.password or None,
        max_steps=req.max_steps,
    )
    result = TaskResult(task=task)
    tasks_store[task.id] = result
    asyncio.create_task(_guarded_exploration(task.id))

    return TaskSummary(
        id=task.id,
        target_url=task.target_url,
        requirements=task.requirements,
        status=TaskStatus.PENDING,
        created_at=result.created_at,
    )


@router.get("/api/tasks", response_model=list[TaskSummary])
async def list_tasks():
    summaries = []
    for tid, result in tasks_store.items():
        summaries.append(TaskSummary(
            id=tid,
            target_url=result.task.target_url,
            requirements=result.task.requirements,
            status=result.status,
            step_count=len(result.steps),
            created_at=result.created_at,
            completed_at=result.completed_at,
        ))
    return sorted(summaries, key=lambda s: s.created_at, reverse=True)


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="Task not found")
    result = tasks_store[task_id]
    data = result.model_dump(mode="json")
    if "task" in data and "password" in data["task"]:
        data["task"]["password"] = None
    return data


@router.delete("/api/tasks/{task_id}")
async def cancel_task(task_id: str):
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="Task not found")
    result = tasks_store[task_id]
    if result.status in (TaskStatus.EXPLORING, TaskStatus.PENDING):
        result.status = TaskStatus.CANCELLED
        result.completed_at = datetime.now()
        save_task(result)
    return {"status": "cancelled"}


@router.post("/api/tasks/{task_id}/run")
async def run_task_tests(task_id: str):
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="Task not found")
    result = tasks_store[task_id]
    if not result.test_script:
        raise HTTPException(status_code=400, detail="No test script generated")

    result.status = TaskStatus.RUNNING

    async def runner_with_output():
        exec_result = await test_runner.run_with_fallback(result.test_script, task_id)
        result.execution_log = exec_result["log"]
        result.execution_passed = exec_result["passed"]
        result.status = TaskStatus.COMPLETED
        result.completed_at = datetime.now()
        save_task(result)
        if task_id in ws_connections:
            msg = WSMessage(type="execution_complete", task_id=task_id,
                            data={"passed": exec_result["passed"], "log": exec_result["log"][-2000:]})
            for ws in ws_connections[task_id]:
                try:
                    await ws.send_json(msg.model_dump(mode="json"))
                except Exception:
                    pass

    asyncio.create_task(runner_with_output())
    return {"status": "running"}
