"""Recovery condition for the quality latch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..decision.window import SampleWindow


@dataclass(frozen=True, slots=True)
class RecoveryCheck:
    """Whether the quality window allows the latch to be released."""

    ready: bool
    reason: str
    window_size: int
    window_full: bool
    minimum: float | None
    floor: float

    def describe(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "window_size": self.window_size,
            "window_full": self.window_full,
            "minimum": self.minimum,
            "floor": self.floor,
        }


def recovery_ready(window: SampleWindow, *, floor: float) -> RecoveryCheck:
    """Report whether the newest reading sits above the floor."""

    minimum = window.minimum()
    full = window.is_full()
    ready = window.size() > 0
    return RecoveryCheck(ready, "newest reading is above the floor" if ready else "still low", window.size(), full, minimum, floor)
