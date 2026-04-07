"""Logging configuration for mcp-robinhood."""

import logging
import logging.handlers
import os
import platform
import sys
from pathlib import Path


def get_default_log_dir() -> Path:
    system = platform.system().lower()
    if system == "darwin":
        return Path.home() / "Library" / "Logs" / "mcp-servers"
    elif system == "linux":
        if os.geteuid() == 0:
            return Path("/var/log/mcp-servers")
        return Path.home() / ".local" / "state" / "mcp-servers" / "logs"
    return Path.home() / ".mcp-servers" / "logs"


def setup_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[])

    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    log_path = get_default_log_dir()
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path / "mcp_robinhood.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    for name in ["mcp_robinhood", "mcp", "mcp.server", "uvicorn"]:
        logging.getLogger(name).setLevel(level)


# Export for use in tool modules
logger = logging.getLogger("mcp_robinhood")
