import importlib
import sys
import threading
import time
import types
import unittest


class FakePahoClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.on_connect = None
        self.on_connect_fail = None
        self.on_disconnect = None
        self.connect_side_effects = []
        self.reconnect_side_effects = []
        self.connect_calls = 0
        self.reconnect_calls = 0
        self.disconnect_calls = 0
        self.loop_start_calls = 0
        self.loop_stop_calls = 0

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def reconnect_delay_set(self, min_delay, max_delay):
        self.reconnect_delay = (min_delay, max_delay)

    def loop_start(self):
        self.loop_start_calls += 1

    def loop_stop(self):
        self.loop_stop_calls += 1

    def connect(self, broker, port):
        self.connect_calls += 1
        if self.connect_side_effects:
            effect = self.connect_side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect(self, broker, port)
        return 0

    def reconnect(self):
        self.reconnect_calls += 1
        if self.reconnect_side_effects:
            effect = self.reconnect_side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect(self)
        return 0

    def disconnect(self):
        self.disconnect_calls += 1
        if self.on_disconnect is not None:
            self.on_disconnect(self, None, 0)

    def publish(self, topic, payload=None, qos=0, retain=False):
        return None

    def subscribe(self, topic, qos=0):
        return None

    def unsubscribe(self, topic):
        return None

    def message_callback_add(self, topic, callback):
        return None

    def message_callback_remove(self, topic):
        return None

    def trigger_disconnect(self, rc):
        if self.on_disconnect is not None:
            self.on_disconnect(self, None, rc)
        if rc != 0:
            threading.Thread(target=self._auto_reconnect, daemon=True).start()

    def _auto_reconnect(self):
        while True:
            try:
                self.reconnect()
                return
            except Exception:
                if self.on_connect_fail is not None:
                    self.on_connect_fail(self, None)
                time.sleep(0.01)


class MQTTClientRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_client_module = types.ModuleType("paho.mqtt.client")
        fake_client_module.Client = FakePahoClient
        fake_client_module.MQTTMessage = type("MQTTMessage", (), {})

        fake_mqtt_module = types.ModuleType("paho.mqtt")
        fake_mqtt_module.client = fake_client_module

        fake_paho_module = types.ModuleType("paho")
        fake_paho_module.mqtt = fake_mqtt_module

        cls._module_patches = {
            "paho": fake_paho_module,
            "paho.mqtt": fake_mqtt_module,
            "paho.mqtt.client": fake_client_module,
        }
        cls._original_modules = {
            name: sys.modules.get(name) for name in cls._module_patches
        }
        sys.modules.update(cls._module_patches)
        cls.mqtt_client_module = importlib.import_module("mqtt.client")
        cls.mqtt_client_module = importlib.reload(cls.mqtt_client_module)

    @classmethod
    def tearDownClass(cls):
        for name, original in cls._original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    def make_client(self):
        client = self.mqtt_client_module.MQTTClient("broker", port=1883)
        client._retry_min_delay = 0.01
        client._retry_max_delay = 0.02
        client._connect_timeout = 0.05
        return client

    def wait_for(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_startup_connect_retries_until_success(self):
        client = self.make_client()
        fake = client.client
        fake.connect_side_effects = [
            ConnectionRefusedError("refused"),
            lambda fake_client, broker, port: fake_client.on_connect(
                fake_client, None, {}, 0
            ),
        ]

        client.connect()

        self.assertEqual(fake.connect_calls, 2)
        self.assertTrue(client._connected.is_set())
        client.disconnect()

    def test_disconnect_triggers_backoff_reconnect(self):
        client = self.make_client()
        fake = client.client
        fake.connect_side_effects = [
            lambda fake_client, broker, port: fake_client.on_connect(
                fake_client, None, {}, 0
            ),
        ]

        client.connect()
        fake.reconnect_side_effects = [
            ConnectionRefusedError("still down"),
            lambda fake_client: fake_client.on_connect(fake_client, None, {}, 0),
        ]

        fake.trigger_disconnect(1)

        self.assertTrue(self.wait_for(lambda: fake.reconnect_calls >= 2))
        self.assertTrue(client._connected.is_set())
        client.disconnect()

    def test_connect_returns_when_stop_event_is_set(self):
        client = self.make_client()
        fake = client.client
        fake.connect_side_effects = [ConnectionRefusedError("refused")]
        stop_event = threading.Event()

        def trigger_stop():
            time.sleep(0.03)
            stop_event.set()

        stopper = threading.Thread(target=trigger_stop, daemon=True)
        stopper.start()

        client.connect(stop_event)

        self.assertFalse(client._connected.is_set())
        client.disconnect()


if __name__ == "__main__":
    unittest.main()
