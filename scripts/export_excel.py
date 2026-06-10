#!/usr/bin/env python3
"""
export_excel.py — ACMI Tracker daily Excel logger
Appends today's snapshot + history data to data/acmi_log.xlsx
Run this after fetch_acmi.py completes.
"""

import json
import os
from datetime import datetime, timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

DATA_DIR = os.path.join(os.path.dirname(__file__), "../data")
SNAPSHOT = os.path.join(DATA_DIR, "acmi_data.json")
HISTORY  = os.path.join(DATA_DIR, "acmi_history.json")
EXCEL    = os.path.join(DATA_DIR, "acmi_log.xlsx")

# ── Styles ────────────────────────────────────────────────────────────────────

HEADER_FILL   = PatternFill("solid", start_color="0D1320", end_color="0D1320")
HEADER_FONT   = Font(name="Arial", bold=True, color="00D4FF", size=10)
SUBHEAD_FILL  = PatternFill("solid", start_color="111827", end_color="111827")
SUBHEAD_FONT  = Font(name="Arial", bold=True, color="E2E8F0", size=9)
NORMAL_FONT   = Font(name="Arial", size=9)
ACMI_FONT     = Font(name="Arial", size=9, color="00D4FF")
GREEN_FONT    = Font(name="Arial", size=9, color="00CC66")
AMBER_FONT    = Font(name="Arial", size=9, color="FFAA00")
MUTED_FONT    = Font(name="Arial", size=9, color="64748B")
DATE_FILL     = PatternFill("solid", start_color="0A1628", end_color="0A1628")
DATE_FONT     = Font(name="Arial", bold=True, color="A78BFA", size=9)
THIN_BORDER   = Border(bottom=Side(style="thin", color="1E2D42"))

CENTER = Alignment(horizontal="center", vertical="center")
LEFT   = Alignment(horizontal="left",   vertical="center")

def style_header_row(ws, row, cols):
    for col in range(1, cols + 1):
        c = ws.cell(row=row, column=col)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = CENTER
        c.border = THIN_BORDER

def style_subheader_row(ws, row, cols):
    for col in range(1, cols + 1):
        c = ws.cell(row=row, column=col)
        c.fill = SUBHEAD_FILL
        c.font = SUBHEAD_FONT
        c.alignment = CENTER

def style_date_row(ws, row, cols):
    for col in range(1, cols + 1):
        c = ws.cell(row=row, column=col)
        c.fill = DATE_FILL
        c.font = DATE_FONT
        c.alignment = LEFT

def set_col_widths(ws, widths):
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w

# ── Sheet 1: Live Snapshot log ────────────────────────────────────────────────

SNAP_HEADERS = [
    "Date", "Report Date", "Registration", "Type", "Owner ICAO", "Owner Name",
    "Group", "Status", "Callsign", "Operator ICAO", "Operator Name",
    "Route", "Last Seen", "Altitude", "Speed", "Heading",
]
SNAP_WIDTHS = [12, 12, 12, 8, 12, 22, 22, 14, 14, 14, 24, 14, 20, 10, 8, 8]

def append_snapshot(ws, snap):
    is_new = ws.max_row == 1 and ws.cell(1, 1).value is None

    if is_new:
        ws.append(SNAP_HEADERS)
        style_header_row(ws, 1, len(SNAP_HEADERS))
        ws.freeze_panes = "A2"
        set_col_widths(ws, SNAP_WIDTHS)

    run_date  = snap.get("last_updated", "")[:10]
    rep_date  = snap.get("report_date", "")
    fleet     = snap.get("fleet", [])

    # Date separator row
    sep_row = ws.max_row + 1
    ws.cell(sep_row, 1, f"── {run_date}  ({len(fleet)} aircraft, "
            f"{snap.get('summary',{}).get('acmi_active',0)} ACMI active) ──")
    style_date_row(ws, sep_row, len(SNAP_HEADERS))
    ws.merge_cells(start_row=sep_row, start_column=1, end_row=sep_row, end_column=len(SNAP_HEADERS))

    for ac in fleet:
        row_data = [
            run_date,
            rep_date,
            ac.get("registration"),
            ac.get("type"),
            ac.get("owner_icao"),
            ac.get("owner_name"),
            ac.get("group"),
            ac.get("status"),
            ac.get("callsign"),
            ac.get("current_operator_icao"),
            ac.get("current_operator_name"),
            ac.get("last_route"),
            ac.get("last_seen", "")[:19].replace("T", " ") if ac.get("last_seen") else None,
            ac.get("altitude"),
            ac.get("speed"),
            ac.get("heading"),
        ]
        r = ws.max_row + 1
        for col, val in enumerate(row_data, 1):
            c = ws.cell(r, col, val)
            c.font = NORMAL_FONT
            c.alignment = LEFT
            c.border = THIN_BORDER

        # Color by status
        status = ac.get("status", "")
        reg_cell = ws.cell(r, 3)
        if status == "acmi_active":
            reg_cell.font = ACMI_FONT
            ws.cell(r, 8).font = ACMI_FONT
        elif status == "own_ops":
            ws.cell(r, 8).font = GREEN_FONT
        else:
            ws.cell(r, 8).font = MUTED_FONT

