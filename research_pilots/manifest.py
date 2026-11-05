"""Research-only compact evidence interface for controlled composer experiments."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from harness2.core.proposer import Reply

INTERFACE = "COMPACT_MANIFEST"
MANIFEST_NAME = "EVIDENCE_MANIFEST.md"
DEFAULT_MAX_TOKENS = 4_000
INTERFACE_NOTE = """
# RESEARCH EVIDENCE INTERFACE

Read `context/EVIDENCE_MANIFEST.md` first. It faithfully consolidates every base rollout and
candidate's identifier, scope, exact changed-file contents, visible execution result, and paths
to the original evidence. Reading every entry in that manifest satisfies the inventory and
inspect-each-candidate-once requirements. Open the referenced original files only when the
manifest leaves a material ambiguity. All composition and evidence-weighing rules above are
unchanged.
""".strip()

_DECISION_LINE = re.compile(r"^(kept|revised|dropped)\s*->\s*.+\s*->\s*.+$", re.I)
_FORBIDDEN = (
    "hidden_utility",
    "expected_utility",
    "required_bundle",
    "pave_hidden_state",
    "cite_reference",
    "candidate a+b is correct",
    "reference repair",
)


@dataclass(frozen=True)
class ManifestBuild:
    path: Path
    sha256: str
    characters: int
    estimated_tokens: int
    candidate_ids: tuple[str, ...]
    referenced_paths: tuple[str, ...]
    condition_token: str
    provenance_visible: bool

    def to_dict(self) -> dict:
        return {
            "interface": INTERFACE,
            "sha256": self.sha256,
            "characters": self.characters,
            "estimated_tokens": self.estimated_tokens,
            "candidate_ids": list(self.candidate_ids),
            "referenced_paths": list(self.referenced_paths),
            "condition_token": self.condition_token,
            "provenance_visible": self.provenance_visible,
        }


def _files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _edits(base: Mapping[str, str], candidate: Mapping[str, str]) -> list[dict]:
    edits = []
    for path in sorted(set(base) | set(candidate)):
        before = base.get(path)
        after = candidate.get(path)
        if before == after:
            continue
        operation = "add" if before is None else "delete" if after is None else "modify"
        edits.append(
            {"path": path, "operation": operation, "before": before, "after": after}
        )
    return edits


def _visible_errors(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if re.search(r"\b(ERROR|FAILED|FAILURE)\b", line, re.I)
    ]


def _ref(root: Path, path: Path) -> str:
    return "context/" + path.relative_to(root).as_posix()


def build_manifest(
    context_root: Path,
    *,
    candidate_scopes: Mapping[str, str],
    condition_token: str,
    source_ids: Mapping[str, str] | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ManifestBuild:
    """Summarize only already-visible context evidence; keep all original files in place."""
    root = Path(context_root)
    if not root.is_dir():
        raise ValueError(f"context root does not exist: {root}")
    if not condition_token.strip():
        raise ValueError("condition_token must be a nonempty opaque identifier")
    base_dir = root / "harness"
    pool_dir = root / "pool"
    base = _files(base_dir)
    candidates = sorted(path.name for path in pool_dir.iterdir() if path.is_dir())
    if set(candidates) != set(candidate_scopes):
        raise ValueError(
            f"candidate scope map does not match pool: {sorted(candidate_scopes)} vs {candidates}"
        )

    refs: list[str] = ["context/task.md"]
    lines = [
        "# Compact composer evidence manifest",
        "",
        f"- Interface: `{INTERFACE}`",
        "- Base harness identifier: `base`",
        f"- Evidence condition token: `{condition_token}`",
        "- Original evidence remains authoritative at the paths listed below.",
        "",
        "## Task instruction",
        "",
        (root / "task.md").read_text(encoding="utf-8", errors="replace").strip(),
        "",
        "## Base executions",
        "",
    ]
    for path in sorted((root / "rollouts").glob("*.md")):
        label = path.stem
        rel = _ref(root, path)
        refs.append(rel)
        lines += [f"### `{label}`", "", f"- Original trajectory: `{rel}`"]
        deliverable = root / "deliverables" / label
        if deliverable.is_dir():
            dref = _ref(root, deliverable)
            refs.append(dref)
            lines.append(f"- Original deliverables: `{dref}/`" )
        if source_ids and label in source_ids:
            lines.append(f"- Evidence source identifier: `{source_ids[label]}`")
        body = path.read_text(encoding="utf-8", errors="replace").strip()
        lines += ["- Visible execution record:", "", "```text", body, "```", ""]

    lines += ["## Candidate harnesses", ""]
    for candidate_id in candidates:
        candidate_root = pool_dir / candidate_id
        harness_root = candidate_root / "harness"
        trajectory = candidate_root / "rollout.md"
        produced = candidate_root / "produced.md"
        diff = candidate_root / "harness.diff"
        for path in (trajectory, produced, diff):
            if not path.is_file():
                raise ValueError(f"candidate {candidate_id} is missing {path.name}")
        candidate = _files(harness_root)
        edits = _edits(base, candidate)
        if not edits:
            edits_note = "[]"
        else:
            edits_note = json.dumps(edits, indent=2, ensure_ascii=False)
        trajectory_text = trajectory.read_text(encoding="utf-8", errors="replace").strip()
        important = _visible_errors(trajectory_text)
        changed_paths = ", ".join(f"`{edit['path']}`" for edit in edits) or "(none)"
        tref, pref, dref, href = (
            _ref(root, trajectory),
            _ref(root, produced),
            _ref(root, diff),
            _ref(root, harness_root),
        )
        refs.extend((tref, pref, dref, href))
        lines += [
            f"### Candidate `{candidate_id}`",
            "",
            f"- Scope: `{candidate_scopes[candidate_id].upper()}`",
            f"- Changed paths: {changed_paths}",
            f"- Original trajectory: `{tref}`",
            f"- Original produced artifact: `{pref}`",
            f"- Original unified diff: `{dref}`",
            f"- Full candidate harness: `{href}/`",
        ]
        if source_ids and candidate_id in source_ids:
            lines.append(f"- Evidence source identifier: `{source_ids[candidate_id]}`")
        lines += [
            f"- Important visible errors: {json.dumps(important, ensure_ascii=False)}",
            "- Exact reconstructable file edits (`null` means absent):",
            "",
            "```json",
            edits_note,
            "```",
            "",
            "- Visible execution record:",
            "",
            "```text",
            trajectory_text,
            "```",
            "",
        ]

    body = "\n".join(lines).rstrip() + "\n"
    lowered = body.lower()
    leaked = [term for term in _FORBIDDEN if term in lowered]
    if leaked:
        raise ValueError(f"manifest contains prohibited hidden-evidence marker(s): {leaked}")
    estimated_tokens = (len(body) + 3) // 4
    if estimated_tokens > int(max_tokens):
        raise ValueError(
            f"manifest estimate {estimated_tokens} tokens exceeds bound {int(max_tokens)}"
        )
    path = root / MANIFEST_NAME
    path.write_text(body, encoding="utf-8")
    build = ManifestBuild(
        path=path,
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        characters=len(body),
        estimated_tokens=estimated_tokens,
        candidate_ids=tuple(candidates),
        referenced_paths=tuple(dict.fromkeys(refs)),
        condition_token=condition_token,
        provenance_visible=bool(source_ids),
    )
    return build


def assert_references_accessible(build: ManifestBuild) -> None:
    root = build.path.parent
    for ref in build.referenced_paths:
        if not ref.startswith("context/"):
            raise AssertionError(f"manifest reference is outside context: {ref}")
        target = root / ref.removeprefix("context/").rstrip("/")
        if not target.exists():
            raise AssertionError(f"manifest reference is missing: {ref}")


def explicit_decision(text: str) -> bool:
    match = re.search(r"<notes>(.*?)</notes>", text or "", re.S | re.I)
    if not match:
        return False
    decisions = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    return bool(decisions) and all(_DECISION_LINE.match(line) for line in decisions)


def manifest_edits(text: str) -> dict[str, list[dict]]:
    """Parse the exact edit records emitted by :func:`build_manifest`."""
    pattern = re.compile(
        r"^### Candidate `([^`]+)`.*?^```json\n(.*?)\n```", re.M | re.S
    )
    return {candidate: json.loads(body) for candidate, body in pattern.findall(text)}


def reconstruct(base: Mapping[str, str], edits: list[dict]) -> dict[str, str]:
    """Reconstruct one candidate from manifest edits, checking every stated before value."""
    tree = dict(base)
    for edit in edits:
        path = str(edit["path"])
        if tree.get(path) != edit.get("before"):
            raise ValueError(f"before content does not match base for {path}")
        after = edit.get("after")
        if after is None:
            tree.pop(path, None)
        else:
            tree[path] = str(after)
    return tree


class ManifestProposer:
    """Duck-typed Proposer wrapper that changes only the research evidence interface."""

    def __init__(
        self,
        delegate,
        *,
        candidate_scopes: Mapping[str, str],
        condition_token: str,
        source_ids: Mapping[str, str] | None = None,
        artifact_dir: Path | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self.delegate = delegate
        self.spec = delegate.spec
        self.candidate_scopes = dict(candidate_scopes)
        self.condition_token = condition_token
        self.source_ids = dict(source_ids or {}) or None
        self.artifact_dir = Path(artifact_dir) if artifact_dir else None
        self.max_tokens = max_tokens
        self.builds: list[ManifestBuild] = []
        self.replies: list[Reply] = []

    def call(self, mission: str, context_dir: Path, label: str, **kwargs) -> Reply:
        built = build_manifest(
            Path(context_dir),
            candidate_scopes=self.candidate_scopes,
            condition_token=self.condition_token,
            source_ids=self.source_ids,
            max_tokens=self.max_tokens,
        )
        assert_references_accessible(built)
        self.builds.append(built)
        if self.artifact_dir:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
            shutil.copy2(built.path, self.artifact_dir / f"{safe}.manifest.md")
            (self.artifact_dir / f"{safe}.manifest.json").write_text(
                json.dumps(built.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
        reply = self.delegate.call(mission + "\n\n" + INTERFACE_NOTE, context_dir, label, **kwargs)
        self.replies.append(reply)
        return reply
