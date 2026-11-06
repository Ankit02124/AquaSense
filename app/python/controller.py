"""Decides when the probes are switched on.

A measurement is started when:
  - the camera reports alerts in `confirm_windows` windows in a row
    (any alert counts, they don't have to be the same kind)
  - a scheduled time is reached (default 05:00, when oxygen is lowest and the
    camera cannot see much, and 15:00, when pH and temperature peak)
  - the last result was WARNING/CRITICAL (follow-up every `followup_min`)
  - at start-up, to have one reference reading

After a camera-triggered measurement, further camera triggers are ignored for
`cooldown_min` so the probes are not cycled all day by one event. A failed
measurement (MCU not answering, timeout) is retried after `followup_min`.

Durations use a monotonic clock, so a clock change at boot (NTP sync) does not
break timeouts. Scheduled times use the wall clock in `timezone` from the config.
"""

import logging
import time
from datetime import datetime

import water_check
from probes import ALL_PROBES, to_reading

log = logging.getLogger("controller")


def _timezone(name):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # no tz database (e.g. Windows without tzdata)
        log.warning("timezone %s not available, using the system's local time", name)
        return None


class Controller:
    def __init__(self, cfg, probes, calibration, profile, datalog=None, clock=time.time, mono=None):
        t = cfg["trigger"]
        self.probes, self.cal, self.profile, self.datalog = probes, calibration, profile, datalog
        self.clock = clock                                   # wall clock: schedule, timestamps
        self.mono = mono or (time.monotonic if clock is time.time else clock)
        self.tz = _timezone(cfg.get("timezone"))
        self.confirm = t["confirm_windows"]
        self.cooldown_s = t["cooldown_min"] * 60
        self.followup_s = t["followup_min"] * 60
        self.timeout_s = t["timeout_s"]
        self.schedule = [tuple(map(int, s.split(":"))) for s in t["scheduled"]]
        out = cfg["outputs"]
        self.auto_aerator = out["auto_aerator"]
        self.aerator_margin = out.get("aerator_off_margin", 1.0)
        self.use_buzzer = out["buzzer"]

        self.busy = False
        self.pending = "startup" if t["measure_on_start"] else None
        self.pending_alerts = []
        self.reason, self.alerts = None, []
        self.cooldown_until = 0.0
        self.next_followup = None
        self.started_at = 0.0
        self.streak = 0
        self.fired = set()
        self.last_level = water_check.OK
        self.aerator_on = False

    def on_behaviour(self, result):
        """Called once per behaviour window."""
        self.streak = self.streak + 1 if result.alerts else 0
        if self.streak >= self.confirm and not self.busy and self.mono() >= self.cooldown_until:
            log.warning("camera: %s, alerts in %d windows in a row, measuring water",
                        ", ".join(result.alerts), self.streak)
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
        if self.busy:
            self._poll(self.mono())
            return
        if not self.pending:
            self._check_timers()
        if self.pending:
            self._start(self.mono())

    def _check_timers(self):
        if self.next_followup and self.mono() >= self.next_followup:
            self.next_followup = None
            self.request("follow-up")
            return
        local = datetime.fromtimestamp(self.clock(), self.tz)
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
                self._finish(raw)
                return
        if state == "ERROR" or now - self.started_at > self.timeout_s:
            reason = "MCU not answering" if state == "ERROR" else "timeout"
            log.error("measurement failed (%s), probes switched off, retrying in %d min",
                      reason, self.followup_s // 60)
            self.probes.abort()
            self.busy = False
            self.next_followup = now + self.followup_s
            self.probes.indicator(self.last_level)
            if self.datalog:
                self.datalog.event("measurement_failed", reason, {})

    def _finish(self, raw):
        self.busy = False
        now = self.mono()
        reading = to_reading(raw, self.cal, self.clock())
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
        self._aerator(reading.do_mg_l)

        self.next_followup = now + self.followup_s if level >= water_check.WARNING else None
        if self.reason == "camera":
            self.cooldown_until = now + self.cooldown_s

    def _aerator(self, do):
        """On below the species' warn_low for DO, off only once DO is `aerator_off_margin` above it."""
        lim = self.profile.get("do_mg_l") or {}
        low = lim.get("warn_low", lim.get("crit_low"))
        if not self.auto_aerator or do is None or low is None:
            return
        if not self.aerator_on and do < low:
            self.aerator_on = True
        elif self.aerator_on and do >= low + self.aerator_margin:
            self.aerator_on = False
        else:
            return
        self.probes.aerator(self.aerator_on)
        log.warning("aerator %s (DO %.2f mg/L)", "ON" if self.aerator_on else "OFF", do)
