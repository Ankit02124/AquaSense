"""Probe millivolts -> water quality values.

The MCU only sends raw millivolts (and temperature in degC), all the maths is
done here so calibration can change without re-flashing the board.

Formulas:
  DO solubility   Benson & Krause (1984), APHA 4500-O, with salinity and pressure terms
  Salinity        PSS-78 (Lewis & Perkin 1981) + Hill et al. (1986) below 2 PSU
  NH3 fraction    Emerson et al. (1975)
  Probe boards    DFRobot SEN0161-V2 (pH), SEN0237 (DO), DFR0300 (EC), SEN0189 (turbidity)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KELVIN = 273.15
STD_PRESSURE_KPA = 101.325
# Conductivity of standard seawater (S = 35, T = 15 degC, p = 0), mS/cm.
C_35_15_0 = 42.914


# --------------------------------------------------------------------------
# pH  (DFRobot Gravity analog pH V2, two-point calibration)
# --------------------------------------------------------------------------
@dataclass
class PhCalibration:
    v_neutral_mv: float = 1500.0  # probe output in pH 7.00 buffer
    v_acid_mv: float = 2032.44  # probe output in pH 4.00 buffer
    cal_temp_c: float = 25.0  # buffer temperature during calibration


def ph_from_mv(mv: float, cal: PhCalibration, temp_c: float | None = None) -> float:
    """Convert pH-board millivolts to pH using a two-point linear calibration.

    If ``temp_c`` is given the electrode slope is corrected with the Nernst
    relation (slope in mV/pH is proportional to absolute temperature).
    """
    if cal.v_neutral_mv == cal.v_acid_mv:
        raise ValueError("pH calibration voltages must differ")
    slope = (7.0 - 4.0) / (cal.v_neutral_mv - cal.v_acid_mv)  # pH per mV
    if temp_c is not None:
        slope *= (cal.cal_temp_c + KELVIN) / (temp_c + KELVIN)
    return 7.0 + slope * (mv - cal.v_neutral_mv)


# --------------------------------------------------------------------------
# Dissolved oxygen (galvanic probe, DFRobot SEN0237)
# --------------------------------------------------------------------------
def do_saturation_mg_l(
    temp_c: float, salinity_ppt: float = 0.0, pressure_kpa: float = STD_PRESSURE_KPA
) -> float:
    """Oxygen solubility (mg/L) in water in equilibrium with moist air.

    Benson & Krause (1984) / APHA 4500-O. Valid for 0-40 degC, 0-40 g/kg.
    """
    t_k = temp_c + KELVIN
    ln_c = (
        -139.34411
        + 1.575701e5 / t_k
        - 6.642308e7 / t_k**2
        + 1.243800e10 / t_k**3
        - 8.621949e11 / t_k**4
        - salinity_ppt * (0.017674 - 10.754 / t_k + 2140.7 / t_k**2)
    )
    c_star = math.exp(ln_c)
    if abs(pressure_kpa - STD_PRESSURE_KPA) > 1e-6:
        p_atm = pressure_kpa / STD_PRESSURE_KPA
        p_wv = math.exp(11.8571 - 3840.70 / t_k - 216961.0 / t_k**2)  # atm
        theta = 0.000975 - 1.426e-5 * temp_c + 6.436e-8 * temp_c**2
        c_star *= p_atm * ((1 - p_wv / p_atm) * (1 - theta * p_atm)) / ((1 - p_wv) * (1 - theta))
    return c_star


def pressure_from_altitude_kpa(altitude_m: float) -> float:
    """Standard-atmosphere barometric pressure at a given altitude."""
    return STD_PRESSURE_KPA * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588


@dataclass
class DoCalibration:
    mode: str = "single"  # "single" or "two_point"
    cal1_mv: float = 1600.0  # probe output in 100 % saturated water at cal1_temp_c
    cal1_temp_c: float = 25.0
    cal2_mv: float = 1300.0  # second point (two_point mode only)
    cal2_temp_c: float = 15.0
    single_point_mv_per_c: float = 35.0  # DFRobot typical temperature drift


def do_saturation_voltage_mv(temp_c: float, cal: DoCalibration) -> float:
    """Probe voltage expected in 100 % air-saturated water at ``temp_c``."""
    if cal.mode == "two_point" and cal.cal1_temp_c != cal.cal2_temp_c:
        k = (cal.cal1_mv - cal.cal2_mv) / (cal.cal1_temp_c - cal.cal2_temp_c)
        return cal.cal2_mv + (temp_c - cal.cal2_temp_c) * k
    return cal.cal1_mv + cal.single_point_mv_per_c * (temp_c - cal.cal1_temp_c)


def do_percent_saturation(mv: float, temp_c: float, cal: DoCalibration) -> float:
    v_sat = do_saturation_voltage_mv(temp_c, cal)
    if v_sat <= 0:
        raise ValueError("DO saturation voltage must be positive; re-calibrate")
    return max(0.0, 100.0 * mv / v_sat)


def do_mg_l_from_mv(
    mv: float,
    temp_c: float,
    cal: DoCalibration,
    salinity_ppt: float = 0.0,
    pressure_kpa: float = STD_PRESSURE_KPA,
) -> float:
    """Galvanic probes respond to O2 partial pressure, i.e. % saturation.

    Concentration = %sat x solubility(T, S, P).
    """
    pct = do_percent_saturation(mv, temp_c, cal)
    return pct / 100.0 * do_saturation_mg_l(temp_c, salinity_ppt, pressure_kpa)


# --------------------------------------------------------------------------
# Electrical conductivity (DFRobot DFR0300 K=1 / SEN0451 K=10)
# --------------------------------------------------------------------------
@dataclass
class EcCalibration:
    k_low: float = 1.0  # cell constant used below ~2 mS/cm (1.413 mS/cm buffer)
    k_high: float = 1.0  # cell constant used above ~2 mS/cm (12.88 mS/cm buffer)
    switch_ms_cm: float = 2.0
    temp_coeff: float = 0.0185  # fractional change per degC (linear compensation)
    gain: float = 1000.0 / 820.0 / 200.0  # DFR0300 board transfer: mS/cm per mV at K=1


def ec_at_temp_from_mv(mv: float, cal: EcCalibration) -> float:
    """Conductivity (mS/cm) *at the water temperature* (not compensated)."""
    raw = max(0.0, mv) * cal.gain
    k = cal.k_high if raw * cal.k_low > cal.switch_ms_cm else cal.k_low
    return raw * k


def ec25_from_ec(ec_t_ms_cm: float, temp_c: float, temp_coeff: float = 0.0185) -> float:
    """Linear temperature compensation to the 25 degC reference."""
    return ec_t_ms_cm / (1.0 + temp_coeff * (temp_c - 25.0))


def tds_ppm_from_ec25(ec25_ms_cm: float, factor: float = 0.5) -> float:
    return ec25_ms_cm * 1000.0 * factor


_PSS_A = (0.0080, -0.1692, 25.3851, 14.0941, -7.0261, 2.7081)
_PSS_B = (0.0005, -0.0056, -0.0066, -0.0375, 0.0636, -0.0144)
_PSS_C = (0.6766097, 2.00564e-2, 1.104259e-4, -6.9698e-7, 1.0031e-9)


def salinity_pss78(ec_t_ms_cm: float, temp_c: float) -> float:
    """Practical salinity (PSU ~= ppt) from in-situ conductivity and temperature.

    Uses PSS-78 at atmospheric pressure, with the Hill et al. (1986)
    extension below S = 2 so fresh and brackish ponds read sensibly.
    """
    if ec_t_ms_cm <= 0:
        return 0.0
    t = temp_c
    r = ec_t_ms_cm / C_35_15_0
    rt_temp = sum(c * t**i for i, c in enumerate(_PSS_C))
    rt = r / rt_temp
    sq = math.sqrt(rt)
    ft = (t - 15.0) / (1.0 + 0.0162 * (t - 15.0))
    powers = (1.0, sq, rt, rt * sq, rt * rt, rt * rt * sq)
    s = sum(a * p for a, p in zip(_PSS_A, powers))
    s += ft * sum(b * p for b, p in zip(_PSS_B, powers))
    if s < 2.0:
        x = 400.0 * rt
        y = 100.0 * rt
        s -= _PSS_A[0] / (1.0 + 1.5 * x + x * x)
        s -= _PSS_B[0] * ft / (1.0 + math.sqrt(y) + y + y * math.sqrt(y))
    return max(0.0, s)


# --------------------------------------------------------------------------
# Turbidity (DFRobot SEN0189, optical, powered from 5 V)
# --------------------------------------------------------------------------
@dataclass
class TurbidityCalibration:
    divider_ratio: float = 1.5  # sensor_V / pin_V  (10k over 20k divider -> 1.5)
    clear_water_v: float = 4.2  # sensor output in clear water (calibrate per unit)


def _turbidity_curve(v: float) -> float:
    return -1120.4 * v * v + 5742.3 * v - 4352.9


_TURB_ZERO = _turbidity_curve(4.2)  # ~0.86 NTU; subtracted so clear water is exactly 0


def turbidity_ntu_from_mv(pin_mv: float, cal: TurbidityCalibration) -> float:
    """Approximate NTU from DFRobot's published quadratic (valid 2.5-4.2 V).

    This optical sensor is semi-quantitative: use it for trends and alarms,
    not for regulatory reporting.
    """
    v = pin_mv / 1000.0 * cal.divider_ratio
    v += 4.2 - cal.clear_water_v  # shift so that clear water maps to 4.2 V
    if v >= 4.2 - 1e-9:
        return 0.0
    if v <= 2.5:
        return 3000.0
    return min(3000.0, max(0.0, _turbidity_curve(v) - _TURB_ZERO))


def turbidity_pin_mv_from_ntu(ntu: float, cal: TurbidityCalibration) -> float:
    """Inverse of :func:`turbidity_ntu_from_mv` (used by the simulator and tests)."""
    a, b, c = -1120.4, 5742.3, -4352.9 - (ntu + _TURB_ZERO)
    v = (-b - math.sqrt(b * b - 4 * a * c)) / (2 * a)  # branch inside 2.5-4.2 V
    v -= 4.2 - cal.clear_water_v
    return v * 1000.0 / cal.divider_ratio


# --------------------------------------------------------------------------
# Derived: un-ionised ammonia fraction
# --------------------------------------------------------------------------
def nh3_fraction(ph: float, temp_c: float) -> float:
    """Fraction of total ammonia nitrogen present as toxic NH3 (Emerson 1975)."""
    pka = 0.09018 + 2729.92 / (temp_c + KELVIN)
    return 1.0 / (1.0 + 10 ** (pka - ph))
