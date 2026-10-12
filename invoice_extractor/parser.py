"""Parse raw invoice text into structured fields.

The parser is deliberately heuristic - real-world invoices vary widely.
Every field is looked up with several labelled patterns plus a fallback,
and anything the parser cannot find is simply left empty (never guessed).

Supported field labels include (case-insensitive, extra words tolerated):

* Invoice number : "Invoice No", "Invoice Number", "Inv. No", "Bill No",
  "Doc No", "Invoice: XYZ-123"
* Date           : "Invoice Date", "Bill Date", "Doc Date", "Date of Supply",
  formats 05/10/2026, 14-09-2026, 05.10.2026, 2026-09-14, 22 Sep 2026 ...
* Vendor         : "Vendor/Supplier/Seller/From/Sold by: ...", otherwise the
  first plausible header line of the document
* GSTIN          : any 15-character Indian GSTIN pattern in the text
* Taxable amount : "Taxable Value/Amount", "Assessable Value", "Sub Total" ...
* CGST / SGST / IGST : labelled lines (also "Central/State/Integrated GST")
* Total          : "Grand Total", "Invoice Total", "Total Invoice",
  "Amount Payable", bare "Total: ..."
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

__all__ = ["InvoiceFields", "parse_invoice_text"]

# --------------------------------------------------------------------------
# Amounts
# --------------------------------------------------------------------------

# Matches "1234", "1234.56", "1,234,567.89" (western grouping) and
# "1,45,000.00" (Indian 2-2-3 grouping). Percentages ("9%") are excluded.
AMOUNT_TOKEN_RE = re.compile(r"(?<![\d.,])(\d[\d,]*(?:\.\d{1,2})?)(?![\d.,])(?!\s*%)")


def _to_float(token: str) -> Optional[float]:
    t = token.replace(",", "")
    if t.count(".") > 1 or not t.replace(".", "", 1).isdigit():
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _amounts(line: str) -> List[float]:
    vals: List[float] = []
    for m in AMOUNT_TOKEN_RE.finditer(line):
        v = _to_float(m.group(1))
        if v is not None:
            vals.append(v)
    return vals


def _last_amount(line: str) -> Optional[float]:
    vals = _amounts(line)
    return vals[-1] if vals else None


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_DATE_TOKEN = (
    r"(\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}"
    r"|\d{4}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{1,2}"
    r"|\d{1,2}\s+" + _MONTHS + r"[a-z]*\.?\s*,?\s+\d{4}"
    r"|" + _MONTHS + r"[a-z]*\.?\s+\d{1,2}\s*,?\s+\d{4})"
)

DATE_LABELED_RE = re.compile(
    r"\b(?:invoice\s+date|bill\s+date|doc(?:ument)?\s*date|order\s+date|supply\s+date"
    r"|date\s+of\s+supply|issue\s+date|tax\s+date|date)\b"
    r"\s*[:\-#]?\s*" + _DATE_TOKEN,
    re.IGNORECASE,
)

DATE_STANDALONE_RE = re.compile(
    r"^" + _DATE_TOKEN + r"$", re.IGNORECASE
)

_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d/%m/%y", "%d-%m-%y",
    "%Y-%m-%d", "%Y/%m/%d",
    "%d %b %Y", "%d %b, %Y", "%d-%b-%Y", "%d/%b/%Y",
    "%b %d %Y", "%b %d, %Y",
    "%m/%d/%Y", "%m-%d-%Y",
)


def _parse_date_token(raw: str) -> Optional[str]:
    s = re.sub(r"\s+", " ", raw.strip())
    for variant in (s, s.replace(".", "/"), s.replace("-", "/")):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(variant, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------
# Invoice number
# --------------------------------------------------------------------------

INV_NO_RES = (
    re.compile(
        r"\b(?:invoice|inv|bill|doc(?:ument)?|proforma|quote|order)\s*"
        r"(?:no|number|num\.?)\s*(?:\.|:|#|\-|\s)+\s*"
        r"([A-Za-z0-9][A-Za-z0-9\-_/]{1,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:invoice|bill)\s*[:#]\s*([A-Za-z][A-Za-z0-9\-_/]{2,40})",
        re.IGNORECASE,
    ),
)

_INV_NO_REJECT = {
    "no", "number", "num", "date", "gstin", "gst", "of", "the", "a", "and",
    "for", "note", "notes", "to", "from", "per", "page", "total", "amount",
    "value", "tax", "inr", "rs",
}


def _clean_invoice_no(value: str) -> str:
    v = value.strip().rstrip(".,;:")
    if not (2 <= len(v) <= 45):
        return ""
    if v.lower() in _INV_NO_REJECT:
        return ""
    if re.fullmatch(r"\d{4}", v):  # almost certainly a year
        return ""
    if re.fullmatch(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}", v):  # a date
        return ""
    return v


# --------------------------------------------------------------------------
# GSTIN
# --------------------------------------------------------------------------

# 15 chars: state code (2 digits) + PAN (9: 5 letters, 4 digits, 1 letter)
# + entity number (3) + check char (1)
GSTIN_RE = re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3})\b")


# --------------------------------------------------------------------------
# Vendor
# --------------------------------------------------------------------------

VENDOR_LABELED_RE = re.compile(
    r"^\s*(?:vendor|supplier|seller|merchant|from|sold\s*by|name\s+of\s+supplier"
    r"|supplying\s+dealer|party|company|firm)\s*(?:name)?\s*[:\-]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Lines that are almost certainly NOT a company name. Kept deliberately
# conservative: company names may contain words like "Road" or "Market"
# (e.g. "Silk Road Stationers"), so we only skip lines that start with a
# number, have a "street word + number" pattern, or contain obvious address
# markers.
_VENDOR_STOP_RE = re.compile(
    r"^\s*\d"
    r"|\b(road|street|lane|avenue|cross|nagar|colony|park)\s*\d"
    r"|\b(near|opposite|opp\.?|plot|phase|pin\s*code|zip\s*code"
    r"|regd|registered|m\.?s\s*$)\b",
    re.IGNORECASE,
)

_VENDOR_NOISE_RE = re.compile(
    r"(?:\bgst\s*no\b|\bgstin\b|\bcin\b|\bpan\b|\bemailed?to\b|\bphone\b|\btel\b"
    r"|\bfax\b|\bwebsite\b|www\.|@|regd\.|registered|m/s\s*$)",
    re.IGNORECASE,
)

_TITLE_NOISE_RE = re.compile(
    r"^(?:tax\s*)?(?:invoice|bill|pro-?forma|credit\s*note|debit\s*note|estimate"
    r"|quotation|tax\s*credit\s*note|gst\s+invoice)"
    r"(?:\s*(?:note|no|number))?\s*[:\-]?\s*$",
    re.IGNORECASE,
)


def _clean_vendor(value: str) -> str:
    v = value.strip().strip(":;-").strip()
    v = re.sub(r"^(?:m/s|mesa\s*services)\s*[,:\-]?\s*", "", v, flags=re.IGNORECASE)
    if "," in v:
        head = v.split(",")[0].strip()
        if 3 <= len(head) <= 48:
            v = head
    v = re.sub(r"\s{2,}", " ", v)
    if len(v) > 60:
        v = v[:60].rstrip()
    return v


def _vendor_from_header(lines: List[str]) -> str:
    """Fallback: first plausible company name in the document header."""
    for line in lines[:15]:
        s = line.strip()
        if not s or len(s) < 3:
            continue
        if _TITLE_NOISE_RE.match(s):
            continue
        if GSTIN_RE.search(s.upper()):
            continue
        if _VENDOR_STOP_RE.search(s):
            continue
        if _VENDOR_NOISE_RE.search(s):
            continue
        if re.fullmatch(r"[\d\s\-/,.()A-Za-z]{0,3}\d{4,}", s):
            continue
        if not re.search(r"[A-Za-z]{3,}", s):
            continue
        return _clean_vendor(s)
    return ""


# --------------------------------------------------------------------------
# Money labels
# --------------------------------------------------------------------------

TAXABLE_RE = re.compile(
    r"\b(?:taxable\s+value|taxable\s+amount|total\s+taxable|assessable\s+value"
    r"|assessable\s+amount|net\s+amount|net\s+total|sub-?total|total\s+before\s+tax)\b",
    re.IGNORECASE,
)
CGST_RE = re.compile(r"\b(?:cgst|central\s+gst)\b", re.IGNORECASE)
SGST_RE = re.compile(r"\b(?:sgst|state\s+gst)\b", re.IGNORECASE)
IGST_RE = re.compile(r"\b(?:igst|integrated\s+gst)\b", re.IGNORECASE)

TOTAL_RES = (
    re.compile(
        r"\b(?:grand\s+total|invoice\s+total|total\s+invoice|bill\s+total"
        r"|total\s+amount\s+payable|amount\s+payable|total\s+payable"
        r"|total\s+due|payable\s+amount|rounded\s+total)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*total\s*(?:amount)?\s*[:\-]?", re.IGNORECASE | re.MULTILINE),
)

_SKIP_TOTAL_LINE = re.compile(r"round\s*off|total\s+tax|tax\s+total|taxable", re.IGNORECASE)
_TABLE_HEADER_RE = re.compile(
    r"\b(?:qty|quantity|rate|hsn|sac|description|particulars|part\s*no|item\s*no"
    r"|s\.?\s?no)\b",
    re.IGNORECASE,
)


def _find_amount_for(
    lines: List[str],
    regex,
    look_ahead: int = 2,
    skip_re=None,
) -> Optional[float]:
    """Find the first line matching *regex* and return its trailing amount."""
    label_res = (TAXABLE_RE, CGST_RE, SGST_RE, IGST_RE)
    for i, line in enumerate(lines):
        if skip_re is not None and skip_re.search(line):
            continue
        if not regex.search(line):
            continue
        val = _last_amount(line)
        if val is None and not _TABLE_HEADER_RE.search(line):
            # Label present but amount on the next line(s).
            for j in range(i + 1, min(i + 1 + look_ahead, len(lines))):
                nxt = lines[j]
                if any(rx.search(nxt) for rx in label_res):
                    break
                val = _last_amount(nxt)
                if val is not None:
                    break
        elif val is None:
            # A table header such as "HSN Qty Rate CGST SGST" - skip it.
            continue
        if val is not None:
            return val
    return None


# --------------------------------------------------------------------------
# Result container + public API
# --------------------------------------------------------------------------


@dataclass
class InvoiceFields:
    """Structured data extracted from a single invoice."""

    invoice_no: str = ""
    date: str = ""  # ISO format YYYY-MM-DD, "" when unknown
    vendor: str = ""
    gstin: str = ""
    taxable: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    total: Optional[float] = None

    def missing(self) -> List[str]:
        items = [
            ("Invoice No", self.invoice_no),
            ("Date", self.date),
            ("Vendor", self.vendor),
            ("GSTIN", self.gstin),
            ("Total", self.total),
        ]
        return [name for name, value in items if not value]

    def to_dict(self) -> dict:
        return {
            "invoice_no": self.invoice_no,
            "date": self.date,
            "vendor": self.vendor,
            "gstin": self.gstin,
            "taxable": self.taxable,
            "cgst": self.cgst,
            "sgst": self.sgst,
            "igst": self.igst,
            "total": self.total,
        }


def parse_invoice_text(text: str) -> InvoiceFields:
    """Extract invoice fields from raw text (PDF text layer or OCR output)."""
    fields = InvoiceFields()
    if not text or not text.strip():
        return fields

    lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]
    upper_text = "\n".join(ln.upper() for ln in lines)

    # --- GSTIN -----------------------------------------------------------
    m = GSTIN_RE.search(upper_text)
    if m:
        fields.gstin = m.group(1)

    # --- Invoice number ----------------------------------------------------
    for rx in INV_NO_RES:
        for m in rx.finditer(text):
            v = _clean_invoice_no(m.group(1))
            if v:
                fields.invoice_no = v
                break
        if fields.invoice_no:
            break

    # --- Date ----------------------------------------------------------------
    m = DATE_LABELED_RE.search(text)
    if m:
        fields.date = _parse_date_token(m.group(1)) or ""
    if not fields.date:
        for line in lines[:40]:
            m2 = DATE_STANDALONE_RE.match(line.strip())
            if m2:
                fields.date = _parse_date_token(m2.group(1)) or ""
                if fields.date:
                    break

    # --- Vendor --------------------------------------------------------------
    m = VENDOR_LABELED_RE.search(text)
    if m:
        fields.vendor = _clean_vendor(m.group(1))
    if not fields.vendor:
        fields.vendor = _vendor_from_header(lines)

    # --- Amounts ---------------------------------------------------------------
    fields.taxable = _find_amount_for(lines, TAXABLE_RE)
    fields.cgst = _find_amount_for(lines, CGST_RE)
    fields.sgst = _find_amount_for(lines, SGST_RE)
    fields.igst = _find_amount_for(lines, IGST_RE)
    for rx in TOTAL_RES:
        fields.total = _find_amount_for(lines, rx, skip_re=_SKIP_TOTAL_LINE)
        if fields.total is not None:
            break

    return fields
