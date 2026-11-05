"""Talking to the STM32 side of the UNO Q over the Arduino Bridge.

The sketch powers one probe at a time, waits for it to settle, averages the ADC
and switches it off again. A full run takes ~35 s, longer than a Bridge call is
allowed to block, so Python starts a run and then polls for the result.

RPC functions provided by sketch.ino:
    aq_ping()                  -> "AquaSense MCU <version>"
    aq_start(mask)             -> 1 if accepted, 0 if busy
    aq_status()                -> "IDLE|BUSY|DONE|ERROR,<step>,<total>,<seq>"
    aq_result()                -> "R1;seq=..;t=..;ph=..;do=..;ec=..;tu=..;f=.."
    aq_abort()                 -> 1
    aq_indicator(level)        -> 1   0 ok, 1 measuring, 2 warning, 3 critical
    aq_buzzer(on), aq_aerator(on)
    aq_set_warmup(channel, ms) -> 1   channel 1 pH, 2 DO, 3 EC, 4 turbidity
"""

import math
import random
import time
from dataclasses import asdict, dataclass, field

import chemistry as chem

TEMP, PH, DO, EC, TURB = 1, 2, 4, 8, 16
ALL_PROBES = TEMP | PH | DO | EC | TURB
WARMUP_CHANNEL = {"ph": 1, "do": 2, "ec": 3, "turbidity": 4}

FLAG_TEMP_FAIL, FLAG_ADC_SAT, FLAG_ABORTED, FLAG_TIMEOUT = 1, 2, 4, 8


@dataclass
class RawResult:
    seq: int
    temp_c: float = math.nan
    ph_mv: float = math.nan
    do_mv: float = math.nan
    ec_mv: float = math.nan
    turb_mv: float = math.nan
    flags: int = 0

    @classmethod
    def parse(cls, text):
        parts = text.strip().split(";")
        if not parts or parts[0] != "R1":
            raise ValueError(f"unexpected result string: {text!r}")
        kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)

        def num(key):
            v = kv.get(key, "nan")
            return math.nan if v in ("nan", "") else float(v)

        return cls(int(kv.get("seq", 0)), num("t"), num("ph"), num("do"), num("ec"), num("tu"), int(kv.get("f", 0)))

    def encode(self):
        def f(x):
            return "nan" if math.isnan(x) else f"{x:.2f}"

        return (f"R1;seq={self.seq};t={f(self.temp_c)};ph={f(self.ph_mv)};do={f(self.do_mv)};"
                f"ec={f(self.ec_mv)};tu={f(self.turb_mv)};f={self.flags}")


@dataclass
class Calibration:
    ph: chem.PhCalibration = field(default_factory=chem.PhCalibration)
    do: chem.DoCalibration = field(default_factory=chem.DoCalibration)
    ec: chem.EcCalibration = field(default_factory=chem.EcCalibration)
    turbidity: chem.TurbidityCalibration = field(default_factory=chem.TurbidityCalibration)
    tds_factor: float = 0.5
    pressure_kpa: float = chem.STD_PRESSURE_KPA

    @classmethod
    def from_config(cls, c, altitude_m=0.0):
        return cls(chem.PhCalibration(**c["ph"]), chem.DoCalibration(**c["do"]), chem.EcCalibration(**c["ec"]),
                   chem.TurbidityCalibration(**c["turbidity"]), c.get("tds_factor", 0.5),
                   chem.pressure_from_altitude_kpa(altitude_m))


@dataclass
class Reading:
    time: float
    temperature_c: float = None
    ph: float = None
    do_mg_l: float = None
    do_sat_pct: float = None
    ec_ms_cm: float = None
    ec25_ms_cm: float = None
    salinity_ppt: float = None
    tds_ppm: float = None
    turbidity_ntu: float = None
    nh3_fraction: float = None
    flags: int = 0

    def as_dict(self):
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def to_reading(raw, cal, now=None):
    def ok(x):
        return not math.isnan(x)

    r = Reading(time=now or time.time(), flags=raw.flags)
    temp = raw.temp_c if ok(raw.temp_c) else None
    r.temperature_c = temp
    t = temp if temp is not None else 25.0  # fallback when the DS18B20 is missing

    if ok(raw.ec_mv):
        r.ec_ms_cm = chem.ec_at_temp_from_mv(raw.ec_mv, cal.ec)
        r.ec25_ms_cm = chem.ec25_from_ec(r.ec_ms_cm, t, cal.ec.temp_coeff)
        r.salinity_ppt = chem.salinity_pss78(r.ec_ms_cm, t)
        r.tds_ppm = chem.tds_ppm_from_ec25(r.ec25_ms_cm, cal.tds_factor)
    if ok(raw.ph_mv):
        r.ph = chem.ph_from_mv(raw.ph_mv, cal.ph, temp)
    if ok(raw.do_mv):
        r.do_sat_pct = chem.do_percent_saturation(raw.do_mv, t, cal.do)
        r.do_mg_l = chem.do_mg_l_from_mv(raw.do_mv, t, cal.do, r.salinity_ppt or 0.0, cal.pressure_kpa)
    if ok(raw.turb_mv):
        r.turbidity_ntu = chem.turbidity_ntu_from_mv(raw.turb_mv, cal.turbidity)
    if r.ph is not None and temp is not None:
        r.nh3_fraction = chem.nh3_fraction(r.ph, temp)
    return r


