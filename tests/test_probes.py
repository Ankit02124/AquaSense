import math

import pytest

from probes import ALL_PROBES, DO, TEMP, Calibration, FakeProbes, RawResult, to_reading


def test_result_string_roundtrip():
    raw = RawResult(seq=7, temp_c=26.31, ph_mv=1523.4, do_mv=1298.0, ec_mv=712.5, turb_mv=2820.1, flags=2)
    assert len(raw.encode()) < 256
    assert RawResult.parse(raw.encode()) == raw


def test_parse_what_the_sketch_sends():
    raw = RawResult.parse("R1;seq=3;t=nan;ph=nan;do=1311.5;ec=nan;tu=nan;f=1")
    assert raw.seq == 3 and raw.flags == 1
    assert math.isnan(raw.temp_c) and raw.do_mv == pytest.approx(1311.5)


def test_bad_string():
    with pytest.raises(ValueError):
        RawResult.parse("hello")


@pytest.mark.parametrize("condition, key, expected", [
    ("normal", "do_mg_l", 6.8),
    ("normal", "ph", 7.6),
    ("normal", "ec25_ms_cm", 0.45),
    ("low_oxygen", "do_mg_l", 2.1),
    ("algal_bloom", "ph", 9.3),
])
def test_fake_probes_go_through_calibration(clock, condition, key, expected):
    cal = Calibration()
    p = FakeProbes(cal, condition, duration=2, clock=clock)
    assert p.start(ALL_PROBES)
    assert not p.start(ALL_PROBES)
    clock.advance(2.5)
    assert p.status()[0] == "DONE"
    r = to_reading(p.result(), cal)
    assert getattr(r, key) == pytest.approx(expected, rel=0.05, abs=0.1)


def test_missing_temperature_falls_back_to_25c(clock):
    p = FakeProbes(duration=0, clock=clock)
    p.start(TEMP | DO)
    p.status()
    raw = p.result()
    raw.temp_c = math.nan
    r = to_reading(raw, Calibration())
    assert r.temperature_c is None and r.do_mg_l is not None and r.ph is None
