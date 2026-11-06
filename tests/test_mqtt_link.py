"""MqttLink with a fake paho client: topics, payloads, QoS, retained flags,
Last Will, the offline queue and the "measure" command."""
import json
from types import SimpleNamespace

import pytest

from controller import Controller
from mqtt_link import MqttLink
from probes import Calibration, FakeProbes


class FakeClient:
    def __init__(self):
        self.published, self.subscribed = [], []
        self.will = self.auth = self.tls = None
        self.started = self.stopped = self.disconnected = False
        self.reject = False  # make publish() fail like paho does when the link just dropped

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, json.loads(payload), qos, retain)

    def username_pw_set(self, user, password):
        self.auth = (user, password)

    def tls_set(self):
        self.tls = True

    def reconnect_delay_set(self, min_delay, max_delay):
        self.backoff = (min_delay, max_delay)

    def connect_async(self, host, port, keepalive):
        self.target = (host, port, keepalive)

    def loop_start(self):
        self.started = True

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic, qos):
        self.subscribed.append((topic, qos))

    def publish(self, topic, payload, qos=0, retain=False):
        if self.reject:
            return SimpleNamespace(rc=4)  # MQTT_ERR_NO_CONN
        self.published.append((topic, json.loads(payload), qos, retain))
        return SimpleNamespace(rc=0)

    def on(self, topic):
        return [p for p in self.published if p[0] == topic]


CFG = {"device_id": "pond1", "topic_prefix": "aquasense", "host": "broker.local", "port": 1883, "queue_limit": 3}


def make(cfg=None, clock=lambda: 1_790_000_000.0):
    client = FakeClient()
    link = MqttLink({**CFG, **(cfg or {})}, client=client, clock=clock)
    return link, client


def connect(link):
    link._on_connect(link.client, None, {}, 0, None)


def message(text):
    return SimpleNamespace(payload=text.encode(), topic="aquasense/pond1/cmd")


def test_last_will_is_retained_offline_on_status_topic():
    link, client = make()
    topic, payload, qos, retain = client.will
    assert topic == "aquasense/pond1/status"
    assert payload["state"] == "offline" and payload["device"] == "pond1"
    assert qos == 1 and retain is True


def test_connect_publishes_retained_online_and_subscribes_to_cmd():
    link, client = make()
    link.start()
    assert client.started and client.target == ("broker.local", 1883, 30)
    connect(link)
    assert client.on("aquasense/pond1/status") == [
        ("aquasense/pond1/status", {"device": "pond1", "ts": 1_790_000_000.0, "time": "2026-09-21T14:13:20+00:00",
                                    "state": "online"}, 1, True)]
    assert client.subscribed == [("aquasense/pond1/cmd", 1)]


def test_reading_payload_topic_and_qos():
    link, client = make()
    connect(link)
    reading = SimpleNamespace(flags=0, as_dict=lambda: {"time": 5.0, "ph": 7.6, "do_mg_l": 6.8, "tds_ppm": None,
                                                          "flags": 0})
    link.reading(reading, "scheduled 05:00", "OK", ["tip"])
    topic, payload, qos, retain = client.on("aquasense/pond1/readings")[0]
    assert qos == 1 and retain is False
    assert payload["device"] == "pond1" and "time" in payload and "ts" in payload
    assert payload["values"] == {"ph": 7.6, "do_mg_l": 6.8}
    assert payload["reason"] == "scheduled 05:00" and payload["level"] == "OK" and payload["advice"] == ["tip"]


def test_messages_are_queued_while_offline_and_oldest_dropped_when_full():
    link, client = make()
    for i in range(5):
        link.alert("behaviour", [f"a{i}"])
    assert client.published == []
    assert link.dropped == 2 and len(link.queue) == 3
    connect(link)
    alerts = [p[1]["alerts"] for p in client.on("aquasense/pond1/alerts")]
    assert alerts == [["a2"], ["a3"], ["a4"]]  # oldest two dropped, order kept
    assert len(link.queue) == 0


