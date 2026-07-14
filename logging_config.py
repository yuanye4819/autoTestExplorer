# Centralized logging — used by both web server and desktop app.
from __future__ import annotations

import logging
from pathlib import Path

from config import settings


def setup_logging():
    from logging.handlers import RotatingFileHandler
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                settings.LOG_DIR / "autotest.log",
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=3,
                encoding="utf-8",
            ),
        ],
    )
    return logging.getLogger("autotest")
