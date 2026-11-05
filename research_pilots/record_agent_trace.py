"""Relay agent JSONL while retaining research-only usage and sanitized tool telemetry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _part(event: dict) -> dict:
    value = event.get("part")
    return value if isinstance(value, dict) else event


def _clip(value, limit: int = 4_000):
    if value is None:
        return None
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"...<{len(text) - limit} chars omitted>"


def tool_event(event: dict, workspace: Path) -> dict | None:
    part = _part(event)
    kind = part.get("type") or event.get("type")
    if kind not in ("tool", "tool_use", "tool_call", "tool-invocation"):
        return None
    state = part.get("state") if isinstance(part.get("state"), dict) else part
    invocation = part.get("toolInvocation") or {}
    name = part.get("tool") or event.get("tool") or part.get("name")
    name = name or invocation.get("toolName") or "tool"
    raw_input = state.get("input") or part.get("input") or part.get("args")
    rendered_input = _clip(raw_input)
    if rendered_input:
        rendered_input = rendered_input.replace(str(workspace), "$WORKSPACE")
    output = state.get("output") or state.get("result") or part.get("output")
    error = state.get("error") or event.get("error")
    return {
        "call_id": part.get("id") or part.get("callID") or invocation.get("toolCallId"),
        "tool": str(name),
        "status": str(state.get("status") or ""),
        "input": rendered_input,
        "had_output": output is not None,
        "output_chars": len(str(output)) if output is not None else 0,
        "error": _clip(error, 1_000),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", required=True)
    parser.add_argument("--bun", required=True)
    parser.add_argument("--telemetry", required=True, type=Path)
    args, agent_args = parser.parse_known_args()
    if agent_args[:1] == ["--"]:
        agent_args = agent_args[1:]
    workspace = Path.cwd()
    if "--dir" in agent_args:
        workspace = Path(agent_args[agent_args.index("--dir") + 1]).resolve()
    command = [args.launcher, "--workspace", str(workspace), "--", args.bun, *agent_args]
    args.telemetry.mkdir(parents=True, exist_ok=True)
    trace_id = uuid4().hex
    event_path = args.telemetry / f"{trace_id}.events.jsonl"
    record_path = args.telemetry / f"{trace_id}.json"
    started = time.monotonic()
    record = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "raw_event_log": str(event_path),
        "usage_events": [],
        "tool_events": [],
    }
    with event_path.open("wb") as raw_stream:
        with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
            assert process.stdout is not None
            for line in process.stdout:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
                raw_stream.write(line)
                raw_stream.flush()
                try:
                    event = json.loads(line)
                    part = _part(event)
                    if (part.get("type") or event.get("type")) in (
                        "step-finish",
                        "step_finish",
                    ):
                        record["usage_events"].append(
                            {"tokens": part.get("tokens"), "cost_usd": part.get("cost")}
                        )
                    parsed = tool_event(event, workspace)
                    if parsed:
                        record["tool_events"].append(parsed)
                except (ValueError, AttributeError):
                    pass
            code = process.wait()
    record.update(exit_code=code, wall_s=round(time.monotonic() - started, 3))
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
