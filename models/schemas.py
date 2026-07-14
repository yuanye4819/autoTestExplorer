"""
Pydantic 数据模型 — 定义系统中所有核心数据结构
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── 枚举 ─────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    EXPLORING = "exploring"
    GENERATING = "generating"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepAction(str, Enum):
    NAVIGATE = "navigate"       # 导航到 URL
    CLICK = "click"             # 点击元素
    FILL = "fill"               # 输入文本
    SELECT = "select"           # 下拉选择
    CHECK = "check"             # 勾选复选框
    HOVER = "hover"             # 悬停
    WAIT = "wait"               # 等待
    ASSERT_VISIBLE = "assert_visible"
    ASSERT_TEXT = "assert_text"
    ASSERT_URL = "assert_url"
    SCREENSHOT = "screenshot"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── 元素定位器 ────────────────────────────────────────

class ElementLocator(BaseModel):
    """Web 元素定位信息，优先使用语义化定位"""
    strategy: str = "auto"      # auto, role, label, text, placeholder, css, xpath, testid
    selector: str = ""
    role: Optional[str] = None          # button, link, textbox, checkbox, etc.
    name: Optional[str] = None          # 可访问名称
    text: Optional[str] = None          # 文本内容
    label: Optional[str] = None         # 关联 label
    placeholder: Optional[str] = None
    css: Optional[str] = None
    xpath: Optional[str] = None
    test_id: Optional[str] = None


# ── 探索步骤 ─────────────────────────────────────────

class ExploreStep(BaseModel):
    """单次探索步骤的记录"""
    index: int
    action: StepAction
    description: str                        # 人类可读描述
    reasoning: str = ""                     # Agent 推理过程
    locator: Optional[ElementLocator] = None
    value: Optional[str] = None             # 输入值/URL
    status: StepStatus = StepStatus.PENDING
    screenshot_b64: Optional[str] = None    # 步骤截图 (base64)
    error: Optional[str] = None
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)


# ── 页面快照 ─────────────────────────────────────────

class PageSnapshot(BaseModel):
    """当前页面的结构快照"""
    url: str
    title: str
    interactive_elements: list[dict[str, Any]] = []   # 可交互元素列表
    body_text: str = ""                                # 页面可见文本摘要
    screenshot_b64: Optional[str] = None


# ── 探索任务定义 ─────────────────────────────────────

class ExplorationTask(BaseModel):
    """用户提交的探索任务"""
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    target_url: str
    requirements: str = ""                  # 自然语言测试要求
    username: Optional[str] = None          # 登录凭据
    password: Optional[str] = None
    custom_headers: dict[str, str] = Field(default_factory=dict)
    max_steps: int = 30
    explore_domain_only: bool = True        # 是否仅探索同域


# ── 任务结果 ─────────────────────────────────────────

class TaskResult(BaseModel):
    """单个任务的完整结果"""
    task: ExplorationTask
    status: TaskStatus = TaskStatus.PENDING
    steps: list[ExploreStep] = Field(default_factory=list)
    feature_content: str = ""               # 生成的 Feature 文件内容
    test_script: str = ""                   # 生成的测试脚本
    page_object_code: str = ""              # Page Object 代码
    execution_log: str = ""                 # 脚本执行日志
    execution_passed: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


# ── WebSocket 消息 ───────────────────────────────────

class WSMessage(BaseModel):
    """通过 WebSocket 推送的实时消息"""
    type: str                               # step_update, log, screenshot, generation, execution, complete, error
    task_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


# ── 请求/响应模型 ────────────────────────────────────

class CreateTaskRequest(BaseModel):
    target_url: str
    requirements: str = ""
    username: Optional[str] = None
    password: Optional[str] = None
    max_steps: int = 30


class TaskSummary(BaseModel):
    id: str
    target_url: str
    requirements: str
    status: TaskStatus
    step_count: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None
