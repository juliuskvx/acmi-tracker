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
import re
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
    # European LCCs & majors
    "EWG": "Eurowings",
    "EW":  "Eurowings",
    "EWD": "Eurowings Discover",
    "EZY": "easyJet",
    "EZS": "easyJet Switzerland",
    "RYR": "Ryanair",
    "FR":  "Ryanair",
    "WZZ": "Wizz Air",
    "W6":  "Wizz Air",
    "VLG": "Vueling",
    "IBE": "Iberia",
    "AEA": "Air Europa",
    "AP7": "Air Europa",
    "VOE": "Volotea",
    "NAX": "Norwegian",
    "DY":  "Norwegian",
    # TUI group
    "TCX": "TUI Airways",
    "TOM": "TUI Airways",
    "TUI": "TUI fly",
    "TFL": "TUI fly Nordic",
    "TBM": "TUI fly Belgium",
    "TFD": "TUI fly Deutschland",
    "TFN": "TUI fly Netherlands",
    # Network carriers
    "DLH": "Lufthansa",
    "LH":  "Lufthansa",
    "SWR": "Swiss",
    "LX":  "Swiss",
    "AUA": "Austrian Airlines",
    "OS":  "Austrian Airlines",
    "BEL": "Brussels Airlines",
    "SN":  "Brussels Airlines",
    "AFR": "Air France",
    "AF":  "Air France",
    "KLM": "KLM",
    "KL":  "KLM",
    "SAS": "SAS Scandinavian",
    "SK":  "SAS Scandinavian",
    "FIN": "Finnair",
    "AY":  "Finnair",
    "LOT": "LOT Polish Airlines",
    "LO":  "LOT Polish Airlines",
    "TAP": "TAP Air Portugal",
    "TP":  "TAP Air Portugal",
    "EIN": "Aer Lingus",
    "EI":  "Aer Lingus",
    "ICE": "Icelandair",
    "FI":  "Icelandair",
    # Charter / leisure
    "CFG": "Condor",
    "TRA": "Transavia",
    "HV":  "Transavia",
    "SCC": "Sunclass Airlines",
    "EXS": "Jet2",
    "LS":  "Jet2",
    "CAI": "Corendon Airlines",
    "XC":  "Corendon Airlines",
    "SXS": "SunExpress",
    "XQ":  "SunExpress",
    "PGT": "Pegasus Airlines",
    "PC":  "Pegasus Airlines",
    "THY": "Turkish Airlines",
    "TK":  "Turkish Airlines",
    "FHY": "Freebird Airlines",
    "PVG": "Privilege Style",
    "NOS": "Neos",
    "BPA": "Blue Panorama",
    # North Africa / Middle East
    "DAH": "Air Algérie",
    "AH":  "Air Algérie",
    "TAR": "Tunisair",
    "TU":  "Tunisair",
    "LBT": "Nouvelair",
    "ABY": "Air Arabia",
    "G9":  "Air Arabia",
    "ETD": "Etihad Airways",
    "EY":  "Etihad Airways",
    # Israel
    "AIZ": "Arkia Israeli Airlines",
    "IZ":  "Arkia Israeli Airlines",
    "ISR": "Israir",
    # Scandinavia / Nordics
    "NVD": "Novair",
    "NVR": "Novair",
    # Eastern Europe / FSU
    "AHY": "Azerbaijan Airlines",
    "J2":  "Azerbaijan Airlines",
    "PBD": "Pobeda",
    "SBI": "S7 Airlines",
    "SVR": "Ural Airlines",
    # Atlantic / island
    "SAT": "Azores Airlines",
    "APO": "Azores Airlines",
    "ARU": "Aruba Airlines",
    # Malta
    "AMC": "Air Malta",
    "KM":  "Air Malta",
    "MAT": "Malta Air",
    # France regional
    "MLH": "Air Alsace",
    # Africa
    "SZN": "Air Senegal",
    "CRC": "Camair-Co",
    "ASL": "ASL Airlines",
    # UK
    "EFW": "BA Euroflyer",
    "KRH": "UK Royal Flight",
    # Cargo / specialist
    "BCS": "EAT Leipzig",
    # Hungary
    "TVL": "Travel Service",
    # ACMI operators (own registry — kept for fallback)
    "AVE": "Avion Express",
    "MLT": "Avion Express Malta",
    "HST": "Heston Airlines",
    "HOT": "Valletta Airlines",
    "GJT": "GetJet Airlines",
    "GJM": "GetJet Airlines Malta",
    "AWC": "Titan Airways",
    "ZT":  "Titan Airways",
    "TMT": "Titan Airways Malta",
    "ENT": "Enter Air",
    "AXQ": "AirExplore",
    "TVS": "Smartwings",
    "QS":  "Smartwings",
    "TVQ": "Travel Service Slovakia",
    # Verified 2026-07-09 during contract-window data cleanup
    "BBG": "Bluebird Airways",
    "JAF": "TUI fly Belgium",
    "SYR": "Syrian Arab Airlines",
}

