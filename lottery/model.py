"""Prize configuration and weighted drawing logic.

Everything in this module is pure Python and has no third-party
dependencies, so the game can run on a stock Python installation.
"""

from __future__ import annotations

import math
import random
import re
import secrets
from typing import Any, Mapping, Sequence

DEFAULT_TITLE = "幸运大转盘"
CONFIG_VERSION = 1
MIN_PRIZES = 2
MAX_PRIZES = 24
MAX_NAME_LENGTH = 24
MAX_TITLE_LENGTH = 30
MAX_WEIGHT = 1_000_000.0

# Colours used for new prizes and for prizes whose colour is missing/invalid.
PALETTE = (
    "#f6c453",
    "#ef6f6c",
    "#7b61ff",
    "#2ec4b6",
    "#ff9f1c",
    "#4d96ff",
    "#f06595",
    "#5c6b8a",
    "#b7e778",
    "#8d6e63",
    "#00b4d8",
    "#e0aaff",
)

_DEFAULT_PRIZES = (
    ("特等奖", 1),
    ("一等奖", 4),
    ("二等奖", 8),
    ("三等奖", 12),
    ("四等奖", 15),
    ("五等奖", 20),
    ("幸运奖", 20),
    ("谢谢参与", 20),
)

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class ConfigError(ValueError):
    """Raised when a prize configuration is invalid."""


def default_config() -> dict[str, Any]:
    """Return a fresh copy of the built-in prize configuration."""
    prizes = [
        {
            "id": f"prize-{index + 1}",
            "name": name,
            "weight": weight,
            "color": PALETTE[index % len(PALETTE)],
        }
        for index, (name, weight) in enumerate(_DEFAULT_PRIZES)
    ]
    return {"version": CONFIG_VERSION, "title": DEFAULT_TITLE, "prizes": prizes}


def _clean_text(value: Any, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{field}必须是字符串")
    text = " ".join(value.split())
    if not text:
        raise ConfigError(f"{field}不能为空")
    if len(text) > max_length:
        raise ConfigError(f"{field}不能超过 {max_length} 个字符")
    return text


def _clean_weight(value: Any, index: int) -> float:
    label = f"第 {index + 1} 个奖品的权重"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label}必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"{label}必须是有限的数字")
    if number <= 0:
        raise ConfigError(f"{label}必须大于 0")
    if number > MAX_WEIGHT:
        raise ConfigError(f"{label}不能超过 {MAX_WEIGHT:g}")
    rounded = round(number, 6)
    if rounded <= 0:
        raise ConfigError(f"{label}太小了")
    return rounded


def _clean_color(value: Any, index: int) -> str:
    # Invalid colours are replaced rather than rejected: hand-edited JSON with
    # a colour name should not make the whole configuration unusable.
    if isinstance(value, str) and COLOR_RE.match(value.strip()):
        return value.strip().lower()
    return PALETTE[index % len(PALETTE)]


def _clean_id(value: Any, used: set[str]) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if ID_RE.match(candidate) and candidate not in used:
            used.add(candidate)
            return candidate
    while True:
        candidate = f"p-{secrets.token_hex(4)}"
        if candidate not in used:
            used.add(candidate)
            return candidate


def normalize_config(raw: Any) -> dict[str, Any]:
    """Validate an arbitrary JSON value and return the canonical config.

    Raises :class:`ConfigError` with a user-facing Chinese message when the
    value cannot be used as a prize configuration.
    """
    if not isinstance(raw, Mapping):
        raise ConfigError("配置必须是一个 JSON 对象")

    version = raw.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise ConfigError(f"不支持的配置版本：{version!r}")

    prizes_raw = raw.get("prizes")
    if not isinstance(prizes_raw, (list, tuple)):
        raise ConfigError("prizes 必须是一个数组")
    if not MIN_PRIZES <= len(prizes_raw) <= MAX_PRIZES:
        raise ConfigError(
            f"奖品数量必须在 {MIN_PRIZES} 到 {MAX_PRIZES} 个之间"
        )

    title_raw = raw.get("title", DEFAULT_TITLE)
    if title_raw is None or (isinstance(title_raw, str) and not title_raw.strip()):
        title = DEFAULT_TITLE
    else:
        title = _clean_text(title_raw, "活动标题", MAX_TITLE_LENGTH)

    prizes: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, item in enumerate(prizes_raw):
        if not isinstance(item, Mapping):
            raise ConfigError(f"第 {index + 1} 个奖品必须是一个 JSON 对象")
        name = _clean_text(
            item.get("name"), f"第 {index + 1} 个奖品的名称", MAX_NAME_LENGTH
        )
        prizes.append(
            {
                "id": _clean_id(item.get("id"), used_ids),
                "name": name,
                "weight": _clean_weight(item.get("weight"), index),
                "color": _clean_color(item.get("color"), index),
            }
        )

    if math.fsum(prize["weight"] for prize in prizes) > 1_000_000_000:
        raise ConfigError("所有奖品的权重之和过大")

    return {"version": CONFIG_VERSION, "title": title, "prizes": prizes}


def total_weight(prizes: Sequence[Mapping[str, Any]]) -> float:
    """Return the sum of all weights."""
    return math.fsum(float(prize["weight"]) for prize in prizes)


def with_probabilities(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *config* with a percentage probability per prize."""
    prizes = [dict(prize) for prize in config["prizes"]]
    total = total_weight(prizes)
    for prize in prizes:
        prize["probability"] = round(float(prize["weight"]) / total * 100, 6)
    return {
        "version": config.get("version", CONFIG_VERSION),
        "title": config["title"],
        "prizes": prizes,
        "total_weight": round(total, 6),
    }


def weighted_index(
    prizes: Sequence[Mapping[str, Any]], rng: random.Random | None = None
) -> int:
    """Pick a prize index using weights and a random number in [0, 1).

    ``rng`` exists for deterministic tests; production callers use
    :class:`random.SystemRandom`, which draws from the operating system's
    cryptographic randomness source.
    """
    if not prizes:
        raise ConfigError("没有可抽取的奖品")
    weights = [float(prize["weight"]) for prize in prizes]
    total = math.fsum(weights)
    if total <= 0:
        raise ConfigError("奖品权重之和必须大于 0")

    picker = rng if rng is not None else random.SystemRandom()
    threshold = picker.random() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if threshold < cumulative:
            return index
    return len(weights) - 1


def draw(
    config: Mapping[str, Any], rng: random.Random | None = None
) -> dict[str, Any]:
    """Draw one prize from *config* and return a JSON-friendly result."""
    prizes = config["prizes"]
    index = weighted_index(prizes, rng)
    prize = prizes[index]
    total = total_weight(prizes)
    return {
        "index": index,
        "id": prize["id"],
        "name": prize["name"],
        "color": prize["color"],
        "weight": prize["weight"],
        "probability": round(float(prize["weight"]) / total * 100, 6),
    }


__all__ = [
    "CONFIG_VERSION",
    "ConfigError",
    "DEFAULT_TITLE",
    "MAX_NAME_LENGTH",
    "MAX_PRIZES",
    "MAX_TITLE_LENGTH",
    "MAX_WEIGHT",
    "MIN_PRIZES",
    "PALETTE",
    "default_config",
    "draw",
    "normalize_config",
    "total_weight",
    "weighted_index",
    "with_probabilities",
]
