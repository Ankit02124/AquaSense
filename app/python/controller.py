"""Decides when the probes are switched on.

A measurement is started when:
  - the camera reports the same kind of problem for `confirm_windows` windows in a row
  - a scheduled time is reached (default 05:00, when oxygen is lowest and the
    camera cannot see much, and 15:00, when pH and temperature peak)
  - the last result was WARNING/CRITICAL (follow-up every `followup_min`)
  - at start-up, to have one reference reading

After a camera-triggered measurement, further camera triggers are ignored for
`cooldown_min` so the probes are not cycled all day by one event.
"""

import logging
import time
from datetime import datetime

import water_check
from probes import ALL_PROBES, to_reading

log = logging.getLogger("controller")


class Controller:
    def __init__(self, cfg, probes, calibration, profile, datalog=None, clock=time.time):
        t = cfg["trigger"]
        self.probes, self.cal, self.profile, self.datalog = probes, calibration, profile, datalog
        self.clock = clock
        self.confirm = t["confirm_windows"]
        self.cooldown_s = t["cooldown_min"] * 60
        self.followup_s = t["followup_min"] * 60
        self.timeout_s = t["timeout_s"]
        self.schedule = [tuple(map(int, s.split(":"))) for s in t["scheduled"]]
        self.auto_aerator = cfg["outputs"]["auto_aerator"]
        self.use_buzzer = cfg["outputs"]["buzzer"]

        self.busy = False
        self.pending = "startup" if t["measure_on_start"] else None
        self.pending_alerts = []
        self.cooldown_until = 0.0
        self.next_followup = None
        self.started_at = 0.0
        self.streak = 0
        self.fired = set()
        self.last_level = water_check.OK
        self.aerator_on = False

    def on_behaviour(self, result):
        """Called once per behaviour window."""
        if result.alerts:
            self.streak += 1
        else:
            self.streak = 0
        if self.streak >= self.confirm and not self.busy and self.clock() >= self.cooldown_until:
            log.warning("camera: %s for %d windows, measuring water", ", ".join(result.alerts), self.streak)
            if self.datalog:
                self.datalog.event("camera_alert", ";".join(result.alerts), result.summary)
            self.request("camera", result.alerts)
            self.streak = 0

    def request(self, reason, alerts=()):
        if self.busy or self.pending:
            return False
        self.pending, self.pending_alerts = reason, list(alerts)
        return True

    def tick(self):
        now = self.clock()
        if self.busy:
            self._poll(now)
            return
        if not self.pending:
            self._check_timers(now)
        if self.pending:
            self._start(now)

    def _check_timers(self, now):
        if self.next_followup and now >= self.next_followup:
            self.next_followup = None
            self.request("follow-up")
            return
        local = datetime.fromtimestamp(now)
        for hh, mm in self.schedule:
            late = local.hour * 60 + local.minute - (hh * 60 + mm)
            key = (local.date(), hh, mm)
            if 0 <= late < 30 and key not in self.fired:
                self.fired.add(key)
                self.request(f"scheduled {hh:02d}:{mm:02d}")
                return

    def _start(self, now):
        if not self.probes.start(ALL_PROBES):
            log.error("MCU busy or not answering, will retry")
            return
        log.info("measuring (%s)", self.pending)
        self.reason, self.alerts = self.pending, self.pending_alerts
        self.pending, self.busy, self.started_at = None, True, now
        self.probes.indicator(water_check.MEASURING)

    def _poll(self, now):
        state, *_ = self.probes.status()
        if state == "DONE":
            raw = self.probes.result()
            if raw is not None:
                self._finish(raw, now)
                return
        if state == "ERROR" or now - self.started_at > self.timeout_s:
            log.error("measurement failed (%s), probes switched off", state)
            self.probes.abort()
            self.busy = False
            self.probes.indicator(self.last_level)
            if self.datalog:
                self.datalog.event("measurement_failed", state, {})

    def _finish(self, raw, now):
        self.busy = False
        reading = to_reading(raw, self.cal, now)
        level, rows, tips = water_check.check(reading, self.profile, self.alerts)
        self.last_level = level

        log.info("result (%s): %s", self.reason, water_check.LEVEL_NAMES[level])
        for name, value, unit, lvl, direction in rows:
            if value is not None:
                flag = f"  <- {direction}" if lvl >= water_check.WARNING else ""
                log.info("  %-17s %8.2f %s%s", name, value, unit, flag)
        for tip in tips:
            log.warning("  advice: %s", tip)
        if self.datalog:
            self.datalog.measurement(reading, self.reason, water_check.LEVEL_NAMES[level], raw.encode(), tips)

        self.probes.indicator(level)
        self.probes.buzzer(self.use_buzzer and level == water_check.CRITICAL)
        low_do = water_check.classify(reading.do_mg_l, self.profile.get("do_mg_l"))[1] == "low"
        if self.auto_aerator and low_do != self.aerator_on and reading.do_mg_l is not None:
            self.aerator_on = low_do
            self.probes.aerator(low_do)
            log.warning("aerator %s", "ON" if low_do else "OFF")

        self.next_followup = now + self.followup_s if level >= water_check.WARNING else None
        if self.reason == "camera":
            self.cooldown_until = now + self.cooldown_s
