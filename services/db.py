"""SQLite persistence layer for task storage."""
from __future__ import annotations

import json as _json
import logging
import sqlite3

from config import settings
from models.schemas import TaskResult


def _db_path():
    return settings.PROJECT_ROOT / "tasks.db"

def _db_init():
    """Initialize the SQLite database for task persistence."""
    db = sqlite3.connect(str(_db_path()))
    db.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            target_url TEXT NOT NULL,
            requirements TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            step_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            data_json TEXT DEFAULT '{}'
        )
    """)
    db.commit()
    db.close()

def _db_save_task(result: TaskResult):
    """Persist a task result to SQLite (screenshots excluded to save space)."""
    try:
        db = sqlite3.connect(str(_db_path()), timeout=5)
        data = result.model_dump(mode="json")
        if "steps" in data:
            for step in data["steps"]:
                step.pop("screenshot_b64", None)
        if "task" in data and "password" in data["task"]:
            data["task"]["password"] = None
        db.execute(
            """INSERT OR REPLACE INTO tasks (id, target_url, requirements, status, step_count, created_at, completed_at, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.task.id,
                result.task.target_url,
                result.task.requirements,
                result.status.value,
                len(result.steps),
                result.created_at.isoformat() if result.created_at else "",
                result.completed_at.isoformat() if result.completed_at else None,
                _json.dumps(data, ensure_ascii=False),
            ),
        )
        db.commit()
        db.close()
    except Exception as e:
        logging.getLogger("autotest").warning(f"DB save failed: {e}")

def _db_load_all_tasks() -> dict:
    """Load all tasks from SQLite into memory on startup."""
    tasks = {}
    db_path = _db_path()
    if not db_path.exists():
        return tasks
    try:
        db = sqlite3.connect(str(db_path), timeout=5)
        rows = db.execute("SELECT id, data_json FROM tasks").fetchall()
        db.close()
        for task_id, data_json in rows:
            try:
                data = _json.loads(data_json)
                result = TaskResult(**data)
                tasks[task_id] = result
            except Exception as e:
                logging.getLogger("autotest").warning(f"Failed to restore task {task_id}: {e}")
    except Exception as e:
        logging.getLogger("autotest").warning(f"DB load failed: {e}")
    return tasks

_db_init()
