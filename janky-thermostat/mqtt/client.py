from .device import MQTTDevice

DEVICE = MQTTDevice("janky-thermostat", "Janky Thermostat", "Janky Thermo v1")

from typing import List, Optional, Any
import paho.mqtt.client as mqtt
import json
import logging
import threading
import time

from .entity import MQTTEntity

_LOGGER = logging.getLogger(__name__)

class MQTTClient:
    def __init__(self,
                 broker: str,
                 port: int = 1883,
                 device: MQTTDevice = DEVICE,
                 username: Optional[str] = None,
                 password: Optional[str] = None) -> None:
        self.broker: str = broker
        self.port: int = port
        self.client: mqtt.Client = mqtt.Client(client_id=device.deviceid)
        if username and password:
            self.client.username_pw_set(username, password)
        self.device: MQTTDevice = device
        self.entities: List[MQTTEntity] = []
        self._retry_min_delay = 1.0
        self._retry_max_delay = 60.0
        self._connect_timeout = 10.0
        self._connected = threading.Event()
        self._connect_result = threading.Event()
        self._shutdown = threading.Event()
        self._loop_started = False
        self._last_connect_rc: Optional[int] = None
        self._stop_event: Optional[threading.Event] = None
        # Paho callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        if hasattr(self.client, "on_connect_fail"):
            self.client.on_connect_fail = self._on_connect_fail
        if hasattr(self.client, "reconnect_delay_set"):
            self.client.reconnect_delay_set(
                min_delay=int(self._retry_min_delay),
                max_delay=int(self._retry_max_delay),
            )

    def register_entity(self, entity: MQTTEntity) -> MQTTEntity:
        """Add an entity and subscribe to its command topic if defined."""
        entity.build_topics(self.device)
        self.entities.append(entity)
        return entity

    def connect(self, stop_event: Optional[threading.Event] = None) -> None:
        """Establish connection and keep retrying until connected or stopped."""
        self._shutdown.clear()
        self._stop_event = stop_event
        self._ensure_loop_started()
        delay = self._retry_min_delay
        while not self._should_stop():
            self._connect_result.clear()
            self._last_connect_rc = None
            try:
                self.client.connect(self.broker, self.port)
            except Exception:
                _LOGGER.warning(
                    "MQTT connect attempt to %s:%s failed; retrying in %.1fs",
                    self.broker,
                    self.port,
                    delay,
                    exc_info=True,
                )
            else:
                connect_result = self._wait_for_connect_result()
                if connect_result is None:
                    return
                if connect_result:
                    if self._connected.is_set():
                        return
                    _LOGGER.warning(
                        "MQTT connect attempt to %s:%s failed (rc=%s); retrying in %.1fs",
                        self.broker,
                        self.port,
                        self._last_connect_rc,
                        delay,
                    )

            if self._wait_for_stop(delay):
                return
            delay = min(delay * 2, self._retry_max_delay)

    def disconnect(self) -> None:
        self._shutdown.set()
        self._connected.clear()
        try:
            self.client.disconnect()
        except Exception:
            _LOGGER.debug("MQTT disconnect failed during shutdown", exc_info=True)
        if self._loop_started:
            self.client.loop_stop()
            self._loop_started = False

    def _on_connect(self,
                    client: mqtt.Client,
                    userdata: Any,
                    flags: dict,
                    rc: int) -> None:
        self._last_connect_rc = rc
        self._connect_result.set()
        if rc != 0:
            self._connected.clear()
            _LOGGER.warning(
                "MQTT connection to %s:%s was refused (rc=%s)",
                self.broker,
                self.port,
                rc,
            )
            return

        self._connected.set()
        _LOGGER.info("Connected to MQTT (%s:%s)", self.broker, self.port)
        # register client in entities and setup callbacks
        for entity in self.entities:
            entity._on_connect(self.client)
        # Publish discovery configs
        self.publish_discovery_configs()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        rc: int,
    ) -> None:
        self._connected.clear()
        self._connect_result.set()
        if self._shutdown.is_set():
            _LOGGER.info("Disconnected from MQTT (%s:%s)", self.broker, self.port)
            return
        if rc == 0:
            _LOGGER.info("MQTT disconnected cleanly (%s:%s)", self.broker, self.port)
            return

        _LOGGER.warning(
            "MQTT connection lost (%s:%s, rc=%s); retrying with backoff",
            self.broker,
            self.port,
            rc,
        )

    def _on_connect_fail(self, client: mqtt.Client, userdata: Any) -> None:
        if self._shutdown.is_set():
            return
        _LOGGER.warning(
            "Automatic MQTT reconnect to %s:%s failed; continuing with backoff",
            self.broker,
            self.port,
        )

    def _ensure_loop_started(self) -> None:
        if self._loop_started:
            return
        self.client.loop_start()
        self._loop_started = True

    def _should_stop(self) -> bool:
        return self._shutdown.is_set() or (
            self._stop_event is not None and self._stop_event.is_set()
        )

    def _wait_for_connect_result(self) -> Optional[bool]:
        deadline = time.monotonic() + self._connect_timeout
        while not self._should_stop():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _LOGGER.warning(
                    "MQTT connect attempt to %s:%s timed out after %.1fs",
                    self.broker,
                    self.port,
                    self._connect_timeout,
                )
                return False
            if self._connect_result.wait(timeout=min(0.25, remaining)):
                return True
        return None

    def _wait_for_stop(self, delay: float) -> bool:
        deadline = time.monotonic() + delay
        while not self._should_stop():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._shutdown.wait(timeout=min(0.25, remaining))
        return True

    def publish_discovery_configs(self) -> None:
        for entity in self.entities:
            topic: str = entity.discovery_topic(self.device)
            payload: dict = entity.discovery_payload(self.device)
            self.client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
            _LOGGER.debug("Published discovery %s -> %s", entity.object_id, topic)
