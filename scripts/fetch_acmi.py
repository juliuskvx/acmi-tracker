#!/usr/bin/env python3
"""
fetch_acmi.py — ACMI Tracker FR24 data fetcher
Queries FR24 Explorer API for each registration in fleet_registry.json
Outputs data/acmi_data.json for the dashboard

Usage: python3 scripts/fetch_acmi.py
Requires: FR24_API_KEY environment variable
"""

import json
import os
import time
import requests
from datetime import datetime, timezone

# --- Config ---
FR24_BASE = "https://fr24api.flightradar24.com"
FR24_TOKEN = os.environ.get("FR24_API_KEY", "")
REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "../data/fleet_registry.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "../data/acmi_data.json")
DELAY = 0.4  # seconds between API calls

HEADERS = {
    "Authorization": f"Bearer {FR24_TOKEN}",
    "Accept-Version": "v1",
    "Accept": "application/json",
}

def get_live_position(registration):
    url = f"{FR24_BASE}/api/flights/live/positions/full"
    try:
        r = requests.get(url, headers=HEADERS, params={"registration": registration}, timeout=10)
        r.raise_for_status()
        flights = r.json().get("data", [])
        return flights[0] if flights else None
    except Exception as e:
        print(f"  ERROR live {registration}: {e}")
        return None

def get_recent_events(registration, limit=3):
    url = f"{FR24_BASE}/api/flights/historic/events/full"
    try:
        r = requests.get(url, headers=HEADERS, params={"registration": registration, "limit": limit}, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"  ERROR historic {registration}: {e}")
        return []

def detect_operator(callsign, owner_icao):
    """Extract operator ICAO from callsign and compare to owner."""
    if not callsign:
        return None, False
    op_icao = callsign[:3].upper()
    is_acmi = op_icao != owner_icao.upper()
    return op_icao, is_acmi

def main():
    if not FR24_TOKEN:
        print("ERROR: FR24_API_KEY not set")
        raise SystemExit(1)

    with open(REGISTRY_FILE) as f:
        registry = json.load(f)

    total = sum(len(op["aircraft"]) for op in registry["operators"])
    print(f"Fetching {total} aircraft across {len(registry['operators'])} operators")

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
                "current_operator_name": None,
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

                entry["callsign"] = callsign
                entry["current_operator_icao"] = op_icao
                entry["last_seen"] = datetime.now(timezone.utc).isoformat()
                entry["latitude"] = live.get("lat")
                entry["longitude"] = live.get("lon")
                entry["altitude"] = live.get("alt")
                entry["speed"] = live.get("spd")
                entry["heading"] = live.get("track")
                entry["last_flight"] = callsign

                orig = live.get("orig_iata", "")
                dest = live.get("dest_iata", "")
                if orig and dest:
                    entry["last_route"] = f"{orig}-{dest}"

                if is_acmi:
                    entry["status"] = "acmi_active"
                    acmi_count += 1
                    print(f"ACMI → {op_icao} ({callsign})")
                else:
                    entry["status"] = "own_ops"
                    own_ops_count += 1
                    print(f"own ops ({callsign})")
            else:
                # Not airborne — get last known flight from historic events
                events = get_recent_events(reg, limit=1)
                time.sleep(DELAY)
                if events:
                    last = events[0]
                    entry["last_flight"] = last.get("callsign")
                    entry["last_seen"] = last.get("arr_time") or last.get("dep_time")
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
