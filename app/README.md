# AquaSense (Arduino App Lab app)

Copy this folder to the UNO Q as an App Lab app and press Run.

- `sketch/` runs on the STM32U585: probe power switching, ADC, DS2484 temperature, LEDs, buzzer, relay.
- `python/` runs on Linux: USB camera, YOLOv8n fish detection (ONNX), tracking, behaviour checks, deciding when to measure, CSV logging.

Site settings go in `python/config.local.yaml`. Logs and snapshots are written to `data/`.

Details: `docs/uno-q-setup.md` and `docs/how-it-works.md` in the repository.
