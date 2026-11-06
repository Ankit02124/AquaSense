"""
Evaluate on the held-out test split at the training size and at the input size
the app uses, and write the numbers to training/results/metrics.md.

    python training/evaluate.py --weights training/weights/yolov8n_brackish_best.pt \
        --data data/brackish-yolo/brackish.yaml
"""

import argparse
from pathlib import Path

from ultralytics import YOLO

RESULTS = Path(__file__).resolve().parent / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--sizes", type=int, nargs="+", default=[640, 416])
    args = ap.parse_args()

    model = YOLO(args.weights)
    names = model.names
    lines = ["| image size | class | precision | recall | mAP@0.5 | mAP@0.5:0.95 |",
             "|---|---|---|---|---|---|"]
    for size in args.sizes:
        m = model.val(data=args.data, split="test", imgsz=size, batch=16, plots=False, verbose=False)
        b = m.box
        lines.append(f"| {size} | all | {b.mp:.3f} | {b.mr:.3f} | {b.map50:.3f} | {b.map:.3f} |")
        for i, c in enumerate(m.ap_class_index):
            p, r, ap50, ap = b.class_result(i)
            lines.append(f"| {size} | {names[int(c)]} | {p:.3f} | {r:.3f} | {ap50:.3f} | {ap:.3f} |")

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "metrics.md").write_text("Test split of the Brackish Dataset (1468 frames).\n\n" + "\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
