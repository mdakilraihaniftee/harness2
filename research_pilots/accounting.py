"""Separate call and spend accounting for research-only live sessions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LiveBudget:
    max_usd: float = 20.0
    max_calls: int = 3
    calls: list[dict] = field(default_factory=list)

    @property
    def spent_usd(self) -> float:
        return round(sum(float(call.get("cost_usd") or 0) for call in self.calls), 6)

    def require_capacity(self) -> None:
        if len(self.calls) >= self.max_calls:
            raise RuntimeError(f"research live-call cap reached ({self.max_calls})")
        if self.spent_usd >= self.max_usd:
            raise RuntimeError(f"research spend cap reached (${self.max_usd:.2f})")

    def record(self, name: str, cost_usd: float, **metadata) -> None:
        self.calls.append({"name": name, "cost_usd": float(cost_usd), **metadata})
        if self.spent_usd > self.max_usd:
            raise RuntimeError(
                f"research spend cap exceeded: ${self.spent_usd:.4f} > ${self.max_usd:.2f}"
            )

    def to_dict(self) -> dict:
        return {
            "max_usd": self.max_usd,
            "max_calls": self.max_calls,
            "calls": self.calls,
            "spent_usd": self.spent_usd,
        }
