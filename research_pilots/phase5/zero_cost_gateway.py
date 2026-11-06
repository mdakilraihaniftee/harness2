#!/usr/bin/env python3
"""Exact-model OpenRouter proxy enforcing Phase 5 zero-price request constraints."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socketserver
import ssl
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from harness2 import config

from . import FALLBACK_MODEL


def _json_objects(body: bytes) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for raw in body.decode("utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if raw.startswith("data:"):
            raw = raw[5:].strip()
        if not raw or raw == "[DONE]" or not raw.startswith("{"):
            continue
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    if not objects:
        try:
            value = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            value = None
        if isinstance(value, dict):
            objects.append(value)
    return objects


def response_telemetry(body: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "actual_models": [],
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
    }
    for item in _json_objects(body):
        model = item.get("model")
        if isinstance(model, str) and model not in result["actual_models"]:
            result["actual_models"].append(model)
        usage = item.get("usage")
        if not isinstance(usage, dict):
            continue
        for field in ("cost", "cost_usd"):
            value = usage.get(field)
            if isinstance(value, (int, float)):
                result["cost_usd"] = max(result["cost_usd"], float(value))
        mapping = {
            "prompt_tokens": "input_tokens",
            "completion_tokens": "output_tokens",
            "reasoning_tokens": "reasoning_tokens",
            "cached_tokens": "cache_read_tokens",
        }
        for source, target in mapping.items():
            value = usage.get(source)
            if isinstance(value, int):
                result[target] = max(result[target], value)
        prompt_details = usage.get("prompt_tokens_details")
        if isinstance(prompt_details, dict) and isinstance(prompt_details.get("cached_tokens"), int):
            result["cache_read_tokens"] = max(
                result["cache_read_tokens"], prompt_details["cached_tokens"]
            )
        completion_details = usage.get("completion_tokens_details")
        if isinstance(completion_details, dict) and isinstance(
            completion_details.get("reasoning_tokens"), int
        ):
            result["reasoning_tokens"] = max(
                result["reasoning_tokens"], completion_details["reasoning_tokens"]
            )
    return result


class State:
    def __init__(self, model: str, max_requests: int, api_key: str, events: Path):
        self.model = model.removeprefix("openrouter/")
        self.max_requests = max_requests
        self.api_key = api_key
        self.events = events
        self.requests = 0
        self.blocked = False
        self.lock = threading.Lock()
        events.parent.mkdir(parents=True, exist_ok=True)
        events.touch(mode=0o600, exist_ok=True)
        events.chmod(0o600)

    def reserve(self) -> bool:
        with self.lock:
            if self.blocked or self.requests >= self.max_requests:
                return False
            self.requests += 1
            return True

    def record(self, event: dict[str, Any]) -> None:
        if float(event.get("cost_usd") or 0) > 0:
            self.blocked = True
        with self.events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")


def constrain_payload(payload: dict[str, Any], expected_model: str) -> dict[str, Any]:
    if payload.get("model") != expected_model:
        raise ValueError("model is outside the exact free-model allowlist")
    if "models" in payload:
        raise ValueError("model-level fallback is forbidden")
    if payload.get("plugins") or payload.get("web_search_options"):
        raise ValueError("paid or external plugins are forbidden")
    provider = payload.get("provider")
    if provider is not None and not isinstance(provider, dict):
        raise ValueError("provider routing must be an object")
    provider = dict(provider or {})
    # Do not accept caller-supplied alternates or cost relaxation.
    for field in ("order", "only", "ignore"):
        if field in provider:
            raise ValueError(f"caller-controlled provider.{field} routing is forbidden")
    provider.update(
        {
            "allow_fallbacks": False,
            "max_price": {"prompt": 0, "completion": 0, "image": 0, "request": 0},
        }
    )
    payload["provider"] = provider
    usage = payload.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("usage must be an object")
    payload["usage"] = {**(usage or {}), "include": True}
    return payload


def proxy_handler(state: State):
    class ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            if self.path not in ("/api/v1/chat/completions", "/api/v1/responses"):
                self.send_error(403, "only generation endpoints are permitted")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 10 * 1024 * 1024:
                self.send_error(413, "invalid request size")
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("request must be an object")
                payload = constrain_payload(payload, state.model)
            except (ValueError, UnicodeDecodeError) as exc:
                self.send_error(403, str(exc))
                return
            if not state.reserve():
                self.send_error(429, "zero-cost request cap reached or gateway stopped")
                return
            body = json.dumps(payload, separators=(",", ":")).encode()
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower()
                not in {"authorization", "connection", "host", "content-length", "x-api-key"}
            }
            headers.update(
                {"Authorization": "Bearer " + state.api_key, "Content-Length": str(len(body))}
            )
            connection = http.client.HTTPSConnection(
                "openrouter.ai", timeout=900, context=ssl.create_default_context()
            )
            response_body = bytearray()
            status = 599
            try:
                connection.request("POST", self.path, body=body, headers=headers)
                response = connection.getresponse()
                status = response.status
                self.send_response(response.status, response.reason)
                for key, value in response.getheaders():
                    if key.lower() not in {
                        "connection",
                        "keep-alive",
                        "transfer-encoding",
                        "content-length",
                    }:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                while chunk := response.read(64 * 1024):
                    if len(response_body) < 20 * 1024 * 1024:
                        response_body.extend(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
                telemetry = response_telemetry(bytes(response_body))
                state.record(
                    {
                        "request_number": state.requests,
                        "requested_model": state.model,
                        "http_status": status,
                        **telemetry,
                    }
                )
                connection.close()
                self.close_connection = True

        def do_GET(self):
            self.send_error(404)

        def log_message(self, _format, *_args):
            return

    return ProxyHandler


def main() -> int:
    config.load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=FALLBACK_MODEL)
    parser.add_argument("--max-requests", type=int, default=26)
    parser.add_argument("--unix-socket", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    args = parser.parse_args()
    if args.model != FALLBACK_MODEL:
        parser.error(f"Phase 5 gateway permits only {FALLBACK_MODEL}")
    if not 1 <= args.max_requests <= 26:
        parser.error("--max-requests must be in [1, 26]")
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        parser.error("OPENROUTER_API_KEY is required in the trusted host environment")
    state = State(args.model, args.max_requests, api_key, args.events)

    class ThreadingUnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    args.unix_socket.parent.mkdir(parents=True, exist_ok=True)
    args.unix_socket.unlink(missing_ok=True)
    server = ThreadingUnixHTTPServer(str(args.unix_socket), proxy_handler(state))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert, args.key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    args.ready_file.write_text("ready\n", encoding="utf-8")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        args.unix_socket.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