# ── Sheet 2: Daily History log ────────────────────────────────────────────────

HIST_HEADERS = [
    "Date", "Report Date", "Registration", "Type", "Owner ICAO", "Owner Name", "Group",
    "Total Flights", "Total BH", "ACMI Flights", "ACMI BH",
    "Clients (name · BH)", "Routes",
]
HIST_WIDTHS = [12, 12, 12, 8, 12, 22, 22, 12, 10, 12, 10, 40, 35]

def append_history(ws, hist):
    is_new = ws.max_row == 1 and ws.cell(1, 1).value is None

    if is_new:
        ws.append(HIST_HEADERS)
        style_header_row(ws, 1, len(HIST_HEADERS))
        ws.freeze_panes = "A2"
        set_col_widths(ws, HIST_WIDTHS)

    run_date  = hist.get("last_updated", "")[:10]
    rep_date  = hist.get("report_date", "")
    fleet     = hist.get("fleet", [])

    tot_flights = sum(r.get("total_flights", 0) for r in fleet)
    tot_bh      = round(sum(r.get("total_bh", 0.0) for r in fleet), 1)
    acmi_bh     = round(sum(r.get("acmi_bh", 0.0) for r in fleet), 1)

    sep_row = ws.max_row + 1
    ws.cell(sep_row, 1,
        f"── {rep_date}  ({tot_flights} flights / {tot_bh} BH total / {acmi_bh} BH ACMI) ──")
    style_date_row(ws, sep_row, len(HIST_HEADERS))
    ws.merge_cells(start_row=sep_row, start_column=1, end_row=sep_row, end_column=len(HIST_HEADERS))

    active = [r for r in fleet if r.get("total_flights", 0) > 0]
    active.sort(key=lambda x: -x.get("total_bh", 0))

    for ac in active:
        clients_str = "  |  ".join(
            f"{c.get('name') or c.get('icao')} · {c.get('bh')}h"
            for c in (ac.get("clients") or [])
        )
        routes_str = "  ".join(ac.get("routes") or [])

        row_data = [
            run_date,
            rep_date,
            ac.get("registration"),
            ac.get("type"),
            ac.get("owner_icao"),
            ac.get("owner_name"),
            ac.get("group"),
            ac.get("total_flights"),
            ac.get("total_bh"),
            ac.get("acmi_flights") or 0,
            ac.get("acmi_bh") or 0.0,
            clients_str or None,
            routes_str or None,
        ]
        r = ws.max_row + 1
        for col, val in enumerate(row_data, 1):
            c = ws.cell(r, col, val)
            c.font = NORMAL_FONT
            c.alignment = LEFT
            c.border = THIN_BORDER

        # Highlight ACMI rows
        if ac.get("acmi_flights", 0) > 0:
            ws.cell(r, 3).font = ACMI_FONT
            ws.cell(r, 11).font = GREEN_FONT

# ── Sheet 3: Operator summary log ────────────────────────────────────────────

OPS_HEADERS = [
    "Date", "Report Date", "Operator Group",
    "Total Flights", "Total BH", "ACMI Flights", "ACMI BH", "Active Aircraft",
]
OPS_WIDTHS = [12, 12, 24, 14, 10, 14, 10, 16]

def append_op_summaries(ws, hist):
    is_new = ws.max_row == 1 and ws.cell(1, 1).value is None

    if is_new:
        ws.append(OPS_HEADERS)
        style_header_row(ws, 1, len(OPS_HEADERS))
        ws.freeze_panes = "A2"
        set_col_widths(ws, OPS_WIDTHS)

    run_date = hist.get("last_updated", "")[:10]
    rep_date = hist.get("report_date", "")
    ops      = hist.get("operator_summaries", {})

    sep_row = ws.max_row + 1
    ws.cell(sep_row, 1, f"── {rep_date}  ({len(ops)} operators) ──")
    style_date_row(ws, sep_row, len(OPS_HEADERS))
    ws.merge_cells(start_row=sep_row, start_column=1, end_row=sep_row, end_column=len(OPS_HEADERS))

    for group, data in sorted(ops.items(), key=lambda x: -x[1].get("acmi_bh", 0)):
        row_data = [
            run_date,
            rep_date,
            group,
            data.get("total_flights"),
            data.get("total_bh"),
            data.get("acmi_flights"),
            data.get("acmi_bh"),
            data.get("active_aircraft"),
        ]
        r = ws.max_row + 1
        for col, val in enumerate(row_data, 1):
            c = ws.cell(r, col, val)
            c.font = NORMAL_FONT
            c.alignment = LEFT
            c.border = THIN_BORDER

        if data.get("acmi_bh", 0) > 0:
            ws.cell(r, 3).font = ACMI_FONT
            ws.cell(r, 7).font = GREEN_FONT

