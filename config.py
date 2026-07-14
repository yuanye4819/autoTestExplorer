"""Global configuration — supports environment variable override with AUTOTEST_ prefix."""
from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class ServerConfig(BaseSettings):
    """HTTP server settings."""
    HOST: str = "0.0.0.0"
    PORT: int = 8000


class BrowserConfig(BaseSettings):
    """Playwright browser settings."""
    HEADLESS: bool = True
    TIMEOUT: int = 30_000
    SLOW_MO: int = 300


class AgentConfig(BaseSettings):
    """Exploration agent settings."""
    MAX_STEPS: int = 30
    STEP_DELAY: float = 1.0
    ELEMENT_WAIT: int = 10_000


class AIConfig(BaseSettings):
    """AI / LLM settings."""
    API_KEY: str = ""
    API_BASE: str = "https://api.deepseek.com"
    MODEL: str = "deepseek-v4-pro"
    MAX_TOKENS: int = 1024
    TEMPERATURE: float = 0.3


class SecurityConfig(BaseSettings):
    """Security settings."""
    MAX_CONCURRENT_TASKS: int = 5
    ALLOWED_DOMAINS: list[str] = []


class DatabaseConfig(BaseSettings):
    """Database settings."""
    URL: str = ""


class Settings(BaseSettings):
    """Top-level settings aggregator."""
    PROJECT_ROOT: Path = Path(__file__).parent.resolve()
    OUTPUT_DIR: Path = PROJECT_ROOT / "output"
    LOG_DIR: Path = PROJECT_ROOT / "logs"

    server: ServerConfig = ServerConfig()
    browser: BrowserConfig = BrowserConfig()
    agent: AgentConfig = AgentConfig()
    ai: AIConfig = AIConfig()
    security: SecurityConfig = SecurityConfig()
    database: DatabaseConfig = DatabaseConfig()

    # Backward-compatible flat accessors
    @property
    def HOST(self): return self.server.HOST
    @property
    def PORT(self): return self.server.PORT
    @property
    def BROWSER_HEADLESS(self): return self.browser.HEADLESS
    @property
    def BROWSER_TIMEOUT(self): return self.browser.TIMEOUT
    @property
    def BROWSER_SLOW_MO(self): return self.browser.SLOW_MO
    @property
    def AGENT_MAX_STEPS(self): return self.agent.MAX_STEPS
    @property
    def AGENT_STEP_DELAY(self): return self.agent.STEP_DELAY
    @property
    def AGENT_ELEMENT_WAIT(self): return self.agent.ELEMENT_WAIT
    @property
    def AI_API_KEY(self): return self.ai.API_KEY
    @AI_API_KEY.setter
    def AI_API_KEY(self, value): self.ai.API_KEY = value

    @property
    def AI_API_BASE(self): return self.ai.API_BASE
    @AI_API_BASE.setter
    def AI_API_BASE(self, value): self.ai.API_BASE = value

    @property
    def AI_MODEL(self): return self.ai.MODEL
    @AI_MODEL.setter
    def AI_MODEL(self, value): self.ai.MODEL = value
    @property
    def AI_MAX_TOKENS(self): return self.ai.MAX_TOKENS
    @property
    def AI_TEMPERATURE(self): return self.ai.TEMPERATURE
    @property
    def MAX_CONCURRENT_TASKS(self): return self.security.MAX_CONCURRENT_TASKS
    @property
    def ALLOWED_DOMAINS(self): return self.security.ALLOWED_DOMAINS
    @property
    def DATABASE_URL(self): return self.database.URL

    model_config = {"env_prefix": "AUTOTEST_", "env_file": ".env", "env_nested_delimiter": "__"}


settings = Settings()

# Ensure required directories exist
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

# Legacy: set DATABASE_URL for backward compat
settings.database.URL = f"sqlite+aiosqlite:///{settings.PROJECT_ROOT}/data.db"
