"""Regenerate the sample invoices in the ``samples/`` folder.

Run:
    pip install -r requirements-dev.txt
    python scripts/generate_samples.py

Creates four samples covering every extraction path:
    invoice_1_gst.pdf        - text PDF, intrastate (CGST + SGST)
    invoice_2_igst.pdf       - text PDF, interstate (IGST), Indian 2-2-3 grouping
    invoice_3_image.png      - image invoice (OCR path)
    invoice_4_scanned.pdf    - image-only ("scanned") PDF (render + OCR path)
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "samples"))

FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "C:/Windows/Fonts",
)
FONT_CANDIDATES = ("DejaVuSans.ttf", "arial.ttf", "calibri.ttf", "segoeui.ttf")


def _find_font() -> str:
    for d in FONT_DIRS:
        for name in FONT_CANDIDATES:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    raise SystemExit("No usable TTF font found (install a DejaVu font).")


def _text_pdf(path: str, lines) -> None:
    """Render simple labelled lines into an A4 text PDF."""
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 60
    for text, size, bold, dx in lines:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(dx, y, text)
        y -= size * 1.55
    c.save()


def _render_image(lines, width: int = 1600, base_size: int = 34,
                  pad: int = 90) -> Image.Image:
    """Render invoice lines onto a white A4-ish image (for OCR samples)."""
    font_path = _find_font()
    fonts = {size: ImageFont.truetype(font_path, size) for size in (base_size, base_size + 8)}
    small = fonts[base_size]
    big = fonts[base_size + 8]

    line_boxes = []
    for text, bold in lines:
        f = big if bold else small
        line_boxes.append((text, f))
    line_h = (base_size + 8) * 1.7
    height = int(pad * 2 + line_h * len(line_boxes))

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = pad
    for text, f in line_boxes:
        draw.text((pad, y), text, font=f, fill="black")
        y += line_h
    return img


# ---------------------------------------------------------------------------
# Invoice 1: text PDF, intrastate (CGST + SGST)
# ---------------------------------------------------------------------------

INVOICE_1 = [
    ("ACME SUPPLIERS PVT LTD", 16, True, 50),
    ("Plot 21, Udyog Vihar Phase 2, Gurugram - 122015, Haryana", 10, False, 50),
    ("CIN: U74999HR2015PTC012345   GSTIN: 06AAACA1234A1Z5", 10, False, 50),
    ("", 10, False, 50),
    ("TAX INVOICE", 15, True, 50),
    ("", 10, False, 50),
    ("Invoice No : INV/2026/0042", 11, False, 50),
    ("Invoice Date: 05/10/2026", 11, False, 50),
    ("Place of Supply: 06 - Haryana", 11, False, 50),
    ("", 10, False, 50),
    ("Bill To:", 11, True, 50),
    ("Bharat Traders LLP", 11, False, 50),
    ("45 MG Road, Bengaluru - 560001, Karnataka", 10, False, 50),
    ("GSTIN: 29ABFBL5678C1Z2", 10, False, 50),
    ("", 10, False, 50),
    ("Sr  Description            HSN    Qty   Rate         Amount", 10, True, 50),
    ("1   Widget A-100            8471    10    1500.00    15,000.00", 10, False, 50),
    ("2   Widget B-200            8471     5    2200.00    11,000.00", 10, False, 50),
    ("", 10, False, 50),
    ("Taxable Value:                              26,000.00", 11, True, 50),
    ("CGST @ 9%:                                   2,340.00", 11, False, 50),
    ("SGST @ 9%:                                   2,340.00", 11, False, 50),
    ("Total Invoice:                              30,680.00", 12, True, 50),
    ("Amount in Words: Rupees Thirty Thousand Six Hundred Eighty Only", 9, False, 50),
]


# ---------------------------------------------------------------------------
# Invoice 2: text PDF, interstate (IGST), Indian digit grouping
# ---------------------------------------------------------------------------

INVOICE_2 = [
    ("DELHI FINE FOODS", 16, True, 50),
    ("2nd Floor, Lajpat Nagar Market, New Delhi - 110024", 10, False, 50),
    ("GSTIN: 07AAFCD7890B1Z8", 10, False, 50),
    ("", 10, False, 50),
    ("TAX INVOICE", 15, True, 50),
    ("Invoice No: TAXINV-1123", 11, False, 50),
    ("Bill Date: 14-09-2026", 11, False, 50),
    ("Reverse Charge: No", 11, False, 50),
    ("", 10, False, 50),
    ("To:", 11, True, 50),
    ("Shree Ganesh Agencies", 11, False, 50),
    ("12, Gandhi Road, Mysuru - 570001, Karnataka", 10, False, 50),
    ("", 10, False, 50),
    ("Item                   HSN    Qty   Rate           Amount", 10, True, 50),
    ("Basmati Rice 25kg      1006     4     36,250.00    1,45,000.00", 10, False, 50),
    ("", 10, False, 50),
    ("Taxable Value:                           1,45,000.00", 11, True, 50),
    ("IGST @ 18%:                                  26,100.00", 11, False, 50),
    ("Total Invoice:                           1,71,100.00", 12, True, 50),
    ("Amount in Words: Rupees One Lakh Seventy-One Thousand One Hundred Only", 9, False, 50),
]


# ---------------------------------------------------------------------------
# Invoice 3: PNG image (OCR path)
# ---------------------------------------------------------------------------

INVOICE_3 = [
    ("SILK ROAD STATIONERS", True),
    ("17, 100 Feet Road, Indiranagar, Bengaluru - 560038", False),
    ("GSTIN: 29AABCS9876D1Z9", False),
    ("", False),
    ("TAX INVOICE", True),
    ("Invoice No: BKT-2026-0078", False),
    ("Invoice Date: 01/10/2026", False),
    ("", False),
    ("Bill To:", True),
    ("Krishna Enterprises", False),
    ("80, 1st Cross, Jayanagar 4th Block, Bengaluru - 560041", False),
    ("", False),
    ("Notebooks (Box of 50)          Qty   6     Rate  1400.00     Amount  8400.00", False),
    ("", False),
    ("Taxable Value:                        8,400.00", True),
    ("CGST @ 9%:                               756.00", False),
    ("SGST @ 9%:                               756.00", False),
    ("Total Invoice:                        9,912.00", True),
    ("Amount in Words: Rupees Nine Thousand Nine Hundred Twelve Only", False),
]


# ---------------------------------------------------------------------------
# Invoice 4: scanned (image-only) PDF (render + OCR path)
# ---------------------------------------------------------------------------

INVOICE_4 = [
    ("CHENNAI AUTO PARTS", True),
    ("No. 8, Coimbatore High Road, Kilpauk, Chennai - 600010", False),
    ("GSTIN: 33AAKCC8765D1Z3", False),
    ("", False),
    ("TAX INVOICE", True),
    ("Invoice No: CA-2026-0301", False),
    ("Invoice Date: 22 Sep 2026", False),
    ("", False),
    ("To:", True),
    ("Madurai Motors", False),
    ("22, Trichy Road, Madurai - 625009", False),
    ("", False),
    ("CA-101  Oil Filter              Qty  10    Rate   350.00    Amount  3,500.00", False),
    ("CA-205  Brake Pad Set            Qty   9    Rate 5,750.00    Amount 51,750.00", False),
    ("", False),
    ("Taxable Value:                       55,250.00", True),
    ("IGST @ 18%:                            9,945.00", False),
    ("Total Invoice:                       65,195.00", True),
    ("Amount in Words: Rupees Sixty-Five Thousand One Hundred Ninety-Five Only", False),
]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    _text_pdf(os.path.join(OUT, "invoice_1_gst.pdf"), INVOICE_1)
    _text_pdf(os.path.join(OUT, "invoice_2_igst.pdf"), INVOICE_2)

    img3 = _render_image(INVOICE_3)
    img3.save(os.path.join(OUT, "invoice_3_image.png"))

    # Scanned PDF: embed the rendered image as the only content (no text layer)
    img4 = _render_image(INVOICE_4)
    tmp_png = os.path.join(OUT, "_tmp_invoice_4.png")
    img4.save(tmp_png)
    c = canvas.Canvas(os.path.join(OUT, "invoice_4_scanned.pdf"), pagesize=A4)
    width, height = A4
    c.drawImage(tmp_png, 0, 0, width=width, height=height, preserveAspectRatio=False)
    c.showPage()
    c.save()
    os.remove(tmp_png)

    for name in ("invoice_1_gst.pdf", "invoice_2_igst.pdf",
                 "invoice_3_image.png", "invoice_4_scanned.pdf"):
        p = os.path.join(OUT, name)
        print(f"wrote {p} ({os.path.getsize(p)} bytes)")


if __name__ == "__main__":
    main()
