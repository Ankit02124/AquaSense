"""
Draw predictions of the exported ONNX model (the same file and code the UNO Q
uses) on random test images, next to the ground truth.

    python training/sample_predictions.py --data data/brackish-yolo --out training/results/test_predictions.jpg
"""

import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np

APP = Path(__file__).resolve().parents[1] / "app" / "python"
sys.path.insert(0, str(APP))
from fish_detector import FishDetector  # noqa: E402

COLOURS = [(0, 200, 255), (0, 0, 255), (255, 160, 0), (255, 0, 255), (0, 255, 0)]


def draw_truth(img, label_file, names):
    h, w = img.shape[:2]
    for line in label_file.read_text().splitlines():
        c, cx, cy, bw, bh = line.split()
        c, cx, cy, bw, bh = int(c), float(cx) * w, float(cy) * h, float(bw) * w, float(bh) * h
        cv2.rectangle(img, (int(cx - bw / 2), int(cy - bh / 2)), (int(cx + bw / 2), int(cy + bh / 2)), COLOURS[c], 2)
    cv2.putText(img, "ground truth", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)


def draw_pred(img, dets):
    for d in dets:
        cv2.rectangle(img, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)), COLOURS[d.cls], 2)
        cv2.putText(img, f"{d.label} {d.conf:.2f}", (int(d.x1), max(14, int(d.y1) - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOURS[d.cls], 1, cv2.LINE_AA)
    cv2.putText(img, "YOLOv8n (ONNX, 416)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="converted dataset folder")
    ap.add_argument("--model", default=str(APP / "models" / "aquasense_yolov8n_416.onnx"))
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    names = (APP / "models" / "classes.txt").read_text().split()
    det = FishDetector(args.model, names, conf=0.35)
    data = Path(args.data)
    # frames with at least two fish, one per video so the grid is not four copies of one scene
    labels = [p for p in sorted((data / "labels" / "test").glob("*.txt"))
              if sum(line.startswith("0 ") for line in p.read_text().splitlines()) >= 2]
    random.Random(args.seed).shuffle(labels)
    picked, videos = [], set()
    for p in labels:
        video = p.stem.rsplit("-", 1)[0]
        if video not in videos:
            videos.add(video)
            picked.append(p)

    rows = []
    for lbl in picked[:args.n]:
        img = cv2.imread(str(data / "images" / "test" / f"{lbl.stem}.jpg"))
        truth, pred = img.copy(), img.copy()
        draw_truth(truth, lbl, names)
        draw_pred(pred, det.detect(img))
        rows.append(np.hstack([truth, pred]))
    grid = np.vstack(rows)
    grid = cv2.resize(grid, (grid.shape[1] // 2, grid.shape[0] // 2), interpolation=cv2.INTER_AREA)
    cv2.imwrite(args.out, grid, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print("written", args.out, grid.shape)


if __name__ == "__main__":
    main()
