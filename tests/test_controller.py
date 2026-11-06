from datetime import datetime

from behaviour import WindowResult
from controller import Controller
from probes import Calibration, FakeProbes


def make(cfg, clock, condition="normal", **trigger):
    cfg["trigger"].update({"measure_on_start": False, "scheduled": [], **trigger})
    cfg["timezone"] = None  # test timestamps are in the machine's local time
    probes = FakeProbes(condition=condition, duration=3, clock=clock)
    ctl = Controller(cfg, probes, Calibration(), cfg["species_profiles"]["tilapia"], clock=clock)
    return ctl, probes


def finish(ctl, clock):
    for _ in range(40):
        ctl.tick()
        if not ctl.busy and not ctl.pending:
            return
        clock.advance(0.5)
    raise AssertionError("measurement never finished")


def alert(t=0):
    return WindowResult(t, {"n_fish": 5}, ["surface_crowding"], True)


def test_one_window_is_not_enough(cfg, clock):
    ctl, _ = make(cfg, clock)
    ctl.on_behaviour(alert())
    assert ctl.pending is None


def test_camera_trigger_then_cooldown(cfg, clock):
    ctl, probes = make(cfg, clock, "low_oxygen")
    ctl.on_behaviour(alert())
    ctl.on_behaviour(alert())
    assert ctl.pending == "camera"
    finish(ctl, clock)
    assert probes.level == 3 and probes.buzzing          # CRITICAL
    assert ctl.next_followup is not None                 # will re-check
    ctl.on_behaviour(alert())
    ctl.on_behaviour(alert())
    assert ctl.pending is None                           # cooling down
    clock.advance(ctl.followup_s + 1)
    ctl.tick()
    assert ctl.reason == "follow-up"


def test_auto_aerator_with_hysteresis(cfg, clock):
    cfg["outputs"]["auto_aerator"] = True
    ctl, probes = make(cfg, clock, "low_oxygen")
    ctl.request("manual")
    finish(ctl, clock)
    assert probes.aerating                       # 2.1 mg/L, below warn_low 4.0
    ctl._aerator(4.4)                            # back above warn_low but inside the margin
    assert probes.aerating
    probes.condition = "normal"
    ctl.request("manual")
    finish(ctl, clock)
    assert not probes.aerating                   # 6.8 mg/L >= 4.0 + 1.0


def test_mcu_not_answering_is_retried(cfg, clock):
    ctl, probes = make(cfg, clock)
    probes.status = lambda: ("ERROR", 0, 0, 0)    # what McuProbes.status() returns on a Bridge failure
    ctl.request("manual")
    ctl.tick()
    ctl.tick()
    assert not ctl.busy and ctl.next_followup is not None
    del probes.status                            # MCU answers again
    clock.advance(ctl.followup_s + 1)
    ctl.tick()
    assert ctl.busy and ctl.reason == "follow-up"


def test_alerts_of_different_kinds_count_together(cfg, clock):
    ctl, _ = make(cfg, clock)
    ctl.on_behaviour(WindowResult(0, {}, ["surface_crowding"], True))
    ctl.on_behaviour(WindowResult(10, {}, ["water_colour"], True))
    assert ctl.pending == "camera"


def test_timeout_switches_probes_off(cfg, clock):
    ctl, probes = make(cfg, clock, timeout_s=10)
    probes.status = lambda: ("BUSY", 1, 5, 1)
    ctl.request("manual")
    ctl.tick()
    clock.advance(11)
    ctl.tick()
    assert not ctl.busy and probes.started is None


def test_schedule_fires_once(cfg, clock):
    clock.t = datetime(2026, 11, 6, 4, 59).timestamp()
    ctl, _ = make(cfg, clock, scheduled=["05:00"])
    ctl.tick()
    assert not ctl.busy
    clock.advance(90)
    ctl.tick()
    assert ctl.reason == "scheduled 05:00"
    finish(ctl, clock)
    clock.advance(60)
    ctl.tick()
    assert not ctl.busy
