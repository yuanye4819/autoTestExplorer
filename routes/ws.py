"""WebSocket endpoint for real-time exploration progress."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from models.schemas import TaskStatus, WSMessage
from state import tasks_store, ws_connections
from services.db import _db_save_task

router = APIRouter()


@router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await websocket.accept()
    if task_id not in ws_connections:
        ws_connections[task_id] = []
    ws_connections[task_id].append(websocket)

    try:
        if task_id in tasks_store:
            result = tasks_store[task_id]
            await websocket.send_json(WSMessage(
                type="status", task_id=task_id,
                data={"status": result.status.value, "steps": len(result.steps)},
            ).model_dump(mode="json"))

        while True:
            data = await websocket.receive_text()
            if data == "cancel" and task_id in tasks_store:
                tasks_store[task_id].status = TaskStatus.CANCELLED
                tasks_store[task_id].completed_at = datetime.now()
                _db_save_task(tasks_store[task_id])

    except WebSocketDisconnect:
        pass
    finally:
        ws_connections[task_id].remove(websocket)
        if not ws_connections[task_id]:
            del ws_connections[task_id]
