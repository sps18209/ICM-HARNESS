from __future__ import annotations

import json
import os
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

import anyio

from icm_harness.application import HarnessApplication
from icm_harness.kernel.contracts import TaskIntent, TaskProfile

MAX_REQUEST_BYTES = 64 * 1024
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class WebRuntime:
    def __init__(self, root: Path):
        self.root = root
        self._threads: dict[str, Thread] = {}
        self._lock = Lock()

    def app(self, *, dry_run: bool = False) -> HarnessApplication:
        return HarnessApplication(self.root, dry_run=dry_run)

    def start(self, round_id: str, *, dry_run: bool = False) -> bool:
        with self._lock:
            existing = self._threads.get(round_id)
            if existing and existing.is_alive():
                return False

            def worker() -> None:
                try:
                    anyio.run(self.app(dry_run=dry_run).run_round, round_id)
                finally:
                    with self._lock:
                        self._threads.pop(round_id, None)

            thread = Thread(target=worker, name=f"icm-{round_id}", daemon=True)
            self._threads[round_id] = thread
            thread.start()
            return True


class OperatorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, *, runtime: WebRuntime, token: str | None):
        super().__init__(address, handler)
        self.runtime = runtime
        self.token = token


class OperatorHandler(BaseHTTPRequestHandler):
    server: OperatorServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        print(f"web: {self.address_string()} - {format % args}")

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def do_GET(self) -> None:
        try:
            self._authorize(mutation=False)
            route = urlparse(self.path)
            if route.path == "/":
                self._static("index.html", "text/html; charset=utf-8")
                return
            if route.path == "/static/app.css":
                self._static("app.css", "text/css; charset=utf-8")
                return
            if route.path == "/static/app.js":
                self._static("app.js", "text/javascript; charset=utf-8")
                return
            if route.path == "/api/health":
                self._send_json({"status": "ok"})
                return
            if route.path == "/api/rounds":
                app = self.server.runtime.app()
                self._send_json([app.round_payload(item) for item in app.list_rounds()])
                return
            parts = self._parts(route.path)
            if len(parts) == 3 and parts[:2] == ["api", "rounds"]:
                self._round_detail(parts[2])
                return
            if len(parts) == 4 and parts[:2] == ["api", "rounds"] and parts[3] == "events":
                after = int(parse_qs(route.query).get("after", ["0"])[0])
                app = self.server.runtime.app()
                self._send_json([asdict(item) for item in app.events(parts[2], after_id=after)])
                return
            if len(parts) == 4 and parts[:2] == ["api", "rounds"] and parts[3] == "diff":
                content = self.server.runtime.app().diff_round(parts[2])
                self._send_json({"content": content})
                return
            if len(parts) == 3 and parts[:2] == ["api", "artifacts"]:
                record, content = self.server.runtime.app().read_artifact(int(parts[2]))
                payload = asdict(record)
                payload["content"] = content
                self._send_json(payload)
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        try:
            self._authorize(mutation=True)
            route = urlparse(self.path)
            body = self._body()
            if route.path == "/api/rounds":
                self._create_round(body)
                return
            parts = self._parts(route.path)
            if len(parts) == 4 and parts[:2] == ["api", "rounds"]:
                round_id, action = parts[2], parts[3]
                app = self.server.runtime.app(dry_run=bool(body.get("dry_run", False)))
                if action == "run":
                    started = self.server.runtime.start(
                        round_id, dry_run=bool(body.get("dry_run", False))
                    )
                    self._send_json({"started": started}, HTTPStatus.ACCEPTED)
                    return
                if action == "approve":
                    record = app.approve_round(round_id)
                elif action == "cancel":
                    record = app.cancel_round(round_id)
                elif action == "retry":
                    record = app.retry_round(round_id)
                elif action == "promote":
                    record = app.promote_round(round_id)
                else:
                    self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                if body.get("run"):
                    self.server.runtime.start(round_id, dry_run=bool(body.get("dry_run", False)))
                self._send_json(app.round_payload(record))
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._handle_error(exc)

    def _create_round(self, body: dict[str, Any]) -> None:
        objective = str(body.get("objective", "")).strip()
        if not objective:
            raise ValueError("objective is required")
        app = self.server.runtime.app(dry_run=bool(body.get("dry_run", False)))
        profile = TaskProfile(
            objective,
            intent=TaskIntent(body.get("intent", "auto")),
            specification_clarity=float(body.get("clarity", 0.5)),
            epistemic_uncertainty=float(body.get("uncertainty", 0.5)),
            stakes=float(body.get("stakes", 0.5)),
            reversibility=float(body.get("reversibility", 0.5)),
            production_change_required=bool(body.get("production_change", False)),
            code_intensity=float(body.get("code_intensity", 0.0)),
            research_intensity=float(body.get("research_intensity", 0.0)),
            tool_intensity=float(body.get("tool_intensity", 0.0)),
            privacy_restricted=bool(body.get("privacy_restricted", False)),
            budget_usd=(float(body["budget_usd"]) if body.get("budget_usd") is not None else None),
        )
        record = app.create_round(profile)
        if body.get("run"):
            self.server.runtime.start(record.round_id, dry_run=bool(body.get("dry_run", False)))
        self._send_json(app.round_payload(record), HTTPStatus.CREATED)

    def _round_detail(self, round_id: str) -> None:
        app = self.server.runtime.app()
        record = app.get_round(round_id)
        payload = app.round_payload(record)
        payload["events"] = [asdict(item) for item in app.events(round_id)]
        payload["artifacts"] = [asdict(item) for item in app.list_artifacts(round_id)]
        payload["promoted"] = any(item.kind == "round_promoted" for item in app.events(round_id))
        payload["workspace_diff"] = app.diff_round(round_id)[:100_000]
        self._send_json(payload)

    def _authorize(self, *, mutation: bool) -> None:
        token = self.server.token
        if token:
            header = self.headers.get("Authorization", "")
            if header != f"Bearer {token}":
                raise PermissionError("valid bearer token required")
        if mutation:
            origin = self.headers.get("Origin")
            if origin:
                host = self.headers.get("Host", "")
                if origin not in {f"http://{host}", f"https://{host}"}:
                    raise PermissionError("cross-origin requests are not allowed")

    def _body(self) -> dict[str, Any]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if size < 0 or size > MAX_REQUEST_BYTES:
            raise ValueError(f"request body exceeds {MAX_REQUEST_BYTES} bytes")
        if size == 0:
            return {}
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        payload = json.loads(self.rfile.read(size))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _static(self, name: str, media_type: str) -> None:
        content = resources.files("icm_harness.web").joinpath("static", name).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, PermissionError):
            status = HTTPStatus.FORBIDDEN
        elif isinstance(exc, KeyError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
            status = HTTPStatus.BAD_REQUEST
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status)

    @staticmethod
    def _parts(path: str) -> list[str]:
        return [part for part in path.split("/") if part]


def serve(root: str | Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    token = os.environ.get("ICM_WEB_TOKEN")
    if host not in LOOPBACK_HOSTS and not token:
        raise ValueError("ICM_WEB_TOKEN is required when binding outside loopback")
    runtime = WebRuntime(Path(root).resolve())
    server = OperatorServer((host, port), OperatorHandler, runtime=runtime, token=token)
    print(f"ICM operator console listening on http://{host}:{server.server_port}")
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
