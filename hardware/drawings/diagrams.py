#!/usr/bin/env python3
"""Draws hardware/wiring_diagram.svg and docs/images/block_diagram.svg (plain SVG, no dependencies).

    python hardware/drawings/diagrams.py
"""

from __future__ import annotations

import math
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

C = {
    "sw5v": "#d62728", "v3": "#ff7f0e", "gnd": "#222222", "sig": "#1f77b4", "iso": "#17becf",
    "ctl": "#2ca02c", "i2c": "#9467bd", "usb": "#7f7f7f", "vin": "#8c564b", "act": "#e377c2",
    "ink": "#1d1d1b", "ink2": "#55534e", "line": "#c9c7bf",
    "probe": "#eef6fc", "board": "#f4f1fb", "mcu": "#e9f5ec", "shield": "#fff7e8", "ext": "#f6f6f4",
}


class Svg:
    def __init__(self, w: int, h: int, title: str):
        self.w, self.h, self.items = w, h, []
        self.title = title

    def rect(self, x, y, w, h, fill="#fff", stroke=C["line"], rx=10, sw=1.5, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                          f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=13, anchor="start", weight="normal", fill=C["ink"], italic=False):
        style = ' font-style="italic"' if italic else ""
        for i, line in enumerate(str(s).split("\n")):
            self.items.append(f'<text x="{x}" y="{y + i * (size + 3)}" font-size="{size}" text-anchor="{anchor}" '
                              f'font-weight="{weight}" fill="{fill}"{style}>{escape(line)}</text>')

    def wire(self, pts, color, width=2.6, dash=None, label=None, lx=None, ly=None):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pts))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
                          f'stroke-linejoin="round" stroke-linecap="round"{da}/>')
        if label:
            x = lx if lx is not None else (pts[0][0] + pts[-1][0]) / 2
            y = ly if ly is not None else (pts[0][1] + pts[-1][1]) / 2 - 6
            self.items.append(f'<text x="{x}" y="{y}" font-size="11" text-anchor="middle" fill="{color}" '
                              f'font-weight="600" paint-order="stroke" stroke="#ffffff" stroke-width="4">'
                              f'{escape(label)}</text>')

    def pin(self, x, y):
        self.items.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#fff" stroke="{C["ink"]}" stroke-width="1.5"/>')

    def arrow(self, pts, color, width=2.2, dash=None):
        self.wire(pts, color, width, dash=dash)
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        a = math.atan2(y2 - y1, x2 - x1)
        p1 = (x2 - 10 * math.cos(a - 0.4), y2 - 10 * math.sin(a - 0.4))
        p2 = (x2 - 10 * math.cos(a + 0.4), y2 - 10 * math.sin(a + 0.4))
        self.items.append(f'<path d="M{x2},{y2} L{p1[0]:.1f},{p1[1]:.1f} L{p2[0]:.1f},{p2[1]:.1f} Z" fill="{color}"/>')

    def save(self, path: Path):
        body = "\n".join(self.items)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
               f'height="{self.h}" font-family="Segoe UI, Helvetica, Arial, sans-serif">\n'
               f'<title>{escape(self.title)}</title>\n<rect width="100%" height="100%" fill="#ffffff"/>\n{body}\n</svg>\n')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
        print("wrote", path.relative_to(ROOT))


# ===========================================================================
# Wiring diagram
# ===========================================================================
PINS = {  # y position of each UNO Q header pin used (left edge of the board)
    "5V": 350, "3V3": 380, "GND": 410,
    "A0": 460, "A1": 500, "A2": 540, "A3": 580,
    "D4": 620, "D5": 650, "D6": 680, "D7": 710,
    "D8": 800, "D9": 860, "QWIIC": 940,
}


