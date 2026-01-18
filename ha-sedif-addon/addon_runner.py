from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import sedif_scraper

OPTIONS_PATH = Path("/data/options.json")


def _load_options() -> dict:
    if OPTIONS_PATH.exists():
        with OPTIONS_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def _set_env_from_options(options: dict) -> None:
    if options.get("sedif_username"):
        os.environ["SEDIF_USERNAME"] = options["sedif_username"]
    if options.get("sedif_password"):
        os.environ["SEDIF_PASSWORD"] = options["sedif_password"]

    os.environ["SEDIF_DAYS"] = "40"
    os.environ["SEDIF_HEADLESS"] = "true"
    os.environ["SEDIF_DEBUG"] = str(options.get("debug", False)).lower()
    os.environ["HA_SENSOR_PREFIX"] = options.get("sensor_prefix", "sedif")

    ha_url = os.getenv("HA_URL") or "http://supervisor/core"
    os.environ["HA_URL"] = ha_url

    ha_token = os.getenv("HA_TOKEN") or os.getenv("SUPERVISOR_TOKEN", "")
    if ha_token:
        os.environ["HA_TOKEN"] = ha_token


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