# ── API helper ────────────────────────────────────────────────────────────────

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

# ── FR24 queries ──────────────────────────────────────────────────────────────

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

# ── Helpers ───────────────────────────────────────────────────────────────────

_CALLSIGN_PREFIX_RE = re.compile(r'^[A-Z]+')

def build_group_maps(registry):
    """
    Per-group sets of ICAO codes and lowercase names. Used so detect_operator
    can recognise when a flight's callsign belongs to the aircraft's OWN
    operator group (a sibling AOC, or the same airline under an IATA-format
    callsign) rather than an external ACMI client — even though the raw code
    doesn't match this specific aircraft's single owner_icao.
    """
    group_icaos = {}
    group_names = {}
    for op in registry["operators"]:
        grp = op.get("group", op["name"])
        group_icaos.setdefault(grp, set()).add(op["icao"].upper())
        group_names.setdefault(grp, set()).add(op["name"].strip().lower())
    return group_icaos, group_names

def detect_operator(callsign, registration, owner_icao, group_icaos, group_names):
    """
    Returns (op_icao, is_acmi).

    - (None, False) if callsign is missing/too short, or if the callsign is
      just the aircraft's own tail number (common on ferry/positioning
      flights with no ATC callsign assigned) — there is no client here.
    - Extracts the airline-code prefix as the callsign's actual leading run
      of letters (2 or 3 chars, whichever it naturally has before its
      digits) rather than guessing a fixed length. This correctly reads
      IATA-format callsigns like "AH1125" as "AH" instead of mangling it to
      "AH1", without ever misreading a genuine 3-letter code (e.g.
      "KMM612") as a coincidentally-matching 2-letter code from a different
      airline (an earlier version of this fix had exactly that bug). If the
      raw 3-character slice is already a known AIRLINE_NAMES entry (some
      operators use non-standard digit-containing codes, e.g. "AP7" for
      Air Europa in this fleet's data), that verified mapping always wins.
    - Treats any code/name belonging to the aircraft's own operator GROUP
      (not just its single owner_icao) as non-ACMI. This covers intra-group
      AOC swaps (Heston <-> Valletta, GetJet <-> GetJet Malta) and
      same-airline IATA-vs-ICAO callsign mismatches (Titan's "ZT" vs
      "AWC"/"TMT") that were previously mis-flagged as external clients.
    """
    if not callsign or len(callsign) < 2:
        return None, False

    cs = callsign.upper().strip()
    reg_clean = registration.upper().replace("-", "")
    if cs == reg_clean:
        return None, False  # tail number used as callsign — ferry/positioning, no client

    cs3 = cs[:3]
    if cs3 in AIRLINE_NAMES:
        op_icao = cs3  # respects previously-verified non-standard codes (e.g. "AP7")
    else:
        m = _CALLSIGN_PREFIX_RE.match(cs)
        alpha_prefix = m.group(0) if m else ""
        op_icao = alpha_prefix if 2 <= len(alpha_prefix) <= 3 else cs3

    resolved_name = resolve_airline_name(op_icao).strip().lower()
    same_group = (op_icao.upper() in group_icaos) or (resolved_name in group_names)
    is_acmi = (not same_group) and (op_icao.upper() != owner_icao.upper())
    return op_icao, is_acmi

def resolve_airline_name(icao_code):
    if not icao_code:
        return icao_code
    return AIRLINE_NAMES.get(icao_code.upper(), icao_code)

