"""
Deprecito — Core Financial Engine (WDV depreciation)

This module contains ALL the financial logic. It is deliberately free of any
UI dependency so it can be unit-tested in isolation and reused by any front end
(Streamlit, CLI, tests, etc.).

Calculation model  (standard WDV, exact-day pro-rata)
------------------------------------------------------
* Depreciation follows the classic Written-Down-Value method:
  dep = Opening WDV of the year  x  Depreciation rate  x  (days used / days_in_year)
* The WDV is recalculated once a *financial year* (1 Apr - 31 Mar, the Indian
  convention) — the block's opening WDV carries the prior years' written-down
  value, and the year's depreciation is applied to that opening WDV prorated by
  the exact number of days the asset was in use that year.
* Both start (PTU) and end (cut-off / disposal) dates are INCLUSIVE.
* A fixed leap basis (365 or 366) is used as the year denominator.
* Scrap Value Floor: WDV can never fall below Gross x (Scrap Value %).  When
  reached, depreciation stops.
* Useful Life is deliberately IGNORED — the engine relies entirely on Dep Rate %.
* Cumulative depreciation to any date D is computed by walking the financial
  years; "Period Depreciation" is the difference of cumulative depreciation at
  two dates, which is exact on the running-WDV basis (even across the floor).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

# ---------------------------------------------------------------------------
# Constants / configuration
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = [
    "Asset Name",
    "Gross Amount",
    "PTU Date",
    "Date of Disposal",
    "Useful Life",
    "Dep Rate %",
    "Scrap Value %",
    "Sale Proceeds",
]

PERIOD_BASIS_FY = "Financial Year"
PERIOD_BASIS_CY = "Calendar Year"
PERIOD_BASIS_QUARTER = "Quarter"
PERIOD_BASIS_TILL_DATE = "Till Date"

PERIOD_BASIS_OPTIONS = [
    PERIOD_BASIS_FY,
    PERIOD_BASIS_CY,
    PERIOD_BASIS_QUARTER,
    PERIOD_BASIS_TILL_DATE,
]

LEAP_BASIS_365 = 365
LEAP_BASIS_366 = 366

EXCEL_EPOCH = date(1899, 12, 30)  # Excel serial date epoch


# ---------------------------------------------------------------------------
# Parsing helpers (dependency-free, reusable by the UI / tests)
# ---------------------------------------------------------------------------

def parse_percentage(value) -> float:
    """Parse a percentage that may be '18.10', '18.10%', ' 18.10 % ' etc."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace("%", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"Cannot parse percentage from value: {value!r}")


