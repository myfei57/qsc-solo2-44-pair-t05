"""Quality latch, flare line and storage inlet."""

from __future__ import annotations

import pytest

from bgs.errors import InterlockBlockedError, OrderViolationError, OverLimitError


def test_low_methane_sets_the_quality_latch(runtime, drive):
    drive()

    runtime.dispatch("mem.analyze", {"methane": 90.0})

    assert runtime.health()["latched"]["vent"] is True
    assert runtime.state()["lines"]["vent"]["phase"] == "quality_alarm"
    assert runtime.alarms.count() == 1


def test_flare_opens_the_line_after_the_latch(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})

    runtime.dispatch("vent.flare", {"reason": "methane low"})

    state = runtime.state()
    assert state["lines"]["vent"]["phase"] == "flaring"
    assert state["subsystems"]["vent"]["flaring"] is True


def test_flare_before_the_latch_is_rejected_as_out_of_order(runtime, drive):
    drive()

    with pytest.raises(OrderViolationError) as caught:
        runtime.dispatch("vent.flare", {"reason": "no alarm"})

    assert caught.value.context["required_phase"] == "quality_alarm"


def test_recovery_before_flaring_is_rejected_as_out_of_order(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})

    with pytest.raises(OrderViolationError):
        runtime.dispatch("vent.recover", {})


def test_latch_clears_only_after_the_quality_window_recovers(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})
    runtime.dispatch("vent.flare", {"reason": "methane low"})

    with pytest.raises(InterlockBlockedError) as caught:
        runtime.dispatch("vent.recover", {})

    assert caught.value.context["ready"] is False

    for _ in range(8):
        runtime.advance_ticks(1)
        runtime.dispatch("mem.analyze", {"methane": 97.0})

    runtime.dispatch("vent.recover", {})

    assert runtime.health()["latched"]["vent"] is False
    assert runtime.state()["lines"]["vent"]["phase"] == "recovered"


def test_a_single_good_reading_does_not_clear_the_latch(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})
    runtime.dispatch("vent.flare", {"reason": "methane low"})

    # The reading that raised the alarm still sits in the recovery window;
    # one good reading on top of it must not clear the latch.
    runtime.advance_ticks(1)
    runtime.dispatch("mem.analyze", {"methane": 97.0})

    with pytest.raises(InterlockBlockedError) as caught:
        runtime.dispatch("vent.recover", {})

    context = caught.value.context
    assert context["ready"] is False
    assert context["window_full"] is False
    assert context["all_above_floor"] is False
    assert context["window_size"] == 2
    assert context["window_remaining"] == 2
    assert context["window_capacity"] == context["window_size"] + context["window_remaining"]
    assert runtime.health()["latched"]["vent"] is True


def test_recovery_waits_for_a_full_window_even_when_every_sample_is_good(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})
    runtime.dispatch("vent.flare", {"reason": "methane low"})

    # Drop the alarm reading out of the span, then fill the window with good
    # samples one at a time: partial windows stay blocked, the full one clears.
    runtime.advance_ticks(5)
    runtime.dispatch("mem.analyze", {"methane": 97.0})
    progress = runtime.state()["subsystems"]["vent"]["recovery"]
    assert progress["window_size"] == 1
    assert progress["all_above_floor"] is True
    assert progress["window_full"] is False
    with pytest.raises(InterlockBlockedError) as caught:
        runtime.dispatch("vent.recover", {})
    assert caught.value.context["ready"] is False

    for _ in range(3):
        runtime.advance_ticks(1)
        runtime.dispatch("mem.analyze", {"methane": 97.0})

    runtime.dispatch("vent.recover", {})
    assert runtime.health()["latched"]["vent"] is False


def test_recovery_needs_every_sample_in_the_full_window_above_the_floor(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})
    runtime.dispatch("vent.flare", {"reason": "methane low"})

    # Three good samples fill most of the window; one stale low reading still sits in it.
    runtime.advance_ticks(1)
    runtime.dispatch("mem.analyze", {"methane": 97.0})
    runtime.advance_ticks(1)
    runtime.dispatch("mem.analyze", {"methane": 90.0})
    runtime.advance_ticks(1)
    runtime.dispatch("mem.analyze", {"methane": 97.0})
    runtime.advance_ticks(1)
    runtime.dispatch("mem.analyze", {"methane": 97.0})

    with pytest.raises(InterlockBlockedError) as caught:
        runtime.dispatch("vent.recover", {})

    context = caught.value.context
    assert context["ready"] is False
    assert context["window_full"] is True
    assert context["all_above_floor"] is False
    assert context["minimum"] == 90.0

    for _ in range(4):
        runtime.advance_ticks(1)
        runtime.dispatch("mem.analyze", {"methane": 97.0})

    runtime.dispatch("vent.recover", {})
    assert runtime.health()["latched"]["vent"] is False


