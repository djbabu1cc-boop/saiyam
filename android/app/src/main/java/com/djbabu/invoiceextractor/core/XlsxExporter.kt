package com.djbabu.invoiceextractor.core

import java.io.OutputStream
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Writes the results as a formatted Excel workbook (.xlsx).
 *
 * Same layout as `invoice_extractor/exporter.py` (openpyxl) - an "Invoices"
 * sheet (styled header, money formats, striped rows, red error rows, frozen
 * header, auto-filter) plus a "Summary" sheet - but written directly as
 * SpreadsheetML with java.util.zip, so the APK needs no spreadsheet library.
 */
object XlsxExporter {

    val HEADERS = listOf(
        "#", "File", "Status", "Invoice No", "Invoice Date", "Vendor / Supplier", "GSTIN",
        "Taxable Amount", "CGST", "SGST", "IGST", "Total Invoice Amount", "Method / Engine", "Notes",
    )
    private val WIDTHS = listOf(4, 34, 13, 18, 14, 36, 20, 15, 12, 12, 12, 18, 22, 40)

    // cellXfs indexes (see STYLES_XML)
    private const val S_HEADER = 1
    private const val S_TEXT = 2
    private const val S_CENTER = 3
    private const val S_MONEY = 4
    private const val S_ERROR_OFFSET = 3 // 5..7
    private const val S_STRIPE_OFFSET = 6 // 8..10
    private const val S_TITLE = 11
    private const val S_BOLD = 12
    private const val S_WRAP = 13

    /** A single cell value: text, number or empty. */
    private sealed class Cell {
        data class Text(val value: String) : Cell()
        data class Num(val value: Double) : Cell()
        data object Empty : Cell()
    }

    private fun text(s: String?): Cell = if (s.isNullOrEmpty()) Cell.Empty else Cell.Text(s)
    private fun num(d: Double?): Cell = if (d == null) Cell.Empty else Cell.Num(d)

    fun write(rows: List<ResultRow>, out: OutputStream, now: LocalDateTime = LocalDateTime.now()) {
        val zip = ZipOutputStream(out)
        fun entry(name: String, content: String) {
            zip.putNextEntry(ZipEntry(name))
            zip.write(content.toByteArray(Charsets.UTF_8))
            zip.closeEntry()
        }
        entry("[Content_Types].xml", CONTENT_TYPES_XML)
        entry("_rels/.rels", ROOT_RELS_XML)
        entry("docProps/app.xml", APP_XML)
        entry("docProps/core.xml", coreXml(Instant.now().truncatedTo(ChronoUnit.SECONDS).toString()))
        entry("xl/workbook.xml", workbookXml(rows.size))
        entry("xl/_rels/workbook.xml.rels", WORKBOOK_RELS_XML)
        entry("xl/styles.xml", STYLES_XML)
        entry("xl/worksheets/sheet1.xml", invoicesSheetXml(rows))
        entry("xl/worksheets/sheet2.xml", summarySheetXml(rows, now))
        zip.finish()
        zip.flush()
    }

    // ------------------------------------------------------------------
    // Sheets
    // ------------------------------------------------------------------