def wiring() -> None:
    s = Svg(1500, 1040, "AquaSense wiring diagram")
    s.text(30, 40, "AquaSense - wiring diagram", size=22, weight="700")
    s.text(30, 64, "Arduino UNO Q (ABX00173, 4 GB), all MCU I/O is 3.3 V, analog inputs A0–A5 must stay within 0–3.3 V",
           size=13, fill=C["ink2"])

    def module(x, y, w, h, title, sub, fill, stroke="#8aa9c4"):
        s.rect(x, y, w, h, fill=fill, stroke=stroke, rx=10)
        s.text(x + 12, y + 22, title, size=13.5, weight="700")
        s.text(x + 12, y + 40, sub, size=11, fill=C["ink2"])

    # ---------------- UNO Q -------------------------------------------------
    ux, uy, uw, uh = 960, 95, 280, 885
    s.rect(ux, uy, uw, uh, fill=C["mcu"], stroke="#2e7d32", sw=2.2, rx=14)
    s.text(ux + uw / 2, uy + 30, "Arduino UNO Q", size=18, anchor="middle", weight="700")
    s.text(ux + uw / 2, uy + 50, "ABX00173, 4 GB RAM, 32 GB eMMC", size=11.5, anchor="middle", fill=C["ink2"])
    bx = ux + 45
    s.rect(bx, uy + 62, 190, 92, fill="#ffffff", stroke="#9bbfa0", rx=8)
    s.text(bx + 95, uy + 83, "Qualcomm QRB2210 (MPU)", size=12.5, anchor="middle", weight="700")
    s.text(bx + 95, uy + 100, "4× Cortex-A53, Debian Linux", size=11, anchor="middle", fill=C["ink2"])
    s.text(bx + 95, uy + 116, "Python: camera, YOLOv8n,", size=11, anchor="middle", fill=C["ink2"])
    s.text(bx + 95, uy + 132, "behaviour checks, logging", size=11, anchor="middle", fill=C["ink2"])
    s.text(bx + 95, uy + 170, "↕ Bridge RPC (aq_*)", size=11.5, anchor="middle", fill="#2e7d32", weight="700")
    s.rect(bx, uy + 178, 190, 62, fill="#ffffff", stroke="#9bbfa0", rx=8)
    s.text(bx + 95, uy + 198, "STM32U585 (MCU)", size=12.5, anchor="middle", weight="700")
    s.text(bx + 95, uy + 215, "Zephyr, sketch.ino", size=11, anchor="middle", fill=C["ink2"])
    s.text(bx + 95, uy + 231, "power gating, ADC, I²C", size=11, anchor="middle", fill=C["ink2"])

    for name, y in PINS.items():
        s.pin(ux, y)
        s.text(ux + 10, y + 4, "Qwiic" if name == "QWIIC" else name, size=12, weight="700")
    groups = {"5V": "JANALOG power", "A0": "JANALOG ADC", "D4": "JDIGITAL", "D8": "JDIGITAL",
              "QWIIC": "I²C4, Wire1, 3.3 V"}
    for name, label in groups.items():
        s.text(ux + 60, PINS[name] + 4, label, size=10.5, fill=C["ink2"], italic=True)
    s.pin(ux + uw, 400)
    s.text(ux + uw - 10, 404, "USB-C", size=12, anchor="end", weight="700")
    s.pin(ux + uw, 580)
    s.text(ux + uw - 10, 584, "VIN 7–24 V", size=12, anchor="end", weight="700")
    for i, ln in enumerate(("LED3 RGB: water status", "LED4: link heartbeat")):
        s.text(ux + uw - 10, 700 + i * 17, ln, size=11, anchor="end", fill=C["ink2"])

    # ---------------- Sensor shield -----------------------------------------
    sx, sy, sw_, sh = 560, 330, 290, 420
    s.rect(sx, sy, sw_, sh, fill=C["shield"], stroke="#d9a33a", sw=2, rx=12)
    s.text(sx + 16, sy + 26, "Sensor shield", size=15, weight="700")
    s.text(sx + 16, sy + 44, "perfboard on the UNO headers", size=11, fill=C["ink2"])
    s.text(sx + 16, sy + 76, "per channel:", size=11.5, weight="700")
    for i, ln in enumerate(("• high-side switch AO3401A + BC547", "• 1 kΩ + 100 nF RC, BAT54S clamp",
                            "• CH4: 10k / 20k divider", "  (4.5 V → 3.0 V)")):
        s.text(sx + 16, sy + 94 + i * 16, ln, size=11, fill=C["ink2"])
    for label, pin in (("CH1 pH", "A0"), ("CH2 DO", "A1"), ("CH3 EC", "A2"), ("CH4 turbidity", "A3")):
        s.text(sx + sw_ - 12, PINS[pin] + 4, label, size=11.5, anchor="end", weight="600")
    s.text(sx + sw_ - 12, PINS["5V"] + 4, "power in", size=11, anchor="end", fill=C["ink2"])
    s.text(sx + sw_ - 12, PINS["D4"] + 4, "enables", size=11, anchor="end", fill=C["ink2"])

    x_mid = (sx + sw_ + ux) / 2
    s.wire([(sx + sw_, PINS["5V"]), (ux, PINS["5V"])], C["sw5v"], label="+5V_SYS", lx=x_mid)
    s.wire([(sx + sw_, PINS["3V3"]), (ux, PINS["3V3"])], C["v3"], label="+3V3 (clamps)", lx=x_mid)
    s.wire([(sx + sw_, PINS["GND"]), (ux, PINS["GND"])], C["gnd"], label="GND", lx=x_mid)
    for name in ("A0", "A1", "A2", "A3"):
        s.wire([(sx + sw_, PINS[name]), (ux, PINS[name])], C["sig"], label=f"{name} ← signal", lx=x_mid)
    for name, ch in (("D4", "EN_PH"), ("D5", "EN_DO"), ("D6", "EN_EC"), ("D7", "EN_TU")):
        s.wire([(sx + sw_, PINS[name]), (ux, PINS[name])], C["ctl"], label=f"{name} → {ch}", lx=x_mid)
    for name in ("5V", "3V3", "GND", "A0", "A1", "A2", "A3", "D4", "D5", "D6", "D7"):
        s.pin(sx + sw_, PINS[name])

    # ---------------- Probes, isolators --------------------------------------
    def channel(y, title, sub, sw_label, sig_label, isolator):
        module(40, y, 230, 80, title, sub, C["probe"])
        if isolator:
            module(320, y, 170, 80, "Signal isolator", "DFR0504\ngalvanic isolation", C["board"], "#a99bd0")
            s.wire([(270, y + 28), (320, y + 28)], C["iso"])
            s.wire([(270, y + 56), (320, y + 56)], C["iso"], dash="5 4")
            x0 = 490
        else:
            x0 = 270
        s.wire([(x0, y + 28), (sx, y + 28)], C["sw5v"], label=sw_label, lx=(x0 + sx) / 2)
        s.wire([(x0, y + 56), (sx, y + 56)], C["sig"], label=sig_label, lx=(x0 + sx) / 2)
        s.pin(sx, y + 28)
        s.pin(sx, y + 56)

    channel(330, "pH probe + Gravity pH V2", "BNC electrode, SEN0161-V2\nout 0–3.0 V", "SW_5V_PH", "SIG_PH", True)
    channel(440, "Dissolved-oxygen probe", "galvanic, Gravity SEN0237\nout 0–3.0 V", "SW_5V_DO", "SIG_DO", False)
    channel(550, "Conductivity / salinity", "K=1 DFR0300 (fresh) or\nK=10 SEN0451 (brackish)", "SW_5V_EC", "SIG_EC", True)
    channel(660, "Turbidity sensor", "optical, Gravity SEN0189\nout 0–4.5 V @ 5 V", "SW_5V_TU", "SIG_TU (÷1.5 on shield)", False)
    s.text(295, 428, "isolated probe side ┘", size=10.5, fill=C["iso"], italic=True)

    # ---------------- Relay + buzzer -------------------------------------------
    module(590, 775, 210, 52, "Aerator relay / SSR", "opto-isolated, optional", C["ext"], "#d48fbf")
    s.wire([(800, PINS["D8"]), (ux, PINS["D8"])], C["act"], label="D8 → relay IN", lx=880)
    s.arrow([(590, 801), (520, 801)], C["act"])
    s.text(512, 797, "contactor → pond aerator", size=11, anchor="end", fill=C["ink2"])
    s.text(512, 812, "(mains wiring by an electrician)", size=10.5, anchor="end", fill=C["ink2"], italic=True)
    module(590, 835, 210, 52, "Alarm buzzer", "5 V active, BC547 driver", C["ext"], "#d48fbf")
    s.wire([(800, PINS["D9"]), (ux, PINS["D9"])], C["act"], label="D9 → buzzer", lx=880)

    # ---------------- Temperature ------------------------------------------------
    module(40, 905, 230, 70, "DS18B20 waterproof", "water temperature (compensation)", C["probe"])
    module(320, 905, 190, 70, "DS2484 / DS2482-100", "I²C → 1-Wire bridge, 0x18", C["board"], "#a99bd0")
    s.wire([(270, 930), (320, 930)], C["sig"], label="DQ", lx=295)
    s.wire([(270, 955), (320, 955)], C["v3"], label="3V3", lx=295, ly=971)
    s.wire([(510, PINS["QWIIC"]), (ux, PINS["QWIIC"])], C["i2c"], width=3.4,
           label="Qwiic cable: SDA, SCL, 3V3, GND", lx=735)

    # ---------------- Right side: camera, power ----------------------------------
    module(1290, 330, 190, 60, "USB-C hub (PD)", "data + power pass-through", C["ext"])
    module(1290, 420, 190, 74, "USB UVC camera", "IR night vision helps;\nabove tank / pond", C["ext"])
    s.wire([(ux + uw, 400), (1265, 400), (1265, 360), (1290, 360)], C["usb"], width=3, label="USB", lx=1266, ly=392)
    s.wire([(1385, 390), (1385, 420)], C["usb"], width=3)
    module(1290, 535, 190, 90, "12 V supply", "LiFePO4 / lead-acid +\nsolar charge controller\nor 12 V 3 A adapter", C["ext"])
    s.wire([(1290, 580), (ux + uw, 580)], C["vin"], width=3, label="12 V", lx=1265)

    # ---------------- Legend --------------------------------------------------------
    lx, ly = 1270, 660
    s.rect(lx, ly, 215, 290, fill="#ffffff", stroke=C["line"], rx=10)
    s.text(lx + 14, ly + 24, "Legend", size=14, weight="700")
    legend = [
        (C["sw5v"], "+5 V (switched per probe)"), (C["v3"], "+3.3 V"), (C["gnd"], "ground (common)"),
        (C["sig"], "analog signal 0–3.3 V"), (C["iso"], "isolated probe side"), (C["ctl"], "MCU enable (HIGH = on)"),
        (C["i2c"], "I²C (Qwiic, Wire1)"), (C["act"], "actuator outputs"), (C["usb"], "USB"), (C["vin"], "12 V input"),
    ]
    for i, (col, label) in enumerate(legend):
        y = ly + 48 + i * 23
        s.wire([(lx + 16, y), (lx + 48, y)], col, width=3.5)
        s.text(lx + 58, y + 4, label, size=11.5)
    s.text(30, 1022, "Every module GND is tied to the UNO Q GND (isolated sides excepted). Probe rails stay OFF until the "
           "vision model (or a schedule) requests a measurement.", size=11.5, fill=C["ink2"])
    s.save(ROOT / "hardware" / "wiring_diagram.svg")