def parse_date(value) -> date:
    """Flexibly parse a date that may be an Excel serial or text DD-MM-YYYY."""
    if value is None:
        raise ValueError("Empty date value")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, (int, float)):
        serial = float(value)
        if serial < 1:
            raise ValueError(f"Not a valid Excel serial date: {value!r}")
        return EXCEL_EPOCH + pd.Timedelta(days=serial).to_pytimedelta()
    text = str(value).strip()
    for fmt in (
        "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d",
        "%d-%m-%y", "%d/%m/%y", "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(text).date()
    except Exception:
        raise ValueError(f"Cannot parse date from value: {value!r}")


def parse_number(value) -> float:
    """Parse a plain number, stripping thousand separators and currency marks."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("₹", "").replace("$", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"Cannot parse number from value: {value!r}")


def fy_start(d: date) -> date:
    """Return Apr 1 of the Indian Financial Year containing date d."""
    year = d.year
    if d.month < 4:
        year -= 1  # Jan-Mar belong to the previous FY
    return date(year, 4, 1)


def fy_end(fy_start_date: date) -> date:
    """Return Mar 31 of the FY that begins on fy_start_date."""
    return date(fy_start_date.year + 1, 3, 31)


def next_fy(fy_start_date: date) -> date:
    return date(fy_start_date.year + 1, 4, 1)


def quarter_start(d: date) -> date:
    month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, month, 1)


# ---------------------------------------------------------------------------
# Period computation
# ---------------------------------------------------------------------------

@dataclass
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        """Number of calendar days in the period, both ends inclusive."""
        return (self.end - self.start).days + 1


def compute_period(
    reporting_date: date,
    period_basis: str,
    till_date_basis: str = PERIOD_BASIS_FY,
) -> Period:
    """
    Auto-calculate the Period Start / End from the Reporting Date + Period Basis.

    Period End is always the Reporting Date.  Period Start depends on the basis:
      * Financial Year -> Apr 1 of the FY containing the reporting date.
      * Calendar Year   -> Jan 1 of the year of the reporting date.
      * Quarter         -> first day of the quarter containing the reporting date.
      * Till Date       -> Apr 1 (FY) or Jan 1 (CY) of the reporting date.
    """
    r = reporting_date
    if period_basis == PERIOD_BASIS_FY:
        start = fy_start(r)
    elif period_basis == PERIOD_BASIS_CY:
        start = date(r.year, 1, 1)
    elif period_basis == PERIOD_BASIS_QUARTER:
        start = quarter_start(r)
    elif period_basis == PERIOD_BASIS_TILL_DATE:
        start = fy_start(r) if till_date_basis == PERIOD_BASIS_FY else date(r.year, 1, 1)
    else:
        raise ValueError(f"Unknown period basis: {period_basis!r}")
    return Period(start=start, end=r)


# ---------------------------------------------------------------------------
# Per-asset engine
# ---------------------------------------------------------------------------

@dataclass
class WDVEngine:
    """Compute one asset's WDV depreciation with the exact-day pro-rata model."""

    gross: float
    ptu_date: date
    dep_rate_pct: float
    scrap_value_pct: float
    days_in_year: int
    disposal_date: date | None = None
    sale_proceeds: float | None = None

    def _floor(self) -> float:
        if self.scrap_value_pct <= 0:
            return 0.0
        return self.gross * (self.scrap_value_pct / 100.0)

    def _cumulative_dep(self, end_date: date) -> float:
        """
        Total depreciation accumulated from PTU to end_date (INCLUSIVE),
        computed across financial-year blocks with opening-WDV pro-rata.
        """
        if end_date < self.ptu_date:
            return 0.0
        floor = self._floor()
        rate = self.dep_rate_pct / 100.0
        wdv = self.gross
        total = 0.0
        block = fy_start(self.ptu_date)
        while block <= end_date:
            b_start = max(block, self.ptu_date)
            b_end = min(fy_end(block), end_date)
            if b_start <= b_end:
                days = (b_end - b_start).days + 1
                dep = wdv * rate * days / self.days_in_year
                if floor > 0:
                    if wdv <= floor + 1e-9:
                        dep = 0.0
                    elif wdv - dep < floor:
                        dep = wdv - floor
                total += dep
                wdv -= dep
            block = next_fy(block)
        return total

    def compute_until(self, end_date: date) -> tuple[float, float]:
        """Return (total_dep, wdv) as of end_date (inclusive)."""
        total = self._cumulative_dep(end_date)
        return total, round(self.gross - total, 2)

    def slice_dep(self, slice_start: date, slice_end: date) -> float:
        """
        Depreciation strictly on days within [slice_start, slice_end]
        (inclusive), bounded by the asset's own PTU.  Exact difference of
        cumulative depreciation at the two endpoints.
        """
        if slice_end < self.ptu_date or slice_start > slice_end:
            return 0.0
        lo = max(slice_start, self.ptu_date)
        hi = slice_end
        if lo > hi:
            return 0.0
        day_before = lo - pd.Timedelta(days=1).to_pytimedelta()
        return self._cumulative_dep(hi) - self._cumulative_dep(day_before)

    def period_dep(self, period_start: date, period_end: date, cutoff: date) -> float:
        """Depreciation strictly within the period but not past the cutoff."""
        s = max(period_start, self.ptu_date)
        e = min(cutoff, period_end)
        if s > e:
            return 0.0
        return self.slice_dep(s, e)


# ---------------------------------------------------------------------------
# Top-level asset processing
# ---------------------------------------------------------------------------

@dataclass
class AssetResult:
    asset_name: str
    gross: float
    total_dep: float
    period_dep: float
    wdv: float
    profit_loss: float | None  # None when the asset is not sold
    sold: bool
    scrap_floor: float
    reason: str = ""


def process_asset(
    row,
    period: Period,
    days_in_year: int,
) -> AssetResult | None:
    """
    Decide whether an asset belongs in the working and compute its figures.

    Returns None when the asset must be excluded from the output.
    """
    name = str(row.get("Asset Name", "")).strip()
    gross = parse_number(row.get("Gross Amount"))
    ptu = parse_date(row.get("PTU Date"))
    dep_rate = parse_percentage(row.get("Dep Rate %"))
    scrap_pct = parse_percentage(row.get("Scrap Value %"))

    # Disposal info (may be blank)
    disposal_raw = row.get("Date of Disposal")
    disposal = None
    sale_proceeds = None
    if disposal_raw is not None and str(disposal_raw).strip() not in ("", "nan", "None"):
        disposal = parse_date(disposal_raw)
        sale_proceeds = parse_number(row.get("Sale Proceeds") or 0.0)

    # --- Filtering rules ----------------------------------------------------
    # 1. Exclude assets not yet in commission by the reporting date (future PTU)
    if ptu > period.end:
        return None
    # 2. Exclude assets disposed of before the period start
    if disposal is not None and disposal < period.start:
        return None
    # 3. Sold during the period? (disposal within [period.start, period.end])
    sold = disposal is not None and disposal <= period.end

    engine = WDVEngine(
        gross=gross,
        ptu_date=ptu,
        dep_rate_pct=dep_rate,
        scrap_value_pct=scrap_pct,
        days_in_year=days_in_year,
        disposal_date=disposal,
        sale_proceeds=sale_proceeds,
    )

    if sold:
        cutoff = disposal
        total_dep, wdv = engine.compute_until(cutoff)
        period_dep = engine.period_dep(period.start, period.end, cutoff)
        profit_loss = sale_proceeds - wdv if sale_proceeds is not None else None
        reason = "sold"
    else:
        cutoff = period.end
        total_dep, wdv = engine.compute_until(cutoff)
        period_dep = engine.period_dep(period.start, period.end, cutoff)
        profit_loss = None
        reason = "active"

    return AssetResult(
        asset_name=name or f"Asset {row.name}",
        gross=round(gross, 2),
        total_dep=round(total_dep, 2),
        period_dep=round(period_dep, 2),
        wdv=round(wdv, 2),
        profit_loss=(round(profit_loss, 2) if profit_loss is not None else None),
        sold=sold,
        scrap_floor=round(engine._floor(), 2),
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def build_working(
    df: pd.DataFrame,
    reporting_date,
    period_basis: str,
    leap_basis: int,
    till_date_basis: str = PERIOD_BASIS_FY,
) -> dict:
    """
    Full pipeline from a raw DataFrame to the 6-column output.

    Returns a dict with:
      'output'  : list of AssetResult for every included asset
      'excluded': list of dicts describing excluded rows
      'period'  : the computed Period
      'days_in_year', 'reporting_date', 'period_basis', 'till_date_basis'
    """
    period = compute_period(reporting_date, period_basis, till_date_basis)

    output: list[AssetResult] = []
    excluded: list[dict] = []

    for idx, row in df.iterrows():
        name = str(row.get("Asset Name", "")).strip() or f"Row {idx}"
        try:
            result = process_asset(row, period, leap_basis)
        except Exception as exc:  # surface bad rows rather than crash the app
            excluded.append({"Asset Name": name, "reason": f"Error: {exc}"})
            continue
        if result is None:
            disposal_str = row.get("Date of Disposal")
            reason = (
                "Disposed before period start"
                if str(disposal_str).strip() not in ("", "nan", "None")
                else "PTU after reporting date"
            )
            excluded.append({"Asset Name": name, "reason": reason})
        else:
            output.append(result)

    return {
        "output": output,
        "excluded": excluded,
        "period": period,
        "days_in_year": leap_basis,
        "reporting_date": reporting_date,
        "period_basis": period_basis,
        "till_date_basis": till_date_basis,
    }


OUTPUT_COLUMNS = [
    "Asset Name",
    "Gross Value",
    "Total Dep.",
    "Period Dep.",
    "WDV",
    "Profit/Loss on Sale",
]


def working_to_dataframe(results: list[AssetResult]) -> pd.DataFrame:
    """Convert AssetResult list into the EXACT 6-column output DataFrame."""
    rows = []
    for r in results:
        rows.append(
            {
                "Asset Name": r.asset_name,
                "Gross Value": r.gross,
                "Total Dep.": r.total_dep,
                "Period Dep.": r.period_dep,
                "WDV": r.wdv,
                "Profit/Loss on Sale": r.profit_loss if r.sold else None,
            }
        )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
