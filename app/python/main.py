"""AquaSense - Linux side, started by Arduino App Lab on the UNO Q.

camera -> YOLOv8n (fish) -> tracker -> behaviour checks -> controller -> MCU probes
"""

import logging
import time
from pathlib import Path

import yaml
from arduino.app_peripherals.camera import Camera
from arduino.app_utils import App

from behaviour import BehaviourMonitor
from controller import Controller
from datalog import DataLog
from fish_detector import FishDetector, draw
from probes import Calibration, McuProbes
from tracker import CentroidTracker

HERE = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-10s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("main")


def load_config():
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    local = HERE / "config.local.yaml"           # site specific values, not in git
    if local.exists():
        for section, values in (yaml.safe_load(local.read_text()) or {}).items():
            if isinstance(values, dict):
                cfg.setdefault(section, {}).update(values)
            else:
                cfg[section] = values
    return cfg


cfg = load_config()
profile = cfg["species_profiles"][cfg["species"]]
classes = (HERE / cfg["model"]["classes"]).read_text().split()

detector = FishDetector(HERE / cfg["model"]["path"], classes, cfg["model"]["conf"], cfg["model"]["iou"],
                        cfg["model"]["threads"])
tracker = CentroidTracker(**cfg["tracker"])
monitor = BehaviourMonitor(cfg["behaviour"])
datalog = DataLog(HERE.parent / "data")

probes = McuProbes()
log.info("MCU: %s", probes.ping())
probes.set_warmups(cfg["probes"]["warmup_ms"])
controller = Controller(cfg, probes, Calibration.from_config(cfg["calibration"], cfg["altitude_m"]), profile, datalog)

cam_cfg = cfg["camera"]
camera = Camera(cam_cfg["source"], resolution=tuple(cam_cfg["resolution"]), fps=cam_cfg["fps"])
camera.start()
log.info("model %s (%dx%d), species %s", cfg["model"]["path"], detector.size, detector.size, cfg["species"])

frame_period = 1.0 / cfg["detect_fps"]
last_frame = 0.0


def loop():
    global last_frame
    now = time.time()
    if now - last_frame >= frame_period:
        last_frame = now
        frame = camera.capture()
        if frame is not None:
            t0 = time.perf_counter()
            detections = detector.detect(frame)
            fish = [d for d in detections if d.label == "fish"]
            tracks = tracker.update(fish, now)
            result = monitor.add_frame(now, frame, fish, tracks)
            if result:
                s = result.summary
                log.info("fish %2.0f  surface %.2f  speed %.2f BL/s  green %.3f  infer %3.0f ms  %s",
                         s["n_fish"], s["surface_ratio"], s["mean_speed"], s["green_index"],
                         (time.perf_counter() - t0) * 1000,
                         ",".join(result.alerts) if result.alerts else ("ok" if result.baseline_ready else "learning"))
                datalog.window(result)
                if result.alerts:
                    datalog.snapshot(draw(frame, detections, tracks), "_".join(result.alerts))
                controller.on_behaviour(result)
    controller.tick()
    time.sleep(0.05)


try:
    App.run(user_loop=loop)
finally:
    probes.abort()
    camera.stop()
