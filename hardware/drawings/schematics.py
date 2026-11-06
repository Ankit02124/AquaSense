"""Regenerate the circuit schematics (SVG) with schemdraw.

    pip install schemdraw
    python hardware/drawings/schematics.py
"""

from pathlib import Path

import schemdraw
import schemdraw.elements as elm

OUT = Path(__file__).resolve().parents[1] / "schematics"
schemdraw.use("svg")
FONT = 11
NL = "\n"


def title(d: schemdraw.Drawing, text: str, xy) -> None:
    d.add(elm.Label().at(xy).label(text, fontsize=13, halign="left"))


def note(d: schemdraw.Drawing, text: str, xy) -> None:
    d.add(elm.Label().at(xy).label(text, fontsize=9, halign="left", color="#555555"))


def wire(d: schemdraw.Drawing, a, b) -> None:
    d.add(elm.Line().at(a).to(b))


def dot(d: schemdraw.Drawing, xy) -> None:
    d.add(elm.Dot().at(xy))


# ---------------------------------------------------------------------------
# 1. High-side power switch (one per probe: pH, DO, EC, turbidity)
# ---------------------------------------------------------------------------
def power_switch() -> None:
    with schemdraw.Drawing(file=str(OUT / "power_switch_channel.svg"), show=False) as d:
        d.config(fontsize=FONT, unit=2.4)
        d.add(elm.Vdd().at((0, 1.5)).label("+5V_SYS  (UNO Q 5V pin)"))
        wire(d, (-3, 1.5), (0, 1.5))
        dot(d, (0, 1.5))
        q1 = d.add(elm.PFet(bulk=True).theta(0).reverse().anchor("source").at((0, 0))
                   .label("Q1  AO3401A" + NL + "P-MOSFET", loc="right", ofst=(0.2, 0)))
        wire(d, (0, 0), (0, 1.5))
        d.add(elm.Resistor().at((-3, 1.5)).to((-3, -0.75)).label("R1" + NL + "10 kΩ", loc="bottom"))
        dot(d, (-3, -0.75))
        wire(d, q1.gate, (-3, -0.75))
        wire(d, (-3, -0.75), (-3, -1.75))
        q2 = d.add(elm.BjtNpn(circle=True).theta(0).anchor("collector").at((-3, -1.75))
                   .label("Q2  BC547 / 2N3904" + NL + "NPN", loc="right", ofst=(0.1, -0.2)))
        d.add(elm.Ground().at(q2.emitter))
        bx, by = q2.base
        wire(d, q2.base, (bx - 1.0, by))
        dot(d, (bx - 1.0, by))
        d.add(elm.Resistor().at((bx - 1.0, by)).left(2.6).label("R2  10 kΩ"))
        d.add(elm.Dot(open=True).label("MCU D4 / D5 / D6 / D7" + NL + "(3.3 V logic, HIGH = ON)", loc="left"))
        d.add(elm.Resistor().at((bx - 1.0, by)).down(2.0).label("R3" + NL + "100 kΩ", loc="bottom"))
        d.add(elm.Ground())
        wire(d, q1.drain, (0, -3.0))
        dot(d, (0, -3.0))
        wire(d, (0, -3.0), (2.5, -3.0))
        dot(d, (2.5, -3.0))
        d.add(elm.Capacitor(polar=True).at((2.5, -3.0)).down(2.0).label("C1" + NL + "10 µF", loc="bottom"))
        d.add(elm.Ground())
        wire(d, (2.5, -3.0), (4.5, -3.0))
        dot(d, (4.5, -3.0))
        d.add(elm.Capacitor().at((4.5, -3.0)).down(2.0).label("C2" + NL + "100 nF", loc="bottom"))
        d.add(elm.Ground())
        wire(d, (4.5, -3.0), (6.5, -3.0))
        d.add(elm.Dot(open=True).at((6.5, -3.0))
              .label("SW_5V_x  →  probe board" + NL + "(or signal isolator) VCC", loc="right"))
        title(d, "High-side probe power switch  (×4: pH, DO, EC, turbidity)", (-11, 4.6))
        note(d, "MCU pin LOW or in reset → R3 keeps Q2 off → R1 keeps Q1 off → probe unpowered (fail-safe).", (-11, 3.8))
        note(d, "Only +5 V is switched; ground stays common so analog references are never lifted.", (-11, 3.2))


