"""AquaSense - Linux side, started by Arduino App Lab on the UNO Q.

camera -> YOLOv8n (fish) -> tracker -> behaviour checks -> controller -> MCU probes
"""

import logging
import time
from pathlib import Path

from arduino.app_peripherals.camera import Camera
from arduino.app_utils import App

from behaviour import BehaviourMonitor
from controller import Controller
from datalog import DataLog
from fish_detector import FishDetector, draw
from probes import Calibration, McuProbes
from settings import load_config
from tracker import CentroidTracker

HERE = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-10s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("main")


cfg = load_config(HERE)
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
last_frame = last_ping = last_snapshot = 0.0


def status_word(result):
    if result.too_dark:
        return "too dark"
    if result.alerts:
        return ",".join(result.alerts)
    return "ok" if result.baseline_ready else "learning"


def loop():
    global last_frame, last_ping, last_snapshot
    now = time.monotonic()
    if now - last_ping >= 60:          # keeps LED4 (link heartbeat on the MCU) green
        last_ping = now
        probes.ping()
    if now - last_frame >= frame_period:
        last_frame = now
        frame = camera.capture()
        if frame is not None:
            t0 = time.perf_counter()
            detections = detector.detect(frame)
            infer_ms = (time.perf_counter() - t0) * 1000
            fish = [d for d in detections if d.label == "fish"]
            tracks = tracker.update(fish, now)
            result = monitor.add_frame(now, frame, fish, tracks)
            if result:
                s = result.summary
                log.info("fish %2.0f  surface %.2f  speed %.2f BL/s  green %.3f  infer %3.0f ms  %s",
                         s["n_fish"], s["surface_ratio"], s["mean_speed"], s["green_index"], infer_ms,
                         status_word(result))
                datalog.window(result)
                if result.alerts and now - last_snapshot >= 60:   # at most one snapshot a minute
                    last_snapshot = now
                    datalog.snapshot(draw(frame, detections, tracks), "_".join(result.alerts))
                controller.on_behaviour(result)
    controller.tick()
    time.sleep(0.05)


try:
    App.run(user_loop=loop)
finally:
    probes.abort()
    camera.stop()
