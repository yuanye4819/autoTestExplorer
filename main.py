"""
AI-Driven Web Exploration & Automated Testing System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Main FastAPI Application Entry Point
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import logging

from config import settings

# ── 日志配置 ────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_DIR / "autotest.log", encoding="utf-8"),
    ],
)

from models.schemas import (
    ExplorationTask, TaskResult, TaskStatus, TaskSummary,
    CreateTaskRequest, WSMessage,
)
from agent.agent import ExplorationAgent
from generators.feature_generator import generate_feature_file
from generators.script_generator import generate_test_script
from generators.page_object_generator import generate_page_object
from executor.test_runner import TestRunner


# ── App 初始化 ──────────────────────────────────────

app = FastAPI(
    title="AI Web 探索测试系统",
    description="智能体驱动的 Web 应用探索与自动化测试生成平台",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局状态 ────────────────────────────────────────

# 任务存储 (内存)
tasks_store: dict[str, TaskResult] = {}

# WebSocket 连接管理
ws_connections: dict[str, list[WebSocket]] = {}

# Agent 单例
agent = ExplorationAgent()

# 测试执行器
test_runner = TestRunner()


# ── 启动/关闭事件 ───────────────────────────────────

@app.on_event("startup")
async def startup():
    """注册 WebSocket 广播回调"""
    async def broadcast_ws(message: dict):
        task_id = message.get("task_id", "")
        if task_id in ws_connections:
            dead = []
            for ws in ws_connections[task_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                ws_connections[task_id].remove(ws)

    await agent.add_ws_callback(broadcast_ws)

    # 同样给 test_runner 注册
    async def test_output(text: str):
        """测试输出的广播 — 通过所有连接广播"""
        pass  # 测试输出通过 WebSocket 直接推送

    test_runner.on_output(test_output)


# ── REST API ────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.post("/api/tasks", response_model=TaskSummary)
async def create_task(req: CreateTaskRequest):
    """创建新的探索任务"""
    task = ExplorationTask(
        target_url=req.target_url,
        requirements=req.requirements,
        username=req.username,
        password=req.password,
        max_steps=req.max_steps,
    )
    result = TaskResult(task=task)
    tasks_store[task.id] = result

    # 异步启动探索
    asyncio.create_task(_run_exploration(task.id))

    return TaskSummary(
        id=task.id,
        target_url=task.target_url,
        requirements=task.requirements,
        status=TaskStatus.PENDING,
        created_at=result.created_at,
    )


@app.get("/api/tasks", response_model=list[TaskSummary])
async def list_tasks():
    """列出所有任务"""
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


@app.get("/api/tasks/{task_id}", response_model=TaskResult)
async def get_task(task_id: str):
    """获取任务详情"""
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="任务不存在")
    return tasks_store[task_id]


@app.delete("/api/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = tasks_store[task_id]
    if result.status in (TaskStatus.EXPLORING, TaskStatus.PENDING):
        result.status = TaskStatus.CANCELLED
        result.completed_at = datetime.now()
    return {"status": "cancelled"}


@app.post("/api/tasks/{task_id}/run")
async def run_task_tests(task_id: str):
    """运行已生成任务的测试脚本"""
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = tasks_store[task_id]
    if not result.test_script:
        raise HTTPException(status_code=400, detail="该任务尚未生成测试脚本")

    result.status = TaskStatus.RUNNING

    async def runner_with_output():
        exec_result = await test_runner.run_with_fallback(result.test_script, task_id)
        result.execution_log = exec_result["log"]
        result.execution_passed = exec_result["passed"]
        result.status = TaskStatus.COMPLETED
        result.completed_at = datetime.now()

        # 通过 WebSocket 通知完成
        if task_id in ws_connections:
            msg = WSMessage(
                type="execution_complete",
                task_id=task_id,
                data={"passed": exec_result["passed"], "log": exec_result["log"][-2000:]},
            )
            for ws in ws_connections[task_id]:
                try:
                    await ws.send_json(msg.model_dump(mode="json"))
                except Exception:
                    pass

    asyncio.create_task(runner_with_output())
    return {"status": "running"}


# ── WebSocket ───────────────────────────────────────

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket 连接：实时推送探索进度、步骤、日志"""
    await websocket.accept()

    if task_id not in ws_connections:
        ws_connections[task_id] = []
    ws_connections[task_id].append(websocket)

    try:
        # 发送已有数据（重连时恢复状态）
        if task_id in tasks_store:
            result = tasks_store[task_id]
            await websocket.send_json(WSMessage(
                type="status",
                task_id=task_id,
                data={"status": result.status.value, "steps": len(result.steps)},
            ).model_dump(mode="json"))

        # 保持连接
        while True:
            data = await websocket.receive_text()
            # 可接收客户端指令（如取消）
            if data == "cancel" and task_id in tasks_store:
                tasks_store[task_id].status = TaskStatus.CANCELLED
                tasks_store[task_id].completed_at = datetime.now()

    except WebSocketDisconnect:
        pass
    finally:
        ws_connections[task_id].remove(websocket)
        if not ws_connections[task_id]:
            del ws_connections[task_id]


