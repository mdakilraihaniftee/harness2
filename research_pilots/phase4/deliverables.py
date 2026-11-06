"""Conservative requested-deliverable extraction for installed benchmark tasks."""

from __future__ import annotations

import re
from pathlib import Path

_EXTENSIONS = "xlsx|xls|docx|pptx|pdf|csv|json|md|txt|py|db"
_QUOTED_FILE = re.compile(
    rf"[\"'`](?P<name>[^\"'`\n]{{1,120}}\.(?:{_EXTENSIONS}))[\"'`]", re.I
)
_TOKEN_FILE = re.compile(rf"(?<![\w./-])(?P<name>[\w][\w.-]*\.(?:{_EXTENSIONS}))\b", re.I)
_OUTPUT_CUE = re.compile(
    r"\b(produce|prepare|create|draft|generate|deliver|submit|save|write|record|complete)\b",
    re.I,
)


def _source_files(adapter, task_id: str) -> list[str]:
    root = adapter.task_files(task_id)
    if not root or not Path(root).is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in Path(root).rglob("*")
        if path.is_file() and path.name != "TASK_INSTRUCTIONS.txt"
    )


def _file_mentions(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    quoted_spans: list[tuple[int, int]] = []
    for match in _QUOTED_FILE.finditer(text):
        found.append((match.start(), match.group("name").strip()))
        quoted_spans.append(match.span())
    for match in _TOKEN_FILE.finditer(text):
        if any(start <= match.start() < end for start, end in quoted_spans):
            continue
        found.append((match.start(), match.group("name").strip()))
    return list(dict.fromkeys(name for _, name in sorted(found)))


def _description_clauses(text: str) -> list[str]:
    # The adapter appends a source inventory after this marker. It is input metadata, never an
    # output request, so remove it before examining imperative clauses.
    body = text.split("Local Reference Files:", 1)[0]
    clauses = re.split(r"(?<=[.!?])\s+|\n+", body)
    return [
        clause.strip()
        for clause in clauses
        if _OUTPUT_CUE.search(clause) and 8 <= len(clause.strip()) <= 600
    ]


def extract_deliverables(benchmark: str, adapter, task_id: str) -> dict:
    """Separate input filenames, exact requested outputs, descriptions and ambiguity."""
    prompt = adapter.task_prompt(task_id)
    sources = _source_files(adapter, task_id)
    source_names = {Path(name).name.casefold() for name in sources}

    if benchmark == "lab":
        raw = adapter._task_json(task_id)
        mapping = raw.get("deliverables") or {}
        exact = [str(name) for name in mapping]
        descriptions = [
            str(description).strip()
            for description in mapping.values()
            if str(description or "").strip()
        ]
    elif benchmark == "jb":
        mentions = _file_mentions(prompt.split("Local Reference Files:", 1)[0])
        exact = [name for name in mentions if Path(name).name.casefold() not in source_names]
        descriptions = _description_clauses(prompt)
    else:
        raise ValueError(f"unsupported benchmark {benchmark!r}")

    return {
        "provided_source_files": sources,
        "explicit_output_files": list(dict.fromkeys(exact)),
        "deliverable_descriptions": list(dict.fromkeys(descriptions)),
        "ambiguous_output_requirements": not bool(exact),
        "temporary_working_files": [],
        "method": (
            "LAB task.json deliverables mapping"
            if benchmark == "lab"
            else "JobBench imperative text before Local Reference Files; source basenames excluded"
        ),
    }

