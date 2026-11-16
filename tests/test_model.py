"""Tests for prize validation, probability math and weighted drawing."""

from __future__ import annotations

import random
import unittest

from lottery.model import (
    DEFAULT_TITLE,
    MAX_PRIZES,
    MIN_PRIZES,
    ConfigError,
    default_config,
    draw,
    normalize_config,
    total_weight,
    weighted_index,
    with_probabilities,
)


class _FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def _two_prizes() -> list[dict[str, object]]:
    return [
        {"name": "甲", "weight": 1},
        {"name": "乙", "weight": 3},
    ]


class DefaultConfigTests(unittest.TestCase):
    def test_default_config_is_valid_and_sums_to_100(self) -> None:
        config = default_config()
        self.assertEqual(config["title"], DEFAULT_TITLE)
        self.assertEqual(len(config["prizes"]), 8)
        self.assertAlmostEqual(total_weight(config["prizes"]), 100.0)
        self.assertTrue(all(prize["weight"] > 0 for prize in config["prizes"]))
        self.assertEqual(normalize_config(config), config)

    def test_default_config_is_a_fresh_copy(self) -> None:
        first = default_config()
        first["prizes"][0]["name"] = "被修改"
        self.assertEqual(default_config()["prizes"][0]["name"], "特等奖")

    def test_probabilities_sum_to_100(self) -> None:
        payload = with_probabilities(default_config())
        self.assertAlmostEqual(
            sum(prize["probability"] for prize in payload["prizes"]),
            100.0,
            places=4,
        )
        self.assertEqual(payload["total_weight"], 100.0)

    def test_probability_payload_does_not_mutate_source(self) -> None:
        config = default_config()
        payload = with_probabilities(config)
        payload["prizes"][0]["name"] = "回写"
        self.assertEqual(config["prizes"][0]["name"], "特等奖")


