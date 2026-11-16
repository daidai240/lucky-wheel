"""Tests for JSON configuration persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lottery.model import ConfigError, default_config
from lottery.store import ConfigStore


class ConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_missing_file_uses_defaults(self) -> None:
        store = ConfigStore(self.data_dir)
        self.assertIsNone(store.warning)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.snapshot(), default_config())

    def test_save_persists_utf8_json_and_reloads(self) -> None:
        store = ConfigStore(self.data_dir)
        raw = {
            "title": "自定义抽奖",
            "prizes": [
                {"name": "咖啡券", "weight": 1},
                {"name": "电影票", "weight": 3},
            ],
        }
        saved = store.save(raw)
        self.assertTrue(store.path.is_file())
        on_disk = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["title"], "自定义抽奖")
        self.assertEqual([p["weight"] for p in on_disk["prizes"]], [1.0, 3.0])

        reloaded = ConfigStore(self.data_dir)
        self.assertIsNone(reloaded.warning)
        self.assertEqual(reloaded.snapshot(), saved)
        self.assertEqual(
            [p["name"] for p in reloaded.snapshot()["prizes"]],
            ["咖啡券", "电影票"],
        )

    def test_invalid_config_does_not_touch_existing_file(self) -> None:
        store = ConfigStore(self.data_dir)
        store.save(
            {
                "title": "原配置",
                "prizes": [
                    {"name": "甲", "weight": 1},
                    {"name": "乙", "weight": 1},
                ],
            }
        )
        before = store.path.read_bytes()
        with self.assertRaises(ConfigError):
            store.save({"prizes": []})
        self.assertEqual(store.path.read_bytes(), before)
        self.assertEqual(store.snapshot()["title"], "原配置")

    def test_corrupt_file_is_backed_up(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        broken = "{ definitely not json"
        (self.data_dir / "config.json").write_text(broken, encoding="utf-8")

        store = ConfigStore(self.data_dir)

        self.assertIsNotNone(store.warning)
        self.assertIn("默认奖品", store.warning or "")
        self.assertEqual(store.snapshot(), default_config())
        backups = list(self.data_dir.glob("config.invalid-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), broken)
        self.assertFalse(store.path.exists())

    def test_semantically_invalid_file_is_backed_up(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "config.json").write_text(
            json.dumps({"prizes": []}), encoding="utf-8"
        )

        store = ConfigStore(self.data_dir)

        self.assertIsNotNone(store.warning)
        self.assertEqual(len(store.snapshot()["prizes"]), 8)
        self.assertEqual(len(list(self.data_dir.glob("config.invalid-*.json"))), 1)

    def test_warning_is_cleared_after_successful_save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "config.json").write_text("{", encoding="utf-8")
        store = ConfigStore(self.data_dir)
        self.assertIsNotNone(store.warning)

        store.save(
            {
                "prizes": [
                    {"name": "甲", "weight": 1},
                    {"name": "乙", "weight": 1},
                ]
            }
        )
        self.assertIsNone(store.warning)

    def test_atomic_write_leaves_no_temporary_files(self) -> None:
        store = ConfigStore(self.data_dir)
        store.save(
            {
                "prizes": [
                    {"name": "甲", "weight": 1},
                    {"name": "乙", "weight": 1},
                ]
            }
        )
        self.assertEqual(
            sorted(path.name for path in self.data_dir.iterdir()), ["config.json"]
        )

    def test_snapshot_is_isolated_from_stored_state(self) -> None:
        store = ConfigStore(self.data_dir)
        snapshot = store.snapshot()
        snapshot["prizes"][0]["name"] = "被外部修改"
        self.assertEqual(store.snapshot()["prizes"][0]["name"], "特等奖")


if __name__ == "__main__":
    unittest.main()
