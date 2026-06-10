#!/usr/bin/env python3
"""
fetch_acmi.py — ACMI Tracker FR24 data fetcher
Runs daily at 10:00 AM Lithuanian time (08:00 UTC)

Does two things:
1. Live snapshot — current positions of all tracked aircraft → acmi_data.json
2. Daily report — yesterday's full flight activity (BH, flights, routes, clients) → acmi_history.json
"""

import json
import os
import time
import requests
from datetime import datetime, timezone, timedelta

FR24_BASE   = "https://fr24api.flightradar24.com"
FR24_TOKEN  = os.environ.get("FR24_API_KEY", "")
DATA_DIR    = os.path.join(os.path.dirname(__file__), "../data")
REGISTRY    = os.path.join(DATA_DIR, "fleet_registry.json")
SNAPSHOT    = os.path.join(DATA_DIR, "acmi_data.json")
HISTORY     = os.path.join(DATA_DIR, "acmi_history.json")

DELAY       = 6.0
RETRY_DELAY = 30.0
MAX_RETRIES = 3

HEADERS = {
    "Authorization": f"Bearer {FR24_TOKEN}",
    "Accept-Version": "v1",
    "Accept": "application/json",
}

# ── Airline name lookup ───────────────────────────────────────────────────────

AIRLINE_NAMES = {
    # Eurowings group
    "EWG": "Eurowings",
    "EW":  "Eurowings",
    "EZY": "easyJet",
    "EZS": "easyJet Switzerland",
    # Thomas Cook / TUI group
    "TCX": "TUI Airways",
    "TOM": "TUI Airways",
    "TUI": "TUI fly",
    "TFL": "TUI fly Nordic",
    "TBM": "TUI fly Belgium",
    "TFD": "TUI fly Deutschland",
    "TFN": "TUI fly Netherlands",
    # Condor
    "CFG": "Condor",
    # Transavia
    "TRA": "Transavia",
    "HV":  "Transavia",
    # Wizz Air
    "WZZ": "Wizz Air",
    "W6":  "Wizz Air",
    # Ryanair
    "RYR": "Ryanair",
    "FR":  "Ryanair",
    # Vueling
    "VLG": "Vueling",
    # Iberia
    "IBE": "Iberia",
    # Air Europa
    "AEA": "Air Europa",
    "AP7": "Air Europa",
    # Volotea
    "VOE": "Volotea",
    # Norwegian
    "NAX": "Norwegian",
    "DY":  "Norwegian",
    # SAS
    "SAS": "SAS Scandinavian",
    "SK":  "SAS Scandinavian",
    # Finnair
    "FIN": "Finnair",
    "AY":  "Finnair",
    # LOT Polish
    "LOT": "LOT Polish Airlines",
    "LO":  "LOT Polish Airlines",
    # Corendon
    "CAI": "Corendon Airlines",
    "XC":  "Corendon Airlines",
    # SunExpress
    "SXS": "SunExpress",
    "XQ":  "SunExpress",
    # Pegasus
    "PGT": "Pegasus Airlines",
    "PC":  "Pegasus Airlines",
    # Turkish Airlines
    "THY": "Turkish Airlines",
    "TK":  "Turkish Airlines",
    # Azerbaijan Airlines
    "AHY": "Azerbaijan Airlines",
    "J2":  "Azerbaijan Airlines",
    # Tunisair
    "TAR": "Tunisair",
    "TU":  "Tunisair",
    # Air Algérie
    "DAH": "Air Algérie",
    "AH":  "Air Algérie",
    # Nouvelair
    "LBT": "Nouvelair",
    # Tunisair Express
    "TAR": "Tunisair",
    # Air Arabia
    "ABY": "Air Arabia",
    "G9":  "Air Arabia",
    # Arkia
    "AIZ": "Arkia Israeli Airlines",
    "IZ":  "Arkia Israeli Airlines",
    # Israir
    "ISR": "Israir",
    # Novair
    "NVD": "Novair",
    # Neos
    "NOS": "Neos",
    # Blue Panorama
    "BPA": "Blue Panorama",
    # Privilege Style
    "PVG": "Privilege Style",
    # Freebird
    "FHY": "Freebird Airlines",
    # Jet2
    "EXS": "Jet2",
    "LS":  "Jet2",
    # Aer Lingus
    "EIN": "Aer Lingus",
    "EI":  "Aer Lingus",
    # Icelandair
    "ICE": "Icelandair",
    "FI":  "Icelandair",
    # Air Portugal / TAP
    "TAP": "TAP Air Portugal",
    "TP":  "TAP Air Portugal",
    # SATA / Azores Airlines
    "SAT": "Azores Airlines",
    "APO": "Azores Airlines",
    # Pobeda
    "PBD": "Pobeda",
    # S7 Airlines
    "SBI": "S7 Airlines",
    # Ural Airlines
    "SVR": "Ural Airlines",
    # Air Malta
    "AMC": "Air Malta",
    "KM":  "Air Malta",
    # Malta Air (Ryanair subsidiary)
    "MAT": "Malta Air",
    # KLM
    "KLM": "KLM",
    "KL":  "KLM",
    # Air France
    "AFR": "Air France",
    "AF":  "Air France",
    # Lufthansa
    "DLH": "Lufthansa",
    "LH":  "Lufthansa",
    # Swiss
    "SWR": "Swiss",
    "LX":  "Swiss",
    # Austrian
    "AUA": "Austrian Airlines",
    "OS":  "Austrian Airlines",
    # Brussels Airlines
    "BEL": "Brussels Airlines",
    "SN":  "Brussels Airlines",
    # Eurowings Discover
    "EWD": "Eurowings Discover",
    # Smartwings
    "TVS": "Smartwings",
    "QS":  "Smartwings",
    # Sunclass Airlines (formerly Thomas Cook Scandinavia)
    "SCC": "Sunclass Airlines",
    # Aruba Airlines
    "ARU": "Aruba Airlines",
    # Other common codes
    "MLH": "Air Alsace",
    "NVR": "Novair",
}