class NormalizeConfigTests(unittest.TestCase):
    def test_accepts_custom_fields_and_normalises_values(self) -> None:
        raw = {
            "title": "  公司年会抽奖  ",
            "prizes": [
                {"id": "first", "name": " 一等奖 ", "weight": 2, "color": "#ABCDEF"},
                {"name": "参与奖", "weight": 0.5},
            ],
        }
        config = normalize_config(raw)
        self.assertEqual(config["title"], "公司年会抽奖")
        self.assertEqual(config["prizes"][0]["id"], "first")
        self.assertEqual(config["prizes"][0]["name"], "一等奖")
        self.assertEqual(config["prizes"][0]["weight"], 2.0)
        self.assertEqual(config["prizes"][0]["color"], "#abcdef")
        self.assertRegex(str(config["prizes"][1]["id"]), r"^p-[0-9a-f]{8}$")
        self.assertEqual(config["prizes"][1]["color"], "#ef6f6c")

    def test_blank_title_falls_back_to_default(self) -> None:
        raw = {"title": "   ", "prizes": _two_prizes()}
        self.assertEqual(normalize_config(raw)["title"], DEFAULT_TITLE)

    def test_duplicate_ids_are_replaced(self) -> None:
        raw = {
            "prizes": [
                {"id": "same", "name": "甲", "weight": 1},
                {"id": "same", "name": "乙", "weight": 1},
            ]
        }
        prizes = normalize_config(raw)["prizes"]
        self.assertEqual(prizes[0]["id"], "same")
        self.assertNotEqual(prizes[1]["id"], "same")
        self.assertRegex(prizes[1]["id"], r"^p-[0-9a-f]{8}$")

    def test_invalid_colour_uses_palette(self) -> None:
        prizes = normalize_config(
            {
                "prizes": [
                    {"name": "甲", "weight": 1, "color": "red"},
                    {"name": "乙", "weight": 1, "color": "#12345"},
                ]
            }
        )["prizes"]
        self.assertEqual(prizes[0]["color"], "#f6c453")
        self.assertEqual(prizes[1]["color"], "#ef6f6c")

    def test_weight_is_rounded_to_six_decimals(self) -> None:
        prizes = normalize_config(
            {
                "prizes": [
                    {"name": "甲", "weight": 0.123456789},
                    {"name": "乙", "weight": 1},
                ]
            }
        )["prizes"]
        self.assertEqual(prizes[0]["weight"], 0.123457)

    def test_rejects_invalid_payloads(self) -> None:
        cases = [
            (None, "JSON 对象"),
            ("not a config", "JSON 对象"),
            ({}, "prizes"),
            ({"prizes": "nope"}, "数组"),
            ({"prizes": []}, "数量"),
            ({"prizes": [{"name": "甲", "weight": 1}]}, "数量"),
            ({"prizes": _two_prizes() * 13}, "数量"),
            ({"version": 2, "prizes": _two_prizes()}, "版本"),
            ({"prizes": ["甲", "乙"]}, "JSON 对象"),
            (
                {
                    "prizes": [
                        {"name": "", "weight": 1},
                        {"name": "乙", "weight": 1},
                    ]
                },
                "不能为空",
            ),
            (
                {
                    "prizes": [
                        {"name": "甲" * 25, "weight": 1},
                        {"name": "乙", "weight": 1},
                    ]
                },
                "24",
            ),
            (
                {
                    "title": "标题" * 16,
                    "prizes": [
                        {"name": "甲", "weight": 1},
                        {"name": "乙", "weight": 1},
                    ],
                },
                "30",
            ),
            (
                {
                    "prizes": [
                        {"name": "甲", "weight": 0},
                        {"name": "乙", "weight": 1},
                    ]
                },
                "大于 0",
            ),
            (
                {
                    "prizes": [
                        {"name": "甲", "weight": -1},
                        {"name": "乙", "weight": 1},
                    ]
                },
                "大于 0",
            ),
            (
                {
                    "prizes": [
                        {"name": "甲", "weight": "1"},
                        {"name": "乙", "weight": 1},
                    ]
                },
                "数字",
            ),
            (
                {
                    "prizes": [
                        {"name": "甲", "weight": True},
                        {"name": "乙", "weight": 1},
                    ]
                },
                "数字",
            ),
            (
                {
                    "prizes": [
                        {"name": "甲", "weight": float("nan")},
                        {"name": "乙", "weight": 1},
                    ]
                },
                "有限",
            ),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigError) as context:
                    normalize_config(raw)
                self.assertIn(expected, str(context.exception))

    def test_exactly_minimum_and_maximum_prizes_are_allowed(self) -> None:
        for count in (MIN_PRIZES, MAX_PRIZES):
            raw = {
                "prizes": [
                    {"name": f"奖品{i + 1}", "weight": 1} for i in range(count)
                ]
            }
            with self.subTest(count=count):
                self.assertEqual(len(normalize_config(raw)["prizes"]), count)

    def test_extra_fields_are_ignored(self) -> None:
        raw = {
            "updated_at": "yesterday",
            "prizes": [
                {"name": "甲", "weight": 1, "probability": 99, "extra": True},
                {"name": "乙", "weight": 1},
            ],
        }
        config = normalize_config(raw)
        self.assertNotIn("updated_at", config)
        self.assertNotIn("probability", config["prizes"][0])


class WeightedDrawTests(unittest.TestCase):
    def test_boundaries(self) -> None:
        prizes = _two_prizes()
        self.assertEqual(weighted_index(prizes, _FixedRandom(0.0)), 0)
        self.assertEqual(weighted_index(prizes, _FixedRandom(0.2499)), 0)
        self.assertEqual(weighted_index(prizes, _FixedRandom(0.25)), 1)
        self.assertEqual(weighted_index(prizes, _FixedRandom(0.9999)), 1)

    def test_distribution_matches_weights(self) -> None:
        prizes = [
            {"name": "甲", "weight": 1},
            {"name": "乙", "weight": 3},
            {"name": "丙", "weight": 6},
        ]
        counts = [0, 0, 0]
        rng = random.Random(20241116)
        for _ in range(30_000):
            counts[weighted_index(prizes, rng)] += 1
        for observed, expected in zip(counts, (0.1, 0.3, 0.6)):
            with self.subTest(observed=observed):
                self.assertAlmostEqual(observed / 30_000, expected, delta=0.015)

    def test_draw_returns_prize_and_probability(self) -> None:
        config = normalize_config(
            {
                "prizes": [
                    {"id": "a", "name": "甲", "weight": 1, "color": "#112233"},
                    {"id": "b", "name": "乙", "weight": 1, "color": "#445566"},
                ]
            }
        )
        result = draw(config, _FixedRandom(0.75))
        self.assertEqual(result["index"], 1)
        self.assertEqual(result["id"], "b")
        self.assertEqual(result["name"], "乙")
        self.assertEqual(result["probability"], 50.0)

    def test_empty_prizes_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            weighted_index([])


if __name__ == "__main__":
    unittest.main()
