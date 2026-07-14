"""Unit tests for data models."""
from datetime import datetime
from models.schemas import (
    ExplorationTask, TaskResult, TaskStatus, StepAction, StepStatus,
    CreateTaskRequest, ExploreStep, ElementLocator, TaskSummary, WSMessage,
)

def test_create_task_request():
    req = CreateTaskRequest(target_url="https://example.com", requirements="Test login", max_steps=15)
    assert req.target_url == "https://example.com"
    assert req.max_steps == 15

def test_exploration_task_has_id():
    task = ExplorationTask(target_url="https://example.com", requirements="Login flow")
    assert len(task.id) == 12  # uuid4 hex[:12]

def test_task_result_defaults():
    result = TaskResult(task=ExplorationTask(target_url="https://example.com"))
    assert result.status == TaskStatus.PENDING
    assert result.steps == []
    assert result.feature_content == ""
    assert result.test_script == ""

def test_create_task_request_no_password():
    req = CreateTaskRequest(target_url="https://example.com")
    assert req.password == ""    # defaults to empty string, not exposed in responses
    assert req.username == ""

def test_step_action_enum():
    assert StepAction.CLICK.value == "click"
    assert StepAction.FILL.value == "fill"

def test_element_locator_defaults():
    loc = ElementLocator()
    assert loc.strategy == "auto"
    assert loc.selector == ""

def test_task_summary():
    ts = TaskSummary(id="abc", target_url="https://x.com", requirements="test",
                     status=TaskStatus.COMPLETED, created_at=datetime.now())
    assert ts.id == "abc"

def test_ws_message():
    msg = WSMessage(type="log", task_id="123", data={"key": "val"})
    d = msg.model_dump(mode="json")
    assert d["type"] == "log"
