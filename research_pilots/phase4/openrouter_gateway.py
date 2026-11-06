#!/usr/bin/env python3
"""Host-side, model-allowlisted OpenRouter gateway over a TLS Unix socket."""

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

from harness2 import config


class State:
    def __init__(self, model: str, max_requests: int, api_key: str):
        self.model = model.removeprefix("openrouter/")
        self.max_requests = max_requests
        self.api_key = api_key
        self.requests = 0
        self.lock = threading.Lock()

    def reserve(self) -> bool:
        with self.lock:
            if self.requests >= self.max_requests:
                return False
            self.requests += 1
            return True


def proxy_handler(state: State):
    class ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            if self.path not in ("/api/v1/chat/completions", "/api/v1/responses"):
                self.send_error(403, "gateway permits only OpenRouter generation endpoints")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 10 * 1024 * 1024:
                self.send_error(413, "invalid request size")
                return
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                self.send_error(400, "request must be JSON")
                return
            if payload.get("model") != state.model:
                self.send_error(403, "model is outside the configured allowlist")
                return
            if not state.reserve():
                self.send_error(429, "gateway request cap reached")
                return
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower()
                not in {
                    "authorization",
                    "connection",
                    "host",
                    "content-length",
                    "x-api-key",
                }
            }
            headers["Authorization"] = "Bearer " + state.api_key
            headers["Content-Length"] = str(len(body))
            connection = http.client.HTTPSConnection(
                "openrouter.ai", timeout=900, context=ssl.create_default_context()
            )
            try:
                connection.request("POST", self.path, body=body, headers=headers)
                response = connection.getresponse()
                self.send_response(response.status, response.reason)
                for key, value in response.getheaders():
                    if key.lower() not in {"connection", "keep-alive", "transfer-encoding"}:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
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
    parser.add_argument("--model", default=os.environ.get("HARNESS2_QWEN_MODEL"))
    parser.add_argument("--max-requests", type=int, default=20)
    parser.add_argument("--unix-socket", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    if not args.model:
        parser.error("--model or HARNESS2_QWEN_MODEL is required")
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        parser.error("OPENROUTER_API_KEY is required in the trusted host environment")
    if args.max_requests < 1 or args.max_requests > 20:
        parser.error("--max-requests must be in [1, 20] for the Phase 4 gate")
    state = State(args.model, args.max_requests, api_key)

    class ThreadingUnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    args.unix_socket.parent.mkdir(parents=True, exist_ok=True)
    args.unix_socket.unlink(missing_ok=True)
    server = ThreadingUnixHTTPServer(str(args.unix_socket), proxy_handler(state))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert, args.key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    args.ready_file.write_text("ready\n", encoding="utf-8")
    try:
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        args.unix_socket.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

