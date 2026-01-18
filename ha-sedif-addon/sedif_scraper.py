from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dateutil import parser as date_parser
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = "https://connexion.leaudiledefrance.fr/espace-particuliers/s/"
LOGIN_URL = "https://connexion.leaudiledefrance.fr/s/login"
HISTORIQUE_URL = "https://connexion.leaudiledefrance.fr/espace-particuliers/s/historique"
SCRAPE_DAYS = 40

DATE_KEYS = (
    "date",
    "jour",
    "day",
    "dateconso",
    "datereleve",
    "date_releve",
    "date_index",
)
VOLUME_KEYS = (
    "volume",
    "conso",
    "consommation",
    "litre",
    "litres",
    "m3",
    "m^3",
)
COST_KEYS = ("euros", "euro", "prix", "montant", "ttc", "cost")
UNIT_KEYS = ("unit", "unite", "unité", "uom")
PRICE_KEYS = {
    "prixmoyeneau",
    "prixmoyen",
    "prixmoyen_eau",
    "prixmoyenent",
    "prixm3",
}
METADATA_KEYS = {
    "consommationmax": "consommation_max_m3",
    "consommationmoyenne": "consommation_moyenne_m3",
    "dateconsommationmax": "date_consommation_max",
    "datedebut": "date_debut",
    "datefin": "date_fin",
    "idpds": "id_pds",
    "numerocompteur": "numero_compteur",
    "indexmesure": "index_mesure",
}


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("\u00a0", " ")
        cleaned = cleaned.replace("€", "").replace("m³", "m3")
        cleaned = cleaned.replace(" ", "")
        cleaned = cleaned.replace(",", ".")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _round_money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 2)


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def find_price_m3(payload: Any) -> Optional[float]:
    price: Optional[float] = None

    def walk(node: Any) -> None:
        nonlocal price
        if price is not None:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                normalized = _normalize_key(key)
                if normalized in PRICE_KEYS:
                    price = _coerce_float(value)
                    if price is not None:
                        return
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return price


def _parse_index_mesure(entries: Any) -> Dict[str, Any]:
    if not isinstance(entries, list):
        return {}
    latest_date: Optional[datetime] = None
    latest_value: Optional[float] = None
    latest_raw: Optional[str] = None
    for entry in entries:
        if not isinstance(entry, str) or ";" not in entry:
            continue
        value_raw, date_raw = entry.split(";", 1)
        value = _coerce_float(value_raw)
        date_value = _parse_date(date_raw)
        if date_value is None or value is None:
            continue
        if latest_date is None or date_value > latest_date:
            latest_date = date_value
            latest_value = value
            latest_raw = entry
    if latest_date is None:
        return {}
    return {
        "index_last_value": latest_value,
        "index_last_date": latest_date.isoformat(),
        "index_last_raw": latest_raw,
    }


