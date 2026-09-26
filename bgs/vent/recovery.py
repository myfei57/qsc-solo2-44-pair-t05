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
    window_capacity: int
    window_full: bool
    minimum: float | None
    floor: float
    all_above_floor: bool

    def describe(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "window_size": self.window_size,
            "window_capacity": self.window_capacity,
            "window_full": self.window_full,
            "window_remaining": max(0, self.window_capacity - self.window_size),
            "window_progress": (self.window_size / self.window_capacity) if self.window_capacity else 0.0,
            "minimum": self.minimum,
            "floor": self.floor,
            "all_above_floor": self.all_above_floor,
        }


def recovery_ready(window: SampleWindow, *, floor: float) -> RecoveryCheck:
    """Report whether the whole window sits at or above the floor.

    Releasing the latch needs every retained sample to be at or above the
    floor *and* a full window: a single good reading must never clear a
    latch that a whole low window set.
    """

    size = window.size()
    capacity = window.capacity
    full = window.is_full()
    minimum = window.minimum()
    all_above = window.all_at_least(floor)
    ready = full and all_above
    if size == 0:
        reason = "no quality readings since the flare opened"
    elif not all_above:
        reason = "quality window still holds readings below the floor"
    elif not full:
        reason = "quality window is not full yet"
    else:
        reason = "full quality window sits at or above the floor"
    return RecoveryCheck(ready, reason, size, capacity, full, minimum, floor, all_above)
