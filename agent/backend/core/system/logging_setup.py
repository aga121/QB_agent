"""
Central logging setup.
Redirects stdout/stderr to file logs with daily rotation.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from . import config


class _StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int) -> None:
        self._logger = logger
        self._level = level

    def write(self, message: str) -> None:
        text = (message or "").strip()
        if text:
            self._logger.log(self._level, text)

    def flush(self) -> None:
        return

    def isatty(self) -> bool:
        return False


def setup_logging(
    log_dir: str | None = None,
    log_name: str | None = None,
    when: str | None = None,
    backup_count: int | None = None,
) -> None:
    """Configure file logging and redirect stdout/stderr."""
    root = logging.getLogger()
    if getattr(root, "_queenbee_logging_configured", False):
        return

    log_dir = log_dir or config.LOG_DIR
    if os.name == "nt" and log_dir.startswith("/"):
        log_dir = os.path.join(os.getcwd(), "logs")
    log_name = log_name or config.LOG_FILE_NAME
    when = when or config.LOG_ROTATE_WHEN
    backup_count = backup_count if backup_count is not None else config.LOG_BACKUP_COUNT
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(log_dir, log_name)

    handler = TimedRotatingFileHandler(
        log_path,
        when=when,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.suffix = "%Y-%m-%d"
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root._queenbee_logging_configured = True

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    stdout_logger = logging.getLogger("stdout")
    stderr_logger = logging.getLogger("stderr")
    sys.stdout = _StreamToLogger(stdout_logger, logging.INFO)
    sys.stderr = _StreamToLogger(stderr_logger, logging.ERROR)

    # Silence noisy HTTP client request logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
