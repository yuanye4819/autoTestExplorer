# Shared application state -- single source of truth for the server process.
from __future__ import annotations

import asyncio as _asyncio

from config import settings
from agent.agent import ExplorationAgent
from executor.test_runner import TestRunner

# In-memory task storage (persisted to SQLite via services.db)
tasks_store: dict[str, object] = {}

# WebSocket connection pool: task_id -> [WebSocket, ...]
ws_connections: dict[str, list] = {}

# Concurrency semaphore
_task_semaphore = _asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)

# Singleton instances
agent = ExplorationAgent()
test_runner = TestRunner()