def test_rejected_publish_stays_queued_and_disconnect_stops_sending():
    link, client = make()
    connect(link)
    client.reject = True
    link.alert("behaviour", ["x"])
    assert len(link.queue) == 1
    link._on_disconnect(client, None, None, 7, None)
    client.reject = False
    link.alert("behaviour", ["y"])
    assert client.on("aquasense/pond1/alerts") == [] and len(link.queue) == 2
    connect(link)
    assert [p[1]["alerts"] for p in client.on("aquasense/pond1/alerts")] == [["x"], ["y"]]


def test_refused_connection_does_not_count_as_connected():
    link, client = make()
    link._on_connect(client, None, {}, 5, None)  # 5 = not authorised
    assert not link.connected and client.subscribed == []


def test_measure_command_plain_or_json_and_unknown_ignored():
    link, _ = make()
    link._on_message(None, None, message("measure"))
    link._on_message(None, None, message('{"cmd": "MEASURE"}'))
    link._on_message(None, None, message("reboot"))
    assert link.take_commands() == ["measure", "measure"]
    assert link.take_commands() == []


def test_password_comes_from_environment(monkeypatch):
    monkeypatch.setenv("POND_PW", "s3cret")
    _, client = make({"username": "pond", "password_env": "POND_PW", "tls": True})
    assert client.auth == ("pond", "s3cret") and client.tls


def test_start_never_raises():
    link, client = make()

    def boom(*a, **k):
        raise OSError("no route to host")

    client.connect_async = boom
    link.start()  # logs a warning instead


def test_stop_publishes_offline_retained():
    link, client = make()
    connect(link)
    link.stop()
    topic, payload, qos, retain = client.on("aquasense/pond1/status")[-1]
    assert payload["state"] == "offline" and qos == 1 and retain is True
    assert client.disconnected and client.stopped


# ---------- through the controller ----------

@pytest.fixture
def run(cfg, clock):
    def go(condition):
        link, client = make(clock=clock)
        connect(link)
        cfg["trigger"]["measure_on_start"] = False
        probes = FakeProbes(condition=condition, clock=clock)
        ctl = Controller(cfg, probes, Calibration.from_config(cfg["calibration"]),
                         cfg["species_profiles"]["tilapia"], clock=clock, mqtt=link)
        return ctl, link, client
    return go


def finish_measurement(ctl, clock):
    ctl.tick()
    clock.advance(5)
    ctl.tick()


def test_measure_command_starts_a_measurement_and_publishes_reading(run, clock):
    ctl, link, client = run("normal")
    link._on_message(None, None, message("measure"))
    for cmd in link.take_commands():
        assert ctl.request("mqtt command")
    finish_measurement(ctl, clock)
    (_, payload, qos, _), = client.on("aquasense/pond1/readings")
    assert payload["reason"] == "mqtt command" and payload["level"] == "OK"
    assert 6.0 < payload["values"]["do_mg_l"] < 7.5
    assert client.on("aquasense/pond1/alerts") == []


def test_critical_reading_also_publishes_water_alert(run, clock):
    ctl, link, client = run("low_oxygen")
    ctl.request("scheduled 05:00")
    finish_measurement(ctl, clock)
    (_, alert, qos, retain), = client.on("aquasense/pond1/alerts")
    assert alert["kind"] == "water" and alert["level"] == "CRITICAL"
    assert alert["alerts"] == ["dissolved oxygen low"] and qos == 1 and not retain


def test_confirmed_camera_alert_is_published(run, clock):
    ctl, link, client = run("normal")
    window = SimpleNamespace(alerts=["surface_crowding"], summary={"n_fish": 8.0, "surface_ratio": 0.8})
    ctl.on_behaviour(window)
    ctl.on_behaviour(window)  # confirm_windows = 2
    (_, alert, _, _), = client.on("aquasense/pond1/alerts")
    assert alert["kind"] == "behaviour" and alert["alerts"] == ["surface_crowding"]
    assert alert["detail"]["surface_ratio"] == 0.8
