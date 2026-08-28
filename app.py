"""
Deprecito — Streamlit UI (localhost)

Upload a raw fixed-asset Excel file, pick reporting parameters, and download a
processed Excel working with exact-day WDV depreciation.

The UI only renders and orchestrates; ALL financial logic lives in
`depreciation_engine.py` (the `Calculate` core).
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from depreciation_engine import (
    EXPECTED_COLUMNS,
    LEAP_BASIS_365,
    LEAP_BASIS_366,
    OUTPUT_COLUMNS,
    PERIOD_BASIS_CY,
    PERIOD_BASIS_FY,
    PERIOD_BASIS_QUARTER,
    PERIOD_BASIS_TILL_DATE,
    PERIOD_BASIS_OPTIONS,
    build_working,
    parse_percentage,
    working_to_dataframe,
)

st.set_page_config(
    page_title="Deprecito — Fixed Asset WDV Depreciation",
    layout="wide",
)

LEAP_OPTIONS = {
    "Leap Year (366 days)": LEAP_BASIS_366,
    "Non-Leap Year (365 days)": LEAP_BASIS_365,
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with the canonical 8 columns, in spec order."""
    # If an expected header is present, align by name (smart about whitespace/case).
    flat = {str(c).strip().lower(): c for c in df.columns}
    if "asset name" in flat:
        mapping = {
            "asset name": "Asset Name",
            "gross amount": "Gross Amount",
            "ptu date": "PTU Date",
            "date of disposal": "Date of Disposal",
            "useful life": "Useful Life",
            "dep rate %": "Dep Rate %",
            "scrap value %": "Scrap Value %",
            "sale proceeds": "Sale Proceeds",
        }
        # Also accept "dep rate" / "scrap %" aliases.
        alias = {
            "dep rate": "Dep Rate %",
            "dep %": "Dep Rate %",
            "scrap %": "Scrap Value %",
            "scrap": "Scrap Value %",
        }
        renamed = {}
        for key, orig in flat.items():
            canon = mapping.get(key) or alias.get(key)
            renamed[orig] = canon if canon and canon not in renamed.values() else orig
        return df.rename(columns=renamed)
    # No header / different headers: take the first 8 columns positionally.
    df = df.iloc[:, :8].copy()
    df.columns = EXPECTED_COLUMNS
    return df


def build_excel_bytes(out_df: pd.DataFrame, period, meta) -> bytes:
    """Render the 6-column output DataFrame as a styled .xlsx (OpenPyXL)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Depreciation Working"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    money_font = Font()

    for col_idx, col in enumerate(OUTPUT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col)
        cell.fill = header_fill
        cell.font = header_font

    for r_idx, row in enumerate(out_df.itertuples(index=False), start=2):
        for c_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            if c_idx >= 2 and isinstance(value, (int, float)):
                cell.number_format = "#,##0.00"

    # Column widths
    for i, col in enumerate(OUTPUT_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, len(col) + 4)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(OUTPUT_COLUMNS))}1"

    # Trivial rounding guard so P/L shows 0.00 rather than tiny floats.
    wb.calculation.fullCalcOnLoad = True

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def main() -> None:
    st.title("Deprecito")
    st.caption(
        "Fixed Asset WDV Depreciation — exact-day working file generator. "
        "Strictly offline (localhost only)."
    )

    st.markdown(
        "**Input columns (in order):** Asset Name | Gross Amount | PTU Date | "
        "Date of Disposal | Useful Life | Dep Rate % | Scrap Value % | Sale Proceeds"
    )

    uploaded = st.file_uploader(
        "Upload the raw fixed-asset Excel file (.xlsx)",
        type=["xlsx", "xls"],
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        reporting_date = st.date_input(
            "Reporting Date",
            value=date(2026, 3, 31),
        )
    with col2:
        period_basis = st.selectbox("Period Basis", PERIOD_BASIS_OPTIONS)
    with col3:
        leap_label = st.selectbox(
            "Leap Basis",
            list(LEAP_OPTIONS.keys()),
            index=1,  # default Non-Leap (365)
        )
    leap_basis = LEAP_OPTIONS[leap_label]

    till_date_basis = PERIOD_BASIS_FY
    if period_basis == PERIOD_BASIS_TILL_DATE:
        till_date_basis = st.radio(
            "Till Date Basis",
            [PERIOD_BASIS_FY, PERIOD_BASIS_CY],
            horizontal=True,
        )

    if uploaded is None:
        st.info("Upload a file to begin.")
        return

    try:
        df = pd.read_excel(uploaded)
        df = normalize_columns(df)
    except Exception as exc:
        st.error(f"Could not read the Excel file: {exc}")
        return

    # Quick preview
    with st.expander("Preview uploaded data", expanded=False):
        st.dataframe(df.head(25), width="stretch")

    st.markdown("---")
    if st.button("Generate Working", type="primary"):
        if df.empty:
            st.error("The uploaded file has no data rows.")
            return

        try:
            result = build_working(
                df,
                reporting_date=reporting_date,
                period_basis=period_basis,
                leap_basis=leap_basis,
                till_date_basis=till_date_basis,
            )
        except Exception as exc:
            st.error(f"Processing failed: {exc}")
            return

        out_df = working_to_dataframe(result["output"])

        st.success(
            f"Processed {len(out_df)} assets "
            f"(period {result['period'].start:%d-%m-%Y} to "
            f"{result['period'].end:%d-%m-%Y}, "
            f"{result['days_in_year']}-day basis)."
        )

        st.subheader("Output Working")
        st.dataframe(out_df, width="stretch")

        if result["excluded"]:
            with st.expander(
                f"Excluded assets ({len(result['excluded'])})"
            ):
                st.dataframe(pd.DataFrame(result["excluded"]))

        if not out_df.empty:
            excel_bytes = build_excel_bytes(out_df, result["period"], result)

            st.download_button(
                label="⬇ Download Output Excel",
                data=excel_bytes,
                file_name=(
                    f"deprecito_working_"
                    f"{reporting_date:%Y%m%d}.xlsx"
                ),
                mime="application/vnd.openxmlformats-officedocument"
                     ".spreadsheetml.sheet",
            )


if __name__ == "__main__":
    main()
