"""Export parser fixtures for the Android app's Kotlin port.

The Android app (``android/``) re-implements ``invoice_extractor/parser.py``
and the OCR line clustering from ``invoice_extractor/ocr.py`` in Kotlin.
This script runs the *Python* implementation over a set of invoice texts and
OCR box layouts and writes the expected results to a JSON file that the
Kotlin unit tests replay - so both apps always extract the same values.

Run after changing the Python parser:
    pip install -r requirements.txt
    python scripts/export_parser_fixtures.py          # rewrite the fixtures
    python scripts/export_parser_fixtures.py --check  # CI: fail if stale
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

from invoice_extractor.ocr import _lines_from_boxes  # noqa: E402
from invoice_extractor.parser import parse_invoice_text  # noqa: E402

OUT = os.path.join(
    ROOT, "android", "app", "src", "test", "resources", "parser_fixtures.json"
)

# --------------------------------------------------------------------------
# Parser cases
# --------------------------------------------------------------------------

TEXT_CASES = {
    "unit_test_sample": """
ACME SUPPLIERS PVT LTD
Plot 21, Udyog Vihar Phase 2, Gurugram - 122015, Haryana
CIN: U74999HR2015PTC012345   GSTIN: 06AAACA1234A1Z5

TAX INVOICE

Invoice No : INV/2026/0042
Invoice Date: 05/10/2026
Place of Supply: 06 - Haryana

Bill To:
Bharat Traders LLP
45 MG Road, Bengaluru - 560001, Karnataka
GSTIN: 29ABFBL5678C1Z2

Sr  Description            HSN    Qty   Rate         Amount
1   Widget A-100            8471    10    1500.00    15,000.00
2   Widget B-200            8471     5    2200.00    11,000.00

