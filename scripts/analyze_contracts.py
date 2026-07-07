#!/usr/bin/env python3
"""
analyze_contracts.py — Infers ACMI wet-lease contract windows and detects
idle/grounded aircraft from already-collected history data.

ZERO FR24 API CALLS. Reads data/acmi_history.json (already fetched by
fetch_acmi.py) and writes data/contract_windows.json.

Run this AFTER fetch_acmi.py in the daily workflow — it only touches
local JSON files, so it never consumes FR24 credits.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────
HISTORY_PATH = Path("data/acmi_history.json")
OUTPUT_PATH  = Path("data/contract_windows.json")

GAP_TOLERANCE_DAYS = 3     # max calendar-day gap between ACMI-active days
                           # for the same client before we call it a new
                           # contract window (covers weekends / rest days)
IDLE_THRESHOLD_DAYS = 3    # consecutive days with zero total_flights before
                           # flagging an aircraft as "possibly idle/grounded"
LOOKBACK_FOR_BASELINE = 14 # days of prior activity used to compute an
                           # aircraft's "normal" BH before it went idle


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def load_history():
    if not HISTORY_PATH.exists():
        print(f"ERROR: {HISTORY_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    raw = json.loads(HISTORY_PATH.read_text())
    days = raw.get("days", raw if isinstance(raw, list) else [])
    days = [d for d in days if d.get("report_date")]
    days.sort(key=lambda d: d["report_date"])
    return days


def build_timelines(days):
    """
    Returns:
      client_timeline: {(registration, client_key): {date: {"bh":.., "client_name":..}}}
      reg_meta: {registration: {"owner_name":.., "group":..}}
      reg_daily_activity: {registration: {date: {"total_flights":.., "total_bh":..}}}
      all_dates: sorted list of date objects present in history
    """
    client_timeline = defaultdict(dict)
    reg_meta = {}
    reg_daily_activity = defaultdict(dict)
    all_dates = []

    for day in days:
        d = parse_date(day["report_date"])
        all_dates.append(d)
        for entry in day.get("fleet", []):
            reg = entry.get("registration")
            if not reg:
                continue
            reg_meta.setdefault(reg, {
                "owner_name": entry.get("owner_name", ""),
                "group": entry.get("group", entry.get("owner_name", "")),
            })
            reg_daily_activity[reg][d] = {
                "total_flights": entry.get("total_flights", 0),
                "total_bh": entry.get("total_bh", 0),
            }
            for c in entry.get("clients", []) or []:
                client_key = c.get("icao") or c.get("name") or "UNKNOWN"
                client_timeline[(reg, client_key)][d] = {
                    "bh": c.get("bh", 0),
                    "client_name": c.get("name", client_key),
                }

    all_dates = sorted(set(all_dates))
    return client_timeline, reg_meta, reg_daily_activity, all_dates


def segment_windows(dates_bh, gap_tolerance):
    """
    dates_bh: {date: {"bh":.., "client_name":..}}
    Returns list of windows: [{start_date, end_date, days_active, total_bh, max_internal_gap_days}]
    """
    dates = sorted(dates_bh.keys())
    if not dates:
        return []
    windows = []
    cur_dates = [dates[0]]
    for prev, cur in zip(dates, dates[1:]):
        gap = (cur - prev).days
        if gap <= gap_tolerance:
            cur_dates.append(cur)
        else:
            windows.append(cur_dates)
            cur_dates = [cur]
    windows.append(cur_dates)

    out = []
    for w in windows:
        total_bh = round(sum(dates_bh[d]["bh"] for d in w), 1)
        gaps = [(b - a).days for a, b in zip(w, w[1:])]
        out.append({
            "start_date": w[0].isoformat(),
            "end_date": w[-1].isoformat(),
            "days_active": len(w),
            "span_days": (w[-1] - w[0]).days + 1,
            "total_bh": total_bh,
            "max_internal_gap_days": max(gaps) if gaps else 0,
        })
    return out


def analyze(days, gap_tolerance=GAP_TOLERANCE_DAYS,
            idle_threshold=IDLE_THRESHOLD_DAYS,
            baseline_days=LOOKBACK_FOR_BASELINE):

    client_timeline, reg_meta, reg_daily_activity, all_dates = build_timelines(days)
    if not all_dates:
        return {"generated_at": None, "contracts": [], "idle_aircraft": [],
                "note": "No history data available yet."}

    latest_date = all_dates[-1]

    # ── Contract windows ────────────────────────────────────────────
    contracts = []
    for (reg, client_key), dates_bh in client_timeline.items():
        windows = segment_windows(dates_bh, gap_tolerance)
        meta = reg_meta.get(reg, {})
        client_name = next(iter(dates_bh.values()))["client_name"]
        for w in windows:
            end_d = parse_date(w["end_date"])
            status = "active" if (latest_date - end_d).days <= gap_tolerance else "ended"
            days_since_last_seen = (latest_date - end_d).days
            avg_bh = round(w["total_bh"] / w["days_active"], 1) if w["days_active"] else 0
            continuity_pct = round(w["days_active"] / w["span_days"] * 100, 1) if w["span_days"] else 0
            contracts.append({
                "registration": reg,
                "owner_name": meta.get("owner_name", ""),
                "group": meta.get("group", ""),
                "client_icao": client_key,
                "client_name": client_name,
                "start_date": w["start_date"],
                "end_date": w["end_date"],
                "status": status,
                "days_active": w["days_active"],
                "span_days": w["span_days"],
                "continuity_pct": continuity_pct,
                "total_bh": w["total_bh"],
                "avg_bh_per_active_day": avg_bh,
                "max_internal_gap_days": w["max_internal_gap_days"],
                "days_since_last_seen": days_since_last_seen,
            })

    contracts.sort(key=lambda c: (c["status"] != "active", -c["total_bh"]))

    # ── Idle / possibly-grounded aircraft ───────────────────────────
    idle_aircraft = []
    for reg, activity in reg_daily_activity.items():
        dates_sorted = sorted(activity.keys())
        if not dates_sorted:
            continue
        last_active_date = None
        for d in reversed(dates_sorted):
            if activity[d]["total_flights"] > 0:
                last_active_date = d
                break
        if last_active_date is None:
            continue
        days_idle = (latest_date - last_active_date).days
        if days_idle < idle_threshold:
            continue
        baseline_start = last_active_date - timedelta(days=baseline_days)
        baseline_vals = [activity[d]["total_bh"] for d in dates_sorted
                          if baseline_start <= d <= last_active_date and activity[d]["total_flights"] > 0]
        prior_avg_bh = round(sum(baseline_vals) / len(baseline_vals), 1) if baseline_vals else 0
        meta = reg_meta.get(reg, {})
        idle_aircraft.append({
            "registration": reg,
            "owner_name": meta.get("owner_name", ""),
            "group": meta.get("group", ""),
            "last_flight_date": last_active_date.isoformat(),
            "days_idle": days_idle,
            "prior_avg_bh": prior_avg_bh,
        })

    idle_aircraft.sort(key=lambda a: -a["days_idle"])

    return {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "date_range": {"from": all_dates[0].isoformat(), "to": latest_date.isoformat()},
        "days_of_history": len(all_dates),
        "gap_tolerance_days": gap_tolerance,
        "idle_threshold_days": idle_threshold,
        "contracts": contracts,
        "idle_aircraft": idle_aircraft,
        "note": ("Contract windows and idle flags are inferred purely from "
                 "already-collected daily history (fleet clients data). No "
                 "additional FR24 API calls are made. Absence from ACMI client "
                 "data does not necessarily mean an aircraft is grounded — it "
                 "may be flying non-ACMI/own-ops routes not attributed to a "
                 "client."),
    }


def main():
    days = load_history()
    if len(days) < 2:
        print(f"Only {len(days)} day(s) of history — need at least 2 for "
              f"meaningful contract inference. Writing empty result.")
    result = analyze(days)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"Wrote {len(result.get('contracts', []))} contract windows and "
          f"{len(result.get('idle_aircraft', []))} idle-aircraft flags to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
