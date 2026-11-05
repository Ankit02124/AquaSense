"""Small centroid tracker so fish speed can be measured between frames.

At 2-4 fps a full tracker (ByteTrack, DeepSORT) is overkill. Each new detection
is matched to the closest existing track, with distance measured in body lengths
of the fish, and unmatched tracks are dropped after a few missed frames.
"""

from collections import deque
from dataclasses import dataclass, field
from itertools import count


@dataclass
class Track:
    id: int
    cx: float
    cy: float
    size: float
    first_seen: float
    last_seen: float
    missed: int = 0
    still_since: float = None
    history: deque = field(default_factory=lambda: deque(maxlen=30))
    speed: float = 0.0  # body lengths per second

    def __post_init__(self):
        self.history.append((self.last_seen, self.cx, self.cy))
        self.still_since = self.first_seen


class CentroidTracker:
    def __init__(self, max_jump=2.0, max_missed=4, still_speed=0.1):
        self.max_jump = max_jump          # max movement between frames, in body lengths
        self.max_missed = max_missed      # frames a track survives without a match
        self.still_speed = still_speed    # below this (BL/s) a fish counts as not moving
        self.tracks = []
        self._ids = count(1)

    def update(self, detections, t):
        dets = list(detections)
        pairs = []
        for ti, tr in enumerate(self.tracks):
            for di, d in enumerate(dets):
                scale = max((tr.size + d.size) / 2, 1.0)
                dist = ((tr.cx - d.cx) ** 2 + (tr.cy - d.cy) ** 2) ** 0.5 / scale
                if dist <= self.max_jump:
                    pairs.append((dist, ti, di))
        pairs.sort()

        used_t, used_d = set(), set()
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            self._move(self.tracks[ti], dets[di], t)

        for ti, tr in enumerate(self.tracks):
            if ti not in used_t:
                tr.missed += 1
        self.tracks = [tr for tr in self.tracks if tr.missed <= self.max_missed]

        for di, d in enumerate(dets):
            if di not in used_d:
                self.tracks.append(Track(next(self._ids), d.cx, d.cy, d.size, t, t))
        return [tr for tr in self.tracks if tr.missed == 0]

    def _move(self, tr, d, t):
        dt = t - tr.last_seen
        if dt > 0:
            step = ((d.cx - tr.cx) ** 2 + (d.cy - tr.cy) ** 2) ** 0.5
            body = max((tr.size + d.size) / 2, 1.0)
            # light smoothing, detections jitter by a few pixels
            tr.speed = 0.6 * tr.speed + 0.4 * (step / body / dt)
        tr.cx, tr.cy, tr.size = d.cx, d.cy, 0.8 * tr.size + 0.2 * d.size
        tr.last_seen, tr.missed = t, 0
        tr.history.append((t, tr.cx, tr.cy))
        if tr.speed > self.still_speed:
            tr.still_since = t
