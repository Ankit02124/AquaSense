"""Feed the behaviour monitor made-up detections and check each rule fires."""

import math
import random

import numpy as np
import pytest

from behaviour import BehaviourMonitor
from fish_detector import Detection
from tracker import CentroidTracker

W, H, FPS, SIZE = 640, 480, 3.0, 40


class Pond:
    def __init__(self, n=8, seed=0):
        self.rng = random.Random(seed)
        self.fish = [[self.rng.uniform(60, W - 60), self.rng.uniform(60, H - 60), self.rng.uniform(0, 6.28)]
                     for _ in range(n)]

    def step(self, mode):
        dets = []
        speed = {"normal": 1.0, "surface": 1.2, "slow": 0.03}.get(mode, 1.0)  # body lengths / s
        for f in self.fish:
            f[2] += self.rng.gauss(0, 0.3)
            f[0] += math.cos(f[2]) * speed * SIZE / FPS
            f[1] += math.sin(f[2]) * speed * SIZE / FPS
            if mode == "surface":
                f[1] += (0.08 * H - f[1]) * 0.3
            f[0] = min(max(f[0], 30), W - 30)
            f[1] = min(max(f[1], 20), H - 20)
            if f[0] in (30, W - 30) or f[1] in (20, H - 20):
                f[2] += math.pi
            dets.append(Detection(f[0] - SIZE / 2, f[1] - 8, f[0] + SIZE / 2, f[1] + 8, 0.9, 0, "fish"))
        if mode == "few":
            dets = dets[:1]
        return dets


def run(cfg, mode, seconds_after=60, frame=None, still_fish=False):
    mon = BehaviourMonitor(cfg["behaviour"])
    tr = CentroidTracker(**cfg["tracker"])
    pond = Pond()
    img = np.full((H, W, 3), 110, np.uint8) if frame is None else frame
    normal_img = np.full((H, W, 3), 110, np.uint8)
    # only count an alert that shows up in two windows in a row, so a single
    # odd window does not decide the test
    alerts_before, alerts_after, previous = set(), set(), set()
    total = cfg["behaviour"]["baseline_minutes"] * 60 + 60 + seconds_after
    for i in range(int(total * FPS)):
        t = i / FPS
        bad = t >= total - seconds_after
        dets = pond.step(mode if bad else "normal")
        if still_fish:
            dets.append(Detection(300, 400, 340, 416, 0.9, 0, "fish"))
        res = mon.add_frame(t, img if bad else normal_img, dets, tr.update(dets, t))
        if res and res.baseline_ready:
            confirmed = previous & set(res.alerts)
            (alerts_after if bad else alerts_before).update(confirmed)
            previous = set(res.alerts)
    return alerts_before, alerts_after


def test_normal_pond_is_quiet(cfg):
    before, after = run(cfg, "normal")
    assert before == set() and after == set()


@pytest.mark.parametrize("mode, alert", [
    ("surface", "surface_crowding"),
    ("slow", "low_activity"),
    ("few", "fish_missing"),
])
def test_rules(cfg, mode, alert):
    before, after = run(cfg, mode)
    assert before == set()
    assert alert in after


def test_green_water(cfg):
    green = np.zeros((H, W, 3), np.uint8)
    green[:] = (60, 160, 70)  # BGR
    _, after = run(cfg, "normal", frame=green)
    assert "water_colour" in after


def test_motionless_fish(cfg):
    cfg["behaviour"]["still_minutes"] = 0.5
    _, after = run(cfg, "normal", still_fish=True)
    assert "motionless_fish" in after


def test_dark_windows_raise_nothing(cfg):
    dark = np.full((H, W, 3), 10, np.uint8)
    before, after = run(cfg, "few", frame=dark)      # fish "missing" because it is night
    assert before == set() and after == set()


def test_still_time_is_the_longest_in_the_window(cfg):
    mon = BehaviourMonitor(cfg["behaviour"])
    tr = CentroidTracker(**cfg["tracker"])
    img = np.full((H, W, 3), 110, np.uint8)
    still = Detection(300, 400, 340, 416, 0.9, 0, "fish")
    result = None
    for i in range(int(12 * FPS)):
        t = i / FPS
        dets = [still] if t < 9 else []              # the fish disappears near the end of the window
        result = mon.add_frame(t, img, dets, tr.update(dets, t)) or result
    assert result.summary["longest_still_s"] >= 8
