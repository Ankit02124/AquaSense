import pytest

from fish_detector import Detection
from tracker import CentroidTracker


def fish(cx, cy, size=40):
    return Detection(cx - size / 2, cy - size / 4, cx + size / 2, cy + size / 4, 0.9, 0, "fish")


def test_ids_stay_with_the_same_fish():
    tr = CentroidTracker()
    a = tr.update([fish(100, 100), fish(400, 300)], t=0.0)
    ids = {t.id: (t.cx, t.cy) for t in a}
    b = tr.update([fish(410, 300), fish(110, 102)], t=0.5)
    for t in b:
        x0, y0 = ids[t.id]
        assert abs(t.cx - x0) < 20 and abs(t.cy - y0) < 20


def test_speed_in_body_lengths_per_second():
    tr = CentroidTracker()
    for i in range(8):
        tracks = tr.update([fish(100 + 20 * i, 100)], t=i * 0.5)   # 20 px per 0.5 s, fish is 40 px long
    assert tracks[0].speed == pytest.approx(1.0, rel=0.1)


def test_lost_tracks_are_dropped():
    tr = CentroidTracker(max_missed=2)
    tr.update([fish(100, 100)], 0)
    for i in range(1, 4):
        tr.update([], i)
    assert tr.tracks == []


def test_still_fish_keeps_still_since():
    tr = CentroidTracker()
    for i in range(10):
        tracks = tr.update([fish(200, 200)], t=float(i))
    assert tracks[0].still_since == 0.0
