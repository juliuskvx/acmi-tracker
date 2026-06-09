# ACMI Intel Tracker

A real-time dashboard tracking European ACMI (wet lease) aircraft operations. Shows which aircraft are currently flying under a different airline's callsign, revealing hidden capacity flows across European aviation.

## What is ACMI?

ACMI (Aircraft, Crew, Maintenance, Insurance) is wet leasing — one airline leases a fully crewed and maintained aircraft to another. The lessee puts its own flight numbers on the aircraft. ACMI operators are the invisible backbone of European aviation, filling capacity gaps for charter carriers, LCCs, and flag carriers.

## How it works

1. A `fleet_registry.json` of known ACMI operator registrations is maintained manually
2. A Python script queries the FR24 Explorer API daily for each registration
3. If an aircraft's callsign prefix doesn't match its owner's ICAO code → it's on ACMI
4. Results are saved to `data/acmi_data.json` and displayed in the dashboard

## Operators tracked

| Group | AOCs | Fleet type |
|---|---|---|
| Avion Express | Lithuania, Malta | A320 family |
| Heston / Valletta Airlines | Lithuania, Malta | A320 |
| GetJet Group | Lithuania, Malta | A320 / B737 |
| Enter Air | Poland | B737-800 / MAX |
| Smartwings | Czech Republic | B737 / A320 |
| Titan Airways | UK, Malta | A320 / A321 / A321F |
| AirExplore | Slovakia | B737-800 |

## Data

- `data/fleet_registry.json` — manually curated list of ACMI operator registrations
- `data/acmi_data.json` — auto-generated daily by GitHub Actions (do not edit manually)

## Setup

1. Clone the repo
2. Add `FR24_API_KEY` to GitHub Secrets (Settings → Secrets → Actions)
3. GitHub Actions runs daily at 10:00 AM Lithuanian time
4. Dashboard is served via GitHub Pages from `index.html`

## Stack

Pure HTML/CSS/JS — no frameworks. Python for data fetching. GitHub Actions for automation.

---

*Built by [@juliuskvx](https://github.com/juliuskvx)*
