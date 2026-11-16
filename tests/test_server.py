"""HTTP integration tests for the wheel server."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from lottery.server import create_server
from lottery.store import ConfigStore


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._temp.name)
        self.store = ConfigStore(self.data_dir)
        self.server = create_server("127.0.0.1", 0, self.store)
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="lucky-wheel-test", daemon=True
        )
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._temp.cleanup()

    def request(
        self,
        path: str,
        method: str = "GET",
        payload: Any = None,
        raw_body: bytes | None = None,
    ) -> tuple[int, Any, bytes]:
        if raw_body is not None:
            data = raw_body
        elif payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        else:
            data = None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def json_request(self, *args: Any, **kwargs: Any) -> tuple[int, Any, Any]:
        status, headers, body = self.request(*args, **kwargs)
        return status, headers, json.loads(body.decode("utf-8"))

    # -- page and static files ---------------------------------------------

    def test_index_page_and_security_headers(self) -> None:
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        html = body.decode("utf-8")
        self.assertIn("幸运大转盘", html)
        self.assertIn("/static/app.js", html)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertIn("no-cache", headers.get("Cache-Control", ""))

    def test_static_assets_have_correct_content_types(self) -> None:
        cases = {
            "/static/styles.css": "text/css",
            "/static/app.js": "text/javascript",
            "/static/favicon.svg": "image/svg+xml",
        }
        for path, content_type in cases.items():
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn(content_type, headers.get("Content-Type", ""))
                self.assertGreater(len(body), 0)

    def test_missing_static_resource_is_json_404(self) -> None:
        status, _, payload = self.json_request("/static/nope.css")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)

    def test_static_path_traversal_is_rejected(self) -> None:
        for path in (
            "/static/%2e%2e/%2e%2e/app.py",
            "/static/..%5c..%5capp.py",
            "/static/",
        ):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404)

    # -- configuration API --------------------------------------------------

    def test_config_endpoint_exposes_probabilities(self) -> None:
        status, _, payload = self.json_request("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(payload["title"], "幸运大转盘")
        self.assertEqual(len(payload["prizes"]), 8)
        self.assertEqual(payload["total_weight"], 100.0)
        self.assertAlmostEqual(
            sum(prize["probability"] for prize in payload["prizes"]),
            100.0,
            places=4,
        )
        self.assertNotIn("warning", payload)

    def test_update_config_persists_and_reflects_changes(self) -> None:
        new_config = {
            "title": "周会抽奖",
            "prizes": [
                {"name": "咖啡", "weight": 1, "color": "#112233"},
                {"name": "蛋糕", "weight": 3, "color": "#445566"},
            ],
        }
        status, _, payload = self.json_request("/api/config", "PUT", new_config)
        self.assertEqual(status, 200)
        self.assertTrue(payload["saved"])
        self.assertEqual(payload["title"], "周会抽奖")
        self.assertEqual(
            [prize["probability"] for prize in payload["prizes"]], [25.0, 75.0]
        )

        status, _, fetched = self.json_request("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(fetched["title"], "周会抽奖")

        reloaded = ConfigStore(self.data_dir).snapshot()
        self.assertEqual(reloaded["title"], "周会抽奖")
        self.assertEqual([p["weight"] for p in reloaded["prizes"]], [1.0, 3.0])

    def test_update_rejects_invalid_config_without_changing_state(self) -> None:
        before = self.store.snapshot()
        status, _, payload = self.json_request(
            "/api/config",
            "PUT",
            {"prizes": [{"name": "", "weight": 1}]},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        self.assertEqual(self.store.snapshot(), before)
        self.assertFalse((self.data_dir / "config.json").exists())

    def test_update_rejects_malformed_json(self) -> None:
        status, _, payload = self.json_request(
            "/api/config", "PUT", raw_body=b"{not json"
        )
        self.assertEqual(status, 400)
        self.assertIn("JSON", payload["error"])

    def test_update_requires_a_body(self) -> None:
        status, _, payload = self.json_request("/api/config", "PUT", raw_body=b"")
        self.assertEqual(status, 400)
        self.assertIn("请求体", payload["error"])

    def test_wrong_methods_are_rejected(self) -> None:
        for path, method in (("/api/config", "POST"), ("/api/spin", "GET")):
            with self.subTest(path=path, method=method):
                status, _, _ = self.json_request(path, method, {})
                self.assertEqual(status, 405)

    def test_unknown_api_is_json_404(self) -> None:
        status, _, payload = self.json_request("/api/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)

    def test_healthz(self) -> None:
        status, _, payload = self.json_request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})

    # -- drawing ------------------------------------------------------------

    def test_spin_returns_a_configured_prize_and_records_history(self) -> None:
        self.json_request(
            "/api/config",
            "PUT",
            {
                "prizes": [
                    {"id": "a", "name": "甲", "weight": 1, "color": "#112233"},
                    {"id": "b", "name": "乙", "weight": 1, "color": "#445566"},
                ]
            },
        )
        status, _, payload = self.json_request("/api/spin", "POST")
        self.assertEqual(status, 200)
        result = payload["result"]
        self.assertIn(result["name"], {"甲", "乙"})
        self.assertIn(result["id"], {"a", "b"})
        self.assertEqual(result["probability"], 50.0)
        self.assertEqual(len(payload["history"]), 1)
        self.assertEqual(payload["history"][0]["name"], result["name"])
        self.assertIn("at", payload["history"][0])

        status, _, history = self.json_request("/api/history")
        self.assertEqual(status, 200)
        self.assertEqual(history["history"], payload["history"])

    def test_spin_history_is_capped_at_twenty(self) -> None:
        for _ in range(21):
            status, _, _ = self.json_request("/api/spin", "POST")
            self.assertEqual(status, 200)
        _, _, payload = self.json_request("/api/history")
        self.assertEqual(len(payload["history"]), 20)

    def test_spin_accepts_post_without_body(self) -> None:
        status, _, payload = self.json_request("/api/spin", "POST")
        self.assertEqual(status, 200)
        self.assertIn("result", payload)


if __name__ == "__main__":
    unittest.main()