# ---------------------------------------------------------------------------
# 2. Analog front-end for each ADC input
# ---------------------------------------------------------------------------
def analog_frontend() -> None:
    with schemdraw.Drawing(file=str(OUT / "analog_frontend.svg"), show=False) as d:
        d.config(fontsize=FONT, unit=2.4)
        # (a) pH / DO / EC
        title(d, "(a) Analog input conditioning: pH (A0), DO (A1), EC (A2)", (-4, 4.2))
        note(d, "RC low-pass fc ≈ 1.6 kHz; dual Schottky clamp keeps the pin inside 0 … 3.3 V.", (-4, 3.5))
        d.add(elm.Dot(open=True).at((0, 0)).label("Probe board" + NL + "signal out" + NL + "(0 – 3.0 V)", loc="left"))
        d.add(elm.Resistor().at((0, 0)).to((3, 0)).label("R4  1 kΩ"))
        dot(d, (3, 0))
        wire(d, (3, 0), (5.5, 0))
        dot(d, (5.5, 0))
        wire(d, (5.5, 0), (8.5, 0))
        d.add(elm.Dot(open=True).at((8.5, 0)).label("A0 / A1 / A2" + NL + "STM32U585 ADC" + NL + "(0 – 3.3 V max)", loc="right"))
        d.add(elm.Capacitor().at((3, 0)).down(2.2).label("C3" + NL + "100 nF", loc="bottom"))
        d.add(elm.Ground())
        d.add(elm.Schottky().at((5.5, 0)).up(2.0).label("D1a", loc="bottom"))
        d.add(elm.Vdd().label("+3V3"))
        d.add(elm.Schottky().at((5.5, 0)).down(2.0).reverse().label("D1b", loc="bottom"))
        d.add(elm.Ground())
        note(d, "D1 = BAT54S (dual Schottky)", (6.2, -2.6))

        # (b) turbidity divider
        y0 = -7.5
        title(d, "(b) Turbidity divider: A3", (-4, y0 + 3.0))
        note(d, "V_A3 = V_sensor × 20k / (10k + 20k): 4.5 V → 3.0 V   (divider_ratio: 1.5 in config.yaml)", (-4, y0 + 2.3))
        d.add(elm.Dot(open=True).at((0, y0)).label("Turbidity SEN0189" + NL + "analog out" + NL + "(0 – 4.5 V @ 5 V)", loc="left"))
        d.add(elm.Resistor().at((0, y0)).to((3, y0)).label("R5  10 kΩ"))
        dot(d, (3, y0))
        wire(d, (3, y0), (5.5, y0))
        dot(d, (5.5, y0))
        wire(d, (5.5, y0), (8.5, y0))
        d.add(elm.Dot(open=True).at((8.5, y0)).label("A3  (≤ 3.0 V)", loc="right"))
        d.add(elm.Resistor().at((3, y0)).down(2.2).label("R6" + NL + "20 kΩ", loc="bottom"))
        d.add(elm.Ground())
        d.add(elm.Capacitor().at((5.5, y0)).down(2.2).label("C4" + NL + "100 nF", loc="bottom"))
        d.add(elm.Ground())

        # (c) optional NTC
        y1 = -15.0
        title(d, "(c) Optional 10 kΩ NTC on A4 (instead of DS18B20 + DS2484)", (-4, y1 + 3.6))
        d.add(elm.Vdd().at((3, y1 + 2.2)).label("+3V3"))
        d.add(elm.Resistor().at((3, y1 + 2.2)).to((3, y1)).label("R7  10 kΩ 0.1 %", loc="bottom"))
        dot(d, (3, y1))
        d.add(elm.Thermistor().at((3, y1)).down(2.2).label("NTC 10 kΩ" + NL + "β = 3950", loc="bottom"))
        d.add(elm.Ground())
        wire(d, (3, y1), (8.5, y1))
        d.add(elm.Dot(open=True).at((8.5, y1)).label("A4  (#define TEMP_SENSOR TEMP_SENSOR_NTC)", loc="right"))