# ── API helper ──────────────────────────────────────────────────────────────

def api_get(url, params, label=""):
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

# ── FR24 queries ─────────────────────────────────────────────────────────────

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

def get_day_flights(registration, date_from_utc, date_to_utc):
    """Get all flights for an aircraft within a UTC time window."""
    result = api_get(
        f"{FR24_BASE}/api/flight-summary/light",
        {
            "registrations": registration,
            "flight_datetime_from": date_from_utc,
            "flight_datetime_to": date_to_utc,
            "limit": 20,
        },
        f"history {registration}"
    )
    if result:
        return result.get("data", [])
    return []

# ── Helpers ──────────────────────────────────────────────────────────────────

def detect_operator(callsign, owner_icao):
    if not callsign or len(callsign) < 3:
        return None, False
    op_icao = callsign[:3].upper()
    return op_icao, op_icao != owner_icao.upper()

def resolve_airline_name(icao_code):
    """Resolve a 3-letter ICAO operator code to a full airline name."""
    if not icao_code:
        return icao_code
    return AIRLINE_NAMES.get(icao_code.upper(), icao_code)

def calc_block_hours(dep_time, arr_time):
    """Calculate block hours to nearest 0.1h.
    Handles both Unix epoch (int/float) and ISO string timestamps.
    """
    if not dep_time or not arr_time:
        return 0.0
    try:
        # FR24 flight-summary/light returns Unix epoch integers
        if isinstance(dep_time, (int, float)):
            dep = datetime.fromtimestamp(dep_time, tz=timezone.utc)
        else:
            dep = datetime.strptime(dep_time, "%Y-%m-%dT%H:%M:%SZ")

        if isinstance(arr_time, (int, float)):
            arr = datetime.fromtimestamp(arr_time, tz=timezone.utc)
        else:
            arr = datetime.strptime(arr_time, "%Y-%m-%dT%H:%M:%SZ")

        diff_minutes = (arr - dep).total_seconds() / 60
        if diff_minutes <= 0:
            return 0.0
        return round(diff_minutes / 60, 1)
    except Exception as e:
        print(f"  BH calc error: {e} | dep={dep_time} arr={arr_time}")
        return 0.0

def lt_day_window(offset_days=0):
    """Return (date_str, utc_from, utc_to) for a day in Lithuanian time (UTC+3)."""
    lt_offset = timedelta(hours=3)
    now_utc   = datetime.now(timezone.utc)
    now_lt    = now_utc + lt_offset + timedelta(days=offset_days)
    day_lt    = now_lt.replace(hour=0, minute=1, second=0, microsecond=0)
    end_lt    = now_lt.replace(hour=23, minute=59, second=0, microsecond=0)
    utc_from  = (day_lt - lt_offset).strftime("%Y-%m-%dT%H:%M:%SZ")
    utc_to    = (end_lt - lt_offset).strftime("%Y-%m-%dT%H:%M:%SZ")
    return now_lt.strftime("%Y-%m-%d"), utc_from, utc_to

# ── Phase 1: Live Snapshot ───────────────────────────────────────────────────

