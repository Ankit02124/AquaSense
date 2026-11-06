# AquaSense

Water quality monitor for fish ponds, running on an Arduino UNO Q. A YOLOv8n model watches the fish through a USB camera. When their behaviour changes (crowding at the surface, slowing down, disappearing from view) the board switches on its probes and measures dissolved oxygen, pH, salinity, turbidity and temperature.

<p align="center">
  <img src="docs/images/demo.gif" width="640" alt="YOLOv8n detecting fish"><br>
  <sub>YOLOv8n detecting and tracking fish through the same ONNX pipeline that runs on the board (clip from the Brackish Dataset).</sub>
</p>

## The idea

<img src="docs/images/components/pond_aerator.jpg" width="360" align="right" alt="aerators in a fish pond">

Fish and shrimp farmers lose stock mostly to water going bad quickly, usually dissolved oxygen dropping at night. Small farms test the water by hand once or twice a day. Probes that stay in the pond and run all the time would catch problems, but they foul, drift and need power and maintenance.

Fish react before people notice anything. They gather and gasp at the surface when oxygen is low, and they slow down when they are stressed. AquaSense lets a camera watch continuously and switches the probes on only when the fish look wrong. It also measures at fixed times: 05:00, when oxygen is lowest, and 15:00, when pH and temperature peak.

<br clear="right">

## How it works

![block diagram](docs/images/block_diagram.svg)

1. A USB camera sends frames to a **YOLOv8n** model (ONNX, 416 px) on the Linux side of the UNO Q, 3 frames per second.
2. A **centroid tracker** follows each fish between frames and measures its speed in body lengths per second.
3. Every 10 s the **behaviour checks** compare fish count, share near the surface, swimming speed and water colour with what was normal during the first 5 minutes.
4. If the same alert comes up twice in a row, Python asks the **STM32 microcontroller** to take a measurement, over the Arduino Bridge (RPC).
5. The STM32 powers the probes **one at a time**, waits for each to settle, takes 64 ADC samples, switches it off and returns raw millivolts.
6. Python converts the readings (temperature, salinity and altitude compensated) and checks them against the **limits for the farmed species**. It writes the advice to the log, sets the status LED, sounds the buzzer if a value is critical, and can switch an aerator on.

| camera alert | what it usually means |
|---|---|
| `surface_crowding` | low dissolved oxygen, fish gasping |
| `low_activity` | stress, cold water, low oxygen |
| `hyperactivity` | irritation, pH or ammonia problems |
| `fish_missing` | fish hiding or sick at the bottom |
| `motionless_fish` | a dead or sick fish |
| `water_colour` | algal bloom or turbid water |

## Arduino UNO Q

<img src="docs/images/components/arduino_uno_q.png" width="420" align="right" alt="Arduino UNO Q">

The UNO Q has the classic UNO shape but two processors on it:

- **Qualcomm Dragonwing QRB2210**: 4x Cortex-A53 at 2.0 GHz, 4 GB RAM, 32 GB eMMC, running Debian Linux. It runs the camera, the YOLO model (onnxruntime), tracking, decisions and logging in Python.
- **STM32U585**: Cortex-M33 at 160 MHz running the Arduino core on Zephyr. It owns the 3.3 V headers: ADC inputs A0-A5, the GPIOs that switch the probes, the Qwiic I2C port, and the on-board RGB LEDs.

The two halves talk through the Arduino Bridge: the sketch registers functions with `Bridge.provide_safe()`, and Python calls them with `Bridge.call()`. Arduino App Lab builds and flashes the sketch and starts the Python app together.

<br clear="right">

Splitting the work this way keeps timing-critical I/O (probe warm-up, ADC oversampling, switching probes off) on the microcontroller. It keeps working the same way while Linux is busy running the neural network, and every probe is off as soon as the MCU boots.

<p align="center"><img src="docs/images/components/uno_q_block_diagram.png" width="900" alt="UNO Q block diagram"><br><sub>UNO Q block diagram: QRB2210 on the left, STM32U585 on the right (image: Arduino, CC BY-SA 4.0)</sub></p>

## Fish detection model

