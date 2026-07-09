#!/usr/bin/env python3
"""
backfill_history.py — ONE-TIME reprocessing of existing acmi_history.json
using the corrected detect_operator logic (intra-group / ferry-callsign /
IATA-format fixes shipped in fetch_acmi.py on 2026-07-09).

Re-derives is_acmi / operator_icao / operator_name for every already-
collected flight from its stored raw callsign — NO new FR24 API calls.
Rebuilds each day's fleet[].clients, client_map, and operator_summaries
from that corrected attribution. total_bh, total_flights, routes, and
flight timestamps are untouched (they don't depend on client attribution).

Run this ONCE (via the one-off backfill.yml workflow), commit the result,
then feel free to delete this script and that workflow file — it's not
part of the daily pipeline.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_acmi import build_group_maps, detect_operator, resolve_airline_name

DATA_DIR = Path(__file__).parent.parent / "data"
HISTORY  = DATA_DIR / "acmi_history.json"
REGISTRY = DATA_DIR / "fleet_registry.json"


def main():
    registry = json.loads(REGISTRY.read_text())
    history  = json.loads(HISTORY.read_text())

    group_icaos_all, group_names_all = build_group_maps(registry)
    reg_info = {}  # registration -> (owner_icao, group)
    for op in registry["operators"]:
        grp = op.get("group", op["name"])
        for ac in op["aircraft"]:
            reg_info[ac["registration"]] = (op["icao"], grp)

    days = history.get("days", [])
    total_changed = 0

    for day in days:
        client_map   = {}  # client_icao -> {group: {flights, bh, aircraft:set()}}
        op_summaries = {}

        for entry in day.get("fleet", []):
            reg = entry.get("registration")
            if reg not in reg_info:
                continue
            owner_icao, group = reg_info[reg]
            this_icaos = group_icaos_all.get(group, {owner_icao.upper()})
            this_names = group_names_all.get(group, set())

            acmi_bh      = 0.0
            acmi_flights = 0
            clients_seen = {}

            for fl in entry.get("flight_log", []):
                callsign = fl.get("callsign", "")
                old_icao = fl.get("operator_icao")
                old_acmi = fl.get("is_acmi")

                new_icao, new_acmi = detect_operator(callsign, reg, owner_icao, this_icaos, this_names)
                if new_icao != old_icao or new_acmi != old_acmi:
                    total_changed += 1

                fl["operator_icao"] = new_icao
                fl["operator_name"] = resolve_airline_name(new_icao) if new_icao else None
                fl["is_acmi"]       = new_acmi

                bh = fl.get("bh", 0.0)
                if new_acmi and new_icao:
                    acmi_bh      += bh
                    acmi_flights += 1
                    if new_icao not in clients_seen:
                        clients_seen[new_icao] = {"flights": 0, "bh": 0.0}
                    clients_seen[new_icao]["flights"] += 1
                    clients_seen[new_icao]["bh"]       += bh

                    if new_icao not in client_map:
                        client_map[new_icao] = {}
                    if group not in client_map[new_icao]:
                        client_map[new_icao][group] = {"flights": 0, "bh": 0.0, "aircraft": set()}
                    client_map[new_icao][group]["flights"] += 1
                    client_map[new_icao][group]["bh"]       = round(client_map[new_icao][group]["bh"] + bh, 1)
                    client_map[new_icao][group]["aircraft"].add(reg)

            entry["acmi_bh"]      = round(acmi_bh, 1)
            entry["acmi_flights"] = acmi_flights
            entry["clients"] = [
                {"icao": k, "name": resolve_airline_name(k), "flights": v["flights"], "bh": round(v["bh"], 1)}
                for k, v in sorted(clients_seen.items(), key=lambda x: -x[1]["bh"])
            ]

            if group not in op_summaries:
                op_summaries[group] = {"total_flights": 0, "total_bh": 0.0, "acmi_flights": 0, "acmi_bh": 0.0, "active_aircraft": 0}
            op_summaries[group]["total_flights"] += entry.get("total_flights", 0)
            op_summaries[group]["total_bh"]       = round(op_summaries[group]["total_bh"] + entry.get("total_bh", 0.0), 1)
            op_summaries[group]["acmi_flights"]  += acmi_flights
            op_summaries[group]["acmi_bh"]        = round(op_summaries[group]["acmi_bh"] + acmi_bh, 1)
            if entry.get("total_flights", 0) > 0:
                op_summaries[group]["active_aircraft"] += 1

        day["client_map"] = {
            icao: {
                "name": resolve_airline_name(icao),
                "providers": {
                    grp: {
                        "flights": data["flights"],
                        "bh": data["bh"],
                        "aircraft_count": len(data["aircraft"]),
                        "aircraft": sorted(data["aircraft"]),
                    }
                    for grp, data in providers.items()
                },
            }
            for icao, providers in client_map.items()
        }
        day["operator_summaries"] = op_summaries

    HISTORY.write_text(json.dumps(history, indent=2))
    print(f"Backfill complete — {total_changed} flight classifications corrected across {len(days)} days.")
    print("Next: run analyze_contracts.py to regenerate contract_windows.json from the cleaned history.")


if __name__ == "__main__":
    main()
