"""
全局配置模块 — 管理系统所有可配置项
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """系统配置，支持环境变量覆盖"""

    # 项目根目录
    PROJECT_ROOT: Path = Path(__file__).parent.resolve()

    # 输出目录
    OUTPUT_DIR: Path = PROJECT_ROOT / "output"
    LOG_DIR: Path = PROJECT_ROOT / "logs"

    # 服务配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Playwright 配置
    BROWSER_HEADLESS: bool = True           # 探索时是否无头模式（默认 True，有桌面可改 False）
    BROWSER_TIMEOUT: int = 30_000           # 页面操作超时 (ms)
    BROWSER_SLOW_MO: int = 300              # 操作间隔慢放 (ms)，便于观察

    # Agent 配置
    AGENT_MAX_STEPS: int = 30               # 单任务最大探索步数
    AGENT_STEP_DELAY: float = 1.0           # 步骤间等待时间
    AGENT_ELEMENT_WAIT: int = 10_000        # 元素等待超时 (ms)

    # AI 配置 (可通过环境变量覆盖)
    AI_API_KEY: str = ""                          # DeepSeek / OpenAI API Key，或设环境变量 AUTOTEST_AI_API_KEY
    AI_API_BASE: str = "https://api.deepseek.com"  # 默认 DeepSeek；OpenAI 用 "https://api.openai.com/v1"
    AI_MODEL: str = "deepseek-v4-pro"               # DeepSeek V4 Pro；OpenAI 用 gpt-4o / gpt-4o-mini
    AI_MAX_TOKENS: int = 1024
    AI_TEMPERATURE: float = 0.3

    # 安全配置
    MAX_CONCURRENT_TASKS: int = 5
    ALLOWED_DOMAINS: list[str] = []         # 空白名单 = 允许所有

    # 数据库
    DATABASE_URL: str = f"sqlite+aiosqlite:///{PROJECT_ROOT}/data.db"

    model_config = {"env_prefix": "AUTOTEST_", "env_file": ".env"}


settings = Settings()

# 确保必要目录存在
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