class McuProbes:
    """The real thing: arduino.app_utils.Bridge on the UNO Q."""

    def __init__(self, bridge=None, timeout=5):
        if bridge is None:
            from arduino.app_utils import Bridge
            bridge = Bridge
        self.bridge = bridge
        self.timeout = timeout

    def _call(self, name, *args):
        try:
            return self.bridge.call(name, *args, timeout=self.timeout)
        except TypeError:  # older app_utils without the timeout argument
            return self.bridge.call(name, *args)

    def ping(self):
        return str(self._call("aq_ping"))

    def set_warmups(self, warmup_ms):
        for name, ms in warmup_ms.items():
            self._call("aq_set_warmup", WARMUP_CHANNEL[name], int(ms))

    def start(self, mask=ALL_PROBES):
        return bool(self._call("aq_start", int(mask)))

    def status(self):
        state, step, total, seq = (str(self._call("aq_status")).split(",") + ["0"] * 4)[:4]
        return state, int(step), int(total), int(seq)

    def result(self):
        text = str(self._call("aq_result"))
        return RawResult.parse(text) if text.startswith("R1") else None

    def abort(self):
        self._call("aq_abort")

    def indicator(self, level):
        self._call("aq_indicator", int(level))

    def buzzer(self, on):
        self._call("aq_buzzer", int(bool(on)))

    def aerator(self, on):
        self._call("aq_aerator", int(bool(on)))


class FakeProbes:
    """Stand-in for the MCU when running on a PC (tools/run_on_video.py, tests).

    Produces raw millivolts for a chosen water condition by running the
    calibration backwards, so the normal conversion code is still exercised.
    """

    CONDITIONS = {
        "normal": dict(t=28.0, ph=7.6, do=6.8, ec=0.45, ntu=25.0),
        "low_oxygen": dict(t=28.0, ph=7.1, do=2.1, ec=0.45, ntu=30.0),
        "algal_bloom": dict(t=30.0, ph=9.3, do=11.5, ec=0.45, ntu=140.0),
        "acidic": dict(t=27.0, ph=5.6, do=6.0, ec=0.45, ntu=25.0),
    }

    def __init__(self, cal=None, condition="normal", duration=3.0, clock=time.monotonic, seed=0):
        self.cal = cal or Calibration()
        self.condition = condition
        self.duration = duration
        self.clock = clock
        self.rng = random.Random(seed)
        self.seq, self.started, self.last = 0, None, None
        self.level, self.buzzing, self.aerating = 0, False, False

    def ping(self):
        return "FakeProbes"

    def set_warmups(self, warmup_ms):
        pass

    def start(self, mask=ALL_PROBES):
        if self.started is not None:
            return False
        self.seq += 1
        self.mask, self.started, self.last = mask, self.clock(), None
        return True

    def status(self):
        if self.started is not None and self.clock() - self.started >= self.duration:
            self.last, self.started = self._make_raw(), None
        if self.started is not None:
            return "BUSY", 1, 5, self.seq
        return ("DONE" if self.last else "IDLE"), 5, 5, self.seq

    def result(self):
        return self.last

    def abort(self):
        self.started = None

    def indicator(self, level):
        self.level = level

    def buzzer(self, on):
        self.buzzing = on

    def aerator(self, on):
        self.aerating = on

    def _make_raw(self):
        w = dict(self.CONDITIONS[self.condition])
        if self.aerating and self.condition == "low_oxygen":
            w["do"] = 4.5
        cal, t, g = self.cal, w["t"], self.rng.gauss
        slope, mv7 = chem.ph_line(cal.ph)
        slope *= (cal.ph.cal_temp_c + chem.KELVIN) / (t + chem.KELVIN)
        ec_t = w["ec"] * (1 + cal.ec.temp_coeff * (t - 25))
        sat = chem.do_saturation_mg_l(t, chem.salinity_pss78(ec_t, t), cal.pressure_kpa)
        m = self.mask
        return RawResult(
            seq=self.seq,
            temp_c=t + g(0, 0.05),
            ph_mv=mv7 + (w["ph"] - 7) / slope + g(0, 1) if m & PH else math.nan,
            do_mv=w["do"] / sat * chem.do_saturation_voltage_mv(t, cal.do) + g(0, 3) if m & DO else math.nan,
            ec_mv=ec_t / (cal.ec.gain * cal.ec.k_low) + g(0, 0.5) if m & EC else math.nan,
            turb_mv=chem.turbidity_pin_mv_from_ntu(w["ntu"], cal.turbidity) + g(0, 0.2) if m & TURB else math.nan,
        )