    private fun invoicesSheetXml(rows: List<ResultRow>): String {
        val lastCol = colName(HEADERS.size)
        val lastRow = rows.size + 1
        val sb = StringBuilder(XML_HEADER)
        sb.append("<worksheet xmlns=\"$NS_MAIN\" xmlns:r=\"$NS_REL\">")
        sb.append("<dimension ref=\"A1:$lastCol$lastRow\"/>")
        sb.append("<sheetViews><sheetView tabSelected=\"1\" workbookViewId=\"0\">")
        sb.append("<pane ySplit=\"1\" topLeftCell=\"A2\" activePane=\"bottomLeft\" state=\"frozen\"/>")
        sb.append("<selection pane=\"bottomLeft\" activeCell=\"A2\" sqref=\"A2\"/>")
        sb.append("</sheetView></sheetViews>")
        sb.append("<sheetFormatPr defaultRowHeight=\"15\"/>")
        sb.append("<cols>")
        WIDTHS.forEachIndexed { i, w ->
            sb.append("<col min=\"${i + 1}\" max=\"${i + 1}\" width=\"$w\" customWidth=\"1\"/>")
        }
        sb.append("</cols><sheetData>")

        // header
        sb.append("<row r=\"1\" ht=\"30\" customHeight=\"1\">")
        HEADERS.forEachIndexed { i, h -> appendCell(sb, i + 1, 1, Cell.Text(h), S_HEADER) }
        sb.append("</row>")

        // data
        rows.forEachIndexed { idx0, row ->
            val idx = idx0 + 1
            val r = idx + 1
            val f = row.fields
            val cells = listOf(
                Cell.Num(idx.toDouble()), text(row.file), text(row.status), text(f?.invoiceNo),
                text(f?.date), text(f?.vendor), text(f?.gstin), num(f?.taxable), num(f?.cgst),
                num(f?.sgst), num(f?.igst), num(f?.total), text(row.methodEngine), text(row.note),
            )
            val offset = when {
                row.isProblem -> S_ERROR_OFFSET
                idx % 2 == 0 -> S_STRIPE_OFFSET
                else -> 0
            }
            sb.append("<row r=\"$r\">")
            cells.forEachIndexed { i, cell ->
                val col = i + 1
                val base = when {
                    col == 1 -> S_CENTER
                    col in 8..12 && cell is Cell.Num -> S_MONEY
                    else -> S_TEXT
                }
                appendCell(sb, col, r, cell, base + offset)
            }
            sb.append("</row>")
        }
        sb.append("</sheetData>")
        if (rows.isNotEmpty()) sb.append("<autoFilter ref=\"A1:$lastCol$lastRow\"/>")
        sb.append(PAGE_MARGINS)
        sb.append("</worksheet>")
        return sb.toString()
    }