def calc_block_hours(dep_time, arr_time):
    """Calculate block hours to nearest 0.1h from ISO timestamp strings."""
    if not dep_time or not arr_time:
        return 0.0
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        if isinstance(dep_time, (int, float)):
            dep = datetime.fromtimestamp(dep_time, tz=timezone.utc)
        else:
            dep = datetime.strptime(dep_time, fmt)
        if isinstance(arr_time, (int, float)):
            arr = datetime.fromtimestamp(arr_time, tz=timezone.utc)
        else:
            arr = datetime.strptime(arr_time, fmt)
        diff_minutes = (arr - dep).total_seconds() / 60
        if diff_minutes <= 0:
            return 0.0
        return round(diff_minutes / 60, 1)
    except Exception as e:
        print(f"  BH calc error: {e} | dep={dep_time} arr={arr_time}")
        return 0.0

def now_vilnius():
    """Return current datetime in Vilnius time (UTC+3 EEST in summer)."""
    lt_offset = timedelta(hours=3)
    return datetime.now(timezone.utc) + lt_offset

def vilnius_timestamp():
    """Return current Vilnius time as a readable string, e.g. '2026-06-18 10:07 LT'."""
    return now_vilnius().strftime("%Y-%m-%d %H:%M LT")

def lt_day_window(offset_days=0):
    lt_offset = timedelta(hours=3)
    now_utc   = datetime.now(timezone.utc)
    now_lt    = now_utc + lt_offset + timedelta(days=offset_days)
    day_lt    = now_lt.replace(hour=0, minute=1, second=0, microsecond=0)
    end_lt    = now_lt.replace(hour=23, minute=59, second=0, microsecond=0)
    utc_from  = (day_lt - lt_offset).strftime("%Y-%m-%dT%H:%M:%SZ")
    utc_to    = (end_lt - lt_offset).strftime("%Y-%m-%dT%H:%M:%SZ")
    return now_lt.strftime("%Y-%m-%d"), utc_from, utc_to

# ── Phase 1: Live Snapshot ────────────────────────────────────────────────────

def run_snapshot(registry):
    print("\n" + "="*60)
    print("PHASE 1 — Live Snapshot")
    print("="*60)

    now_lt    = now_vilnius()
    # report_date is YESTERDAY — the last completed full day
    yesterday = (now_lt - timedelta(days=1)).strftime("%Y-%m-%d")
    report_date = yesterday

    total   = sum(len(op["aircraft"]) for op in registry["operators"])
    fleet   = []
    queried = acmi_count = own_count = ground_count = 0
    group_icaos_all, group_names_all = build_group_maps(registry)

    print(f"Querying {total} aircraft...\n")

    for op in registry["operators"]:
        if not op["aircraft"]:
            continue
        print(f"{op['name']} ({op['icao']}) — {len(op['aircraft'])} aircraft")
        this_icaos = group_icaos_all.get(op.get("group", op["name"]), {op["icao"].upper()})
        this_names = group_names_all.get(op.get("group", op["name"]), {op["name"].strip().lower()})
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
                callsign         = live.get("callsign", "")
                op_icao, is_acmi = detect_operator(callsign, reg, op["icao"], this_icaos, this_names)
                entry.update({
                    "callsign": callsign,
                    "current_operator_icao": op_icao,
                    "current_operator_name": resolve_airline_name(op_icao),
                    "last_seen": vilnius_timestamp(),
                    "latitude": live.get("lat"),
                    "longitude": live.get("lon"),
                    "altitude": live.get("alt"),
                    "speed": live.get("spd"),
                    "heading": live.get("track"),
                    "last_flight": callsign,
                    "status": "acmi_active" if is_acmi else "own_ops",
                })
                orig = live.get("orig_iata") or live.get("orig_icao", "")
                dest = live.get("dest_iata") or live.get("dest_icao_actual") or live.get("dest_icao", "")
                if orig and dest:
                    entry["last_route"] = f"{orig}-{dest}"
                if is_acmi:
                    acmi_count += 1
                    print(f"ACMI → {op_icao} / {resolve_airline_name(op_icao)} ({callsign})")
                else:
                    own_count += 1
                    print(f"own ops ({callsign})")
            else:
                # Fallback: today's flight summary
                _, utc_from, utc_to = lt_day_window(0)
                summary = get_day_flights(reg, utc_from, utc_to)
                time.sleep(DELAY)
                if summary:
                    last = summary[0]
                    entry["last_flight"] = last.get("callsign")
                    entry["last_seen"]   = last.get("datetime_landed") or last.get("datetime_takeoff")
                    orig = last.get("orig_iata") or last.get("orig_icao", "")
                    dest = last.get("dest_iata") or last.get("dest_icao_actual") or last.get("dest_icao", "")
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
        "last_updated": vilnius_timestamp(),
        "report_date":  report_date,
        "interval_from": f"{report_date} 00:01",
        "interval_to":   f"{report_date} 23:59",
        "summary": {
            "total_aircraft": queried,
            "acmi_active":    acmi_count,
            "own_ops":        own_count,
            "on_ground":      ground_count,
        },
        "fleet": fleet,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SNAPSHOT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSnapshot done — {acmi_count} ACMI active, {own_count} own ops, {ground_count} on ground")
    return output

