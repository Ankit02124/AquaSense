"""Fish behaviour and water appearance checks built on top of the YOLO detections.

Every frame contributes a few numbers (fish count, how many are near the
surface, how fast they swim, water colour). Every `window_s` seconds the
numbers are summarised with a median and compared with what is normal for this
pond. "Normal" is learned during the first minutes after start-up and keeps
adapting slowly while nothing is wrong.

Rules (each one names the problem it suggests):
    surface_crowding   fish gathering/gasping at the surface -> low oxygen
    low_activity       fish much slower than usual -> stress, cold, low oxygen
    hyperactivity      fish much faster than usual -> irritation, pH/ammonia
    fish_missing       far fewer fish visible -> hiding, sick at the bottom
    motionless_fish    a fish has not moved for minutes -> dead or sick fish
    water_colour       green/turbid water -> algal bloom

The fish rules only run when at least `min_fish` fish are normally in view.
Windows darker than `dark_level` (night, no IR light) raise no alerts at all.
"""

import statistics
from dataclasses import dataclass, field

import cv2
import numpy as np

METRICS = ("n_fish", "surface_ratio", "mean_speed", "active_ratio", "green_index", "clarity")


@dataclass
class WindowResult:
    t: float
    summary: dict
    alerts: list = field(default_factory=list)
    baseline_ready: bool = False
    too_dark: bool = False


def water_colour(frame_bgr):
    """Excess-green index, a clarity score (log of Laplacian variance) and mean brightness 0-255."""
    small = cv2.resize(frame_bgr, (96, 54), interpolation=cv2.INTER_AREA).astype(np.float32)
    total = small.sum(axis=2) + 1e-6
    b, g, r = small[..., 0] / total, small[..., 1] / total, small[..., 2] / total
    gray = cv2.cvtColor(small.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    return (float((2 * g - r - b).mean()), float(np.log1p(cv2.Laplacian(gray, cv2.CV_32F).var())),
            float(gray.mean()))


class Baseline:
    """Running mean/std per metric (Welford during warm-up, then slow EMA)."""

    def __init__(self, warmup, alpha=0.02):
        self.warmup, self.alpha, self.n = warmup, alpha, 0
        self.mean = {m: 0.0 for m in METRICS}
        self.var = {m: 0.0 for m in METRICS}

    @property
    def ready(self):
        return self.n >= self.warmup

    def update(self, summary):
        self.n += 1
        a = max(1.0 / self.n, self.alpha)
        for m in METRICS:
            d = summary[m] - self.mean[m]
            self.mean[m] += a * d
            self.var[m] = (1 - a) * (self.var[m] + a * d * d)

    def std(self, m, floor):
        return max(self.var[m] ** 0.5, floor)


class BehaviourMonitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.window_s = cfg["window_s"]
        self.surface_y = cfg["surface_band"]           # top fraction of the image = surface
        self.baseline = Baseline(int(cfg["baseline_minutes"] * 60 / self.window_s))
        self._frames = []
        self._window_start = None

    def add_frame(self, t, frame_bgr, fish, tracks):
        """fish: fish detections in this frame, tracks: tracker output for those fish."""
        h = frame_bgr.shape[0]
        green, clarity, brightness = water_colour(frame_bgr)
        moving = [tr.speed for tr in tracks if len(tr.history) > 1]
        self._frames.append({
            "n_fish": len(fish),
            "surface_ratio": (sum(d.cy < self.surface_y * h for d in fish) / len(fish)) if fish else 0.0,
            "mean_speed": statistics.fmean(moving) if moving else 0.0,
            "active_ratio": (sum(s > self.cfg["active_speed"] for s in moving) / len(moving)) if moving else 0.0,
            "green_index": green,
            "clarity": clarity,
            "brightness": brightness,
            "longest_still_s": max((t - tr.still_since for tr in tracks if tr.still_since is not None), default=0.0),
        })

        if self._window_start is None:
            self._window_start = t
        if t - self._window_start < self.window_s:
            return None
        summary = {m: statistics.median(f[m] for f in self._frames) for m in METRICS}
        summary["longest_still_s"] = max(f["longest_still_s"] for f in self._frames)
        summary["brightness"] = statistics.median(f["brightness"] for f in self._frames)
        self._frames, self._window_start = [], t
        return self._evaluate(t, summary)

    def _evaluate(self, t, s):
        res = WindowResult(t, s, baseline_ready=self.baseline.ready)
        if s["brightness"] < self.cfg.get("dark_level", 0):
            # too dark to see the fish (night without IR light): no alerts, and don't
            # let a black image become part of "normal"
            res.too_dark = True
            return res
        if not self.baseline.ready:
            self.baseline.update(s)
            return res

        c, b = self.cfg, self.baseline
        z = c["z"]
        mean = b.mean
        enough_fish = mean["n_fish"] >= c["min_fish"]

        if enough_fish and s["n_fish"] >= c["min_fish"]:
            limit = max(c["surface_ratio_min"], mean["surface_ratio"] + z * b.std("surface_ratio", 0.1))
            if s["surface_ratio"] >= limit:
                res.alerts.append("surface_crowding")
            if mean["mean_speed"] > 0.05:
                if s["mean_speed"] <= min(0.5 * mean["mean_speed"], mean["mean_speed"] - z * b.std("mean_speed", 0.02)):
                    res.alerts.append("low_activity")
                if s["mean_speed"] >= max(2.0 * mean["mean_speed"], mean["mean_speed"] + z * b.std("mean_speed", 0.02)):
                    res.alerts.append("hyperactivity")
        if enough_fish and s["n_fish"] <= c["missing_ratio"] * mean["n_fish"]:
            res.alerts.append("fish_missing")
        if s["longest_still_s"] >= c["still_minutes"] * 60:
            res.alerts.append("motionless_fish")
        if (s["green_index"] - mean["green_index"] >= max(c["green_jump"], z * b.std("green_index", 0.005))
                or mean["clarity"] - s["clarity"] >= max(c["clarity_drop"], z * b.std("clarity", 0.05))):
            res.alerts.append("water_colour")

        if not res.alerts:  # only learn from windows that look normal
            b.update(s)
        return res

    def reset(self):
        self.baseline = Baseline(self.baseline.warmup)
        self._frames, self._window_start = [], None
