# Deprecito — Fixed Asset WDV Depreciation (v1)

A strictly-offline local Python web app that converts a raw fixed-asset Excel
upload into a clean, audit-ready WDV depreciation working file.

- **Exact-day** depreciation (both start & end dates inclusive).
- Configurable **Reporting Date**, **Period Basis** (FY / CY / Quarter / Till
  Date), **Leap Basis** (365 / 366) and **Till Date Basis** (FY / CY).
- **Scrap Value Floor** — WDV never falls below Gross × Scrap Value %.
- **Disposal P/L** — assets sold during the period stop depreciating on the
  sale date and report Profit/Loss (Sale Proceeds − WDV at sale).
- Clean architecture: all financial logic lives in
  `depreciation_engine.py` (the `Calculate` core); `app.py` is UI only.
- No network calls, no telemetry — run it on localhost.
- `.streamlit/config.toml` disables Streamlit's anonymous usage stats and
  binds strictly to `localhost`, so it never phones home or exposes itself.

## Quick start

```bash
# 1. Install dependencies (Python 3.9+)
pip install streamlit pandas openpyxl

# 2. Run the app (localhost only)
streamlit run app.py
```

Open the printed URL (default http://localhost:8501), upload
`sample_input.xlsx`, choose your parameters, and click **Generate Working** to
download the output workbook.

> Note: if your system uses PEP 668 (externally-managed environment, e.g.
> Debian/Ubuntu), add `--break-system-packages` or use a virtual environment:
> `python3 -m venv .venv && . .venv/bin/activate && pip install ...`.

## Try it immediately

`sample_input.xlsx`  — ready-made upload with 6 assets exercising every rule.
`sample_output.xlsx` — the generated working for Reporting Date 31-03-2026,
Financial Year, 365-day basis (regenerate with the app or
`python3 make_samples.py`).

## Input Excel format

Eight columns, **in this order**:

| Asset Name | Gross Amount | PTU Date | Date of Disposal | Useful Life | Dep Rate % | Scrap Value % | Sale Proceeds |
|------------|--------------|----------|------------------|-------------|------------|---------------|---------------|

- Percentages may be `18.10` or `18.10%` (also `15%`, `5%` etc.).
- Dates may be Excel serials or text `DD-MM-YYYY` / `DD/MM/YYYY`.
- Leave **Date of Disposal** and **Sale Proceeds** blank for active assets.
- *Useful Life* is read but **ignored** by the engine (depreciation relies on
  the Dep Rate % only).

## Output Excel — exactly 6 columns

1. Asset Name
2. Gross Value
3. Total Dep. (cumulative from PTU to cut-off/disposal)
4. Period Dep. (depreciation strictly within the selected period)
5. WDV (carrying value; if sold, WDV immediately before sale)
6. Profit/Loss on Sale (blank if not sold)

## Inclusion / exclusion rules

- **Excluded:** PTU after the Reporting Date (future assets).
- **Excluded:** assets disposed before the calculated Period Start.
- **Included:** active assets (no disposal, or disposal after Reporting Date).
- **Included:** assets disposed *during* the period — depreciation stops on the
  disposal date, WDV is computed just before sale, and P/L is reported.

## Calculation model (verifiable by hand)

Standard WDV method, recomputed once per financial year (1 Apr–31 Mar), prorated
by exact days:

```
dep  =  Opening WDV of the year  ×  Dep Rate % / 100  ×  (days used / days_in_year)
WDV  =  Gross − total depreciation (never below Gross × Scrap Value % / 100)
```

**Worked hand example:** Gross 100,000, Dep Rate 18.10%, no scrap, PTU
01-04-2025, Financial Year to 31-03-2026, 365-day basis.
There are exactly 365 days from 01-04-2025 to 31-03-2026 (both inclusive), so:

```
Total Dep. = 100000 × 0.181 × 365/365 = 18100
WDV        = 100000 − 18100 = 81900
```

This matches the app output exactly.

## Verify / tests

```bash
python3 test_engine.py    # engine unit tests (27 checks)
python3 make_samples.py   # regenerate sample input/output
```

## Project layout

```
deprecito/
├── app.py                 # Streamlit UI (upload → generate → download)
├── depreciation_engine.py # Core financial logic (Calculate engine, no UI)
├── test_engine.py         # Engine verification tests
├── make_samples.py        # Regenerates the sample files
├── sample_input.xlsx      # Ready-to-upload sample
├── sample_output.xlsx     # Sample generated output
└── README.md
```

### Assumptions
- Period End is always the Reporting Date; Period Start follows the basis
  (FY: 1 Apr; CY: 1 Jan; Quarter: quarter start; Till Date: 1 Apr or 1 Jan).
- The financial-year boundary (for WDV recomputation) is 1 April–31 March, the
  Indian convention, regardless of the chosen reporting basis.
- Partial-year depreciation uses the prorated opening-WDV method above.
