package com.djbabu.invoiceextractor.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Mirrors tests/test_parser.py from the desktop app. */
class InvoiceParserTest {

    private val sample = """
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
    """.trimIndent()

    @Test
    fun sampleInvoice() {
        val f = InvoiceParser.parse(sample)
        assertEquals("INV/2026/0042", f.invoiceNo)
        assertEquals("2026-10-05", f.date)
        assertEquals("ACME SUPPLIERS PVT LTD", f.vendor)
        assertEquals("06AAACA1234A1Z5", f.gstin)
        assertEquals(26000.0, f.taxable!!, 0.0)
        assertEquals(2340.0, f.cgst!!, 0.0)
        assertEquals(2340.0, f.sgst!!, 0.0)
        assertNull(f.igst)
        assertEquals(30680.0, f.total!!, 0.0)
        assertTrue(f.missing().isEmpty())
    }

    @Test
    fun emptyText() {
        val f = InvoiceParser.parse("")
        assertEquals("", f.invoiceNo)
        assertNull(f.total)
        assertEquals(InvoiceFields(), InvoiceParser.parse(null))
    }

    @Test
    fun igstIndianGrouping() {
        val f = InvoiceParser.parse(
            "DELHI FINE FOODS\nGSTIN: 07AAFCD7890B1Z8\nTAX INVOICE\nInvoice No: TAXINV-1123\n" +
                "Bill Date: 14-09-2026\nTaxable Value: 1,45,000.00\nIGST @ 18%: 26,100.00\n" +
                "Total Invoice: 1,71,100.00\n",
        )
        assertEquals("TAXINV-1123", f.invoiceNo)
        assertEquals("2026-09-14", f.date)
        assertEquals(145000.0, f.taxable!!, 0.0)
        assertEquals(26100.0, f.igst!!, 0.0)
        assertEquals(171100.0, f.total!!, 0.0)
    }

    @Test
    fun monthNameDate() {
        val f = InvoiceParser.parse("Invoice No: CA-2026-0301\nInvoice Date: 22 Sep 2026\nTotal: 65,195.00\n")
        assertEquals("2026-09-22", f.date)
        assertEquals(65195.0, f.total!!, 0.0)
    }

    @Test
    fun labeledVendor() {
        val f = InvoiceParser.parse("Vendor Name: GANESHA TRADERS PVT LTD\nInvoice No: 1001\n")
        assertEquals("GANESHA TRADERS PVT LTD", f.vendor)
    }

    @Test
    fun percentNotTreatedAsAmount() {
        val f = InvoiceParser.parse("CGST @ 9%: 500\nSGST @ 9%: 500\nGrand Total: 1100\n")
        assertEquals(500.0, f.cgst!!, 0.0)
        assertEquals(1100.0, f.total!!, 0.0)
    }

    @Test
    fun nonBreakingSpacesAreTreatedAsSpaces() {
        val f = InvoiceParser.parse("Invoice\u00A0No:\u00A0NB-1\nTotal:\u00A01,000.00\n")
        assertEquals("NB-1", f.invoiceNo)
        assertEquals(1000.0, f.total!!, 0.0)
    }

    @Test
    fun dateFormats() {
        assertEquals("2026-10-05", InvoiceParser.parseDateToken("05/10/2026"))
        assertEquals("2026-10-05", InvoiceParser.parseDateToken("05.10.2026"))
        assertEquals("2026-09-14", InvoiceParser.parseDateToken("2026-09-14"))
        assertEquals("2026-12-25", InvoiceParser.parseDateToken("25-12-26"))
        assertEquals("2026-12-31", InvoiceParser.parseDateToken("12/31/2026"))
        assertEquals("2026-03-05", InvoiceParser.parseDateToken("Mar 5, 2026"))
        assertEquals("2026-09-22", InvoiceParser.parseDateToken("22 sep 2026"))
        assertNull(InvoiceParser.parseDateToken("31/02/2026"))
    }
}
