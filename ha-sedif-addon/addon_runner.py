from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import sedif_scraper

OPTIONS_PATH = Path("/data/options.json")
SERVICES_PATH = Path("/data/services.json")


def _load_options() -> dict:
    if OPTIONS_PATH.exists():
        with OPTIONS_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def _load_services() -> dict:
    if SERVICES_PATH.exists():
        with SERVICES_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def _set_env_from_options(options: dict) -> None:
    services = _load_services()
    mqtt_service = services.get("mqtt", {}) if isinstance(services, dict) else {}
    if options.get("sedif_username"):
        os.environ["SEDIF_USERNAME"] = options["sedif_username"]
    if options.get("sedif_password"):
        os.environ["SEDIF_PASSWORD"] = options["sedif_password"]

    os.environ["SEDIF_DAYS"] = "40"
    os.environ["SEDIF_HEADLESS"] = "true"
    os.environ["SEDIF_DEBUG"] = str(options.get("debug", False)).lower()
    os.environ["HA_SENSOR_PREFIX"] = options.get("sensor_prefix", "sedif")

    mqtt_host = options.get("mqtt_host") or mqtt_service.get("host")
    mqtt_port = options.get("mqtt_port") or mqtt_service.get("port") or 1883
    mqtt_username = options.get("mqtt_username") or mqtt_service.get("username")
    mqtt_password = options.get("mqtt_password") or mqtt_service.get("password")
    mqtt_discovery_prefix = options.get("mqtt_discovery_prefix", "homeassistant")
    mqtt_base_topic = options.get("mqtt_base_topic")

    if mqtt_host:
        os.environ["MQTT_HOST"] = mqtt_host
    os.environ["MQTT_PORT"] = str(mqtt_port)
    if mqtt_username:
        os.environ["MQTT_USERNAME"] = mqtt_username
    if mqtt_password:
        os.environ["MQTT_PASSWORD"] = mqtt_password
    os.environ["MQTT_DISCOVERY_PREFIX"] = mqtt_discovery_prefix
    if mqtt_base_topic:
        os.environ["MQTT_BASE_TOPIC"] = mqtt_base_topic


def main() -> None:
    options = _load_options()
    _set_env_from_options(options)

    refresh_minutes = int(options.get("refresh_interval_minutes", 360))
    if refresh_minutes <= 0:
        refresh_minutes = 360
    while True:
        sys.argv = [sys.argv[0]]
        sedif_scraper.main()
        time.sleep(refresh_minutes * 60)


if __name__ == "__main__":
    main()
