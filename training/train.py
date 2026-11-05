"""
Train YOLOv8n on the converted Brackish dataset.

    python training/train.py --data data/brackish-yolo/brackish.yaml

Defaults are what I used on an RTX 3050 Laptop GPU (4 GB). On a CPU-only
machine use Kaggle/Colab or lower --epochs.
"""

import argparse

from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", default="yolov8n.pt", help="COCO-pretrained starting point")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--name", default="yolov8n_brackish")
    args = ap.parse_args()

    model = YOLO(args.model)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        patience=15,
        close_mosaic=10,
        seed=0,
        project="runs",
        name=args.name,
        exist_ok=True,
        # underwater footage: colour varies a lot with turbidity and light,
        # so keep hue/saturation augmentation on and add a bit more value jitter
        hsv_v=0.5,
        fliplr=0.5,
    )


if __name__ == "__main__":
    main()
