"""
Convert the Brackish Dataset (Kaggle: aalborguniversity/brackish-dataset) into
the folder layout Ultralytics expects.

The Kaggle download ships the 89 original .avi clips plus one label file per
frame. Frames are named <video>-<frame:04d> (1-based), same as the authors'
ffmpeg extraction script, so we decode the videos with OpenCV and match labels by
name. Train/valid/test membership comes from the official split files.

Careful: the files in annotations_YOLO are not standard YOLO. Class ids are
1-based and boxes are "cx cy w h" in pixels of the 960x540 frame, e.g.
"6 432 474 66 78" is a starfish. They are normalised here.

Class mapping (fish and small_fish are merged, the rest kept):
    fish, small_fish -> 0 fish
    crab             -> 1 crab
    shrimp           -> 2 shrimp
    jellyfish        -> 3 jellyfish
    starfish         -> 4 starfish

usage:
    kaggle datasets download aalborguniversity/brackish-dataset -p data/brackish --unzip
    python training/prepare_brackish.py --src data/brackish --dst data/brackish-yolo
"""

import argparse
from pathlib import Path

import cv2

# label files use 1-based ids in the order of Brackish.names
CLASS_MAP = {1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4}
NAMES = ["fish", "crab", "shrimp", "jellyfish", "starfish"]
SPLITS = {"train": "train.txt", "val": "valid.txt", "test": "test.txt"}


FRAME_W, FRAME_H = 960, 540


def read_split(path):
    return {Path(line.strip()).stem for line in open(path) if line.strip()}


def convert_label(text):
    """Brackish label text -> list of (class, normalised YOLO line)."""
    out = []
    for line in text.split("\n"):
        parts = line.split()
        if len(parts) != 5:
            continue
        cls = CLASS_MAP[int(parts[0])]
        cx, cy, w, h = map(float, parts[1:])
        x1, y1 = max(cx - w / 2, 0), max(cy - h / 2, 0)
        x2, y2 = min(cx + w / 2, FRAME_W), min(cy + h / 2, FRAME_H)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        out.append((cls, f"{cls} {(x1 + x2) / 2 / FRAME_W:.6f} {(y1 + y2) / 2 / FRAME_H:.6f} "
                         f"{(x2 - x1) / FRAME_W:.6f} {(y2 - y1) / FRAME_H:.6f}"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="unzipped Kaggle download")
    ap.add_argument("--dst", required=True)
    ap.add_argument("--train-stride", type=int, default=2,
                    help="keep every Nth training frame (neighbouring frames are near duplicates)")
    ap.add_argument("--jpg-quality", type=int, default=92)
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    split_of = {}
    for split, fname in SPLITS.items():
        for stem in read_split(src / fname):
            split_of[stem] = split
    for split in SPLITS:
        (dst / "images" / split).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / split).mkdir(parents=True, exist_ok=True)

    label_dir = src / "annotations" / "annotations_YOLO"
    counts = {s: 0 for s in SPLITS}
    boxes = [0] * len(NAMES)
    videos = sorted((src / "dataset" / "videos").rglob("*.avi"))
    print(f"{len(videos)} videos")

    for vid in videos:
        cap = cv2.VideoCapture(str(vid))
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            stem = f"{vid.stem}-{idx:04d}"
            split = split_of.get(stem)
            if split is None:
                continue
            if split == "train" and idx % args.train_stride:
                continue
            frame = cv2.resize(frame, (FRAME_W, FRAME_H), interpolation=cv2.INTER_CUBIC)
            cv2.imwrite(str(dst / "images" / split / f"{stem}.jpg"), frame,
                        [cv2.IMWRITE_JPEG_QUALITY, args.jpg_quality])

            lbl = label_dir / f"{stem}.txt"
            converted = convert_label(lbl.read_text()) if lbl.exists() else []
            for cls, _ in converted:
                boxes[cls] += 1
            (dst / "labels" / split / f"{stem}.txt").write_text("\n".join(line for _, line in converted))
            counts[split] += 1
        cap.release()

    yaml = (f"path: {dst.resolve().as_posix()}\n"
            "train: images/train\nval: images/val\ntest: images/test\n"
            f"nc: {len(NAMES)}\nnames: {NAMES}\n")
    (dst / "brackish.yaml").write_text(yaml)
    print("images per split:", counts)
    print("boxes per class:", dict(zip(NAMES, boxes)))


if __name__ == "__main__":
    main()
