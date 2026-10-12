"""Headless command-line interface.

Examples
--------
    python main.py invoice.pdf --out results.xlsx
    python main.py invoices/ --json
    invoice-extractor a.pdf b.png --engine tesseract
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import List, Optional

from . import __version__
from .exporter import build_row, export_results
from .extractor import SUPPORTED_EXTENSIONS, extract_file_text
from .ocr import Ocr, available_engines
from .parser import parse_invoice_text

__all__ = ["run"]


def _collect_files(paths: List[str]) -> List[str]:
    files: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                ext = os.path.splitext(name)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    files.append(os.path.join(p, name))
        else:
            files.append(p)
    return files


def run(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="invoice-extractor",
        description=(
            "Batch-extract invoice fields (Invoice No, Date, Vendor, GSTIN, "
            "Taxable, CGST, SGST, IGST, Total) from PDF and image invoices "
            "and export the results to Excel."
        ),
    )
    parser.add_argument("files", nargs="*", help="invoice files or folders")
    parser.add_argument("--out", default=None,
                        help="Excel (.xlsx) output path (default: invoices_<timestamp>.xlsx)")
    parser.add_argument("--engine", choices=["auto", "rapidocr", "tesseract"],
                        default="auto", help="OCR engine to use (default: auto)")
    parser.add_argument("--json", action="store_true",
                        help="print the results as JSON to stdout")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    files = _collect_files(args.files)
    if not files:
        parser.error("no input files given (pass files, or a folder containing invoices)")

    ocr = Ocr(engine=None if args.engine == "auto" else args.engine,
              log=lambda m: print(f"[ocr] {m}", file=sys.stderr))
    if not ocr.available:
        print("ERROR: no OCR engine is available. Install requirements "
              "(pip install -r requirements.txt).", file=sys.stderr)
        return 2

    ocr.warmup()
    print(f"OCR engine: {ocr.engine_name}", file=sys.stderr)
    print("Available engines: " + ", ".join(
        f"{e.name} ({'ok' if e.available else 'unavailable'})" for e in available_engines()
    ), file=sys.stderr)

    rows = []
    for path in files:
        print(f"[*] {os.path.basename(path)}", file=sys.stderr)
        outcome = extract_file_text(
            path, ocr, log=lambda m, p=path: print(f"    {m}", file=sys.stderr)
        )
        if outcome.error:
            rows.append(build_row(path, status="Error", note=outcome.error))
            continue
        fields = parse_invoice_text(outcome.text)
        missing = fields.missing()
        status = "OK" if (fields.invoice_no or fields.total) else "No data found"
        note = ("Missing: " + ", ".join(missing)) if missing else ""
        rows.append(build_row(path, fields=fields, status=status,
                              method=outcome.method, engine=outcome.ocr_engine,
                              note=note))

    out_path = args.out
    if not out_path and not args.json:
        out_path = f"invoices_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    if out_path:
        try:
            export_results(rows, out_path)
            print(f"Saved: {out_path}", file=sys.stderr)
        except Exception as exc:
            print(f"ERROR: could not write Excel file: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps(rows, indent=2, default=str))

    ok_count = sum(
        1 for r in rows if str(r["Status"]).lower() not in {"error", "no data found"}
    )
    print(f"Done: {ok_count}/{len(rows)} file(s) with data.", file=sys.stderr)
    return 0 if ok_count else 1
