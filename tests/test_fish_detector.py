import numpy as np

from fish_detector import FishDetector, nms


def test_nms_keeps_best_of_overlapping_boxes():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], np.float32)
    scores = np.array([0.9, 0.8, 0.7], np.float32)
    assert sorted(nms(boxes, scores, 0.5)) == [0, 2]


class FakeSession:
    """Returns one 'fish' box in the YOLOv8 output layout (1, 4 + nc, N)."""

    def __init__(self, size, nc=5):
        self.size, self.nc = size, nc

    def run(self, _, feeds):
        x = feeds["images"]
        assert x.shape == (1, 3, self.size, self.size) and x.dtype == np.float32
        out = np.zeros((1, 4 + self.nc, 3), np.float32)
        out[0, :4, 0] = [208, 208, 52, 26]   # centre of the 416 input, 52x26 px
        out[0, 4, 0] = 0.9                   # class 0 = fish
        out[0, :4, 1] = [210, 209, 50, 25]   # duplicate, should be suppressed
        out[0, 4, 1] = 0.6
        out[0, 5, 2] = 0.1                   # below threshold
        return [out]


def test_boxes_are_mapped_back_to_the_camera_frame():
    det = FishDetector.__new__(FishDetector)
    det.session, det.input_name, det.size = FakeSession(416), "images", 416
    det.names, det.conf, det.iou = ["fish", "crab", "shrimp", "jellyfish", "starfish"], 0.35, 0.5

    frame = np.zeros((480, 640, 3), np.uint8)    # scale 0.65, letterbox pads 52 px top/bottom
    out = det.detect(frame)
    assert len(out) == 1 and out[0].label == "fish"
    assert abs(out[0].cx - 320) < 1 and abs(out[0].cy - 240) < 1
    assert abs((out[0].x2 - out[0].x1) - 80) < 1