| | |
|---|---|
| model | YOLOv8n (3.2 M parameters), fine-tuned from COCO weights |
| training data | [Brackish Dataset](https://www.kaggle.com/datasets/aalborguniversity/brackish-dataset) from Kaggle: fixed underwater camera in murky brackish water, 89 videos, ~14.7k annotated frames |
| classes | fish, crab, shrimp, jellyfish, starfish (`fish` and `small_fish` merged) |
| training | 640 px, 60 epochs, batch 16, RTX 3050 Laptop GPU, Ultralytics |
| deployment | exported to ONNX at 416x416, run with onnxruntime on the A53 cores; letterbox and NMS written in numpy, so the board needs no PyTorch |

The Brackish footage was chosen because it is murky, low-visibility water filmed by a fixed camera, which is closer to a pond than the clear aquarium or reef images most fish datasets have. Its labels ship in pixel units with 1-based class ids, so [training/prepare_brackish.py](training/prepare_brackish.py) converts them to normal YOLO format.

Accuracy on the held-out test split (1,468 frames):

| input size | precision | recall | mAP@0.5 | mAP@0.5:0.95 |
|---|---|---|---|---|
| 640 px (training size) | 0.957 | 0.934 | 0.966 | 0.739 |
| 416 px (used on the board) | 0.949 | 0.882 | 0.939 | 0.671 |

For the fish class alone, mAP@0.5 is 0.957 at 640 px and 0.912 at 416 px. The dataset's official split is per frame, so test frames come from the same videos as the training frames. A new pond will score lower until the model is fine-tuned on its own footage.

| training curves | test images (left: labels, right: model) |
|---|---|
| ![results](training/results/results.png) | ![predictions](training/results/test_predictions.jpg) |

Training, export and evaluation steps are in [training/README.md](training/README.md).

## Sensors and hardware

| | | | |
|:-:|:-:|:-:|:-:|
| <img src="docs/images/components/arduino_uno_q.png" height="110"> | <img src="docs/images/components/usb_webcam.jpg" height="110"> | <img src="docs/images/components/ph_electrode.jpg" height="110"> | <img src="docs/images/components/ds18b20_probe.jpg" height="110"> |
| Arduino UNO Q 4 GB | USB webcam (UVC) | pH electrode | DS18B20 waterproof probe |

| part | measures | connected to |
|---|---|---|
| DFRobot Gravity analog pH V2 (SEN0161-V2) + DFR0504 isolator | pH | A0, power switch on D4 |
| DFRobot Gravity analog dissolved oxygen kit (SEN0237) | dissolved oxygen | A1, switch on D5 |
| DFRobot conductivity DFR0300 (K=1) or SEN0451 (K=10) + DFR0504 isolator | conductivity, salinity, TDS | A2, switch on D6 |
| DFRobot Gravity turbidity (SEN0189) through a 10k/20k divider | turbidity | A3, switch on D7 |
| DS18B20 on a DS2484 I2C-to-1-Wire bridge | water temperature | Qwiic (I2C4) |
| USB webcam on a USB-C hub | fish behaviour | USB-C |
| 5 V buzzer, relay/SSR for an aerator | alarm, aeration | D9, D8 |

A small perfboard shield carries four P-MOSFET high-side switches (one per probe, off by default), 1 kΩ + 100 nF filters and BAT54S clamps on the analog inputs. The analog pins of the UNO Q are not 5 V tolerant.

![wiring](hardware/wiring_diagram.svg)

Schematics, pin map and installation notes: [hardware/README.md](hardware/README.md).

## Code

```
app/                        Arduino App Lab app: this folder runs on the UNO Q
├── app.yaml
├── sketch/                 STM32U585 (C++)
│   ├── sketch.ino          measurement state machine, Bridge functions, LEDs, buzzer, relay
│   ├── config.h            pins, ADC settings, warm-up times
│   └── ds2484.h            DS2484 I2C-to-1-Wire driver + DS18B20
└── python/                 QRB2210 / Debian (Python)
    ├── main.py             main loop: camera -> detector -> tracker -> behaviour -> controller
    ├── fish_detector.py    YOLOv8 ONNX inference, letterbox, NMS
    ├── tracker.py          centroid tracker, speed in body lengths/s
    ├── behaviour.py        per-window metrics, learned baseline, alert rules, water colour
    ├── controller.py       when to measure: camera alerts, schedule, follow-ups, cool-down
    ├── probes.py           Bridge client for the MCU, raw result parsing
    ├── chemistry.py        mV -> pH, DO, conductivity, salinity (PSS-78), turbidity, NH3
    ├── water_check.py      species limits and advice
    ├── datalog.py          CSV logs and snapshots
    ├── config.yaml         settings, calibration, species profiles
    └── models/             aquasense_yolov8n_416.onnx, classes.txt
training/                   dataset conversion, YOLOv8 training, ONNX export, evaluation
hardware/                   wiring diagram, schematics, parts list, pin map
docs/                       how it works, UNO Q setup, calibration
tools/                      run on a video file, benchmark the model, calibration helper
tests/                      pytest for the Python side
```

More detail: [docs/how-it-works.md](docs/how-it-works.md).

## Running it

On the UNO Q: copy `app/` to the board as an Arduino App Lab app and press Run. App Lab flashes the sketch to the STM32 and starts `main.py` on Linux. Site settings (species, probe calibration) go in `app/python/config.local.yaml`. See [docs/uno-q-setup.md](docs/uno-q-setup.md) and [docs/calibration.md](docs/calibration.md).

On a PC, with a video instead of the camera:

```
pip install -r requirements.txt
python tools/run_on_video.py some_clip.avi --out annotated.mp4
```

## Tech used

Python, OpenCV, NumPy, ONNX Runtime, YOLOv8 (Ultralytics, PyTorch), Kaggle API, C++ on Arduino Zephyr core, Arduino App Lab, Arduino_RouterBridge (RPC between Linux and the MCU), I2C / 1-Wire, analog front-end design.

## Credits

- Brackish Dataset: M. Pedersen, J. B. Haurum, R. Gade, T. B. Moeslund, N. Madsen, *Detection of Marine Animals in a New Underwater Dataset with Varying Visibility*, CVPR Workshops 2019, CC BY-SA 4.0.
- YOLOv8 by [Ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0), used for training and export only.
- Component photos: see [docs/images/components/CREDITS.md](docs/images/components/CREDITS.md).

## License

Code: MIT ([LICENSE](LICENSE)). The trained model and images derived from the dataset are shared under CC BY-SA 4.0. The YOLOv8 weights also fall under the Ultralytics AGPL-3.0 terms.

---

Ankit Choudhury, [github.com/Ankit02124](https://github.com/Ankit02124)
