"""JSON persistence for prize configurations."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .model import ConfigError, default_config, normalize_config

LOGGER = logging.getLogger("lucky_wheel.store")


class ConfigStore:
    """Thread-safe, atomically written prize configuration store.

    A missing file simply means "use the built-in defaults". A corrupt file
    is moved aside (``config.invalid-<timestamp>.json``) so the game can
    still start, and a warning is exposed through :attr:`warning`.
    """

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.path = self.data_dir / "config.json"
        self._lock = threading.RLock()
        self.warning: str | None = None
        with self._lock:
            self._config = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_config()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return normalize_config(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ConfigError) as exc:
            backup = self._backup_invalid()
            suffix = f"（原文件已备份为 {backup.name}）" if backup else ""
            self.warning = f"配置文件无法使用，已恢复默认奖品：{exc}{suffix}"
            LOGGER.warning(self.warning)
            return default_config()

    def _backup_invalid(self) -> Path | None:
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_name(f"config.invalid-{stamp}.json")
            os.replace(self.path, backup)
            return backup
        except OSError:
            return None

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of the current configuration."""
        with self._lock:
            return copy.deepcopy(self._config)

    def save(self, raw: Any) -> dict[str, Any]:
        """Validate, persist and return a new configuration."""
        config = normalize_config(raw)
        with self._lock:
            self._write(config)
            self._config = config
            self.warning = None
            return copy.deepcopy(config)

    def _write(self, config: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        handle = None
        temp_name: str | None = None
        try:
            handle, temp_name = tempfile.mkstemp(
                prefix=".config-", suffix=".tmp", dir=self.data_dir
            )
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                handle = None  # os.fdopen owns the descriptor now
                json.dump(config, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if handle is not None:
                os.close(handle)
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


__all__ = ["ConfigStore"]
