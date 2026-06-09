#!/usr/bin/env python3
"""
fetch_acmi.py — ACMI Tracker FR24 data fetcher
Queries FR24 Explorer API for each registration in fleet_registry.json
Outputs data/acmi_data.json for the dashboard
"""

import json
import os
import time
import requests
from datetime import datetime, timezone, timedelta

FR24_BASE = "https://fr24api.flightradar24.com"
FR24_TOKEN = os.environ.get("FR24_API_KEY", "")
REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "../data/fleet_registry.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "../data/acmi_data.json")

# Explorer plan rate limit: ~10 requests/minute → 6s between calls
DELAY = 6.0
RETRY_DELAY = 30.0  # wait 30s on 429 before retrying
MAX_RETRIES = 3

HEADERS = {
    "Authorization": f"Bearer {FR24_TOKEN}",
    "Accept-Version": "v1",
    "Accept": "application/json",
}

def api_get(url, params, label=""):
    """Make a GET request with retry on 429."""
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code == 429:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"\n    rate limited, waiting {wait}s...", end=" ", flush=True)
                time.sleep(wait)
                continue
            if r.status_code in (404, 204):
                return None
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ERROR {label}: {e}")
                return None
        except Exception as e:
            print(f"  ERROR {label}: {e}")
            return None
    return None

def get_live_position(registration):
    result = api_get(
        f"{FR24_BASE}/api/live/flight-positions/full",
        {"registrations": registration},
        f"live {registration}"
    )
    if result:
        data = result.get("data", [])
        return data[0] if data else None
    return None

def get_flight_summary(registration):
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = api_get(
        f"{FR24_BASE}/api/flight-summary/light",
        {
            "registrations": registration,
            "flight_datetime_from": date_from,
            "flight_datetime_to": date_to,
            "limit": 1,
        },
        f"summary {registration}"
    )
    if result:
        return result.get("data", [])
    return []

def detect_operator(callsign, owner_icao):
    if not callsign or len(callsign) < 3:
        return None, False
    op_icao = callsign[:3].upper()
    return op_icao, op_icao != owner_icao.upper()

def main():
    if not FR24_TOKEN:
        print("ERROR: FR24_API_KEY not set")
        raise SystemExit(1)

    with open(REGISTRY_FILE) as f:
        registry = json.load(f)

    total = sum(len(op["aircraft"]) for op in registry["operators"])
    print(f"Fetching {total} aircraft across {len(registry['operators'])} operators")
    print(f"Estimated time: ~{total * DELAY * 2 / 60:.0f} minutes (live + summary per aircraft)\n")

    fleet = []
    queried = acmi_count = own_ops_count = ground_count = 0

    for op in registry["operators"]:
        print(f"\n{op['name']} ({op['icao']}) — {len(op['aircraft'])} aircraft")

        for ac in op["aircraft"]:
            reg = ac["registration"]
            queried += 1
            print(f"  [{queried}/{total}] {reg}", end=" ... ", flush=True)

            live = get_live_position(reg)
            time.sleep(DELAY)

            entry = {
                "registration": reg,
                "type": ac["type"],
                "owner_icao": op["icao"],
                "owner_name": op["name"],
                "group": op.get("group", op["name"]),
                "status": "unknown",
                "callsign": None,
                "current_operator_icao": None,
                "last_flight": None,
                "last_route": None,
                "last_seen": None,
                "latitude": None,
                "longitude": None,
                "altitude": None,
                "speed": None,
                "heading": None,
            }

            if live:
                callsign = live.get("callsign", "")
                op_icao, is_acmi = detect_operator(callsign, op["icao"])
                entry.update({
                    "callsign": callsign,
                    "current_operator_icao": op_icao,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "latitude": live.get("lat"),
                    "longitude": live.get("lon"),
                    "altitude": live.get("alt"),
                    "speed": live.get("spd"),
                    "heading": live.get("track"),
                    "last_flight": callsign,
                    "status": "acmi_active" if is_acmi else "own_ops",
                })
                orig = live.get("orig_iata", "")
                dest = live.get("dest_iata", "")
                if orig and dest:
                    entry["last_route"] = f"{orig}-{dest}"
                if is_acmi:
                    acmi_count += 1
                    print(f"ACMI → {op_icao} ({callsign})")
                else:
                    own_ops_count += 1
                    print(f"own ops ({callsign})")
            else:
                summary = get_flight_summary(reg)
                time.sleep(DELAY)
                if summary:
                    last = summary[0]
                    entry["last_flight"] = last.get("callsign")
                    entry["last_seen"] = last.get("actual_arr_time") or last.get("actual_dep_time")
                    orig = last.get("orig_iata", "")
                    dest = last.get("dest_iata", "")
                    if orig and dest:
                        entry["last_route"] = f"{orig}-{dest}"
                    entry["status"] = "on_ground"
                    ground_count += 1
                    print(f"on ground (last: {entry['last_flight'] or 'unknown'})")
                else:
                    ground_count += 1
                    print("no data")

            fleet.append(entry)

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_aircraft": queried,
            "acmi_active": acmi_count,
            "own_ops": own_ops_count,
            "on_ground": ground_count,
        },
        "fleet": fleet,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Done — {queried} aircraft queried")
    print(f"  ACMI active:  {acmi_count}")
    print(f"  Own ops:      {own_ops_count}")
    print(f"  On ground:    {ground_count}")
    print(f"Output: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