def test_recover_is_blocked_in_quality_alarm_even_when_a_flare_record_lingers(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})
    runtime.dispatch("vent.flare", {"reason": "methane low"})
    for _ in range(4):
        runtime.advance_ticks(1)
        runtime.dispatch("mem.analyze", {"methane": 97.0})
    runtime.dispatch("vent.recover", {})

    # Quality drops again: the line rewinds to quality_alarm while the old
    # flare record remains active in the derived state.
    runtime.advance_ticks(1)
    runtime.dispatch("mem.analyze", {"methane": 90.0})

    state = runtime.state()
    assert state["lines"]["vent"]["phase"] == "quality_alarm"
    assert state["subsystems"]["vent"]["flaring"] is True

    with pytest.raises(OrderViolationError):
        runtime.dispatch("vent.recover", {})


def test_vent_status_reports_the_recovery_window_progress(runtime, drive):
    drive()
    runtime.dispatch("mem.analyze", {"methane": 90.0})
    runtime.dispatch("vent.flare", {"reason": "methane low"})

    # The reading that raised the alarm already sits in the window.
    recovery = runtime.state()["subsystems"]["vent"]["recovery"]
    assert recovery["window_size"] == 1
    assert recovery["window_capacity"] == 4
    assert recovery["window_full"] is False
    assert recovery["window_remaining"] == 3
    assert recovery["window_progress"] == 0.25
    assert recovery["ready"] is False
    assert recovery["floor"] == 96.0

    for _ in range(2):
        runtime.advance_ticks(1)
        runtime.dispatch("mem.analyze", {"methane": 97.0})

    recovery = runtime.state()["subsystems"]["vent"]["recovery"]
    assert recovery["window_size"] == 3
    assert recovery["window_remaining"] == 1
    assert recovery["window_progress"] == 0.75
    assert recovery["ready"] is False


def test_gas_inlet_is_blocked_while_the_quality_latch_is_set(runtime, drive):
    drive(inlet=False)
    runtime.dispatch("mem.analyze", {"methane": 90.0})

    with pytest.raises(InterlockBlockedError) as caught:
        runtime.dispatch("gas.inlet_open", {})

    assert "vent.latched" in caught.value.context["missing"]


def test_gas_inlet_is_blocked_while_the_vessel_latch_is_set(runtime, drive):
    drive(inlet=False)
    with pytest.raises(OverLimitError):
        runtime.dispatch("digester.pressure", {"kpa": 30.0})

    with pytest.raises(InterlockBlockedError) as caught:
        runtime.dispatch("gas.inlet_open", {})

    assert "digester.latched" in caught.value.context["missing"]


def test_storage_above_the_pressure_bound_is_rejected(runtime, drive):
    drive()

    with pytest.raises(OverLimitError) as caught:
        runtime.dispatch("gas.store", {"volume_m3": 120.0, "pressure_kpa": 30.0})

    assert caught.value.context["limit"] == 24.0


def test_storing_before_the_inlet_opens_is_rejected_as_out_of_order(runtime, drive):
    drive(inlet=False)

    with pytest.raises(OrderViolationError):
        runtime.dispatch("gas.store", {"volume_m3": 120.0, "pressure_kpa": 20.0})


def test_reopening_the_inlet_without_closing_it_is_rejected(runtime, drive):
    drive()

    with pytest.raises(OrderViolationError):
        runtime.dispatch("gas.inlet_open", {})


def test_inlet_can_be_closed_and_sealed(runtime, drive):
    drive()

    runtime.dispatch("gas.inlet_close", {})

    state = runtime.state()
    assert state["lines"]["gas"]["phase"] == "sealed"
    assert state["subsystems"]["gas"]["inlet_open"] is False


def test_closing_an_inlet_that_never_opened_is_blocked(runtime):
    with pytest.raises(Exception) as caught:
        runtime.dispatch("gas.inlet_close", {})

    assert getattr(caught.value, "code", "") in ("interlock_blocked", "order_violation")
