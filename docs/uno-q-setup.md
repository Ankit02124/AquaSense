# Running it on the Arduino UNO Q

## What gets installed where

```
app/                         <- this folder is the Arduino App Lab app
├── app.yaml                 name, icon, description shown in App Lab
├── sketch/                  compiled and flashed to the STM32U585 when you press Run
│   ├── sketch.ino
│   ├── config.h             pins, ADC, warm-up times
│   ├── ds2484.h             DS2484 + DS18B20 driver
│   └── sketch.yaml          board platform (arduino:zephyr)
├── python/                  runs on Debian inside the App Lab container
│   ├── main.py              entry point
│   ├── requirements.txt     onnxruntime, PyYAML (installed by App Lab)
│   ├── config.yaml
│   ├── models/              YOLOv8n ONNX model + class names
│   └── *.py
└── data/                    created at runtime: CSV logs and snapshots
```

## Steps

1. **Set up the board.** Install Arduino App Lab on a PC, connect the UNO Q with USB-C, and go through the first-run wizard (Wi-Fi, password, updates) and install all offered updates.

2. **Copy the app to the board.** Either zip the `app` folder and use *Import app* in App Lab, or copy it over SSH:

   ```
   scp -r app arduino@<board-ip>:~/ArduinoApps/aquasense
   ```

3. **Connect the camera.** Plug the webcam into a powered USB-C hub on the board's USB-C port, and power the board from VIN. Check it shows up with `ls /dev/video*` in the App Lab terminal. If it is not `video0`, change `camera.source` in the config.

4. **Site settings.** Create `app/python/config.local.yaml` with only what differs from `config.yaml`. It is merged into `config.yaml` key by key (nested sections too), so `behaviour: {surface_band: 1.0}` changes just that value. Also set `timezone` if you are not in India, the 05:00 / 15:00 checks use it:

   ```yaml
   species: indian_major_carp
   altitude_m: 120
   calibration:
     ph: {v_neutral_mv: 1512.0, v_acid_mv: 2041.3, cal_temp_c: 27.5}
     do: {mode: single, cal1_mv: 1585.0, cal1_temp_c: 28.0, cal2_mv: 1300.0, cal2_temp_c: 15.0}
   ```

   For a camera looking **down** at a pond instead of through the side of a tank, set `surface_band: 1.0` and rely on the speed and count rules. Every fish you can see from above is at the surface anyway.

5. **Run.** Press Run in App Lab. It compiles and flashes the sketch, installs `requirements.txt`, and starts `main.py`.

## What the console shows

- At start-up: the MCU version string (from `aq_ping`), the model file and input size, then the start-up measurement.
- Every 10 s, one line per behaviour window: fish count, share near the surface, mean speed in body lengths per second, green index, YOLO inference time, and either `learning` (first 5 minutes), `ok`, or the alert names.
- For each measurement: the reason (`startup`, `camera`, `scheduled 05:00`, `follow-up`), the overall level, one line per value, and the advice lines.

The same information is written to `data/behaviour.csv`, `data/measurements.csv` and `data/events.csv`, and alert frames go to `data/snapshots/`.

## Checking the probes one by one

Before connecting a probe, check its switch with a multimeter. `SW_5V_x` must read 0 V when idle and about 5 V only while its own probe is being read (the probes are switched one after another during a measurement, LED3 is blue). Then connect the probes one at a time and look at the `raw` column in `data/measurements.csv`. Every value should be in millivolts within 0-3300.

## Inference speed

The app only needs the `app/` folder, so copy the benchmark script and the app code to the board first, then run it in a virtual environment (Debian does not allow system-wide `pip install`):

```
scp -r app tools arduino@<board-ip>:~/aquasense-bench/
ssh arduino@<board-ip>
python3 -m venv ~/bench && ~/bench/bin/pip install onnxruntime opencv-python-headless numpy
cd ~/aquasense-bench && ~/bench/bin/python tools/benchmark.py --model app/python/models/aquasense_yolov8n_416.onnx
```

If it is too slow, lower `detect_fps`, or export a 320 px model with `python training/export.py --weights ... --imgsz 320` and point `model.path` at it.

## Troubleshooting

| problem | what to check |
|---|---|
| `MCU:` line never appears / Bridge errors | sketch did not compile or flash; update the board; on the board run `arduino-app-cli system cleanup` and `docker network prune`, then reboot |
| no camera frames | `ls /dev/video*`, powered hub, `camera.source` |
| flag 1 in the result | DS2484 not found on Qwiic, or the DS18B20 is not wired. Temperature falls back to 25 C for compensation |
| flag 2 in the result | an analog input reached 3.3 V, check the turbidity divider and isolator supply |
| constant `surface_crowding` | `surface_band` does not match the camera view, or the camera moved. Restart to re-learn |
| measurement timeout | 5 V supply sagging when probes switch on, or warm-up longer than `trigger.timeout_s` |
