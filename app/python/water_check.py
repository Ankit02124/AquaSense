"""Compare a probe reading with the limits for the farmed species and suggest
what to do. Limits are in config.yaml (species_profiles)."""

OK, MEASURING, WARNING, CRITICAL = 0, 1, 2, 3
LEVEL_NAMES = {OK: "OK", MEASURING: "MEASURING", WARNING: "WARNING", CRITICAL: "CRITICAL"}

PARAMS = [
    ("temperature_c", "temperature", "C"),
    ("ph", "pH", ""),
    ("do_mg_l", "dissolved oxygen", "mg/L"),
    ("salinity_ppt", "salinity", "ppt"),
    ("turbidity_ntu", "turbidity", "NTU"),
]


def classify(value, lim):
    """Return (level, 'low'|'high'|None) for one parameter."""
    if value is None or not lim:
        return OK, None
    if value < lim.get("crit_low", float("-inf")):
        return CRITICAL, "low"
    if value > lim.get("crit_high", float("inf")):
        return CRITICAL, "high"
    if value < lim.get("warn_low", float("-inf")):
        return WARNING, "low"
    if value > lim.get("warn_high", float("inf")):
        return WARNING, "high"
    return OK, None


def check(reading, profile, behaviour_alerts=()):
    """Returns overall level, list of (name, value, unit, level, direction) and advice lines."""
    rows, problems = [], {}
    for key, name, unit in PARAMS:
        value = getattr(reading, key)
        level, direction = classify(value, profile.get(key))
        rows.append((name, value, unit, level, direction))
        if level >= WARNING:
            problems[key] = direction
    overall = max((r[3] for r in rows), default=OK)
    return overall, rows, advice(reading, problems, set(behaviour_alerts), overall)


def advice(reading, problems, alerts, overall):
    tips = []
    if problems.get("do_mg_l") == "low":
        tips.append("Low dissolved oxygen: switch on aeration, stop feeding, exchange some water.")
        if "surface_crowding" in alerts:
            tips.append("Camera saw fish crowding at the surface, which matches the low oxygen reading.")
    if problems.get("do_mg_l") == "high":
        tips.append("Oxygen above saturation usually means a heavy algal bloom; expect a drop at night.")
    if problems.get("ph") == "high":
        nh3 = f" ({reading.nh3_fraction * 100:.1f}% of ammonia is in the toxic NH3 form)" if reading.nh3_fraction else ""
        tips.append(f"High pH{nh3}: reduce feeding and exchange some water.")
    if problems.get("ph") == "low":
        tips.append("Low pH: check alkalinity, liming is the usual fix.")
    if problems.get("temperature_c") == "high":
        tips.append("Water is warm and holds less oxygen: aerate and feed less.")
    if problems.get("temperature_c") == "low":
        tips.append("Water is cold: fish eat less, reduce feeding.")
    if "salinity_ppt" in problems:
        tips.append("Salinity is outside the range for this species, adjust slowly.")
    if problems.get("turbidity_ntu") == "high" or "water_colour" in alerts:
        tips.append("Water is turbid or green (possible bloom): watch oxygen closely before dawn.")
    if overall == OK and alerts:
        tips.append("Water values are fine but fish behaviour is unusual: check for disease, parasites or predators.")
    return tips
