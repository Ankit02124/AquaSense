"""End-to-end test against a real MQTT broker. Skipped unless MQTT_TEST_HOST is set.

    docker run -d -p 1883:1883 -p 9001:9001 -v "$PWD/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" eclipse-mosquitto:2
    MQTT_TEST_HOST=localhost pytest tests/integration

Runs tools/run_on_video.py on the demo clip with the STM32 stand-in (FakeProbes),
listens on the broker and checks: retained online status, the start-up reading,
a CRITICAL water alert, a reading started by the "measure" command, and the
offline status after the run ends.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

mqtt = pytest.importorskip("paho.mqtt.client")

HOST = os.environ.get("MQTT_TEST_HOST")
PORT = int(os.environ.get("MQTT_TEST_PORT", "1883"))
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not HOST, reason="set MQTT_TEST_HOST to run against a real broker")


def wait_for(condition, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.2)
    return False


def test_video_run_publishes_to_broker():
    device = f"ci{os.getpid()}"
    base = f"aquasense/{device}"
    got = []

    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"test-{device}")
    sub.on_message = lambda c, u, m: got.append((m.topic, json.loads(m.payload), m.retain))
    sub.connect(HOST, PORT)
    sub.subscribe(f"{base}/#", qos=1)
    sub.loop_start()

    def on(name):
        return [p for t, p, _ in got if t == f"{base}/{name}"]

    proc = subprocess.Popen(
        [sys.executable, "tools/run_on_video.py", "docs/images/demo.gif", "--mqtt", "--mqtt-host", HOST,
         "--mqtt-port", str(PORT), "--device-id", device, "--water", "low_oxygen", "--realtime", "--loops", "4"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert wait_for(lambda: any(s["state"] == "online" for s in on("status")), 20), "no online status"
        assert wait_for(lambda: on("readings"), 30), "no start-up reading"
        sub.publish(f"{base}/cmd", "measure", qos=1)
        assert wait_for(lambda: any(r["reason"] == "mqtt command" for r in on("readings")), 25), \
            "measure command did not lead to a reading"
    finally:
        out, _ = proc.communicate(timeout=90)
        print(out)

    assert proc.returncode == 0
    assert wait_for(lambda: on("status") and on("status")[-1]["state"] == "offline", 10)

    first = on("readings")[0]
    assert first["device"] == device and first["reason"] == "startup" and first["level"] == "CRITICAL"
    assert first["values"]["do_mg_l"] < 3.0
    water = [a for a in on("alerts") if a["kind"] == "water"]
    assert water and water[0]["alerts"] == ["dissolved oxygen low"]

    sub.publish(f"{base}/status", b"", qos=1, retain=True)  # clear the retained status
    sub.loop_stop()
    sub.disconnect()