# ---------------------------------------------------------------------------
# 3. Temperature via DS2484 on Qwiic, buzzer and aerator outputs
# ---------------------------------------------------------------------------
def temperature_and_outputs() -> None:
    with schemdraw.Drawing(file=str(OUT / "temperature_and_outputs.svg"), show=False) as d:
        d.config(fontsize=FONT, unit=2.4)
        ic = d.add(elm.Ic(pins=[
            elm.IcPin(name="SDA", side="left", slot="4/4"),
            elm.IcPin(name="SCL", side="left", slot="3/4"),
            elm.IcPin(name="VCC", side="left", slot="2/4"),
            elm.IcPin(name="GND", side="left", slot="1/4"),
            elm.IcPin(name="IO", side="right", slot="2/2"),
            elm.IcPin(name="GND", side="right", slot="1/2"),
        ], edgepadW=1.2, edgepadH=0.8, pinspacing=1.0, leadlen=1.0).at((0, 0))
            .label("DS2484 / DS2482-100" + NL + "addr 0x18", loc="top"))
        for pin, label in (("inL1", "Qwiic SDA (PD13)"), ("inL2", "Qwiic SCL (PD12)"),
                           ("inL3", "Qwiic +3V3"), ("inL4", "Qwiic GND")):
            x, y = getattr(ic, pin)
            wire(d, (x, y), (x - 1.0, y))
            d.add(elm.Dot(open=True).at((x - 1.0, y)).label(label, loc="left"))
        for pin, label in (("inR1", "DS18B20 DQ (yellow)"), ("inR2", "DS18B20 GND (black)")):
            x, y = getattr(ic, pin)
            wire(d, (x, y), (x + 2.0, y))
            d.add(elm.Dot(open=True).at((x + 2.0, y)).label(label, loc="right"))
        xmin, ymin, xmax, ymax = ic.get_bbox(transform=True)
        title(d, "(a) Water temperature: waterproof DS18B20 via DS2484 I²C→1-Wire bridge (Qwiic, Wire1)", (-6, ymax + 1.6))
        y4 = ymin + 0.4
        note(d, "DS18B20 VDD (red) → +3V3 (external power, not parasitic). No pin-header I/O is used for 1-Wire,", (-6, y4 - 1.6))
        note(d, "because bit-banged 1-Wire timing is unreliable under the Zephyr core.", (-6, y4 - 2.2))

        # (b) buzzer
        by = y4 - 5.0
        title(d, "(b) Alarm buzzer: D9", (-6, by + 1.2))
        d.add(elm.Vdd().at((3, by)).label("+5V_SYS"))
        bz = d.add(elm.ResistorIEC().at((3, by)).down(2.0).label("BZ1  5 V active buzzer", loc="top", ofst=(0.2, 0)))
        q3 = d.add(elm.BjtNpn(circle=True).theta(0).anchor("collector").at(bz.end)
                   .label("Q3  BC547 / 2N3904", loc="right", ofst=(0.1, -0.2)))
        d.add(elm.Ground().at(q3.emitter))
        bx, byy = q3.base
        d.add(elm.Resistor().at(q3.base).to((bx - 2.6, byy)).label("R8  1 kΩ"))
        d.add(elm.Dot(open=True).at((bx - 2.6, byy)).label("MCU D9", loc="left"))
        note(d, "Fit a 1N4148 across BZ1 if it is a magnetic (coil) buzzer.", (-6, byy - 1.9))

        # (c) aerator relay
        ry = byy - 6.8
        title(d, "(c) Optional aerator relay: D8 (mains side by an electrician)", (-6, ry + 3.4))
        d.add(elm.Dot(open=True).at((-2, ry)).label("MCU D8", loc="left"))
        wire(d, (-2, ry), (0, ry))
        rl = d.add(elm.Ic(pins=[elm.IcPin(name="IN", side="left"), elm.IcPin(name="NO/COM", side="right")],
                          edgepadW=1.6, edgepadH=0.8, leadlen=0.6).anchor("inL1").at((0, ry))
                   .label("Opto-isolated relay / SSR" + NL + "(3.3 V-logic input)", loc="top"))
        rx, ryy = rl.inR1
        wire(d, (rx, ryy), (rx + 1.6, ryy))
        d.add(elm.Dot(open=True).at((rx + 1.6, ryy)).label("Contactor coil → pond aerator", loc="right"))
        note(d, "Module VCC → +5V_SYS, GND → GND. Use a contactor rated for the aerator motor's inrush current.", (-6, ry - 2.0))


if __name__ == "__main__":
    power_switch()
    analog_frontend()
    temperature_and_outputs()
    print("SVGs written to", OUT)
