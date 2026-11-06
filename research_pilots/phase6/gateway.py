#!/usr/bin/env python3
"""Phase 6 exact-model zero-cost gateway using the audited model allowlist."""

from __future__ import annotations

import argparse
import json
import os
import socketserver
import ssl
from pathlib import Path

from harness2 import config
from research_pilots.phase5.zero_cost_gateway import State, proxy_handler

from . import MODEL_CANDIDATES, RESULTS


def main() -> int:
    config.load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-requests", type=int, default=42)
    parser.add_argument("--unix-socket", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    args = parser.parse_args()
    audit_path = RESULTS / "model_audit.json"
    if not audit_path.is_file():
        parser.error("run the Phase 6 read-only model audit first")
    audit = json.loads(audit_path.read_text())
    eligible = {
        row.get("model_ref")
        for row in audit.get("candidates", [])
        if row.get("eligible")
    }
    if audit.get("status") != "PASS" or args.model not in eligible:
        parser.error("model did not pass the Phase 6 zero-price audit")
    if args.model not in MODEL_CANDIDATES:
        parser.error("model is outside the Phase 6 candidate allowlist")
    if not 1 <= args.max_requests <= 35:
        parser.error("--max-requests must be in [1, 35]")
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
