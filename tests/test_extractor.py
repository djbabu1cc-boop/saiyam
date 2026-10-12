"""End-to-end extraction tests against the bundled sample invoices.

The OCR tests (PNG image + scanned PDF) load the RapidOCR model and take
tens of seconds on a slow CPU - they are the slow part of this suite.
"""
import os
import re
import unittest

from invoice_extractor.extractor import extract_file_text
from invoice_extractor.ocr import Ocr
from invoice_extractor.parser import parse_invoice_text

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.normpath(os.path.join(HERE, "..", "samples"))


def _sample(name: str) -> str:
    return os.path.join(SAMPLES, name)


def _require_samples():
    missing = [
        n for n in (
            "invoice_1_gst.pdf", "invoice_2_igst.pdf",
            "invoice_3_image.png", "invoice_4_scanned.pdf",
        ) if not os.path.exists(_sample(n))
    ]
    if missing:
        raise unittest.SkipTest(
            "sample files missing: %s (run scripts/generate_samples.py)" % missing
        )


class TestTextPdfs(unittest.TestCase):
    """Samples 1 & 2 use the PDF text layer (fast, no OCR)."""

    def setUp(self):
        _require_samples()
        self.ocr = Ocr(log=lambda m: None)

    def _extract(self, name: str):
        outcome = extract_file_text(_sample(name), self.ocr, log=lambda m: None)
        self.assertTrue(outcome.ok, f"{name}: {outcome.error}")
        return outcome

    def test_invoice_1(self):
        outcome = self._extract("invoice_1_gst.pdf")
        self.assertEqual(outcome.method, "pdf-text")
        f = parse_invoice_text(outcome.text)
        self.assertEqual(f.invoice_no, "INV/2026/0042")
        self.assertEqual(f.date, "2026-10-05")
        self.assertEqual(f.gstin, "06AAACA1234A1Z5")
        self.assertEqual(f.vendor, "ACME SUPPLIERS PVT LTD")
        self.assertEqual(f.taxable, 26000.0)
        self.assertEqual(f.cgst, 2340.0)
        self.assertEqual(f.sgst, 2340.0)
        self.assertEqual(f.total, 30680.0)

    def test_invoice_2(self):
        outcome = self._extract("invoice_2_igst.pdf")
        self.assertEqual(outcome.method, "pdf-text")
        f = parse_invoice_text(outcome.text)
        self.assertEqual(f.invoice_no, "TAXINV-1123")
        self.assertEqual(f.date, "2026-09-14")
        self.assertEqual(f.gstin, "07AAFCD7890B1Z8")
        self.assertEqual(f.vendor, "DELHI FINE FOODS")
        self.assertEqual(f.taxable, 145000.0)
        self.assertEqual(f.igst, 26100.0)
        self.assertEqual(f.total, 171100.0)


class TestOcrExtraction(unittest.TestCase):
    """Samples 3 & 4 go through the OCR engine."""

    def setUp(self):
        _require_samples()
        self.ocr = Ocr(log=lambda m: None)
        if not self.ocr.available:
            raise unittest.SkipTest("no OCR engine available in this environment")
        self.ocr.warmup()

    def _extract(self, name: str):
        outcome = extract_file_text(_sample(name), self.ocr, log=lambda m: None)
        self.assertTrue(outcome.ok, f"{name}: {outcome.error}")
        return outcome

    def test_invoice_3_image(self):
        outcome = self._extract("invoice_3_image.png")
        self.assertEqual(outcome.method, "image-ocr")
        f = parse_invoice_text(outcome.text)
        self.assertEqual(f.invoice_no, "BKT-2026-0078")
        self.assertEqual(f.date, "2026-10-01")
        self.assertEqual(f.gstin, "29AABCS9876D1Z9")
        # OCR may drop the space in "SILK ROAD" -> compare without spaces
        self.assertEqual(re.sub(r"\s+", "", f.vendor).upper(), "SILKROADSTATIONERS")
        self.assertEqual(f.taxable, 8400.0)
        self.assertEqual(f.cgst, 756.0)
        self.assertEqual(f.sgst, 756.0)
        self.assertEqual(f.total, 9912.0)

    def test_invoice_4_scanned_pdf(self):
        outcome = self._extract("invoice_4_scanned.pdf")
        self.assertEqual(outcome.method, "pdf-ocr")
        self.assertGreater(outcome.pages, 0)
        f = parse_invoice_text(outcome.text)
        self.assertEqual(f.invoice_no, "CA-2026-0301")
        self.assertEqual(f.date, "2026-09-22")
        self.assertEqual(f.gstin, "33AAKCC8765D1Z3")
        self.assertEqual(f.vendor, "CHENNAI AUTO PARTS")
        self.assertEqual(f.taxable, 55250.0)
        self.assertEqual(f.igst, 9945.0)
        self.assertEqual(f.total, 65195.0)


class TestErrorHandling(unittest.TestCase):
    def test_unsupported_extension(self):
        outcome = extract_file_text(__file__, Ocr(log=lambda m: None))
        self.assertFalse(outcome.ok)
        self.assertIn("Unsupported file type", outcome.error)

    def test_missing_file(self):
        outcome = extract_file_text("/nonexistent/invoice.pdf", Ocr(log=lambda m: None))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error, "File not found")

    def test_corrupt_pdf(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4\nthis is not a real pdf")
            tmp_path = tmp.name
        try:
            outcome = extract_file_text(tmp_path, Ocr(log=lambda m: None))
            self.assertFalse(outcome.ok)
            self.assertTrue(outcome.error)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
