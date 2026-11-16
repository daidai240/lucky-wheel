"""HTTP server for the lucky wheel game.

The server uses only the Python standard library. It serves the static
single-page UI, exposes a small JSON API, persists prize configurations and
performs the actual weighted draw server-side.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .model import (
    ConfigError,
    draw,
    total_weight,
    with_probabilities,
)
from .store import ConfigStore

LOGGER = logging.getLogger("lucky_wheel")

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_DATA_DIR = PACKAGE_DIR.parent / "data"
MAX_BODY_BYTES = 1_000_000
HISTORY_LIMIT = 20

STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}

SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    (
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'",
    ),
)


class ApiError(Exception):
    """An error that should be rendered as a JSON API response."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


class WheelHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying the config store and in-memory result history."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        store: ConfigStore,
        static_dir: str | os.PathLike[str] = STATIC_DIR,
    ) -> None:
        super().__init__(address, WheelRequestHandler)
        self.store = store
        self.static_dir = Path(static_dir).resolve()
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LIMIT)
        self.history_lock = threading.Lock()

    def record_result(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        entry = {
            "id": secrets.token_hex(6),
            "name": result["name"],
            "color": result["color"],
            "probability": result["probability"],
            "at": _utc_now(),
        }
        with self.history_lock:
            self.history.appendleft(entry)
            return list(self.history)

    def history_snapshot(self) -> list[dict[str, Any]]:
        with self.history_lock:
            return list(self.history)


class WheelRequestHandler(BaseHTTPRequestHandler):
    """Routes for the static UI and the JSON API."""

    server: WheelHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "LuckyWheel/1.0"
    sys_version = ""

    # -- HTTP entry points -------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def _dispatch(self, method: str) -> None:
        try:
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                self._require_method(method, "GET")
                self._serve_index()
            elif path.startswith("/static/"):
                self._require_method(method, "GET")
                self._serve_static(path[len("/static/") :])
            elif path == "/api/config":
                if method == "PUT":
                    self._update_config()
                else:
                    self._require_method(method, "GET")
                    self._serve_config()
            elif path == "/api/history":
                self._require_method(method, "GET")
                self._send_json({"history": self.server.history_snapshot()})
            elif path == "/api/spin":
                self._require_method(method, "POST")
                self._spin()
            elif path == "/healthz":
                self._require_method(method, "GET")
                self._send_json({"ok": True})
            elif path.startswith("/api/"):
                raise ApiError(404, "接口不存在")
            else:
                raise ApiError(404, "页面不存在")
        except ApiError as exc:
            self._send_json({"error": exc.message}, status=exc.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # pragma: no cover - defensive top-level guard
            LOGGER.exception("Unhandled error for %s %s", method, self.path)
            self._send_json({"error": "服务器内部错误"}, status=500)

    # -- API handlers -------------------------------------------------------

    def _serve_config(self) -> None:
        payload = with_probabilities(self.server.store.snapshot())
        warning = self.server.store.warning
        if warning:
            payload["warning"] = warning
        self._send_json(payload)

    def _spin(self) -> None:
        config = self.server.store.snapshot()
        result = draw(config)
        history = self.server.record_result(result)
        self._send_json(
            {
                "result": result,
                "history": history,
                "total_weight": round(total_weight(config["prizes"]), 6),
            }
        )

    def _update_config(self) -> None:
        payload = self._read_json()
        try:
            saved = self.server.store.save(payload)
        except ConfigError as exc:
            raise ApiError(400, str(exc)) from exc
        response = with_probabilities(saved)
        response["saved"] = True
        self._send_json(response)

    # -- static files -------------------------------------------------------

    def _serve_index(self) -> None:
        try:
            body = (self.server.static_dir / "index.html").read_bytes()
        except OSError as exc:
            raise ApiError(500, "页面文件缺失") from exc
        self._send_bytes(
            body, "text/html; charset=utf-8", cache_control="no-cache"
        )

    def _serve_static(self, relative_path: str) -> None:
        try:
            decoded = unquote(relative_path)
        except UnicodeError as exc:
            raise ApiError(404, "资源不存在") from exc
        if not decoded or decoded.endswith("/") or "\x00" in decoded:
            raise ApiError(404, "资源不存在")
        base = self.server.static_dir
        try:
            target = (base / decoded).resolve()
            target.relative_to(base)
        except (OSError, ValueError) as exc:
            raise ApiError(404, "资源不存在") from exc
        if not target.is_file():
            raise ApiError(404, "资源不存在")
        content_type = (
            STATIC_TYPES.get(target.suffix.lower()) or "application/octet-stream"
        )
        try:
            body = target.read_bytes()
        except OSError as exc:
            raise ApiError(404, "资源不存在") from exc
        self._send_bytes(body, content_type, cache_control="no-cache")

    # -- request/response helpers ------------------------------------------

    def _require_method(self, actual: str, expected: str) -> None:
        if actual != expected:
            raise ApiError(405, f"该接口只支持 {expected} 请求")

    def _read_json(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length else 0
        except ValueError as exc:
            raise ApiError(400, "Content-Length 无效") from exc
        if length <= 0:
            raise ApiError(400, "请求体不能为空")
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "请求体过大")
        body = self.rfile.read(length)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "请求体必须是合法的 JSON") from exc

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(
            body,
            "application/json; charset=utf-8",
            status=status,
            cache_control="no-store",
        )

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        *,
        status: int = 200,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        LOGGER.info("%s - %s", self.address_string(), format % args)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    store: ConfigStore | None = None,
    static_dir: str | os.PathLike[str] = STATIC_DIR,
) -> WheelHTTPServer:
    """Create (but do not start) a configured HTTP server."""
    if store is None:
        store = ConfigStore(DEFAULT_DATA_DIR)
    return WheelHTTPServer((host, port), store, static_dir)


def _default_port() -> int:
    raw = os.environ.get("WHEEL_PORT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 8000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="可自定义奖品与概率的 Python 转盘抽奖网页游戏"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("WHEEL_HOST", "127.0.0.1"),
        help="监听地址（默认 127.0.0.1，仅本机可访问）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_default_port(),
        help="监听端口（默认 8000）",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("WHEEL_DATA_DIR", str(DEFAULT_DATA_DIR)),
        help="保存 config.json 的目录（默认 ./data）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    store = ConfigStore(args.data_dir)
    if store.warning:
        LOGGER.warning(store.warning)

    try:
        server = create_server(args.host, args.port, store)
    except OSError as exc:
        print(f"无法启动服务：{exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[:2]
    print()
    print("  幸运大转盘已启动")
    print(f"  地址：http://{host}:{port}/")
    print(f"  配置：{store.path}")
    print("  按 Ctrl+C 停止服务")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
