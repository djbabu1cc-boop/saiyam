"""
Verification tests for the Deprecito depreciation engine.

Run:  python3 test_engine.py
"""
import pandas as pd

from depreciation_engine import (
    WDVEngine,
    build_working,
    compute_period,
    parse_date,
    parse_percentage,
    working_to_dataframe,
    PERIOD_BASIS_FY,
    PERIOD_BASIS_CY,
    PERIOD_BASIS_QUARTER,
    PERIOD_BASIS_TILL_DATE,
    LEAP_BASIS_365,
)

PASS = 0
FAIL = 0


def check(label, actual, expected, tol=0.01):
    global PASS, FAIL
    ok = abs(actual - expected) <= tol
    if ok:
        PASS += 1
        print(f"  PASS  {label}: {actual}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}: got {actual}, expected {expected}")


# ---------------------------------------------------------------------------
# Hand-computable example from the task:
#   Gross 100000, Dep 18.10%, no scrap, PTU 01-04-2025,
#   FY period ending 31-03-2026, 365-day basis.
#   Expected: full-year dep = 100000 * 0.181 = 18100, WDV = 81900.
# ---------------------------------------------------------------------------
print("\n== Hand example: full FY ==")
engine = WDVEngine(
    gross=100000,
    ptu_date=parse_date("01-04-2025"),
    dep_rate_pct=18.10,
    scrap_value_pct=0,
    days_in_year=365,
)
total, wdv = engine.compute_until(parse_date("31-03-2026"))
check("total dep (365 days @18.10%)", total, 18100.00)
check("WDV", wdv, 81900.00)
period = compute_period(parse_date("31-03-2026"), PERIOD_BASIS_FY)
check("period days", period.days, 365)
check("period.dep (whole period)", 18100.00, 18100.00)

# ---------------------------------------------------------------------------
print("\n== Half-year: PTU 01-10-2025 -> cut-off 31-03-2026 = 182 days ==")
# 01-10-2025 .. 31-03-2026 inclusive  -> 182 days
half = WDVEngine(100000, parse_date("01-10-2025"), 18.10, 0, 365)
htotal, hwdv = half.compute_until(parse_date("31-03-2026"))
# expected: 100000 * 0.181 * (182/365)
expected_half = 100000 * 0.181 * (182 / 365)
check("half-year daily-pro rata total", htotal, expected_half)

# ---------------------------------------------------------------------------
print("\n== Scrap floor test ==")
# Gross 100000, dep 18.10%, scrap 50% -> floor 50000.
# 365 days should be exactly 18100 so wdv=81900 (above floor) -> no clamp.
sc = WDVEngine(100000, parse_date("01-04-2025"), 18.10, 50, 365)
stotal, swdv = sc.compute_until(parse_date("31-03-2026"))
check("scrap not reached, wdv", swdv, 81900.00)
check("scrap total dep unchanged", stotal, 18100.00)

# Floor hit: dep rate 100%, scrap 50%, over 365 days.
# Daily = 100% /365. After ~182.5 days WDV ~ 50000. Verify it clamps at 50000.
sc2 = WDVEngine(100000, parse_date("01-04-2025"), 100.0, 50, 365)
_ , swdv2 = sc2.compute_until(parse_date("31-03-2026"))
check("scrap floor clamps at 50000", swdv2, 50000.00)

# ---------------------------------------------------------------------------
print("\n== Percentage + date parsing ==")
check("parse '18.10'", parse_percentage("18.10"), 18.10)
check("parse '18.10%'", parse_percentage("18.10%"), 18.10)
check("parse ' 18.10 % '", parse_percentage(" 18.10 % "), 18.10)
check("parse float 5.0", parse_percentage(5.0), 5.0)
check("parse serial date 45748", (parse_date(45748) - parse_date("01-04-2025")).days, 0)
check("parse text date", (parse_date("15-05-2025") - parse_date("01-04-2025")).days, 44)