def find_metadata(payload: Any) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                normalized = _normalize_key(key)
                if normalized in METADATA_KEYS:
                    target_key = METADATA_KEYS[normalized]
                    if target_key == "index_mesure":
                        metadata.update(_parse_index_mesure(value))
                    elif target_key.endswith("_m3"):
                        metadata[target_key] = _coerce_float(value)
                    else:
                        metadata[target_key] = value
                if normalized in PRICE_KEYS and "price_m3" not in metadata:
                    metadata["price_m3"] = _coerce_float(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return metadata


def _parse_date(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except (OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            if re.match(r"^\d{4}-\d{2}-\d{2}", value):
                return date_parser.parse(value, dayfirst=False, yearfirst=True)
            return date_parser.parse(value, dayfirst=True)
        except (ValueError, OverflowError):
            return None
    return None


def _find_key(obj: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in obj.keys():
        lowered = key.lower()
        if any(token in lowered for token in keys):
            return key
    return None


def extract_records(payload: Any) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            date_key = _find_key(node, DATE_KEYS)
            volume_key = _find_key(node, VOLUME_KEYS)
            if date_key and volume_key:
                record: Dict[str, Any] = {
                    "date": node.get(date_key),
                    "volume": node.get(volume_key),
                    "raw": node,
                }
                cost_key = _find_key(node, COST_KEYS)
                if cost_key:
                    record["cost"] = node.get(cost_key)
                unit_key = _find_key(node, UNIT_KEYS)
                if unit_key:
                    record["unit"] = node.get(unit_key)
                records.append(record)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return records


def normalize_record(record: Dict[str, Any], price_m3: Optional[float]) -> Optional[Dict[str, Any]]:
    raw = record.get("raw") or {}
    date_candidate = record.get("date")
    if isinstance(raw, dict) and raw.get("DATE_INDEX"):
        date_candidate = raw.get("DATE_INDEX")
    date_value = _parse_date(date_candidate)
    volume_value = _coerce_float(record.get("volume"))
    if date_value is None or volume_value is None:
        return None

    unit = str(record.get("unit", "")).lower()
    cost_value = _coerce_float(record.get("cost"))

    if "litre" in unit or unit in {"l", "litres", "litre"}:
        liters = volume_value
        m3 = volume_value / 1000.0
    elif "m3" in unit or "m^3" in unit:
        m3 = volume_value
        liters = volume_value * 1000.0
    else:
        if volume_value > 50:
            liters = volume_value
            m3 = volume_value / 1000.0
        else:
            m3 = volume_value
            liters = volume_value * 1000.0

    if cost_value is None and price_m3 is not None:
        cost_value = m3 * price_m3
    cost_value = _round_money(cost_value)

    normalized = {
        "date": date_value.date().isoformat(),
        "liters": liters,
        "m3": m3,
        "euros": cost_value,
        "raw": raw,
    }
    return normalized


def aggregate_last_days(
    records: List[Dict[str, Any]],
    days: int,
    price_m3: Optional[float],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    dated_records: List[Tuple[datetime.date, Dict[str, Any]]] = []
    for record in records:
        try:
            record_date = datetime.fromisoformat(record["date"]).date()
        except ValueError:
            continue
        dated_records.append((record_date, record))

    if not dated_records:
        return {
            "days": days,
            "from": None,
            "to": None,
            "totals": {"total_liters": 0, "total_m3": 0, "total_euros": 0},
            "price_m3": price_m3,
            "metadata": metadata,
            "analytics": {},
            "daily": [],
        }

    end_date = max(date for date, _ in dated_records)
    cutoff = end_date - timedelta(days=days - 1)
    filtered = [record for date, record in dated_records if cutoff <= date <= end_date]

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for record in filtered:
        key = (
            record["date"],
            round(record["liters"], 6),
            round(record["m3"], 6),
            None if record.get("euros") is None else round(record["euros"], 6),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)

    totals = {
        "total_liters": sum(r["liters"] for r in deduped),
        "total_m3": sum(r["m3"] for r in deduped),
        "total_euros": _round_money(
            sum(r["euros"] for r in deduped if r.get("euros") is not None)
        ),
    }

    day_count = len(deduped)
    avg_daily_liters = totals["total_liters"] / day_count if day_count else 0
    avg_daily_m3 = totals["total_m3"] / day_count if day_count else 0
    avg_daily_euros = totals["total_euros"] / day_count if day_count else 0
    avg_daily_euros = _round_money(avg_daily_euros) or 0

    last_record = max(deduped, key=lambda r: r["date"], default=None)
    last_date = last_record["date"] if last_record else None
    last_liters = last_record["liters"] if last_record else None
    over_ratio: Optional[float] = None
    over_level = "unknown"
    if last_liters is not None and avg_daily_liters > 0:
        over_ratio = last_liters / avg_daily_liters
        if over_ratio >= 3:
            over_level = "critical"
        elif over_ratio >= 2:
            over_level = "high"
        else:
            over_level = "normal"

    week_start = end_date - timedelta(days=end_date.weekday())
    week_records = [
        record
        for record in deduped
        if week_start <= datetime.fromisoformat(record["date"]).date() <= end_date
    ]
    week_totals = {
        "wtd_liters": sum(r["liters"] for r in week_records),
        "wtd_m3": sum(r["m3"] for r in week_records),
        "wtd_euros": _round_money(
            sum(r["euros"] for r in week_records if r.get("euros") is not None)
        ),
    }
    week_day_count = len(week_records)

    month_start = end_date.replace(day=1)
    month_records = [
        record
        for record in deduped
        if month_start <= datetime.fromisoformat(record["date"]).date() <= end_date
    ]
    month_totals = {
        "mtd_liters": sum(r["liters"] for r in month_records),
        "mtd_m3": sum(r["m3"] for r in month_records),
        "mtd_euros": _round_money(
            sum(r["euros"] for r in month_records if r.get("euros") is not None)
        ),
    }
    month_day_count = len(month_records)
    days_in_month = calendar.monthrange(end_date.year, end_date.month)[1]
    estimate_month_euros: Optional[float] = None
    if price_m3 is not None and month_day_count > 0:
        avg_daily_m3_month = month_totals["mtd_m3"] / month_day_count
        estimate_month_euros = _round_money(avg_daily_m3_month * days_in_month * price_m3)

    analytics = {
        "avg_daily_liters": avg_daily_liters,
        "avg_daily_m3": avg_daily_m3,
        "avg_daily_euros": avg_daily_euros,
        "week_start": week_start.isoformat(),
        "week_end": end_date.isoformat(),
        "wtd_liters": week_totals["wtd_liters"],
        "wtd_m3": week_totals["wtd_m3"],
        "wtd_euros": week_totals["wtd_euros"],
        "week_day_count": week_day_count,
        "month_start": month_start.isoformat(),
        "month_end": end_date.isoformat(),
        "mtd_liters": month_totals["mtd_liters"],
        "mtd_m3": month_totals["mtd_m3"],
        "mtd_euros": month_totals["mtd_euros"],
        "month_day_count": month_day_count,
        "days_in_month": days_in_month,
        "estimate_month_euros": estimate_month_euros,
        "last_date": last_date,
        "overconsumption_ratio": over_ratio,
        "overconsumption_level": over_level,
    }

    return {
        "days": days,
        "from": cutoff.isoformat(),
        "to": end_date.isoformat(),
        "totals": totals,
        "price_m3": price_m3,
        "metadata": metadata,
        "analytics": analytics,
        "daily": sorted(deduped, key=lambda r: r["date"]),
    }


def publish_to_home_assistant(result: Dict[str, Any], ha_url: str, token: str, prefix: str) -> None:
    totals = result.get("totals", {})
    daily = result.get("daily", [])
    last_day = daily[-1] if daily else {}
    price_m3 = _round_money(result.get("price_m3"))
    metadata = result.get("metadata", {})
    analytics = result.get("analytics", {})
    device_info = {
        "identifiers": [["sedif", prefix]],
        "name": "SEDIF Water Consumption",
        "manufacturer": "SEDIF",
        "model": "Web Portal",
    }

    last_day_euros = _round_money(last_day.get("euros"))
    sensors = {
        f"sensor.{prefix}_daily": {
            "state": last_day.get("liters", 0),
            "attributes": {
                "device": device_info,
                "friendly_name": "Consommation du dernier relevé (litres)",
                "unit_of_measurement": "L",
                "last_date": last_day.get("date"),
                "last_m3": last_day.get("m3"),
                "last_euros": last_day_euros,
                "price_m3": price_m3,
                "daily": daily,
            },
        },
        f"sensor.{prefix}_daily_euros": {
            "state": last_day_euros or 0,
            "attributes": {
                "device": device_info,
                "friendly_name": "Coût du dernier relevé (EUR)",
                "unit_of_measurement": "EUR",
                "last_date": last_day.get("date"),
                "last_liters": last_day.get("liters"),
                "last_m3": last_day.get("m3"),
                "price_m3": price_m3,
            },
        },
        f"sensor.{prefix}_max_m3": {
            "state": metadata.get("consommation_max_m3", 0),
            "attributes": {
                "device": device_info,
                "friendly_name": "Consommation maximale (m³)",
                "unit_of_measurement": "m3",
                "date": metadata.get("date_consommation_max"),
                "price_m3": price_m3,
            },
        },
        f"sensor.{prefix}_avg_m3": {
            "state": metadata.get("consommation_moyenne_m3", 0),
            "attributes": {
                "device": device_info,
                "friendly_name": "Consommation moyenne (m³)",
                "unit_of_measurement": "m3",
                "price_m3": price_m3,
            },
        },
        f"sensor.{prefix}_meter_index": {
            "state": metadata.get("index_last_value", 0),
            "attributes": {
                "device": device_info,
                "friendly_name": "Index compteur (m³)",
                "unit_of_measurement": "m3",
                "date": metadata.get("index_last_date"),
                "raw": metadata.get("index_last_raw"),
            },
        },
        f"sensor.{prefix}_info": {
            "state": metadata.get("numero_compteur") or metadata.get("id_pds") or "sedif",
            "attributes": {
                "device": device_info,
                "friendly_name": "Informations compteur",
                "numero_compteur": metadata.get("numero_compteur"),
                "id_pds": metadata.get("id_pds"),
                "date_debut": metadata.get("date_debut"),
                "date_fin": metadata.get("date_fin"),
                "consommation_max_m3": metadata.get("consommation_max_m3"),
                "consommation_moyenne_m3": metadata.get("consommation_moyenne_m3"),
                "date_consommation_max": metadata.get("date_consommation_max"),
                "index_last_value": metadata.get("index_last_value"),
                "index_last_date": metadata.get("index_last_date"),
                "price_m3": price_m3,
            },
        },
        f"sensor.{prefix}_week_to_date_m3": {
            "state": analytics.get("wtd_m3", 0),
            "attributes": {
                "device": device_info,
                "friendly_name": "Consommation semaine en cours (m³)",
                "unit_of_measurement": "m3",
                "liters": analytics.get("wtd_liters"),
                "euros": analytics.get("wtd_euros"),
                "from": analytics.get("week_start"),
                "to": analytics.get("week_end"),
                "days": analytics.get("week_day_count"),
                "price_m3": price_m3,
            },
        },
        f"sensor.{prefix}_month_to_date_m3": {
            "state": analytics.get("mtd_m3", 0),
            "attributes": {
                "device": device_info,
                "friendly_name": "Consommation mois en cours (m³)",
                "unit_of_measurement": "m3",
                "liters": analytics.get("mtd_liters"),
                "euros": analytics.get("mtd_euros"),
                "from": analytics.get("month_start"),
                "to": analytics.get("month_end"),
                "days": analytics.get("month_day_count"),
                "price_m3": price_m3,
            },
        },
        f"sensor.{prefix}_monthly_estimate_euros": {
            "state": analytics.get("estimate_month_euros") or 0,
            "attributes": {
                "device": device_info,
                "friendly_name": "Estimation facture mensuelle (EUR)",
                "unit_of_measurement": "EUR",
                "days_in_month": analytics.get("days_in_month"),
                "month_day_count": analytics.get("month_day_count"),
                "mtd_m3": analytics.get("mtd_m3"),
                "price_m3": price_m3,
            },
        },
        f"sensor.{prefix}_last_reading_date": {
            "state": metadata.get("index_last_date") or analytics.get("last_date") or "unknown",
            "attributes": {
                "device": device_info,
                "friendly_name": "Date du dernier relevé",
                "last_date": metadata.get("index_last_date") or analytics.get("last_date"),
                "index_last_value": metadata.get("index_last_value"),
                "index_last_raw": metadata.get("index_last_raw"),
            },
        },
        f"sensor.{prefix}_overconsumption": {
            "state": analytics.get("overconsumption_level", "unknown"),
            "attributes": {
                "device": device_info,
                "friendly_name": "Surconsommation (référence 40 jours)",
                "ratio": analytics.get("overconsumption_ratio"),
                "threshold_high": 2,
                "threshold_critical": 3,
                "avg_daily_liters": analytics.get("avg_daily_liters"),
                "last_liters": last_day.get("liters"),
                "last_date": analytics.get("last_date"),
            },
        },
    }

    base = ha_url.rstrip("/")
    for entity_id, payload in sensors.items():
        url = f"{base}/api/states/{entity_id}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()


def _fill_first(page, selectors: Iterable[str], value: str) -> bool:
    for frame in page.frames:
        for selector in selectors:
            locator = frame.locator(selector)
            try:
                locator.first.wait_for(state="visible", timeout=2000)
            except PlaywrightTimeoutError:
                continue
            locator.first.fill(value)
            return True
    return False


def _click_first(page, selectors: Iterable[str]) -> bool:
    for frame in page.frames:
        for selector in selectors:
            locator = frame.locator(selector)
            try:
                locator.first.wait_for(state="visible", timeout=2000)
            except PlaywrightTimeoutError:
                continue
            locator.first.click()
            return True
    return False


def fetch_consumption(days: int, headless: bool) -> Dict[str, Any]:
    username = os.getenv("SEDIF_USERNAME")
    password = os.getenv("SEDIF_PASSWORD")
    debug = os.getenv("SEDIF_DEBUG", "false").lower() in {"true", "1", "yes"}
    if not username or not password:
        raise RuntimeError("SEDIF_USERNAME et SEDIF_PASSWORD sont requis dans le .env")

    responses: List[Tuple[str, Any]] = []
    price_m3: Optional[float] = None
    metadata: Dict[str, Any] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        def handle_response(response) -> None:
            content_type = response.headers.get("content-type", "").lower()
            url = response.url
            if "json" in content_type:
                try:
                    responses.append((url, response.json()))
                    if debug:
                        print(f"[debug] JSON: {url}", file=sys.stderr)
                except Exception:
                    return
                return

            if not debug:
                return

            url_lower = url.lower()
            if not any(token in url_lower for token in ("api", "aura", "apex", "data")):
                return
            try:
                text = response.text()
            except Exception:
                return
            if text.strip().startswith(("{", "[")):
                try:
                    responses.append((url, json.loads(text)))
                    print(f"[debug] JSON-like: {url}", file=sys.stderr)
                except Exception:
                    return

        page.on("response", handle_response)

        page.goto(BASE_URL, wait_until="networkidle")

        if "/login" not in page.url:
            try:
                page.goto(LOGIN_URL, wait_until="networkidle")
            except PlaywrightTimeoutError:
                pass

        filled_user = _fill_first(
            page,
            (
                "input[inputmode='email']",
                "input[type='email']",
                "input.slds-input[inputmode='email']",
                "input[name*='user']",
                "input[id*='user']",
                "input[name*='email']",
                "input[id*='email']",
            ),
            username,
        )
        filled_pass = _fill_first(
            page,
            (
                "input[type='password']",
                "input.sfdc_usernameinput[type='password']",
                "input.input[type='password']",
                "input[name*='pass']",
                "input[id*='pass']",
            ),
            password,
        )

        if not filled_user or not filled_pass:
            raise RuntimeError("Impossible de remplir le formulaire de connexion. Sélecteurs à ajuster.")

        clicked = _click_first(
            page,
            (
                "button.submit-button",
                "button:has-text('VALIDER')",
                "button[type='submit']",
                "input[type='submit']",
            ),
        )
        if not clicked:
            try:
                page.get_by_role("button", name=re.compile("connexion|connecter|login", re.I)).click()
            except Exception as exc:
                raise RuntimeError("Impossible de cliquer sur le bouton de connexion.") from exc

        try:
            page.wait_for_timeout(1000)
            if "/login" in page.url:
                page.keyboard.press("Enter")
        except PlaywrightTimeoutError:
            pass

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass

        page.goto(HISTORIQUE_URL, wait_until="networkidle")

        try:
            page.wait_for_timeout(4000)
        except PlaywrightTimeoutError:
            pass

        browser.close()

    if not responses:
        return {
            "error": "Aucune réponse JSON capturée. Vérifiez si le site charge des données via API.",
            "hint": "Lancer en mode headless=false pour voir le navigateur.",
        }

    all_records: List[Dict[str, Any]] = []
    for _, payload in responses:
        payload_metadata = find_metadata(payload)
        for key, value in payload_metadata.items():
            metadata.setdefault(key, value)
        if price_m3 is None:
            price_m3 = payload_metadata.get("price_m3") or find_price_m3(payload)
        for record in extract_records(payload):
            normalized = normalize_record(record, price_m3)
            if normalized:
                all_records.append(normalized)

    if not all_records:
        return {
            "error": "Données JSON capturées mais pas de consommation détectée.",
            "responses": [url for url, _ in responses],
        }

    return aggregate_last_days(all_records, days, price_m3, metadata)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Scrape SEDIF consommation (prototype)")
    parser.add_argument("--days", type=int, default=int(os.getenv("SEDIF_DAYS", str(SCRAPE_DAYS))))
    parser.add_argument("--headless", type=str, default=os.getenv("SEDIF_HEADLESS", "true"))
    args = parser.parse_args()

    headless = str(args.headless).lower() not in {"false", "0", "no"}

    result = fetch_consumption(args.days, headless=headless)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    ha_url = os.getenv("HA_URL")
    ha_token = os.getenv("HA_TOKEN")
    prefix = os.getenv("HA_SENSOR_PREFIX", "sedif")
    if ha_url and ha_token and isinstance(result, dict) and "error" not in result:
        try:
            publish_to_home_assistant(result, ha_url, ha_token, prefix)
        except Exception as exc:
            print(f"[warn] HA publish failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
