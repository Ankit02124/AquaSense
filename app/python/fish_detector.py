"""YOLOv8 fish detector running from an ONNX file with onnxruntime.

The model is trained in training/ (Brackish dataset, 5 classes) and exported
without NMS, so the output is the raw (1, 4 + num_classes, N) tensor. Letterbox
preprocessing and NMS are done here so the board does not need torch or
ultralytics installed.
"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    cls: int
    label: str

    @property
    def cx(self):
        return (self.x1 + self.x2) / 2

    @property
    def cy(self):
        return (self.y1 + self.y2) / 2

    @property
    def size(self):
        # longest side of the box, used as "one body length"
        return max(self.x2 - self.x1, self.y2 - self.y1)


def nms(boxes, scores, iou_thr):
    """Plain greedy NMS. boxes: (N, 4) x1y1x2y2."""
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou < iou_thr]
    return keep


class FishDetector:
    def __init__(self, model_path, class_names, conf=0.35, iou=0.5, threads=4):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2])
        self.names = list(class_names)
        self.conf = conf
        self.iou = iou

    def _letterbox(self, img):
        h, w = img.shape[:2]
        r = self.size / max(h, w)
        nw, nh = round(w * r), round(h * r)
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        dx, dy = (self.size - nw) // 2, (self.size - nh) // 2
        canvas[dy:dy + nh, dx:dx + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        return canvas, r, dx, dy

    def detect(self, frame_bgr):
        img, r, dx, dy = self._letterbox(frame_bgr)
        x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        pred = self.session.run(None, {self.input_name: x})[0][0].T  # (N, 4 + nc)

        scores = pred[:, 4:]
        cls = scores.argmax(1)
        conf = scores[np.arange(len(cls)), cls]
        mask = conf >= self.conf
        if not mask.any():
            return []
        cxcywh, cls, conf = pred[mask, :4], cls[mask], conf[mask]

        boxes = np.empty_like(cxcywh)
        boxes[:, 0] = (cxcywh[:, 0] - cxcywh[:, 2] / 2 - dx) / r
        boxes[:, 1] = (cxcywh[:, 1] - cxcywh[:, 3] / 2 - dy) / r
        boxes[:, 2] = (cxcywh[:, 0] + cxcywh[:, 2] / 2 - dx) / r
        boxes[:, 3] = (cxcywh[:, 1] + cxcywh[:, 3] / 2 - dy) / r
        h, w = frame_bgr.shape[:2]
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)

        # class-aware NMS: shift each class to its own region so boxes of
        # different classes never suppress each other
        offset = cls[:, None].astype(np.float32) * 10000.0
        keep = nms(boxes + offset, conf, self.iou)
        return [Detection(*boxes[i].tolist(), float(conf[i]), int(cls[i]), self.names[int(cls[i])]) for i in keep]


def draw(frame, detections, tracks=None):
    colours = {"fish": (0, 200, 255), "shrimp": (255, 160, 0), "crab": (0, 0, 255)}
    out = frame.copy()
    s = out.shape[1] / 960          # keep lines and text readable at any resolution
    line, text = max(1, round(2 * s)), max(1, round(1.5 * s))
    for d in detections:
        c = colours.get(d.label, (200, 200, 200))
        cv2.rectangle(out, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)), c, line)
        cv2.putText(out, f"{d.label} {d.conf:.2f}", (int(d.x1), max(int(14 * s), int(d.y1) - int(4 * s))),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5 * s, c, text, cv2.LINE_AA)
    for t in tracks or []:
        pts = [(int(x), int(y)) for _, x, y in t.history]
        for a, b in zip(pts, pts[1:]):
            cv2.line(out, a, b, (0, 255, 0), line)
    return out
