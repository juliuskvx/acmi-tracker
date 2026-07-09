name: One-Time Backfill (Attribution Fix)
on:
  workflow_dispatch:
permissions:
  contents: write
jobs:
  backfill:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install requests openpyxl
      - name: Backfill corrected attribution
        run: python scripts/backfill_history.py
      - name: Re-run contract analysis on cleaned history
        run: python scripts/analyze_contracts.py
      - name: Commit & push cleaned data
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/acmi_history.json data/contract_windows.json
          git diff --cached --quiet || git commit -m "chore: one-time backfill — corrected ACMI attribution"
          git pull origin main --rebase
          git push origin main