# ── 静态文件 ────────────────────────────────────────

static_dir = Path(__file__).parent / "static"

@app.get("/")
async def serve_index():
    return FileResponse(static_dir / "index.html")


# 挂载静态资源
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── 探索执行流程 ────────────────────────────────────

async def _run_exploration(task_id: str):
    """
    完整的探索 → 生成 → 执行流程
    """
    import traceback
    import logging
    logger = logging.getLogger("autotest")

    result = tasks_store.get(task_id)
    if not result:
        return

    try:
        # Phase 1: 探索 (带超时保护)
        result.status = TaskStatus.EXPLORING
        logger.info(f"[{task_id}] Starting exploration of {result.task.target_url}")
        explored = await asyncio.wait_for(
            agent.explore(result.task),
            timeout=settings.BROWSER_TIMEOUT / 1000 * 3,  # 3 倍浏览器超时
        )
        result.steps = explored.steps

        if result.status == TaskStatus.FAILED:
            logger.warning(f"[{task_id}] Exploration failed")
            return

        if not result.steps:
            logger.warning(f"[{task_id}] Exploration produced 0 steps — target may be unreachable")
            # 即使步数为0也继续生成，给用户看产物

        # Phase 2: 生成 Feature 文件
        result.status = TaskStatus.GENERATING
        result.feature_content = generate_feature_file(result.task, result.steps)
        logger.info(f"[{task_id}] Feature file generated ({len(result.feature_content)} chars)")

        # Phase 3: 生成 Page Object
        result.page_object_code = generate_page_object(
            result.steps,
            page_name=_derive_page_name(result.task.target_url),
        )
        logger.info(f"[{task_id}] Page Object generated ({len(result.page_object_code)} chars)")

        # Phase 4: 生成测试脚本
        result.test_script = generate_test_script(result.task, result.steps)
        logger.info(f"[{task_id}] Test script generated ({len(result.test_script)} chars)")

        # 保存到文件
        task_dir = settings.OUTPUT_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        (task_dir / "test.feature").write_text(result.feature_content, encoding="utf-8")
        (task_dir / "test_generated.py").write_text(result.test_script, encoding="utf-8")
        (task_dir / "page_object.py").write_text(result.page_object_code, encoding="utf-8")
        logger.info(f"[{task_id}] Files saved to {task_dir}")

        # Phase 5: 标记完成
        result.status = TaskStatus.COMPLETED
        result.completed_at = datetime.now()
        logger.info(f"[{task_id}] Task completed successfully")

    except asyncio.TimeoutError:
        result.status = TaskStatus.FAILED
        error_msg = "Exploration timed out — target may be unreachable or too slow"
        logger.error(f"[{task_id}] {error_msg}")
        _broadcast_error(task_id, error_msg)
    except Exception as e:
        result.status = TaskStatus.FAILED
        result.completed_at = datetime.now()
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"[{task_id}] {error_msg}")
        logger.error(traceback.format_exc())
        _broadcast_error(task_id, error_msg)


def _broadcast_error(task_id: str, message: str):
    """向 WebSocket 客户端广播错误消息"""
    if task_id in ws_connections:
        msg = WSMessage(type="error", task_id=task_id, data={"message": message})
        for ws in ws_connections[task_id]:
            try:
                asyncio.create_task(ws.send_json(msg.model_dump(mode="json")))
            except Exception:
                pass


def _derive_page_name(url: str) -> str:
    """从 URL 推导 Page Object 类名"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "").split(".")[0]
    path = parsed.path.strip("/").replace("/", "_").replace("-", "_")
    if path:
        return f"{host.capitalize()}_{path.capitalize()}Page"
    return f"{host.capitalize()}Page"


# ── 入口 ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
