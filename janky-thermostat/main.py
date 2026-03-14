import argparse
import logging
import os
import signal
import sys

from runtime_config import DEFAULT_CONFIG_PATH, apply_runtime_environment, load_runtime_config


class StdoutFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the janky thermostat controller as a standard OCI container."
    )
    parser.add_argument(
        "--config",
        help=f"Path to the JSON config file. Defaults to {DEFAULT_CONFIG_PATH} or JANKY_CONFIG_FILE.",
    )
    return parser.parse_args()


def configure_logging(loglevel: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(loglevel)

    out_hdlr = logging.StreamHandler(sys.stdout)
    out_hdlr.setLevel(logging.DEBUG)
    out_hdlr.addFilter(StdoutFilter())
    out_hdlr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

    err_hdlr = logging.StreamHandler(sys.stderr)
    err_hdlr.setLevel(logging.WARNING)
    err_hdlr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

    root.addHandler(out_hdlr)
    root.addHandler(err_hdlr)


def main() -> int:
    args = parse_args()
    config_path = args.config or os.getenv("JANKY_CONFIG_FILE", DEFAULT_CONFIG_PATH)
    config_required = bool(args.config) or "JANKY_CONFIG_FILE" in os.environ
    options = load_runtime_config(config_path, config_required=config_required)

    configure_logging(options["loglevel"])
    apply_runtime_environment(options)

    from mqtt.client import MQTTClient
    from internals.threadinghelpers import handle_shutdown
    from internals.controller import Controller

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    client = MQTTClient(
        options["mqtt_broker"],
        port=options["mqtt_port"],
        username=options["mqtt_username"],
        password=options["mqtt_password"],
    )

    controller = Controller(client, options)
    controller.loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
