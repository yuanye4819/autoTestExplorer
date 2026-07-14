"""Database persistence — MySQL primary, SQLite fallback.
Schema: tasks / task_steps / task_screenshots / task_artifacts / schema_version
All exploration data stored in structured tables with proper indexes and constraints."""
from __future__ import annotations

import base64
import json as _json
import logging
import threading
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Integer, Text, LargeBinary,
    MetaData, Table, ForeignKey, UniqueConstraint, Index, inspect,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool, QueuePool
from sqlalchemy.exc import IntegrityError, OperationalError

from config import settings
from models.schemas import TaskResult, ExploreStep, ElementLocator, ExplorationTask, TaskStatus

logger = logging.getLogger("autotest")

_engine = None
_Session = None
_tables: dict[str, Table] = {}
_initialized = False
_lock = threading.Lock()
_db_type = "sqlite"  # detected at init time


def _init():
    global _engine, _Session, _tables, _initialized, _db_type
    with _lock:
        if _initialized:
            return

        url = settings.database.connection_url
        _db_type = "sqlite" if "sqlite" in url else "mysql"
        metadata = MetaData()

        # ---- Table definitions ----

        tasks_table = Table(
            "tasks", metadata,
            Column("id", String(32), primary_key=True),
            Column("target_url", String(2048), nullable=False),
            Column("requirements", Text, default=""),
            Column("status", String(20), default="pending", index=True),
            Column("step_count", Integer, default=0),
            Column("config_json", Text, default="{}"),
            Column("metrics_json", Text, default="{}"),
            Column("created_at", String(32), nullable=False, index=True),
            Column("updated_at", String(32), nullable=True),
            Column("completed_at", String(32), nullable=True),
            mysql_charset="utf8mb4",
        )

        steps_table = Table(
            "task_steps", metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("task_id", String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            Column("step_index", Integer, nullable=False),
            Column("action", String(30), nullable=False),
            Column("description", String(500), default=""),
            Column("reasoning", String(500), default=""),
            Column("status", String(20), default="pending", index=True),
            Column("duration_ms", Integer, default=0),
            Column("error", Text, default=""),
            Column("locator_json", Text, default="{}"),
            Column("value", String(500), default=""),
            Column("timestamp", String(32), nullable=True),
            UniqueConstraint("task_id", "step_index", name="uq_task_step"),
            Index("ix_task_steps_task_step", "task_id", "step_index"),
            mysql_charset="utf8mb4",
        )

        screenshots_table = Table(
            "task_screenshots", metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("task_id", String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            Column("step_index", Integer, nullable=False),
            Column("image_data", LargeBinary, nullable=True),
            Column("created_at", String(32), nullable=True),
            Index("ix_screenshots_task_step", "task_id", "step_index"),
            mysql_charset="utf8mb4",
        )

        artifacts_table = Table(
            "task_artifacts", metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("task_id", String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            Column("artifact_type", String(30), nullable=False),
            Column("content", Text, default=""),
            Index("ix_artifacts_task_type", "task_id", "artifact_type"),
            mysql_charset="utf8mb4",
        )

        schema_version_table = Table(
            "schema_version", metadata,
            Column("version", Integer, primary_key=True),
            Column("applied_at", String(32), nullable=False),
            Column("description", String(200), default=""),
        )

        # ---- Connect ----
        for attempt in range(2):
            try:
                if attempt == 1:
                    url = f"sqlite:///{settings.PROJECT_ROOT / 'tasks.db'}"
                    _db_type = "sqlite"
                    logger.info("Falling back to SQLite")

                if _db_type == "sqlite":
                    engine = create_engine(
                        url,
                        connect_args={"check_same_thread": False},
                        poolclass=StaticPool,
                    )
                else:
                    engine = create_engine(
                        url,
                        poolclass=QueuePool,
                        pool_size=8,
                        max_overflow=4,
                        pool_recycle=3600,
                        pool_pre_ping=True,
                        pool_timeout=10,
                    )

                metadata.create_all(engine, checkfirst=True)

                # Record schema version
                with engine.connect() as conn:
                    try:
                        conn.execute(schema_version_table.insert().values(
                            version=2, applied_at=datetime.now().isoformat(),
                            description="v2: optimized schema with indexes, config_json, metrics_json"
                        ))
                        conn.commit()
                    except (IntegrityError, OperationalError):
                        pass  # version already recorded or table just created

                _engine = engine
                _Session = sessionmaker(bind=engine)
                _tables = {
                    "tasks": tasks_table,
                    "steps": steps_table,
                    "screenshots": screenshots_table,
                    "artifacts": artifacts_table,
                    "schema_version": schema_version_table,
                }
                _initialized = True
                logger.info(f"DB ready (v2): {url.split('@')[-1] if '@' in url else url}")
                return
            except Exception as e:
                if attempt == 1:
                    raise
                logger.warning(f"MySQL unavailable ({e}), trying SQLite...")


# ---- Save ----

def save_task(result: TaskResult):
    """Save complete task result with all artifacts to database."""
    _init()
    session = _Session()
    try:
        tid = result.task.id
        now = datetime.now().isoformat()

        # Compute metrics
        total_steps = len(result.steps)
        success_steps = sum(1 for s in result.steps if s.status.value == "success")
        total_duration = sum(s.duration_ms for s in result.steps)
        metrics = _json.dumps({
            "total_steps": total_steps,
            "success_steps": success_steps,
            "failed_steps": total_steps - success_steps,
            "total_duration_ms": total_duration,
            "has_screenshots": sum(1 for s in result.steps if s.screenshot_b64),
            "has_artifacts": bool(result.feature_content or result.test_script),
        }, ensure_ascii=False)

        config = _json.dumps({
            "max_steps": result.task.max_steps,
            "explore_domain_only": result.task.explore_domain_only,
        }, ensure_ascii=False)

        # 1. Main task row
        _upsert(session, _tables["tasks"], {"id": tid}, {
            "id": tid,
            "target_url": result.task.target_url,
            "requirements": result.task.requirements,
            "status": result.status.value,
            "step_count": total_steps,
            "config_json": config,
            "metrics_json": metrics,
            "created_at": result.created_at.isoformat() if result.created_at else now,
            "updated_at": now,
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        })

        # 2. Steps — delete old, insert new
        session.execute(_tables["steps"].delete().where(_tables["steps"].c.task_id == tid))
        for step in result.steps:
            loc_json = _json.dumps(step.locator.model_dump() if step.locator else {}, ensure_ascii=False)
            session.execute(_tables["steps"].insert().values(
                task_id=tid,
                step_index=step.index,
                action=step.action.value,
                description=step.description or "",
                reasoning=step.reasoning or "",
                status=step.status.value,
                duration_ms=step.duration_ms,
                error=step.error or "",
                locator_json=loc_json,
                value=step.value or "",
                timestamp=step.timestamp.isoformat() if step.timestamp else now,
            ))

            # 3. Screenshot (one per step)
            if step.screenshot_b64:
                try:
                    img_bytes = base64.b64decode(step.screenshot_b64)
                    session.execute(_tables["screenshots"].insert().values(
                        task_id=tid,
                        step_index=step.index,
                        image_data=img_bytes,
                        created_at=now,
                    ))
                except Exception:
                    pass

        # 4. Artifacts — delete old, insert new
        session.execute(_tables["artifacts"].delete().where(_tables["artifacts"].c.task_id == tid))
        _insert_artifact(session, tid, "feature", result.feature_content)
        _insert_artifact(session, tid, "script", result.test_script)
        _insert_artifact(session, tid, "pageobject", result.page_object_code)
        _insert_artifact(session, tid, "log", result.execution_log)

        session.commit()
        logger.info(f"[{tid}] Saved: {total_steps} steps, {metrics.count(chr(115)+chr(99)+chr(114)+chr(101)+chr(101)+chr(110)+chr(115)+chr(104)+chr(111)+chr(116))}")
    except Exception as e:
        session.rollback()
        logger.warning(f"DB save failed: {e}")
    finally:
        session.close()


# ---- Load ----

def load_all_tasks() -> dict:
    """Load all tasks with their steps, screenshots and artifacts."""
    _init()
    tasks = {}
    session = _Session()
    try:
        task_rows = session.execute(_tables["tasks"].select().order_by("created_at")).fetchall()
        for t in task_rows:
            tid = t.id

            step_rows = session.execute(
                _tables["steps"].select()
                .where(_tables["steps"].c.task_id == tid)
                .order_by("step_index")
            ).fetchall()

            steps = []
            for s in step_rows:
                loc_data = _json.loads(s.locator_json) if s.locator_json else {}
                locator = ElementLocator(**loc_data) if loc_data else None

                ss_row = session.execute(
                    _tables["screenshots"].select().where(
                        _tables["screenshots"].c.task_id == tid,
                        _tables["screenshots"].c.step_index == s.step_index,
                    )
                ).first()
                ss_b64 = base64.b64encode(ss_row.image_data).decode() if (ss_row and ss_row.image_data) else None

                steps.append(ExploreStep(
                    index=s.step_index,
                    action=s.action,
                    description=s.description,
                    reasoning=s.reasoning,
                    status=s.status,
                    duration_ms=s.duration_ms,
                    error=s.error,
                    locator=locator,
                    value=s.value,
                    screenshot_b64=ss_b64,
                ))

            art_rows = session.execute(
                _tables["artifacts"].select()
                .where(_tables["artifacts"].c.task_id == tid)
                .order_by("artifact_type")
            ).fetchall()

            feature = script = pageobject = log = ""
            for a in art_rows:
                if a.artifact_type == "feature": feature = a.content or ""
                elif a.artifact_type == "script": script = a.content or ""
                elif a.artifact_type == "pageobject": pageobject = a.content or ""
                elif a.artifact_type == "log": log = a.content or ""

            task = ExplorationTask(id=tid, target_url=t.target_url, requirements=t.requirements or "")
            result = TaskResult(
                task=task, status=t.status or "completed", steps=steps,
                feature_content=feature, test_script=script,
                page_object_code=pageobject, execution_log=log,
            )
            result.created_at = datetime.fromisoformat(t.created_at) if t.created_at else datetime.now()
            if t.completed_at:
                result.completed_at = datetime.fromisoformat(t.completed_at)
            tasks[tid] = result

    except Exception as e:
        logger.warning(f"DB load failed: {e}")
    finally:
        session.close()
    return tasks


def list_task_summaries(limit: int = 50, offset: int = 0, status_filter: str | None = None) -> list[dict]:
    """Lightweight task listing — no steps, no screenshots, no artifacts loaded.
    Suitable for the task history sidebar. Returns list of dicts."""
    _init()
    results = []
    session = _Session()
    try:
        query = _tables["tasks"].select().order_by(_tables["tasks"].c.created_at.desc())
        if status_filter:
            query = query.where(_tables["tasks"].c.status == status_filter)
        query = query.limit(limit).offset(offset)
        rows = session.execute(query).fetchall()
        for t in rows:
            results.append({
                "id": t.id,
                "target_url": t.target_url,
                "requirements": (t.requirements or "")[:80],
                "status": t.status,
                "step_count": t.step_count or 0,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
                "metrics": _json.loads(t.metrics_json) if t.metrics_json else {},
            })
    except Exception as e:
        logger.warning(f"List summaries failed: {e}")
    finally:
        session.close()
    return results


def get_task_count(status_filter: str | None = None) -> int:
    """Get total task count, optionally filtered by status."""
    _init()
    session = _Session()
    try:
        query = _tables["tasks"].select()
        if status_filter:
            query = query.where(_tables["tasks"].c.status == status_filter)
        rows = session.execute(query).fetchall()
        return len(rows)
    finally:
        session.close()


def delete_task(task_id: str) -> bool:
    """Delete a task and all its related data (steps, screenshots, artifacts)."""
    _init()
    session = _Session()
    try:
        for tbl_name in ["steps", "screenshots", "artifacts"]:
            session.execute(_tables[tbl_name].delete().where(_tables[tbl_name].c.task_id == task_id))
        session.execute(_tables["tasks"].delete().where(_tables["tasks"].c.id == task_id))
        session.commit()
        logger.info(f"[{task_id}] Deleted from DB")
        return True
    except Exception as e:
        session.rollback()
        logger.warning(f"Delete task failed: {e}")
        return False
    finally:
        session.close()


# ---- Helpers ----

def _upsert(session, table, where_cols: dict, values: dict):
    """Thread-safe upsert: try INSERT first, fallback to UPDATE on conflict."""
    try:
        with session.begin_nested():
            session.execute(table.insert().values(**values))
    except IntegrityError:
        session.rollback()
        session.execute(table.update().where(
            *(table.c[k] == v for k, v in where_cols.items())
        ).values(**values))


def _insert_artifact(session, task_id: str, artifact_type: str, content: str):
    if content:
        session.execute(_tables["artifacts"].insert().values(
            task_id=task_id, artifact_type=artifact_type, content=content,
        ))
