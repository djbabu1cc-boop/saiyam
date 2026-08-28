"""
Generate the sample input Excel and a sample output Excel so the owner can
test the app immediately.

Run:  python3 make_samples.py
"""
import pandas as pd

from depreciation_engine import (
    LEAP_BASIS_365,
    PERIOD_BASIS_FY,
    build_working,
    parse_date,
    working_to_dataframe,
)

SAMPLE_INPUT = "sample_input.xlsx"
SAMPLE_OUTPUT = "sample_output.xlsx"

# Diverse set exercising every rule: %, scrap floor, mid-year PTU, disposal
# during period, future PTU (excluded), disposed-before-period (excluded).
raw = [
    ["Laptop", 100000, "01-04-2025", "", 5, "18.10%", "0%", ""],
    ["Delivery Van", 500000, "15-06-2025", "", 8, "15%", "5%", ""],
    ["Forklift (sold)", 300000, "01-04-2024", "15-10-2025", 15, "10%", "0%", 240000],
    ["Server", 200000, "01-07-2025", "", 6, "20.00", "0", ""],
    ["Furniture", 150000, "01-04-2023", "10-01-2024", 10, "10%", "0%", 90000],
    ["Future Machine", 80000, "01-06-2026", "", 5, "18.10%", "0%", ""],
]

HEADERS = [
    "Asset Name", "Gross Amount", "PTU Date", "Date of Disposal",
    "Useful Life", "Dep Rate %", "Scrap Value %", "Sale Proceeds",
]

df = pd.DataFrame(raw, columns=HEADERS)
df.to_excel(SAMPLE_INPUT, index=False)
print("Wrote", SAMPLE_INPUT)

reporting = parse_date("31-03-2026")  # FY 2025-26
result = build_working(
    df,
    reporting_date=reporting,
    period_basis=PERIOD_BASIS_FY,
    leap_basis=LEAP_BASIS_365,
)
out = working_to_dataframe(result["output"])
out.to_excel(SAMPLE_OUTPUT, index=False)
print("Wrote", SAMPLE_OUTPUT)

print("\nAssets:", out["Asset Name"].tolist())
print("Excluded:", [(e["Asset Name"], e["reason"]) for e in result["excluded"]])
print("\nOutput preview:")
print(out.to_string(index=False))