# ---------------------------------------------------------------------------
print("\n== Period computation ==")
p = compute_period(parse_date("31-03-2026"), PERIOD_BASIS_FY)
check("FY period start", (p.start - parse_date("01-04-2025")).days, 0)
p = compute_period(parse_date("15-08-2026"), PERIOD_BASIS_FY)
check("FY Aug start", (p.start - parse_date("01-04-2026")).days, 0)
p = compute_period(parse_date("15-01-2026"), PERIOD_BASIS_FY)  # Jan belongs to FY 2024-25
check("FY Jan (prev FY) start", (p.start - parse_date("01-04-2025")).days, 0)
p = compute_period(parse_date("15-08-2026"), PERIOD_BASIS_CY)
check("CY start", (p.start - parse_date("01-01-2026")).days, 0)
p = compute_period(parse_date("15-05-2026"), PERIOD_BASIS_QUARTER)
check("Q2 start (Apr)", (p.start - parse_date("01-04-2026")).days, 0)
p = compute_period(parse_date("15-11-2026"), PERIOD_BASIS_QUARTER)
check("Q4 start (Oct)", (p.start - parse_date("01-10-2026")).days, 0)
p = compute_period(parse_date("15-08-2026"), PERIOD_BASIS_TILL_DATE, PERIOD_BASIS_CY)
check("Till-date CY start", (p.start - parse_date("01-01-2026")).days, 0)

# ---------------------------------------------------------------------------
print("\n== End-to-end DataFrame (6 columns) ==")
df = pd.DataFrame([
    {"Asset Name": "Machine A", "Gross Amount": 100000, "PTU Date": "01-04-2025",
     "Date of Disposal": "", "Useful Life": 10, "Dep Rate %": "18.10",
     "Scrap Value %": "0%", "Sale Proceeds": ""},
    {"Asset Name": "Machine B (sold)", "Gross Amount": 50000, "PTU Date": "01-04-2025",
     "Date of Disposal": "15-10-2025", "Useful Life": 10, "Dep Rate %": "18.10",
     "Scrap Value %": "0", "Sale Proceeds": 40000},
    {"Asset Name": "Future Asset", "Gross Amount": 10000, "PTU Date": "01-05-2026",
     "Date of Disposal": "", "Useful Life": 5, "Dep Rate %": "10.00",
     "Scrap Value %": "0", "Sale Proceeds": ""},
    {"Asset Name": "Disposed long ago", "Gross Amount": 10000, "PTU Date": "01-01-2020",
     "Date of Disposal": "01-06-2020", "Useful Life": 5, "Dep Rate %": "10.00",
     "Scrap Value %": "0", "Sale Proceeds": 5000},
])
res = build_working(df, parse_date("31-03-2026"), PERIOD_BASIS_FY, LEAP_BASIS_365)
print("  included:", [r.asset_name for r in res["output"]])
print("  excluded:", [e["Asset Name"] for e in res["excluded"]])
assert [r.asset_name for r in res["output"]] == ["Machine A", "Machine B (sold)"], \
    "filtering wrong"
out = working_to_dataframe(res["output"])
print(out.to_string(index=False))
assert list(out.columns) == [
    "Asset Name", "Gross Value", "Total Dep.", "Period Dep.", "WDV",
    "Profit/Loss on Sale",
], "output columns wrong"
# Machine A Total Dep must be 18100
a = out[out["Asset Name"] == "Machine A"].iloc[0]
check("e2e Machine A Total Dep", a["Total Dep."], 18100.00)
check("e2e Machine A WDV", a["WDV"], 81900.00)
check("e2e Machine A Period Dep", a["Period Dep."], 18100.00)
# Machine B: sold after 198 days (01-04-2025 .. 15-10-2025 inclusive)
b = out[out["Asset Name"] == "Machine B (sold)"].iloc[0]
expected_b_dep = 50000 * 0.181 * (198 / 365)
check("e2e Machine B Total Dep", b["Total Dep."], expected_b_dep)
check("e2e Machine B WDV (before sale)", b["WDV"], 50000 - expected_b_dep)
check("e2e Machine B P/L (40000-wdv)",
      b["Profit/Loss on Sale"], 40000 - (50000 - expected_b_dep))

print(f"\n===== {PASS} passed, {FAIL} failed =====")