Taxable Value:                              26,000.00
CGST @ 9%:                                   2,340.00
SGST @ 9%:                                   2,340.00
Total Invoice:                              30,680.00
Amount in Words: Rupees Thirty Thousand Six Hundred Eighty Only
""",
    "igst_indian_grouping": (
        "DELHI FINE FOODS\nGSTIN: 07AAFCD7890B1Z8\nTAX INVOICE\n"
        "Invoice No: TAXINV-1123\nBill Date: 14-09-2026\n"
        "Taxable Value: 1,45,000.00\nIGST @ 18%: 26,100.00\nTotal Invoice: 1,71,100.00\n"
    ),
    "month_name_date": "Invoice No: CA-2026-0301\nInvoice Date: 22 Sep 2026\nTotal: 65,195.00\n",
    "labeled_vendor": "Vendor Name: GANESHA TRADERS PVT LTD\nInvoice No: 1001\n",
    "percent_not_amount": "CGST @ 9%: 500\nSGST @ 9%: 500\nGrand Total: 1100\n",
    "empty": "",
    "whitespace_only": "   \n\t\n",
    "amount_on_next_line": (
        "SUNRISE ELECTRONICS\nInvoice Number - SE/889\nDate: 2026-03-07\n"
        "Taxable Amount\n12,500.50\nCGST\n1,125.05\nSGST\n1,125.05\n"
        "Amount Payable\n14,750.60\n"
    ),
    "table_header_with_tax_labels": (
        "Kaveri Paper Mills\nGSTIN 33AABCK1111L1Z9\nBill No. KPM-77\n"
        "Bill Date: 3.1.2026\nHSN Qty Rate CGST SGST Amount\n"
        "4802 100 20.00 90.00 90.00 2,000.00\nSub Total: 2,000.00\n"
        "CGST 9%: 180.00\nSGST 9%: 180.00\nRound Off: 0.00\nGrand Total: 2,360.00\n"
    ),
    "ms_prefix_and_comma_vendor": (
        "Sold By: M/s Shree Balaji Enterprises, Shop 4, Main Market\n"
        "Invoice # BAL2026-15\nDated 12/31/2026\nTotal Due: Rs. 4,999\n"
    ),
    "us_style_and_short_year": (
        "TAX INVOICE\nNorthwind Traders Ltd\nInv No: NW-0001\nDate: 25-12-26\n"
        "Net Amount 10,000\nIntegrated GST 1,800\nTotal payable 11,800\n"
    ),
    "month_first_date": "Bright Star Co\nInvoice: BSC-1009\nIssue Date: Mar 5, 2026\nTotal: 999.99\n",
    "full_month_name_date": "Kiran Stores\nInvoice No: KS-22\nDate: 22 September 2026\nTotal: 10\n",
    "invalid_date": "Moonlight Foods\nInvoice No: MF-31\nInvoice Date: 31/02/2026\n2026-04-01\nTotal: 50\n",
    "date_with_spaces": "Invoice No: A-1\nDate : 05 / 10 / 2026\n",
    "standalone_date_line": "Lotus Hardware\n14.11.2026\nInvoice No. LH/22/9\nTotal 1,234.50\n",
    "year_like_invoice_no_rejected": "Invoice No: 2026\nBill No: B-7781\nTotal: 100\n",
    "date_like_invoice_no_rejected": "Invoice No: 05/10/2026\nInvoice: QX-55\n",
    "reject_word_invoice_no": "Invoice No: date\nOrder Number: ORD_9981\n",
    "gstin_lowercase_in_text": "vendor: Tiny Co\ngstin: 24abcde1234f1z5\ntotal: 10.5\n",
    "long_vendor_truncated": (
        "Supplier: The Extraordinarily Long Named Trading Company Of Western India Private Limited\n"
        "Invoice No: L-1\n"
    ),
    "header_noise_skipped": (
        "TAX INVOICE\nPhone: 98765 43210\nwww.example.com\n1234567890\n"
        "Om Sai Distributors\nInvoice No: OSD-5\nBill Total: 3,00,000\n"
    ),
    "crlf_line_endings": "Alpha Beta Ltd\r\nInvoice No: AB-1\r\nInvoice Date: 01-01-2026\r\nTotal: 1,000.00\r\n",
    "total_tax_line_skipped": "Gamma Ltd\nTotal Tax: 180\nTotal Taxable: 1,000\nTotal: 1,180\n",
}


def _sample_pdf_cases() -> dict:
    """Text layers of the bundled sample PDFs (what the app sees on-device)."""
    try:
        import pypdf
    except ImportError:  # pragma: no cover
        return {}
    cases = {}
    for name in ("invoice_1_gst.pdf", "invoice_2_igst.pdf"):
        reader = pypdf.PdfReader(os.path.join(ROOT, "samples", name))
        cases["sample_" + name] = "\n\n".join(p.extract_text() or "" for p in reader.pages)
    return cases


def _fields(text: str) -> dict:
    f = parse_invoice_text(text)
    d = f.to_dict()
    d["missing"] = f.missing()
    return d


# --------------------------------------------------------------------------
# OCR line clustering cases: (box as 4 points, text, score)
# --------------------------------------------------------------------------


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


OCR_CASES = {
    "label_and_amount_split": [
        (_box(600, 400, 800, 430), "26,000.00", 0.9),
        (_box(40, 402, 260, 432), "Taxable Value:", 0.9),
        (_box(40, 450, 200, 480), "CGST @ 9%:", 0.9),
        (_box(610, 452, 800, 481), "2,340.00", 0.9),
        (_box(40, 100, 400, 140), "ACME SUPPLIERS PVT LTD", 0.9),
    ],
    "slightly_skewed_line": [
        (_box(10, 10, 100, 30), "Invoice", 0.9),
        (_box(105, 14, 150, 34), "No:", 0.9),
        (_box(160, 18, 300, 38), "INV-77", 0.9),
        (_box(10, 60, 100, 80), "Total", 0.9),
    ],
    "blank_text_ignored": [
        (_box(0, 0, 50, 20), "   ", 0.9),
        (_box(0, 40, 50, 60), "Hello", 0.9),
    ],
    "tiny_boxes_use_min_tolerance": [
        (_box(0, 0, 10, 2), "a", 0.9),
        (_box(20, 5, 30, 7), "b", 0.9),
        (_box(0, 20, 10, 22), "c", 0.9),
    ],
    "empty": [],
}


def build() -> dict:
    parser_cases = []
    for name, text in {**TEXT_CASES, **_sample_pdf_cases()}.items():
        parser_cases.append({"name": name, "text": text, "expected": _fields(text)})

    ocr_cases = []
    for name, items in OCR_CASES.items():
        result = [[box, text, score] for box, text, score in items]
        ocr_cases.append({
            "name": name,
            "boxes": [
                {
                    "left": min(p[0] for p in box), "top": min(p[1] for p in box),
                    "right": max(p[0] for p in box), "bottom": max(p[1] for p in box),
                    "text": text,
                }
                for box, text, _score in items
            ],
            "expected": _lines_from_boxes(result),
        })
    return {
        "_comment": "Generated by scripts/export_parser_fixtures.py - do not edit by hand.",
        "parser": parser_cases,
        "ocr_lines": ocr_cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed fixtures are out of date")
    args = ap.parse_args()

    content = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        try:
            with open(OUT, encoding="utf-8") as fh:
                current = fh.read()
        except FileNotFoundError:
            current = ""
        if current != content:
            print(f"{os.path.relpath(OUT, ROOT)} is out of date - run "
                  "`python scripts/export_parser_fixtures.py` and commit the result.")
            return 1
        print("Parser fixtures are up to date.")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    print(f"Wrote {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
