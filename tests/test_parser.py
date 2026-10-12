"""Fast unit tests for the text parser (no OCR, no files)."""
import unittest

from invoice_extractor.parser import parse_invoice_text

SAMPLE_TEXT = """
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
"""


class TestParser(unittest.TestCase):
    def setUp(self):
        self.f = parse_invoice_text(SAMPLE_TEXT)

    def test_invoice_no(self):
        self.assertEqual(self.f.invoice_no, "INV/2026/0042")

    def test_date(self):
        self.assertEqual(self.f.date, "2026-10-05")

    def test_vendor(self):
        self.assertEqual(self.f.vendor, "ACME SUPPLIERS PVT LTD")

    def test_gstin(self):
        self.assertEqual(self.f.gstin, "06AAACA1234A1Z5")

    def test_amounts(self):
        self.assertEqual(self.f.taxable, 26000.0)
        self.assertEqual(self.f.cgst, 2340.0)
        self.assertEqual(self.f.sgst, 2340.0)
        self.assertIsNone(self.f.igst)
        self.assertEqual(self.f.total, 30680.0)

    def test_missing_reports(self):
        self.assertEqual(self.f.missing(), [])

    def test_empty_text(self):
        f = parse_invoice_text("")
        self.assertEqual(f.invoice_no, "")
        self.assertIsNone(f.total)

    def test_igst_indian_grouping(self):
        text = (
            "DELHI FINE FOODS\n"
            "GSTIN: 07AAFCD7890B1Z8\n"
            "TAX INVOICE\n"
            "Invoice No: TAXINV-1123\n"
            "Bill Date: 14-09-2026\n"
            "Taxable Value: 1,45,000.00\n"
            "IGST @ 18%: 26,100.00\n"
            "Total Invoice: 1,71,100.00\n"
        )
        f = parse_invoice_text(text)
        self.assertEqual(f.invoice_no, "TAXINV-1123")
        self.assertEqual(f.date, "2026-09-14")
        self.assertEqual(f.taxable, 145000.0)
        self.assertEqual(f.igst, 26100.0)
        self.assertEqual(f.total, 171100.0)

    def test_month_name_date(self):
        text = "Invoice No: CA-2026-0301\nInvoice Date: 22 Sep 2026\nTotal: 65,195.00\n"
        f = parse_invoice_text(text)
        self.assertEqual(f.date, "2026-09-22")
        self.assertEqual(f.total, 65195.0)

    def test_labeled_vendor(self):
        text = "Vendor Name: GANESHA TRADERS PVT LTD\nInvoice No: 1001\n"
        f = parse_invoice_text(text)
        self.assertEqual(f.vendor, "GANESHA TRADERS PVT LTD")

    def test_percent_not_treated_as_amount(self):
        text = "CGST @ 9%: 500\nSGST @ 9%: 500\nGrand Total: 1100\n"
        f = parse_invoice_text(text)
        self.assertEqual(f.cgst, 500.0)
        self.assertEqual(f.total, 1100.0)


if __name__ == "__main__":
    unittest.main()