# ── Phase 2: Daily History Report ─────────────────────────────────────────────

def run_history(registry):
    print("\n" + "="*60)
    print("PHASE 2 — Daily History Report (yesterday)")
    print("="*60)

    report_date, utc_from, utc_to = lt_day_window(-1)
    print(f"Reporting period: {report_date} 00:01 → 23:59 LT")
    print(f"UTC window: {utc_from} → {utc_to}\n")

    total      = sum(len(op["aircraft"]) for op in registry["operators"])
    results    = []
    queried    = 0
    client_map = {}
    group_icaos_all, group_names_all = build_group_maps(registry)

    for op in registry["operators"]:
        if not op["aircraft"]:
            continue
        print(f"{op['name']} ({op['icao']}) — {len(op['aircraft'])} aircraft")
        this_icaos = group_icaos_all.get(op.get("group", op["name"]), {op["icao"].upper()})
        this_names = group_names_all.get(op.get("group", op["name"]), {op["name"].strip().lower()})

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
                    "type":         ac["type"],
                    "owner_icao":   op["icao"],
                    "owner_name":   op["name"],
                    "group":        op.get("group", op["name"]),
                    "total_flights": 0,
                    "total_bh":     0.0,
                    "acmi_flights": 0,
                    "acmi_bh":      0.0,
                    "clients":      [],
                    "routes":       [],
                    "flight_log":   [],
                })
                continue

            total_bh     = 0.0
            acmi_bh      = 0.0
            acmi_flights = 0
            clients_seen = {}
            routes       = []
            flight_log   = []

            for fl in flights:
                callsign = fl.get("callsign", "")
                dep_time = fl.get("datetime_takeoff")
                arr_time = fl.get("datetime_landed")
                orig     = fl.get("orig_iata") or fl.get("orig_icao", "")
                dest     = fl.get("dest_iata") or fl.get("dest_icao_actual") or fl.get("dest_icao", "")
                bh       = calc_block_hours(dep_time, arr_time)
                op_icao, is_acmi = detect_operator(callsign, reg, op["icao"], this_icaos, this_names)

                total_bh += bh
                route = f"{orig}-{dest}" if orig and dest else None
                if route and route not in routes:
                    routes.append(route)

                flight_log.append({
                    "callsign":      callsign,
                    "operator_icao": op_icao,
                    "operator_name": resolve_airline_name(op_icao),
                    "is_acmi":       is_acmi,
                    "route":         route,
                    "dep_time":      dep_time,
                    "arr_time":      arr_time,
                    "bh":            bh,
                })

                if is_acmi and op_icao:
                    acmi_bh      += bh
                    acmi_flights += 1
                    if op_icao not in clients_seen:
                        clients_seen[op_icao] = {"flights": 0, "bh": 0.0}
                    clients_seen[op_icao]["flights"] += 1
                    clients_seen[op_icao]["bh"]      += bh

                    group = op.get("group", op["name"])
                    if op_icao not in client_map:
                        client_map[op_icao] = {}
                    if group not in client_map[op_icao]:
                        client_map[op_icao][group] = {"flights": 0, "bh": 0.0, "aircraft": set()}
                    client_map[op_icao][group]["flights"] += 1
                    client_map[op_icao][group]["bh"]       = round(client_map[op_icao][group]["bh"] + bh, 1)
                    client_map[op_icao][group]["aircraft"].add(reg)

            clients_list = [
                {
                    "icao":    k,
                    "name":    resolve_airline_name(k),
                    "flights": v["flights"],
                    "bh":      round(v["bh"], 1),
                }
                for k, v in sorted(clients_seen.items(), key=lambda x: -x[1]["bh"])
            ]

            total_bh = round(total_bh, 1)
            acmi_bh  = round(acmi_bh,  1)

            summary_str = f"{len(flights)} flights / {total_bh} BH"
            if acmi_flights:
                summary_str += f" / {acmi_flights} ACMI flights ({acmi_bh} BH)"
            print(summary_str)

            results.append({
                "registration":  reg,
                "type":          ac["type"],
                "owner_icao":    op["icao"],
                "owner_name":    op["name"],
                "group":         op.get("group", op["name"]),
                "total_flights": len(flights),
                "total_bh":      total_bh,
                "acmi_flights":  acmi_flights,
                "acmi_bh":       acmi_bh,
                "clients":       clients_list,
                "routes":        routes,
                "flight_log":    flight_log,
            })

    # Serialize client_map
    client_map_serializable = {}
    for client_icao, providers in client_map.items():
        client_map_serializable[client_icao] = {
            "name":      resolve_airline_name(client_icao),
            "providers": {},
        }
        for group, data in providers.items():
            client_map_serializable[client_icao]["providers"][group] = {
                "flights":        data["flights"],
                "bh":             data["bh"],
                "aircraft_count": len(data["aircraft"]),
                "aircraft":       sorted(list(data["aircraft"])),
            }

    # Operator summaries
    op_summaries = {}
    for r in results:
        g = r["group"]
        if g not in op_summaries:
            op_summaries[g] = {"total_flights": 0, "total_bh": 0.0, "acmi_flights": 0, "acmi_bh": 0.0, "active_aircraft": 0}
        op_summaries[g]["total_flights"] += r["total_flights"]
        op_summaries[g]["total_bh"]       = round(op_summaries[g]["total_bh"] + r["total_bh"], 1)
        op_summaries[g]["acmi_flights"]  += r["acmi_flights"]
        op_summaries[g]["acmi_bh"]        = round(op_summaries[g]["acmi_bh"]  + r["acmi_bh"],  1)
        if r["total_flights"] > 0:
            op_summaries[g]["active_aircraft"] += 1

    today_entry = {
        "last_updated":       vilnius_timestamp(),
        "report_date":        report_date,
        "interval_from":      f"{report_date} 00:01",
        "interval_to":        f"{report_date} 23:59",
        "operator_summaries": op_summaries,
        "client_map":         client_map_serializable,
        "fleet":              results,
    }

    # ── Append to multi-day history array (dedup by report_date) ──────────────
    # File format: { "days": [ {...}, {...}, ... ] }  newest first
    existing_days = []
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY) as f:
                raw = json.load(f)
            if isinstance(raw.get("days"), list):
                existing_days = raw["days"]
            elif raw.get("report_date"):
                # Migrate old single-day format
                existing_days = [raw]
                print("  Migrated old single-day history format to multi-day array")
        except Exception as e:
            print(f"  WARNING: could not read existing history: {e}")

    # Remove any entry for the same report_date (idempotent re-runs)
    existing_days = [d for d in existing_days if d.get("report_date") != report_date]
    existing_days.append(today_entry)
    # Sort newest first
    existing_days.sort(key=lambda d: d["report_date"], reverse=True)

    output = {"days": existing_days}

    with open(HISTORY, "w") as f:
        json.dump(output, f, indent=2)

    total_bh_all  = round(sum(r["total_bh"]  for r in results), 1)
    total_acmi_bh = round(sum(r["acmi_bh"]   for r in results), 1)
    total_flights = sum(r["total_flights"]    for r in results)
    n_days_total  = len(existing_days)
    print(f"\nHistory done — {total_flights} flights / {total_bh_all} BH total / {total_acmi_bh} BH on ACMI")
    print(f"History file now contains {n_days_total} day(s)")

# ── Main ──────────────────────────────────────────────────────────────────────

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
