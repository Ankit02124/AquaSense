"""MQTT link: publishes readings, alerts and online status, and takes a "measure" command.

Topics (prefix and device id come from config.yaml):
    <prefix>/<device>/readings   every probe measurement             QoS 1
    <prefix>/<device>/alerts     behaviour alerts, CRITICAL readings  QoS 1
    <prefix>/<device>/status     "online" (retained), Last Will "offline" (retained)
    <prefix>/<device>/cmd        subscribed; "measure" asks for a measurement

The main loop must never wait on the network, so:
  - paho runs its network loop in its own thread (loop_start) and reconnects by
    itself with a backoff that doubles from 1 s up to max_backoff_s;
  - publish() only puts the message in a queue and returns. The queue is sent
    while connected and kept while not. When it is full the oldest message is
    dropped, so memory stays bounded however long the broker is away;
  - commands arrive in paho's thread and are only queued there. The main loop
    collects them with take_commands() and hands them to the controller, so the
    controller is only ever used from one thread.
"""

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger("mqtt")

COMMANDS = {"measure"}


def _failed(reason_code):
    # paho 2 passes a ReasonCode object; the tests pass a plain int
    return getattr(reason_code, "is_failure", reason_code != 0)


class MqttLink:
    def __init__(self, cfg, client=None, clock=time.time):
        self.cfg = cfg
        self.device = str(cfg["device_id"])
        base = f"{cfg.get('topic_prefix', 'aquasense').strip('/')}/{self.device}"
        self.topics = {name: f"{base}/{name}" for name in ("readings", "alerts", "status", "cmd")}
        self.clock = clock
        self.queue = deque(maxlen=int(cfg.get("queue_limit", 500)))
        self.dropped = 0
        self.connected = False
        self._commands = deque()
        self._lock = threading.Lock()
        self.client = client or self._new_client()
        self._configure()

    # ---------- setup ----------

    def _new_client(self):
        import paho.mqtt.client as mqtt

        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"aquasense-{self.device}")

    def _configure(self):
        c, cfg = self.client, self.cfg
        if cfg.get("username"):
            # the password is read from the environment, never from config.yaml
            c.username_pw_set(cfg["username"], os.environ.get(cfg.get("password_env", "AQUASENSE_MQTT_PASSWORD")))
        if cfg.get("tls"):
            c.tls_set()  # system CA certificates
        c.will_set(self.topics["status"], self._status("offline"), qos=1, retain=True)
        c.reconnect_delay_set(min_delay=1, max_delay=int(cfg.get("max_backoff_s", 60)))
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message

    def start(self):
        """Connect in the background. Never raises: without a broker the app just keeps logging to CSV."""
        try:
            self.client.connect_async(self.cfg.get("host", "localhost"), int(self.cfg.get("port", 1883)),
                                      keepalive=int(self.cfg.get("keepalive_s", 30)))
            self.client.loop_start()
            log.info("connecting to %s:%s as %s", self.cfg.get("host"), self.cfg.get("port"), self.device)
        except Exception as e:
            log.warning("MQTT not started (%s), continuing without it", e)

    def stop(self):
        """Clean shutdown: say offline ourselves (a clean disconnect does not fire the Last Will)."""
        try:
            if self.connected:
                self.client.publish(self.topics["status"], self._status("offline"), qos=1, retain=True)
            self.client.disconnect()
            self.client.loop_stop()
        except Exception as e:
            log.warning("MQTT stop: %s", e)

    # ---------- paho callbacks (paho's thread) ----------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if _failed(reason_code):
            log.warning("broker refused the connection: %s", reason_code)
            return
        self.connected = True
        client.publish(self.topics["status"], self._status("online"), qos=1, retain=True)
        client.subscribe(self.topics["cmd"], qos=1)
        log.info("connected, %d queued message(s) to send", len(self.queue))
        self._flush()

    def _on_disconnect(self, client, userdata, flags=None, reason_code=0, properties=None):
        self.connected = False
        log.warning("disconnected (%s), messages are queued until the broker is back", reason_code)

    def _on_message(self, client, userdata, msg):
        text = msg.payload.decode("utf-8", "replace").strip()
        try:
            data = json.loads(text)
            cmd = data.get("cmd") if isinstance(data, dict) else data
        except ValueError:
            cmd = text
        cmd = str(cmd).strip().lower()
        if cmd in COMMANDS:
            self._commands.append(cmd)
        else:
            log.warning("ignored unknown command %r", text[:60])

    # ---------- used by the app (main thread) ----------

    def take_commands(self):
        out = []
        while self._commands:
            out.append(self._commands.popleft())
        return out

    def reading(self, reading, reason, level, tips=()):
        values = {k: v for k, v in reading.as_dict().items() if k not in ("time", "flags") and v is not None}
        self._publish("readings", {"reason": reason, "level": level, "values": values,
                                   "flags": reading.flags, "advice": list(tips)})

    def alert(self, kind, alerts, level=None, detail=None):
        """kind: "behaviour" (camera) or "water" (CRITICAL reading)."""
        self._publish("alerts", {"kind": kind, "alerts": list(alerts), "level": level, "detail": detail or {}})

    # ---------- internals ----------

    def _envelope(self, body):
        now = self.clock()
        return {"device": self.device, "ts": round(now, 3),
                "time": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"), **body}

    def _status(self, state):
        # for the Last Will this time is when the will was registered, not when the link was lost
        return json.dumps(self._envelope({"state": state}))

    def _publish(self, name, body):
        with self._lock:
            if len(self.queue) == self.queue.maxlen:
                self.dropped += 1  # deque drops the oldest entry on append
            self.queue.append((self.topics[name], json.dumps(self._envelope(body))))
        if self.connected:
            self._flush()

    def _flush(self):
        with self._lock:
            while self.queue and self.connected:
                topic, payload = self.queue[0]
                info = self.client.publish(topic, payload, qos=1, retain=False)
                if getattr(info, "rc", 0) != 0:  # not accepted (link just dropped): keep it for later
                    break
                self.queue.popleft()
