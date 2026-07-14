# Centralized logging — used by both web server and desktop app.
from __future__ import annotations

import logging
from pathlib import Path

from config import settings


def setup_logging():
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.LOG_DIR / "autotest.log", encoding="utf-8"),
        ],
    )
    return logging.getLogger("autotest")