# ── Sheet 4: Client map log ───────────────────────────────────────────────────

CLIENT_HEADERS = [
    "Date", "Report Date", "Client ICAO", "Client Name",
    "ACMI Provider", "Flights", "BH", "Aircraft Count", "Aircraft Regs",
]
CLIENT_WIDTHS = [12, 12, 14, 26, 22, 10, 10, 14, 40]

def append_client_map(ws, hist):
    is_new = ws.max_row == 1 and ws.cell(1, 1).value is None

    if is_new:
        ws.append(CLIENT_HEADERS)
        style_header_row(ws, 1, len(CLIENT_HEADERS))
        ws.freeze_panes = "A2"
        set_col_widths(ws, CLIENT_WIDTHS)

    run_date  = hist.get("last_updated", "")[:10]
    rep_date  = hist.get("report_date", "")
    cm        = hist.get("client_map", {})

    if not cm:
        return

    sep_row = ws.max_row + 1
    ws.cell(sep_row, 1, f"── {rep_date}  ({len(cm)} clients) ──")
    style_date_row(ws, sep_row, len(CLIENT_HEADERS))
    ws.merge_cells(start_row=sep_row, start_column=1, end_row=sep_row, end_column=len(CLIENT_HEADERS))

    # Support both old (flat) and new (name + providers) client_map format
    for client_icao, val in sorted(cm.items()):
        if isinstance(val, dict) and "providers" in val:
            client_name = val.get("name", client_icao)
            providers   = val["providers"]
        else:
            client_name = client_icao
            providers   = val

        for provider, data in sorted(providers.items(), key=lambda x: -x[1].get("bh", 0)):
            row_data = [
                run_date,
                rep_date,
                client_icao,
                client_name,
                provider,
                data.get("flights"),
                data.get("bh"),
                data.get("aircraft_count"),
                ", ".join(data.get("aircraft") or []),
            ]
            r = ws.max_row + 1
            for col, val2 in enumerate(row_data, 1):
                c = ws.cell(r, col, val2)
                c.font = NORMAL_FONT
                c.alignment = LEFT
                c.border = THIN_BORDER

            ws.cell(r, 3).font = Font(name="Arial", size=9, color="A78BFA")
            if data.get("bh", 0) > 0:
                ws.cell(r, 7).font = GREEN_FONT

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    snap = hist = None

    if os.path.exists(SNAPSHOT):
        with open(SNAPSHOT) as f:
            snap = json.load(f)
        print(f"Loaded snapshot: {snap.get('report_date')} — {len(snap.get('fleet',[]))} aircraft")
    else:
        print("WARNING: acmi_data.json not found — skipping snapshot sheet")

    if os.path.exists(HISTORY):
        with open(HISTORY) as f:
            hist = json.load(f)
        print(f"Loaded history:  {hist.get('report_date')} — {len(hist.get('fleet',[]))} records")
    else:
        print("WARNING: acmi_history.json not found — skipping history sheets")

    if not snap and not hist:
        print("ERROR: No data files found. Run fetch_acmi.py first.")
        raise SystemExit(1)

    # Load or create workbook
    if os.path.exists(EXCEL):
        wb = load_workbook(EXCEL)
        print(f"Appending to existing {EXCEL}")
    else:
        wb = Workbook()
        wb.remove(wb.active)  # remove default sheet
        print(f"Creating new {EXCEL}")

    # Ensure sheets exist
    def get_or_create(name):
        if name in wb.sheetnames:
            return wb[name]
        ws = wb.create_sheet(name)
        return ws

    if snap:
        append_snapshot(get_or_create("Snapshot Log"), snap)
        print("✓ Snapshot sheet updated")

    if hist:
        append_history(get_or_create("Daily Report Log"), hist)
        append_op_summaries(get_or_create("Operator Summary"), hist)
        append_client_map(get_or_create("Client Map Log"), hist)
        print("✓ History / Operator / Client sheets updated")

    wb.save(EXCEL)
    print(f"\n✓ Saved → {EXCEL}")

if __name__ == "__main__":
    main()
