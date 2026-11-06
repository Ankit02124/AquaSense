# Probe calibration

The defaults in `config.yaml` are typical values for the DFRobot boards. Every probe is a bit different and drifts over time, so calibrate before trusting the numbers:

| probe | how often |
|---|---|
| pH | every 2-4 weeks; store it wet in KCl storage solution |
| DO | every 1-2 weeks, and after changing membrane or electrolyte |
| EC | monthly |
| turbidity | after cleaning the optical window |

The sketch only reports raw millivolts. They are in the `raw` column of `data/measurements.csv`, for example:

```
R1;seq=3;t=27.50;ph=1512.4;do=1585.0;ec=233.0;tu=2805.0;f=0
```

Put the probe in the reference solution, start a measurement (restart the app or wait for the next one), take the value from the last row, and let `tools/calibration_helper.py` do the arithmetic. Put the printed lines in `app/python/config.local.yaml`.

## pH (pH 4.00, 7.00 and 10.00 buffers)

Rinse the probe, put it in pH 7.00, wait a minute, note `ph=` and `t=`. Repeat in pH 4.00 and, if you have it, pH 10.00. Pond water often sits between pH 7.5 and 9, so the third buffer above 7 noticeably improves accuracy there.

```
python tools/calibration_helper.py ph --mv7 1512.4 --mv4 2041.3 --mv10 990.2 --temp 27.5
```

With three buffers a least-squares line is fitted and the helper prints how far each buffer reads back from its true value (anything within ±0.05 pH is fine). With only two buffers leave out `--mv10`. Either way the slope is scaled by `(T_cal + 273.15) / (T + 273.15)` to correct for temperature.

If the pH reading jumps when the temperature probe goes into the water, see the note on the DS18B20 sheath in `hardware/README.md`.

## Dissolved oxygen (one point, saturated)

Fill the membrane cap with fresh electrolyte. Hold the wet probe in air just above the water, or bubble air through a glass of water for 10 minutes and put the probe in it. That is 100 % saturation. Note `do=` and `t=`.

```
python tools/calibration_helper.py do --mv 1585 --temp 28
```

The app then computes `DO = V / V_sat(T) × solubility(T, salinity, altitude)`. For better accuracy across seasons, repeat at a second temperature at least 10 °C apart and use `mode: two_point` with `cal2_mv`, `cal2_temp_c`.

## Conductivity

Use the 1.413 mS/cm buffer for freshwater (gives `k_low`), and also 12.88 mS/cm for brackish water (gives `k_high`).

```
python tools/calibration_helper.py ec --mv 233.0 --temp 27 --buffer 1.413
```

## Turbidity

Clean the window, put the sensor in clear tap water in a dark container, note `tu=`.

```
python tools/calibration_helper.py turb --mv 2805
```

This sensor is only good for trends and alarms, not for exact NTU.

## ADC reference

`ADC_VREF_MV` in `app/sketch/config.h` assumes the 3V3 rail is exactly 3300 mV. Measuring the actual rail and putting the value there improves accuracy a little, although calibrating each probe end to end already cancels most of the error.
