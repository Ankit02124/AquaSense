"""
Run the same detection + behaviour code the UNO Q app uses, but on a video
file on a PC. Useful to tune config.yaml before going to the pond, and it is
how docs/images/demo.gif was made.

    python tools/run_on_video.py clip.avi --out annotated.mp4
    python tools/run_on_video.py clip.avi --gif docs/images/demo.gif --gif-seconds 8
    python tools/run_on_video.py pond.mp4 --save-raw frames/ --raw-every 5   # clean frames for labelling

The MCU is replaced by FakeProbes, so camera alerts still lead to a (fake)
measurement and the log has the same format as the app's log.
"""

import argparse
import logging
import sys
from pathlib import Path

import cv2

APP = Path(__file__).resolve().parents[1] / "app" / "python"
sys.path.insert(0, str(APP))

from behaviour import BehaviourMonitor  # noqa: E402
from controller import Controller  # noqa: E402
from fish_detector import FishDetector, draw  # noqa: E402
from probes import Calibration, FakeProbes  # noqa: E402
from settings import load_config  # noqa: E402
from tracker import CentroidTracker  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", help="write an annotated mp4")
    ap.add_argument("--gif", help="write a short annotated gif")
    ap.add_argument("--start", type=float, default=0, help="skip the first N seconds of the video")
    ap.add_argument("--gif-seconds", type=float, default=8)
    ap.add_argument("--gif-width", type=int, default=480)
    ap.add_argument("--fps", type=float, default=None, help="analysis rate (default: detect_fps from config)")
    ap.add_argument("--water", default="normal", choices=list(FakeProbes.CONDITIONS))
    ap.add_argument("--baseline-minutes", type=float, default=None)
    ap.add_argument("--save-raw", help="folder for un-annotated frames (to label for fine-tuning)")
    ap.add_argument("--raw-every", type=int, default=5, help="save every Nth analysed frame")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)-10s %(message)s")
    cfg = load_config(APP)
    cfg["timezone"] = None  # video time, the daily schedule does not apply
    if args.baseline_minutes is not None:
        cfg["behaviour"]["baseline_minutes"] = args.baseline_minutes
    classes = (APP / cfg["model"]["classes"]).read_text().split()
    detector = FishDetector(APP / cfg["model"]["path"], classes, cfg["model"]["conf"], cfg["model"]["iou"])
    tracker = CentroidTracker(**cfg["tracker"])
    monitor = BehaviourMonitor(cfg["behaviour"])

    cap = cv2.VideoCapture(args.video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25
    fps = args.fps or cfg["detect_fps"]
    step = max(1, round(src_fps / fps))
    video_t = [0.0]
    probes = FakeProbes(condition=args.water, clock=lambda: video_t[0])
    controller = Controller(cfg, probes, Calibration.from_config(cfg["calibration"]),
                            cfg["species_profiles"][cfg["species"]], clock=lambda: video_t[0])

    if args.save_raw:
        Path(args.save_raw).mkdir(parents=True, exist_ok=True)
    writer, gif_frames, idx, analysed = None, [], 0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx % step or idx < args.start * src_fps:
            continue
        t = idx / src_fps - args.start
        video_t[0] = t
        analysed += 1
        if args.save_raw and analysed % args.raw_every == 0:
            cv2.imwrite(str(Path(args.save_raw) / f"{Path(args.video).stem}_{idx:06d}.jpg"), frame)
        dets = detector.detect(frame)
        fish = [d for d in dets if d.label == "fish"]
        tracks = tracker.update(fish, t)
        result = monitor.add_frame(t, frame, fish, tracks)
        if result:
            s = result.summary
            print(f"t={t:6.1f}s fish={s['n_fish']:.0f} surface={s['surface_ratio']:.2f} "
                  f"speed={s['mean_speed']:.2f} "
                  f"{'too dark' if result.too_dark else ','.join(result.alerts) or ('ok' if result.baseline_ready else 'learning')}")
            controller.on_behaviour(result)
        controller.tick()

        vis = draw(frame, dets, tracks)
        s = vis.shape[1] / 960
        cv2.putText(vis, f"fish in view: {len(fish)}", (int(12 * s), int(36 * s)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9 * s, (255, 255, 255), max(1, round(2 * s)), cv2.LINE_AA)
        if args.out:
            if writer is None:
                h, w = vis.shape[:2]
                writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
            writer.write(vis)
        if args.gif and t <= args.gif_seconds:
            h, w = vis.shape[:2]
            small = cv2.resize(vis, (args.gif_width, int(h * args.gif_width / w)), interpolation=cv2.INTER_AREA)
            gif_frames.append(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
    if writer:
        writer.release()
    if gif_frames:
        from PIL import Image

        imgs = [Image.fromarray(f) for f in gif_frames]
        imgs[0].save(args.gif, save_all=True, append_images=imgs[1:], duration=int(1000 / fps), loop=0, optimize=True)
        print("gif written:", args.gif)


if __name__ == "__main__":
    main()
