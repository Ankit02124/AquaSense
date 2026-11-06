"""
Export the trained weights to ONNX for the UNO Q and copy them into the app.

    python training/export.py --weights training/weights/yolov8n_brackish_best.pt --imgsz 416

416 px is a compromise for the Cortex-A53: 640 px detects small fish better but
has about 2.4x the pixels to process. NMS is not baked into the graph, app/python/fish_detector.py
does it in numpy.
"""

import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO

APP_MODELS = Path(__file__).resolve().parents[1] / "app" / "python" / "models"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--imgsz", type=int, default=416)
    args = ap.parse_args()

    model = YOLO(args.weights)
    onnx_path = Path(model.export(format="onnx", imgsz=args.imgsz, opset=12, simplify=True, dynamic=False))

    APP_MODELS.mkdir(parents=True, exist_ok=True)
    target = APP_MODELS / f"aquasense_yolov8n_{args.imgsz}.onnx"
    shutil.copy(onnx_path, target)
    (APP_MODELS / "classes.txt").write_text("\n".join(model.names[i] for i in sorted(model.names)) + "\n")
    print(f"copied to {target} ({target.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
