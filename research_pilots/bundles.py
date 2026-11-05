"""Minimal file-level candidate recombination with existing tree validation."""

from __future__ import annotations

from dataclasses import dataclass

from harness2.core import tree as harness_tree
from harness2.core.tree import SurfaceSpec, Tree


@dataclass(frozen=True)
class FileEdit:
    candidate: str
    path: str
    before: str | None
    after: str | None


def edits_from(base: Tree, candidate: Tree, name: str) -> list[FileEdit]:
    edits = []
    for path in sorted(set(base) | set(candidate)):
        before = base.get(path)
        after = candidate.get(path)
        if before != after:
            edits.append(FileEdit(name, path, before, after))
    return edits


def combine(
    surface: SurfaceSpec,
    base: Tree,
    candidates: dict[str, Tree],
    names: list[str],
    *,
    allow_subagents: bool = False,
) -> Tree:
    """Apply non-conflicting file edits relative to one base, then validate exactly once."""
    merged = dict(base)
    claimed: dict[str, FileEdit] = {}
    for name in names:
        if name not in candidates:
            raise ValueError(f"unknown candidate {name!r}")
        for edit in edits_from(base, candidates[name], name):
            prior = claimed.get(edit.path)
            if prior and prior.after != edit.after:
                raise ValueError(
                    f"conflicting edits to {edit.path}: {prior.candidate} vs {edit.candidate}"
                )
            claimed[edit.path] = edit
            if edit.after is None:
                merged.pop(edit.path, None)
            else:
                merged[edit.path] = edit.after
    harness_tree.validate(surface, merged, allow_subagents=allow_subagents)
    return merged
