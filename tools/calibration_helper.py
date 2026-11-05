"""Turn raw probe millivolts (the `raw` column of data/measurements.csv) into config values.

    python tools/calibration_helper.py ph  --mv7 1512 --mv4 2041 --temp 27.5
    python tools/calibration_helper.py do  --mv 1585 --temp 28.0
    python tools/calibration_helper.py ec  --mv 233.0 --temp 27.0 --buffer 1.413
    python tools/calibration_helper.py turb --mv 2805
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "python"))

import chemistry as chem  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="probe", required=True)
    p = sub.add_parser("ph", help="two-point pH (7.00 and 4.00 buffers)")
    p.add_argument("--mv7", type=float, required=True)
    p.add_argument("--mv4", type=float, required=True)
    p.add_argument("--temp", type=float, default=25.0)
    d = sub.add_parser("do", help="single-point DO in 100 %% saturated water/air")
    d.add_argument("--mv", type=float, required=True)
    d.add_argument("--temp", type=float, required=True)
    e = sub.add_parser("ec", help="cell constant from a conductivity buffer")
    e.add_argument("--mv", type=float, required=True)
    e.add_argument("--temp", type=float, required=True)
    e.add_argument("--buffer", type=float, required=True, help="buffer value at 25 degC, mS/cm (1.413 or 12.88)")
    e.add_argument("--temp-coeff", type=float, default=0.0185)
    t = sub.add_parser("turb", help="turbidity clear-water reference")
    t.add_argument("--mv", type=float, required=True, help="A3 pin millivolts in clear water")
    t.add_argument("--divider", type=float, default=1.5)
    a = ap.parse_args()

    if a.probe == "ph":
        slope_mv = (a.mv4 - a.mv7) / 3.0
        print(f"slope: {slope_mv:.1f} mV/pH  (DFRobot V2 boards are typically ~170-180 mV/pH after amplification)")
        print(f"calibration:\n  ph: {{v_neutral_mv: {a.mv7:.1f}, v_acid_mv: {a.mv4:.1f}, cal_temp_c: {a.temp:.1f}}}")
    elif a.probe == "do":
        sat = chem.do_saturation_mg_l(a.temp)
        print(f"100 % saturation at {a.temp:.1f} degC = {sat:.2f} mg/L (fresh water, sea level)")
        print(f"calibration:\n  do: {{mode: single, cal1_mv: {a.mv:.1f}, cal1_temp_c: {a.temp:.1f}}}")
    elif a.probe == "ec":
        target = a.buffer * (1 + a.temp_coeff * (a.temp - 25.0))  # buffer EC at measuring temperature
        k = target / (a.mv * chem.EcCalibration().gain)
        key = "k_low" if a.buffer < 2.5 else "k_high"
        print(f"buffer at {a.temp:.1f} degC = {target:.3f} mS/cm  ->  {key} = {k:.4f}")
        print(f"calibration:\n  ec: {{{key}: {k:.4f}}}")
    else:
        v = a.mv / 1000.0 * a.divider
        print(f"sensor output in clear water = {v:.3f} V")
        print(f"calibration:\n  turbidity: {{divider_ratio: {a.divider:.3f}, clear_water_v: {v:.3f}}}")


if __name__ == "__main__":
    main()