# ===========================================================================
# Architecture figure
# ===========================================================================
def architecture() -> None:
    s = Svg(1400, 760, "AquaSense block diagram")
    s.text(30, 42, "AquaSense - block diagram", size=22, weight="700")
    s.text(30, 66, "What runs where on the Arduino UNO Q, and how a camera alert turns into a probe reading.",
           size=13, fill=C["ink2"])

    def box(x, y, w, h, title, lines, fill="#ffffff", stroke="#9aa5b1"):
        s.rect(x, y, w, h, fill=fill, stroke=stroke, rx=10)
        s.text(x + 14, y + 24, title, size=14, weight="700")
        for i, ln in enumerate(lines):
            s.text(x + 14, y + 44 + i * 17, ln, size=11.5, fill=C["ink2"])

    blue, red, green = "#2a78d6", "#d03b3b", "#2e7d32"

    def label(x, y, text, col, anchor="start"):
        s.text(x, y, text, size=12, fill=col, weight="700", anchor=anchor)

    s.rect(20, 90, 1360, 330, fill="#f7fbff", stroke="#bcd3ea", rx=14, dash="6 5")
    s.text(36, 114, "Linux MPU, Qualcomm QRB2210, Python (app/python)", size=13, weight="700", fill="#2a5f93")
    s.rect(20, 440, 1360, 160, fill="#f4faf5", stroke="#b9dcc0", rx=14, dash="6 5")
    s.text(36, 464, "Real-time MCU, STM32U585, Zephyr (app/sketch)", size=13, weight="700", fill="#2e7d32")
    s.rect(20, 620, 1360, 120, fill="#fffaf0", stroke="#ecd3a2", rx=14, dash="6 5")
    s.text(36, 644, "Pond hardware", size=13, weight="700", fill="#9a6b13")

    # row 1: vision
    box(40, 130, 180, 120, "USB camera", ["640x480 frames", "3 fps to the model", "fish_detector.py"])
    box(250, 130, 230, 120, "YOLOv8n (ONNX)", ["trained on Brackish dataset", "416 px input, onnxruntime",
                                               "fish, crab, shrimp, ..."], "#eef4ff", "#7aa2d8")
    box(510, 130, 250, 120, "Centroid tracker", ["matches fish frame to frame", "speed in body lengths / s",
                                                 "tracker.py"])
    box(790, 130, 240, 120, "Behaviour checks", ["10 s windows vs learned normal", "surface crowding, low activity,",
                                                 "missing / still fish, green water"])
    box(1060, 130, 260, 120, "Controller", ["2 windows in a row -> measure", "05:00 / 15:00 schedule",
                                            "follow-up, cool-down"], "#fff3f3", "#e09a9a")
    # row 2: sensing results
    box(40, 280, 180, 120, "probes.py", ["Bridge calls to the MCU", "start, poll, read result", "raw mV + temperature"])
    box(250, 280, 230, 120, "chemistry.py", ["pH (Nernst), DO (Benson-Krause", "T/S/altitude), EC -> PSS-78",
                                             "salinity, turbidity, NH3 %"])
    box(510, 280, 250, 120, "water_check.py", ["species limits (tilapia, carp,", "pangasius, vannamei shrimp)",
                                               "OK / WARNING / CRITICAL + advice"])
    box(790, 280, 240, 120, "datalog.py", ["measurements.csv", "behaviour.csv, events.csv", "snapshots of alerts"])
    box(1060, 280, 220, 120, "Outputs", ["LED3 colour = water status", "buzzer on CRITICAL", "aerator relay (optional)"])

    for x1, x2 in ((220, 250), (480, 510), (760, 790)):
        s.arrow([(x1, 190), (x2, 190)], blue)
    s.arrow([(1030, 190), (1060, 190)], red)
    label(1045, 182, "trigger", red, anchor="middle")
    for x1, x2 in ((220, 250), (480, 510), (760, 790), (1030, 1060)):
        s.arrow([(x1, 340), (x2, 340)], blue)

    # MCU lane
    box(250, 490, 330, 96, "Measurement state machine", ["one probe at a time: power → warm-up →",
                                                         "64× oversample → power off (no cross-talk)"])
    box(610, 490, 300, 96, "RPC API (Arduino_RouterBridge)", ["aq_start(mask), aq_status, aq_result",
                                                              "aq_indicator, aq_buzzer, aq_aerator"])
    box(940, 490, 260, 96, "Fail-safes", ["rails OFF at boot / reset", "60 s max rail-on, link LED"])
    s.arrow([(1300, 250), (1300, 470), (800, 470), (800, 490)], red)
    label(1060, 462, "aq_start(mask)", red)
    s.arrow([(700, 490), (700, 430), (130, 430), (130, 400)], green)
    label(150, 425, "raw mV + °C  (aq_result)", green)
    s.arrow([(610, 538), (580, 538)], red)

    # hardware lane
    box(40, 660, 300, 66, "Probe power switches ×4", ["P-MOSFET high-side, MCU-enabled"])
    box(370, 660, 420, 66, "Probes", ["pH, DO, EC/salinity, turbidity, DS18B20 temperature"])
    box(820, 660, 260, 66, "Actuators", ["aerator relay, buzzer"])
    s.arrow([(300, 586), (300, 660)], red)
    label(310, 630, "EN D4–D7", red)
    s.arrow([(340, 693), (370, 693)], red)
    s.arrow([(560, 660), (560, 586)], green)
    label(570, 630, "A0–A3, Qwiic", green)
    s.arrow([(860, 586), (930, 660)], red)
    label(905, 620, "D8, D9", red)
    s.save(ROOT / "docs" / "images" / "block_diagram.svg")


if __name__ == "__main__":
    wiring()
    architecture()
