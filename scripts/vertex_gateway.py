#!/usr/bin/env python3
"""Local Vertex-only gateway for an isolated Harness² agent.

The metadata endpoint returns a non-secret placeholder token. The HTTPS reverse
proxy replaces it with a host-side ADC token and only forwards Vertex prediction
paths for one configured project and location.
"""

from __future__ import annotations

import argparse
import http.client
import json
import socketserver
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class State:
    def __init__(self, project: str, location: str):
        self.project = project
        self.location = location
        self.token = ""
        self.refreshed = 0.0
        self.lock = threading.Lock()

    @property
    def upstream(self) -> str:
        return (
            "aiplatform.googleapis.com"
            if self.location == "global"
            else f"{self.location}-aiplatform.googleapis.com"
        )

    def access_token(self, *, force: bool = False) -> str:
        with self.lock:
            if force or time.monotonic() - self.refreshed > 1200:
                result = subprocess.run(
                    ["gcloud", "auth", "application-default", "print-access-token"],
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                if result.returncode or not result.stdout.strip():
                    raise RuntimeError("ADC token refresh failed")
                self.token = result.stdout.strip()
                self.refreshed = time.monotonic()
            return self.token


def metadata_handler(state: State):
    class MetadataHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Metadata-Flavor") != "Google":
                self.send_error(403)
                return
            if self.path == "/computeMetadata/v1/project/project-id":
                body = state.project.encode()
                content_type = "text/plain"
            elif self.path.startswith(
                "/computeMetadata/v1/instance/service-accounts/default/token"
            ):
                body = json.dumps(
                    {"access_token": "harness2-gateway", "expires_in": 3600, "token_type": "Bearer"}
                ).encode()
                content_type = "application/json"
            elif self.path == "/computeMetadata/v1/instance/service-accounts/":
                body = b"default/\n"
                content_type = "text/plain"
            elif self.path.startswith("/computeMetadata/v1/instance/service-accounts/default/"):
                body = json.dumps(
                    {
                        "email": "default",
                        "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
                    }
                ).encode()
                content_type = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Metadata-Flavor", "Google")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    return MetadataHandler


def proxy_handler(state: State):
    allowed_prefixes = tuple(
        f"/{version}/projects/{state.project}/locations/{state.location}/publishers/"
        for version in ("v1", "v1beta1")
    )

    class ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            if not self.path.startswith(allowed_prefixes) or not any(
                operation in self.path
                for operation in (":generateContent", ":streamGenerateContent")
            ):
                self.send_error(403, "gateway only permits configured Vertex generation paths")
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower()
                not in {
                    "authorization",
                    "connection",
                    "host",
                    "content-length",
                    "x-goog-api-key",
                }
            }
            headers["Authorization"] = "Bearer " + state.access_token()
            headers["Content-Length"] = str(len(body))
            connection = http.client.HTTPSConnection(
                state.upstream, timeout=900, context=ssl.create_default_context()
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="global")
    parser.add_argument("--metadata-port", type=int, required=True)
    parser.add_argument("--vertex-port", type=int, required=True)
    parser.add_argument("--unix-socket", type=Path)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    state = State(args.project, args.location)
    state.access_token()
    metadata = ThreadingHTTPServer(("127.0.0.1", args.metadata_port), metadata_handler(state))
    proxy = ThreadingHTTPServer(("127.0.0.1", args.vertex_port), proxy_handler(state))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    proxy.socket = context.wrap_socket(proxy.socket, server_side=True)
    servers = [metadata, proxy]
    if args.unix_socket:

        class ThreadingUnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        args.unix_socket.parent.mkdir(parents=True, exist_ok=True)
        args.unix_socket.unlink(missing_ok=True)
        unix_proxy = ThreadingUnixHTTPServer(str(args.unix_socket), proxy_handler(state))
        unix_proxy.socket = context.wrap_socket(unix_proxy.socket, server_side=True)
        servers.append(unix_proxy)
    threads = [
        threading.Thread(target=metadata.serve_forever, daemon=True),
        threading.Thread(target=proxy.serve_forever, daemon=True),
    ]
    if args.unix_socket:
        threads.append(threading.Thread(target=unix_proxy.serve_forever, daemon=True))
    for thread in threads:
        thread.start()
    args.ready_file.write_text("ready\n")
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown()
        if args.unix_socket:
            args.unix_socket.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