def run_snapshot(registry):
    print("\n" + "="*60)
    print("PHASE 1 — Live Snapshot")
    print("="*60)

    now_utc   = datetime.now(timezone.utc)
    lt_offset = timedelta(hours=3)
    now_lt    = now_utc + lt_offset
    report_date = now_lt.strftime("%Y-%m-%d")
    interval_from = f"{report_date} 00:01"
    interval_to   = f"{report_date} 23:59"

    total   = sum(len(op["aircraft"]) for op in registry["operators"])
    fleet   = []
    queried = acmi_count = own_count = ground_count = 0

    print(f"Querying {total} aircraft...\n")

    for op in registry["operators"]:
        if not op["aircraft"]:
            continue
        print(f"{op['name']} ({op['icao']}) — {len(op['aircraft'])} aircraft")
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
                callsign        = live.get("callsign", "")
                op_icao, is_acmi = detect_operator(callsign, op["icao"])
                entry.update({
                    "callsign": callsign,
                    "current_operator_icao": op_icao,
                    "current_operator_name": resolve_airline_name(op_icao),
                    "last_seen": now_utc.isoformat(),
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
                    print(f"ACMI → {op_icao} / {resolve_airline_name(op_icao)} ({callsign})")
                else:
                    own_count += 1
                    print(f"own ops ({callsign})")
            else:
                # Fallback: today's last flight
                _, utc_from, utc_to = lt_day_window(0)
                summary = get_day_flights(reg, utc_from, utc_to)
                time.sleep(DELAY)
                if summary:
                    last = summary[0]
                    entry["last_flight"] = last.get("callsign")
                    entry["last_seen"]   = last.get("actual_arr_time") or last.get("actual_dep_time")
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
        "last_updated": now_utc.isoformat(),
        "report_date": report_date,
        "interval_from": interval_from,
        "interval_to": interval_to,
        "summary": {
            "total_aircraft": queried,
            "acmi_active": acmi_count,
            "own_ops": own_count,
            "on_ground": ground_count,
        },
        "fleet": fleet,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SNAPSHOT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSnapshot done — {acmi_count} ACMI active, {own_count} own ops, {ground_count} on ground")
    return output

# ── Phase 2: Daily History Report ────────────────────────────────────────────

def run_history(registry):
    print("\n" + "="*60)
    print("PHASE 2 — Daily History Report (yesterday)")
    print("="*60)

    report_date, utc_from, utc_to = lt_day_window(-1)
    print(f"Reporting period: {report_date} 00:01 → 23:59 LT")
    print(f"UTC window: {utc_from} → {utc_to}\n")

    total   = sum(len(op["aircraft"]) for op in registry["operators"])
    results = []
    queried = 0

    # client_map[client_icao][owner_group] = {flights, bh, routes, aircraft}
    client_map = {}

    for op in registry["operators"]:
        if not op["aircraft"]:
            continue
        print(f"{op['name']} ({op['icao']}) — {len(op['aircraft'])} aircraft")

        for ac in op["aircraft"]:
            reg = ac["registration"]
            queried += 1
            print(f"  [{queried}/{total}] {reg}", end=" ... ", flush=True)

            flights = get_day_flights(reg, utc_from, utc_to)
            time.sleep(DELAY)

            if not flights:
                print("no flights")
                results.append({
                    "registration": reg,
                    "type": ac["type"],
                    "owner_icao": op["icao"],
                    "owner_name": op["name"],
                    "group": op.get("group", op["name"]),
                    "total_flights": 0,
                    "total_bh": 0.0,
                    "acmi_flights": 0,
                    "acmi_bh": 0.0,
                    "clients": [],
                    "routes": [],
                    "flight_log": [],
                })
                continue

            total_bh     = 0.0
            acmi_bh      = 0.0
            acmi_flights = 0
            clients_seen = {}
            routes       = []
            flight_log   = []

            for fl in flights:
                callsign  = fl.get("callsign", "")
                dep_time  = fl.get("actual_dep_time") or fl.get("scheduled_dep_time")
                arr_time  = fl.get("actual_arr_time") or fl.get("scheduled_arr_time")
                orig      = fl.get("orig_iata", "")
                dest      = fl.get("dest_iata", "")
                bh        = calc_block_hours(dep_time, arr_time)
                op_icao, is_acmi = detect_operator(callsign, op["icao"])

                total_bh += bh
                route = f"{orig}-{dest}" if orig and dest else None
                if route and route not in routes:
                    routes.append(route)

                flight_log.append({
                    "callsign": callsign,
                    "operator_icao": op_icao,
                    "operator_name": resolve_airline_name(op_icao),
                    "is_acmi": is_acmi,
                    "route": route,
                    "dep_time": dep_time,
                    "arr_time": arr_time,
                    "bh": bh,
                })

                if is_acmi and op_icao:
                    acmi_bh += bh
                    acmi_flights += 1
                    if op_icao not in clients_seen:
                        clients_seen[op_icao] = {"flights": 0, "bh": 0.0}
                    clients_seen[op_icao]["flights"] += 1
                    clients_seen[op_icao]["bh"] += bh

                    # Build client map
                    group = op.get("group", op["name"])
                    if op_icao not in client_map:
                        client_map[op_icao] = {}
                    if group not in client_map[op_icao]:
                        client_map[op_icao][group] = {"flights": 0, "bh": 0.0, "aircraft": set()}
                    client_map[op_icao][group]["flights"] += 1
                    client_map[op_icao][group]["bh"] = round(client_map[op_icao][group]["bh"] + bh, 1)
                    client_map[op_icao][group]["aircraft"].add(reg)

            clients_list = [
                {
                    "icao": k,
                    "name": resolve_airline_name(k),
                    "flights": v["flights"],
                    "bh": round(v["bh"], 1),
                }
                for k, v in sorted(clients_seen.items(), key=lambda x: -x[1]["bh"])
            ]

            total_bh = round(total_bh, 1)
            acmi_bh  = round(acmi_bh, 1)

            summary_str = f"{len(flights)} flights / {total_bh} BH"
            if acmi_flights:
                summary_str += f" / {acmi_flights} ACMI flights ({acmi_bh} BH)"
            print(summary_str)

            results.append({
                "registration": reg,
                "type": ac["type"],
                "owner_icao": op["icao"],
                "owner_name": op["name"],
                "group": op.get("group", op["name"]),
                "total_flights": len(flights),
                "total_bh": total_bh,
                "acmi_flights": acmi_flights,
                "acmi_bh": acmi_bh,
                "clients": clients_list,
                "routes": routes,
                "flight_log": flight_log,
            })

    # Serialize client_map sets to lists, add full names
    client_map_serializable = {}
    for client_icao, providers in client_map.items():
        client_map_serializable[client_icao] = {
            "name": resolve_airline_name(client_icao),
            "providers": {},
        }
        for group, data in providers.items():
            client_map_serializable[client_icao]["providers"][group] = {
                "flights": data["flights"],
                "bh": data["bh"],
                "aircraft_count": len(data["aircraft"]),
                "aircraft": sorted(list(data["aircraft"])),
            }

    # Operator summaries
    op_summaries = {}
    for r in results:
        g = r["group"]
        if g not in op_summaries:
            op_summaries[g] = {"total_flights": 0, "total_bh": 0.0, "acmi_flights": 0, "acmi_bh": 0.0, "active_aircraft": 0}
        op_summaries[g]["total_flights"]  += r["total_flights"]
        op_summaries[g]["total_bh"]        = round(op_summaries[g]["total_bh"] + r["total_bh"], 1)
        op_summaries[g]["acmi_flights"]   += r["acmi_flights"]
        op_summaries[g]["acmi_bh"]         = round(op_summaries[g]["acmi_bh"] + r["acmi_bh"], 1)
        if r["total_flights"] > 0:
            op_summaries[g]["active_aircraft"] += 1

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "report_date": report_date,
        "interval_from": f"{report_date} 00:01",
        "interval_to": f"{report_date} 23:59",
        "operator_summaries": op_summaries,
        "client_map": client_map_serializable,
        "fleet": results,
    }

    with open(HISTORY, "w") as f:
        json.dump(output, f, indent=2)

    total_bh_all   = round(sum(r["total_bh"] for r in results), 1)
    total_acmi_bh  = round(sum(r["acmi_bh"] for r in results), 1)
    total_flights  = sum(r["total_flights"] for r in results)
    print(f"\nHistory done — {total_flights} flights / {total_bh_all} BH total / {total_acmi_bh} BH on ACMI")

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not FR24_TOKEN:
        print("ERROR: FR24_API_KEY not set")
        raise SystemExit(1)

    with open(REGISTRY) as f:
        registry = json.load(f)

    total = sum(len(op["aircraft"]) for op in registry["operators"])
    print(f"ACMI Intel Fetcher — {total} aircraft across {len(registry['operators'])} operators")
    print(f"Estimated time: ~{total * DELAY * 3 / 60:.0f} minutes\n")

    run_snapshot(registry)
    run_history(registry)

    print("\n✓ All done. acmi_data.json + acmi_history.json updated.")

if __name__ == "__main__":
    main()
