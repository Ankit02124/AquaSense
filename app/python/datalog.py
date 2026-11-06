"""CSV logs and snapshots, written to the app's data/ folder on the UNO Q."""

import csv
import json
import time
from pathlib import Path

import cv2

READING_FIELDS = ["temperature_c", "ph", "do_mg_l", "do_sat_pct", "ec_ms_cm", "salinity_ppt",
                  "tds_ppm", "turbidity_ntu", "nh3_fraction"]


class DataLog:
    def __init__(self, folder):
        self.folder = Path(folder)
        (self.folder / "snapshots").mkdir(parents=True, exist_ok=True)
        self.meas_file = self.folder / "measurements.csv"
        self.event_file = self.folder / "events.csv"
        self.window_file = self.folder / "behaviour.csv"

    def _append(self, path, header, row):
        new = not path.exists()
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(header)
            w.writerow(row)

    @staticmethod
    def _stamp(t=None):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t or time.time()))

    def measurement(self, reading, reason, level, raw, tips):
        values = [getattr(reading, f) for f in READING_FIELDS]
        self._append(self.meas_file, ["time", "reason", "level", *READING_FIELDS, "raw", "advice"],
                     [self._stamp(reading.time), reason, level,
                      *["" if v is None else round(v, 3) for v in values], raw, " | ".join(tips)])

    def event(self, kind, detail, summary):
        self._append(self.event_file, ["time", "event", "detail", "summary"],
                     [self._stamp(), kind, detail, json.dumps({k: round(v, 3) for k, v in summary.items()})])

    def window(self, result):
        s = result.summary
        keys = sorted(s)
        self._append(self.window_file, ["time", *keys, "alerts"],
                     [self._stamp(), *[round(s[k], 3) for k in keys], ";".join(result.alerts)])

    def snapshot(self, frame, tag):
        name = time.strftime("%Y%m%d_%H%M%S") + f"_{tag}.jpg"
        cv2.imwrite(str(self.folder / "snapshots" / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return name
