"""Simple application logging configuration."""

from __future__ import annotations

import logging
import sys


def configure_logging(log_level: str = "INFO") -> None:
    """Write consistently formatted application logs to stdout."""

    level_name = log_level.strip().upper()
    level = logging.getLevelNamesMapping().get(level_name)
    if not isinstance(level, int):
        raise ValueError(f"Unsupported log level: {log_level}")

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