    private fun summarySheetXml(rows: List<ResultRow>, now: LocalDateTime): String {
        val okCount = rows.count { !it.isProblem }
        val methods = rows.map { it.methodEngine }.filter { it.isNotEmpty() }.toSortedSet()
        val data = listOf(
            3 to ("Generated on" to Cell.Text(now.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")))),
            4 to ("Total files processed" to Cell.Num(rows.size.toDouble())),
            5 to ("Files with data" to Cell.Num(okCount.toDouble())),
            6 to ("Errors / no data" to Cell.Num((rows.size - okCount).toDouble())),
            7 to ("Methods / engines used" to Cell.Text(methods.joinToString(", ").ifEmpty { "-" })),
            9 to ("Note" to Cell.Text(
                "Always verify extracted values against the original invoices before " +
                    "entering them into your accounts.",
            )),
        )
        val sb = StringBuilder(XML_HEADER)
        sb.append("<worksheet xmlns=\"$NS_MAIN\" xmlns:r=\"$NS_REL\">")
        sb.append("<dimension ref=\"A1:B9\"/>")
        sb.append("<sheetViews><sheetView workbookViewId=\"0\"/></sheetViews>")
        sb.append("<sheetFormatPr defaultRowHeight=\"15\"/>")
        sb.append("<cols><col min=\"1\" max=\"1\" width=\"30\" customWidth=\"1\"/>")
        sb.append("<col min=\"2\" max=\"2\" width=\"60\" customWidth=\"1\"/></cols>")
        sb.append("<sheetData>")
        sb.append("<row r=\"1\">")
        appendCell(sb, 1, 1, Cell.Text("Invoice Extraction Summary"), S_TITLE)
        sb.append("</row>")
        for ((r, pair) in data) {
            val (label, value) = pair
            sb.append("<row r=\"$r\">")
            appendCell(sb, 1, r, Cell.Text(label), S_BOLD)
            appendCell(sb, 2, r, value, if (r == 9) S_WRAP else 0)
            sb.append("</row>")
        }
        sb.append("</sheetData>")
        sb.append(PAGE_MARGINS)
        sb.append("</worksheet>")
        return sb.toString()
    }

    private fun appendCell(sb: StringBuilder, col: Int, row: Int, cell: Cell, style: Int) {
        val ref = colName(col) + row
        val s = if (style != 0) " s=\"$style\"" else ""
        when (cell) {
            is Cell.Empty -> sb.append("<c r=\"$ref\"$s/>")
            is Cell.Num -> sb.append("<c r=\"$ref\"$s><v>${formatNumber(cell.value)}</v></c>")
            is Cell.Text -> sb.append(
                "<c r=\"$ref\"$s t=\"inlineStr\"><is><t xml:space=\"preserve\">${escape(cell.value)}</t></is></c>",
            )
        }
    }

    private fun formatNumber(d: Double): String =
        if (d.isNaN() || d.isInfinite()) "0" else BigDecimal.valueOf(d).stripTrailingZeros().toPlainString()

    internal fun colName(col: Int): String {
        var n = col
        val sb = StringBuilder()
        while (n > 0) {
            val rem = (n - 1) % 26
            sb.append('A' + rem)
            n = (n - 1) / 26
        }
        return sb.reverse().toString()
    }

    /** XML-escape and drop characters that are illegal in XML 1.0. */
    internal fun escape(s: String): String {
        val sb = StringBuilder(s.length)
        for (ch in s) {
            when {
                ch == '&' -> sb.append("&amp;")
                ch == '<' -> sb.append("&lt;")
                ch == '>' -> sb.append("&gt;")
                ch == '"' -> sb.append("&quot;")
                ch == '\t' || ch == '\n' || ch == '\r' -> sb.append(ch)
                ch < ' ' || ch == '\uFFFE' || ch == '\uFFFF' -> Unit
                else -> sb.append(ch)
            }
        }
        return sb.toString()
    }

    // ------------------------------------------------------------------
    // Package parts
    // ------------------------------------------------------------------

    private const val XML_HEADER = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
    private const val NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    private const val NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    private const val PAGE_MARGINS =
        "<pageMargins left=\"0.75\" right=\"0.75\" top=\"1\" bottom=\"1\" header=\"0.5\" footer=\"0.5\"/>"

    private const val CONTENT_TYPES_XML = XML_HEADER +
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">" +
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>" +
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>" +
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>" +
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>" +
        "<Override PartName=\"/xl/worksheets/sheet2.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>" +
        "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>" +
        "<Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>" +
        "<Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/>" +
        "</Types>"

    private const val ROOT_RELS_XML = XML_HEADER +
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>" +
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/>" +
        "<Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties\" Target=\"docProps/app.xml\"/>" +
        "</Relationships>"

    private const val APP_XML = XML_HEADER +
        "<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\">" +
        "<Application>Invoice Extractor (Android)</Application></Properties>"

    private fun coreXml(ts: String): String {
        return XML_HEADER +
            "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" " +
            "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" " +
            "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">" +
            "<dc:title>Invoice Extraction</dc:title><dc:creator>Invoice Extractor</dc:creator>" +
            "<dcterms:created xsi:type=\"dcterms:W3CDTF\">$ts</dcterms:created>" +
            "<dcterms:modified xsi:type=\"dcterms:W3CDTF\">$ts</dcterms:modified>" +
            "</cp:coreProperties>"
    }

    private fun workbookXml(rowCount: Int): String {
        val filter = if (rowCount > 0) {
            "<definedNames><definedName name=\"_xlnm._FilterDatabase\" localSheetId=\"0\" hidden=\"1\">" +
                "Invoices!\$A\$1:\$${colName(HEADERS.size)}\$${rowCount + 1}</definedName></definedNames>"
        } else {
            ""
        }
        return XML_HEADER +
            "<workbook xmlns=\"$NS_MAIN\" xmlns:r=\"$NS_REL\">" +
            "<bookViews><workbookView activeTab=\"0\"/></bookViews>" +
            "<sheets><sheet name=\"Invoices\" sheetId=\"1\" r:id=\"rId1\"/>" +
            "<sheet name=\"Summary\" sheetId=\"2\" r:id=\"rId2\"/></sheets>" +
            filter +
            "</workbook>"
    }

    private const val WORKBOOK_RELS_XML = XML_HEADER +
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>" +
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet2.xml\"/>" +
        "<Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>" +
        "</Relationships>"

    // numFmt 4 is the built-in "#,##0.00" (same as MONEY_FORMAT in exporter.py)
    private const val BORDER = "applyBorder=\"1\" borderId=\"1\""
    private const val STYLES_XML = XML_HEADER +
        "<styleSheet xmlns=\"$NS_MAIN\">" +
        "<fonts count=\"4\">" +
        "<font><sz val=\"11\"/><color rgb=\"FF000000\"/><name val=\"Calibri\"/><family val=\"2\"/></font>" +
        "<font><b/><sz val=\"11\"/><color rgb=\"FFFFFFFF\"/><name val=\"Calibri\"/><family val=\"2\"/></font>" +
        "<font><b/><sz val=\"14\"/><color rgb=\"FF1F4E79\"/><name val=\"Calibri\"/><family val=\"2\"/></font>" +
        "<font><b/><sz val=\"11\"/><color rgb=\"FF000000\"/><name val=\"Calibri\"/><family val=\"2\"/></font>" +
        "</fonts>" +
        "<fills count=\"5\">" +
        "<fill><patternFill patternType=\"none\"/></fill>" +
        "<fill><patternFill patternType=\"gray125\"/></fill>" +
        "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF1F4E79\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
        "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFFCE4E4\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
        "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFF2F7FB\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
        "</fills>" +
        "<borders count=\"2\">" +
        "<border><left/><right/><top/><bottom/><diagonal/></border>" +
        "<border><left style=\"thin\"><color rgb=\"FFBFBFBF\"/></left><right style=\"thin\"><color rgb=\"FFBFBFBF\"/></right>" +
        "<top style=\"thin\"><color rgb=\"FFBFBFBF\"/></top><bottom style=\"thin\"><color rgb=\"FFBFBFBF\"/></bottom><diagonal/></border>" +
        "</borders>" +
        "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>" +
        "<cellXfs count=\"14\">" +
        // 0 default
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>" +
        // 1 header
        "<xf numFmtId=\"0\" fontId=\"1\" fillId=\"2\" $BORDER xfId=\"0\" applyFont=\"1\" applyFill=\"1\" applyAlignment=\"1\">" +
        "<alignment horizontal=\"center\" vertical=\"center\" wrapText=\"1\"/></xf>" +
        // 2-4 body: text / centre / money
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" $BORDER xfId=\"0\"/>" +
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" $BORDER xfId=\"0\" applyAlignment=\"1\"><alignment horizontal=\"center\"/></xf>" +
        "<xf numFmtId=\"4\" fontId=\"0\" fillId=\"0\" $BORDER xfId=\"0\" applyNumberFormat=\"1\" applyAlignment=\"1\"><alignment horizontal=\"right\"/></xf>" +
        // 5-7 error rows
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"3\" $BORDER xfId=\"0\" applyFill=\"1\"/>" +
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"3\" $BORDER xfId=\"0\" applyFill=\"1\" applyAlignment=\"1\"><alignment horizontal=\"center\"/></xf>" +
        "<xf numFmtId=\"4\" fontId=\"0\" fillId=\"3\" $BORDER xfId=\"0\" applyFill=\"1\" applyNumberFormat=\"1\" applyAlignment=\"1\"><alignment horizontal=\"right\"/></xf>" +
        // 8-10 striped rows
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"4\" $BORDER xfId=\"0\" applyFill=\"1\"/>" +
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"4\" $BORDER xfId=\"0\" applyFill=\"1\" applyAlignment=\"1\"><alignment horizontal=\"center\"/></xf>" +
        "<xf numFmtId=\"4\" fontId=\"0\" fillId=\"4\" $BORDER xfId=\"0\" applyFill=\"1\" applyNumberFormat=\"1\" applyAlignment=\"1\"><alignment horizontal=\"right\"/></xf>" +
        // 11 summary title, 12 bold label, 13 wrapped text
        "<xf numFmtId=\"0\" fontId=\"2\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyFont=\"1\"/>" +
        "<xf numFmtId=\"0\" fontId=\"3\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyFont=\"1\"/>" +
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyAlignment=\"1\"><alignment wrapText=\"1\"/></xf>" +
        "</cellXfs>" +
        "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>" +
        "</styleSheet>"
}
