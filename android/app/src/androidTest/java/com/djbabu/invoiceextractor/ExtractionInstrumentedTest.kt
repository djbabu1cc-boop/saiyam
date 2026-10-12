package com.djbabu.invoiceextractor

import android.content.Context
import android.net.Uri
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.djbabu.invoiceextractor.core.InvoiceParser
import com.djbabu.invoiceextractor.core.ResultRow
import com.djbabu.invoiceextractor.core.XlsxExporter
import com.djbabu.invoiceextractor.extract.ExtractionOutcome
import com.djbabu.invoiceextractor.extract.InvoiceTextExtractor
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.zip.ZipFile

/**
 * Runs the real on-device pipeline (PDFBox, PdfRenderer, ML Kit OCR, XLSX
 * writer) against the same sample invoices as the desktop test-suite
 * (tests/test_extractor.py), with the same expected values.
 */
@RunWith(AndroidJUnit4::class)
class ExtractionInstrumentedTest {

    private lateinit var app: Context
    private lateinit var extractor: InvoiceTextExtractor

    @Before
    fun setUp() {
        app = InstrumentationRegistry.getInstrumentation().targetContext
        extractor = InvoiceTextExtractor(app)
    }

    @After
    fun tearDown() = extractor.close()

    /** Copy a sample from the test APK's assets (repo `samples/`) into app storage. */
    private fun sample(name: String): Uri {
        val testAssets = InstrumentationRegistry.getInstrumentation().context.assets
        val out = File(app.cacheDir, "samples/$name").apply { parentFile!!.mkdirs() }
        testAssets.open(name).use { i -> out.outputStream().use { o -> i.copyTo(o) } }
        return Uri.fromFile(out)
    }

    private fun extract(name: String): ExtractionOutcome {
        val outcome = extractor.extract(sample(name), name)
        assertTrue("$name: ${outcome.error}", outcome.ok)
        return outcome
    }

    @Test
    fun textPdfIntrastate() {
        val o = extract("invoice_1_gst.pdf")
        assertEquals("pdf-text", o.method)
        val f = InvoiceParser.parse(o.text)
        assertEquals("INV/2026/0042", f.invoiceNo)
        assertEquals("2026-10-05", f.date)
        assertEquals("06AAACA1234A1Z5", f.gstin)
        assertEquals("ACME SUPPLIERS PVT LTD", f.vendor)
        assertEquals(26000.0, f.taxable)
        assertEquals(2340.0, f.cgst)
        assertEquals(2340.0, f.sgst)
        assertEquals(30680.0, f.total)
    }

    @Test
    fun textPdfInterstateIndianGrouping() {
        val o = extract("invoice_2_igst.pdf")
        assertEquals("pdf-text", o.method)
        val f = InvoiceParser.parse(o.text)
        assertEquals("TAXINV-1123", f.invoiceNo)
        assertEquals("2026-09-14", f.date)
        assertEquals("07AAFCD7890B1Z8", f.gstin)
        assertEquals("DELHI FINE FOODS", f.vendor)
        assertEquals(145000.0, f.taxable)
        assertEquals(26100.0, f.igst)
        assertEquals(171100.0, f.total)
    }

    @Test
    fun imageInvoiceOcr() {
        val o = extract("invoice_3_image.png")
        assertEquals("image-ocr", o.method)
        assertEquals("mlkit", o.ocrEngine)
        val f = InvoiceParser.parse(o.text)
        val ctx = "OCR text:\n${o.text}"
        assertEquals(ctx, "BKT-2026-0078", f.invoiceNo)
        assertEquals(ctx, "2026-10-01", f.date)
        assertEquals(ctx, "29AABCS9876D1Z9", f.gstin)
        assertEquals(ctx, "SILKROADSTATIONERS", f.vendor.replace(Regex("\\s+"), "").uppercase())
        assertEquals(ctx, 8400.0, f.taxable)
        assertEquals(ctx, 756.0, f.cgst)
        assertEquals(ctx, 756.0, f.sgst)
        assertEquals(ctx, 9912.0, f.total)
    }

    @Test
    fun scannedPdfRenderedAndOcrd() {
        val o = extract("invoice_4_scanned.pdf")
        assertEquals("pdf-ocr", o.method)
        assertTrue(o.pages > 0)
        val f = InvoiceParser.parse(o.text)
        val ctx = "OCR text:\n${o.text}"
        assertEquals(ctx, "CA-2026-0301", f.invoiceNo)
        assertEquals(ctx, "2026-09-22", f.date)
        assertEquals(ctx, "33AAKCC8765D1Z3", f.gstin)
        assertEquals(ctx, "CHENNAI AUTO PARTS", f.vendor)
        assertEquals(ctx, 55250.0, f.taxable)
        assertEquals(ctx, 9945.0, f.igst)
        assertEquals(ctx, 65195.0, f.total)
    }

    @Test
    fun errorsAreReportedNotThrown() {
        val corrupt = File(app.cacheDir, "corrupt.pdf").apply { writeText("this is not a pdf") }
        assertFalse(extractor.extract(Uri.fromFile(corrupt), corrupt.name).ok)

        val tiff = extractor.extract(Uri.fromFile(File(app.cacheDir, "scan.tiff")), "scan.tiff")
        assertTrue(tiff.error.contains("TIFF"))

        val missing = extractor.extract(Uri.fromFile(File(app.cacheDir, "nope.pdf")), "nope.pdf")
        assertFalse(missing.ok)

        val txt = extractor.extract(Uri.fromFile(corrupt), "notes.txt")
        assertTrue(txt.error.startsWith("Unsupported file type"))
    }

    @Test
    fun workbookIsWritten() {
        val rows = listOf("invoice_1_gst.pdf", "invoice_2_igst.pdf").map { name ->
            val o = extract(name)
            ResultRow.fromExtraction(name, o.text, o.method, o.ocrEngine)
        } + ResultRow.error("broken.pdf", "boom")
        val out = File(app.cacheDir, "test.xlsx")
        out.outputStream().use { XlsxExporter.write(rows, it) }
        ZipFile(out).use { zip ->
            val sheet = zip.getInputStream(zip.getEntry("xl/worksheets/sheet1.xml")).readBytes().toString(Charsets.UTF_8)
            assertTrue(sheet.contains("INV/2026/0042"))
            assertTrue(sheet.contains("TAXINV-1123"))
            assertTrue(sheet.contains("<v>171100</v>"))
        }
    }

    @Test
    fun mainScreenLaunches() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertTrue(activity.findViewById<android.view.View>(R.id.extract).isShown)
            }
        }
    }
}
