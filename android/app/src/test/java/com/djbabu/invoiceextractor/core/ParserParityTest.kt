package com.djbabu.invoiceextractor.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * Replays fixtures produced by the desktop (Python) parser
 * (`scripts/export_parser_fixtures.py`) against the Kotlin port, so the
 * Android app extracts exactly the same values as the Windows app.
 */
class ParserParityTest {

    @Suppress("UNCHECKED_CAST")
    private val fixtures: Map<String, Any?> by lazy {
        val stream = javaClass.classLoader!!.getResourceAsStream("parser_fixtures.json")
            ?: error("parser_fixtures.json not found on the test classpath")
        MiniJson.parse(stream.bufferedReader(Charsets.UTF_8).readText()) as Map<String, Any?>
    }

    @Suppress("UNCHECKED_CAST")
    private fun cases(key: String) = fixtures[key] as List<Map<String, Any?>>

    @Test
    fun parserMatchesPythonImplementation() {
        val failures = mutableListOf<String>()
        val parserCases = cases("parser")
        assertTrue("expected fixture cases", parserCases.size >= 20)
        for (case in parserCases) {
            val name = case["name"] as String
            @Suppress("UNCHECKED_CAST")
            val exp = case["expected"] as Map<String, Any?>
            val f = InvoiceParser.parse(case["text"] as String)
            val actual = mapOf(
                "invoice_no" to f.invoiceNo,
                "date" to f.date,
                "vendor" to f.vendor,
                "gstin" to f.gstin,
                "taxable" to f.taxable,
                "cgst" to f.cgst,
                "sgst" to f.sgst,
                "igst" to f.igst,
                "total" to f.total,
                "missing" to f.missing(),
            )
            for ((k, v) in actual) {
                if (exp[k] != v) failures += "$name.$k: python=${exp[k]} kotlin=$v"
            }
        }
        if (failures.isNotEmpty()) fail("Kotlin parser differs from Python:\n" + failures.joinToString("\n"))
    }

    @Test
    fun ocrLineClusteringMatchesPythonImplementation() {
        val failures = mutableListOf<String>()
        for (case in cases("ocr_lines")) {
            val name = case["name"] as String
            @Suppress("UNCHECKED_CAST")
            val boxes = (case["boxes"] as List<Map<String, Any?>>).map {
                OcrBox(
                    it["left"] as Double, it["top"] as Double,
                    it["right"] as Double, it["bottom"] as Double, it["text"] as String,
                )
            }
            val actual = OcrLines.group(boxes)
            if (case["expected"] != actual) failures += "$name: python=${case["expected"]} kotlin=$actual"
        }
        if (failures.isNotEmpty()) fail(failures.joinToString("\n"))
    }

    @Test
    fun statusRulesMatchCli() {
        val ok = ResultRow.fromExtraction("a.pdf", "Invoice No: X-1\nTotal: 10\n", "pdf-text", "")
        assertEquals("OK", ok.status)
        // the header fallback picks up the first line as vendor - same as Python
        assertEquals("Missing: Date, GSTIN", ok.note)
        val none = ResultRow.fromExtraction("b.png", "hello world", "image-ocr", "mlkit")
        assertEquals("No data found", none.status)
        assertTrue(none.isProblem)
        assertEquals("image-ocr / mlkit", none.methodEngine)
        val err = ResultRow.error("c.pdf", "boom")
        assertEquals("Error", err.status)
        assertTrue(err.isProblem)
    }
}
