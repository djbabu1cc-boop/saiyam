package com.djbabu.invoiceextractor.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.time.LocalDateTime
import java.util.zip.ZipInputStream
import javax.xml.parsers.DocumentBuilderFactory

class XlsxExporterTest {

    private fun rows() = listOf(
        ResultRow(
            file = "invoice_1_gst.pdf",
            status = "OK",
            fields = InvoiceFields(
                invoiceNo = "INV/2026/0042", date = "2026-10-05", vendor = "ACME & SONS <PVT> LTD",
                gstin = "06AAACA1234A1Z5", taxable = 26000.0, cgst = 2340.0, sgst = 2340.0,
                igst = null, total = 30680.0,
            ),
            method = "pdf-text",
        ),
        ResultRow.error("broken.pdf", "FileNotFoundError: file not found"),
        ResultRow.fromExtraction("photo.jpg", "Invoice No: Q-9\nTotal: 1,00,000.50", "image-ocr", "mlkit"),
    )

    private fun unzip(bytes: ByteArray): Map<String, String> {
        val out = linkedMapOf<String, String>()
        ZipInputStream(ByteArrayInputStream(bytes)).use { zin ->
            while (true) {
                val e = zin.nextEntry ?: break
                out[e.name] = zin.readBytes().toString(Charsets.UTF_8)
            }
        }
        return out
    }

    @Test
    fun writesWellFormedWorkbook() {
        val buf = ByteArrayOutputStream()
        XlsxExporter.write(rows(), buf, LocalDateTime.of(2026, 10, 12, 9, 30, 0))
        val parts = unzip(buf.toByteArray())

        for (name in listOf(
            "[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
            "xl/styles.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml",
        )) {
            assertTrue("missing part $name", name in parts)
        }
        val factory = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
        for ((name, xml) in parts) {
            factory.newDocumentBuilder().parse(ByteArrayInputStream(xml.toByteArray(Charsets.UTF_8)))
                ?: error("could not parse $name")
        }

        val sheet = parts.getValue("xl/worksheets/sheet1.xml")
        XlsxExporter.HEADERS.forEach { assertTrue("header $it", sheet.contains(">${XlsxExporter.escape(it)}<")) }
        assertTrue(sheet.contains("ACME &amp; SONS &lt;PVT&gt; LTD"))
        assertTrue(sheet.contains("<c r=\"H2\" s=\"4\"><v>26000</v></c>"))
        assertTrue(sheet.contains("<c r=\"L4\" s=\"4\"><v>100000.5</v></c>"))
        // error row is highlighted (styles 5..7)
        assertTrue(sheet.contains("<c r=\"C3\" s=\"5\" t=\"inlineStr\"><is><t xml:space=\"preserve\">Error</t>"))
        assertTrue(sheet.contains("state=\"frozen\""))
        assertTrue(sheet.contains("<autoFilter ref=\"A1:N4\"/>"))

        val summary = parts.getValue("xl/worksheets/sheet2.xml")
        assertTrue(summary.contains("2026-10-12 09:30:00"))
        assertTrue(summary.contains("<c r=\"B4\"><v>3</v></c>"))
        assertTrue(summary.contains("<c r=\"B5\"><v>2</v></c>"))
        assertTrue(summary.contains("<c r=\"B6\"><v>1</v></c>"))
        assertTrue(summary.contains("image-ocr / mlkit, pdf-text"))
    }

    @Test
    fun columnNames() {
        assertEquals("A", XlsxExporter.colName(1))
        assertEquals("N", XlsxExporter.colName(14))
        assertEquals("Z", XlsxExporter.colName(26))
        assertEquals("AA", XlsxExporter.colName(27))
    }

    @Test
    fun emptyResultHasNoAutoFilter() {
        val buf = ByteArrayOutputStream()
        XlsxExporter.write(emptyList(), buf)
        val parts = unzip(buf.toByteArray())
        assertTrue(!parts.getValue("xl/worksheets/sheet1.xml").contains("autoFilter"))
        assertTrue(!parts.getValue("xl/workbook.xml").contains("definedName"))
    }
}
