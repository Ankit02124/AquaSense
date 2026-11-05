"""
Time the YOLO model with onnxruntime. Run it on the UNO Q (over SSH or from the
App Lab terminal) to see how many frames per second the A53 cores manage.

    pip install onnxruntime opencv-python-headless numpy
    python tools/benchmark.py --model app/python/models/aquasense_yolov8n_416.onnx --image sample.jpg
"""

import argparse
import platform
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "python"))
from fish_detector import FishDetector  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--image", help="test image (default: random noise)")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    det = FishDetector(args.model, ["fish", "crab", "shrimp", "jellyfish", "starfish"], threads=args.threads)
    img = cv2.imread(args.image) if args.image else np.random.randint(0, 255, (480, 640, 3), np.uint8)
    for _ in range(3):
        det.detect(img)
    times = []
    for _ in range(args.runs):
        t0 = time.perf_counter()
        n = len(det.detect(img))
        times.append((time.perf_counter() - t0) * 1000)
    print(f"{platform.machine()} {platform.processor() or ''}".strip())
    print(f"model input {det.size}x{det.size}, {args.threads} threads, {n} detections")
    print(f"median {statistics.median(times):.1f} ms, mean {statistics.fmean(times):.1f} ms, "
          f"-> {1000 / statistics.median(times):.1f} fps")


if __name__ == "__main__":
    main()
