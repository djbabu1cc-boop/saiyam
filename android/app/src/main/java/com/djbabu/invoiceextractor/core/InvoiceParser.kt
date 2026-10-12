package com.djbabu.invoiceextractor.core

import java.time.DateTimeException
import java.time.LocalDate
import java.util.regex.Pattern

/**
 * Structured data extracted from a single invoice.
 *
 * Kotlin port of `invoice_extractor/parser.py` (`InvoiceFields`). The Android
 * app and the desktop app must agree on every field - the JVM unit tests
 * replay fixtures generated from the Python parser
 * (`scripts/export_parser_fixtures.py`) to guarantee that.
 */
data class InvoiceFields(
    val invoiceNo: String = "",
    /** ISO format YYYY-MM-DD, "" when unknown. */
    val date: String = "",
    val vendor: String = "",
    val gstin: String = "",
    val taxable: Double? = null,
    val cgst: Double? = null,
    val sgst: Double? = null,
    val igst: Double? = null,
    val total: Double? = null,
) {
    /** Names of the key fields that could not be found. */
    fun missing(): List<String> = listOf(
        "Invoice No" to invoiceNo.isNotEmpty(),
        "Date" to date.isNotEmpty(),
        "Vendor" to vendor.isNotEmpty(),
        "GSTIN" to gstin.isNotEmpty(),
        // Python treats 0.0 as falsy, keep the same semantics.
        "Total" to (total != null && total != 0.0),
    ).filter { !it.second }.map { it.first }

    /** True when the invoice yielded at least an invoice number or a total. */
    val hasData: Boolean get() = invoiceNo.isNotEmpty() || (total != null && total != 0.0)
}

/**
 * Heuristic invoice text parser - a line-by-line port of
 * `invoice_extractor/parser.py`. Anything the parser cannot find is left
 * empty (never guessed).
 */
object InvoiceParser {

    // Python's `re` semantics: `.`/`^`/`$` only care about "\n" (UNIX_LINES).
    private fun rx(pattern: String, ignoreCase: Boolean = false, multiline: Boolean = false): Regex {
        var flags = Pattern.UNIX_LINES
        if (ignoreCase) flags = flags or Pattern.CASE_INSENSITIVE
        if (multiline) flags = flags or Pattern.MULTILINE
        return Pattern.compile(pattern, flags).toRegex()
    }

    // ----------------------------------------------------------------------
    // Amounts
    // ----------------------------------------------------------------------

    /** "1234", "1234.56", "1,234,567.89", "1,45,000.00" - but not "9%". */
    private val AMOUNT_TOKEN_RE = rx("""(?<![\d.,])(\d[\d,]*(?:\.\d{1,2})?)(?![\d.,])(?!\s*%)""")

    private fun toFloat(token: String): Double? {
        val t = token.replace(",", "")
        if (t.count { it == '.' } > 1) return null
        val digits = t.replaceFirst(".", "")
        if (digits.isEmpty() || !digits.all { it in '0'..'9' }) return null
        return t.toDoubleOrNull()
    }

    private fun amounts(line: String): List<Double> =
        AMOUNT_TOKEN_RE.findAll(line).mapNotNull { toFloat(it.groupValues[1]) }.toList()

    private fun lastAmount(line: String): Double? = amounts(line).lastOrNull()

    // ----------------------------------------------------------------------
    // Dates
    // ----------------------------------------------------------------------

    private const val MONTHS = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    private const val DATE_TOKEN =
        """(\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}""" +
            """|\d{4}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{1,2}""" +
            """|\d{1,2}\s+""" + MONTHS + """[a-z]*\.?\s*,?\s+\d{4}""" +
            "|" + MONTHS + """[a-z]*\.?\s+\d{1,2}\s*,?\s+\d{4})"""

    private val DATE_LABELED_RE = rx(
        """\b(?:invoice\s+date|bill\s+date|doc(?:ument)?\s*date|order\s+date|supply\s+date""" +
            """|date\s+of\s+supply|issue\s+date|tax\s+date|date)\b""" +
            """\s*[:\-#]?\s*""" + DATE_TOKEN,
        ignoreCase = true,
    )

    private val DATE_STANDALONE_RE = rx("^$DATE_TOKEN$", ignoreCase = true)

    private val DATE_FORMATS = listOf(
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%d/%m/%y", "%d-%m-%y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d %b %Y", "%d %b, %Y", "%d-%b-%Y", "%d/%b/%Y",
        "%b %d %Y", "%b %d, %Y",
        "%m/%d/%Y", "%m-%d-%Y",
    )

    private val MONTH_ABBRS = listOf(
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    )

    /**
     * Compiled equivalents of CPython's `_strptime` format regexes, so that
     * `strptime(value, fmt)` behaves identically (same alternation order,
     * `re.match` + "unconverted data remains" check).
     */
    private val COMPILED_FORMATS: List<Pair<Regex, List<Char>>> = DATE_FORMATS.map { fmt ->
        val sb = StringBuilder()
        val order = mutableListOf<Char>()
        var i = 0
        while (i < fmt.length) {
            val c = fmt[i]
            if (c == '%' && i + 1 < fmt.length) {
                val d = fmt[i + 1]
                order += d
                sb.append(
                    when (d) {
                        'd' -> "(3[0-1]|[1-2]\\d|0[1-9]|[1-9]| [1-9])"
                        'm' -> "(1[0-2]|0[1-9]|[1-9])"
                        'Y' -> "(\\d\\d\\d\\d)"
                        'y' -> "(\\d\\d)"
                        'b' -> "(" + MONTH_ABBRS.joinToString("|") + ")"
                        else -> error("unsupported directive %$d")
                    },
                )
                i += 2
                continue
            }
            if (c.isWhitespace()) {
                while (i < fmt.length && fmt[i].isWhitespace()) i++
                sb.append("\\s+")
                continue
            }
            sb.append(Pattern.quote(c.toString()))
            i++
        }
        rx(sb.toString(), ignoreCase = true) to order
    }

    private fun strptime(value: String, index: Int): String? {
        val (regex, order) = COMPILED_FORMATS[index]
        val m = regex.toPattern().matcher(value)
        if (!m.lookingAt() || m.end() != value.length) return null
        var day = 1
        var month = 1
        var year = 1900
        order.forEachIndexed { g, directive ->
            val v = m.group(g + 1)
            when (directive) {
                'd' -> day = v.trim().toInt()
                'm' -> month = v.toInt()
                'Y' -> year = v.toInt()
                'y' -> {
                    val y = v.toInt()
                    year = if (y <= 68) y + 2000 else y + 1900
                }
                'b' -> month = MONTH_ABBRS.indexOf(v.lowercase()) + 1
            }
        }
        if (year < 1) return null
        return try {
            LocalDate.of(year, month, day).toString()
        } catch (_: DateTimeException) {
            null
        }
    }

    private val WS_RUN = rx("""\s+""")

    internal fun parseDateToken(raw: String): String? {
        val s = WS_RUN.replace(raw.trim(), " ")
        for (variant in listOf(s, s.replace(".", "/"), s.replace("-", "/"))) {
            for (i in DATE_FORMATS.indices) {
                strptime(variant, i)?.let { return it }
            }
        }
        return null
    }

    // ----------------------------------------------------------------------
    // Invoice number
    // ----------------------------------------------------------------------

    private val INV_NO_RES = listOf(
        rx(
            """\b(?:invoice|inv|bill|doc(?:ument)?|proforma|quote|order)\s*""" +
                """(?:no|number|num\.?)\s*(?:\.|:|#|\-|\s)+\s*""" +
                """([A-Za-z0-9][A-Za-z0-9\-_/]{1,40})""",
            ignoreCase = true,
        ),
        rx("""\b(?:invoice|bill)\s*[:#]\s*([A-Za-z][A-Za-z0-9\-_/]{2,40})""", ignoreCase = true),
    )

    private val INV_NO_REJECT = setOf(
        "no", "number", "num", "date", "gstin", "gst", "of", "the", "a", "and",
        "for", "note", "notes", "to", "from", "per", "page", "total", "amount",
        "value", "tax", "inr", "rs",
    )
    private val YEAR_RE = rx("""\d{4}""")
    private val SHORT_DATE_RE = rx("""\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}""")

    private fun cleanInvoiceNo(value: String): String {
        val v = value.trim().trimEnd('.', ',', ';', ':')
        if (v.length !in 2..45) return ""
        if (v.lowercase() in INV_NO_REJECT) return ""
        if (YEAR_RE.matches(v)) return "" // almost certainly a year
        if (SHORT_DATE_RE.matches(v)) return "" // a date
        return v
    }

    // ----------------------------------------------------------------------
    // GSTIN
    // ----------------------------------------------------------------------

    private val GSTIN_RE = rx("""\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3})\b""")

    // ----------------------------------------------------------------------
    // Vendor
    // ----------------------------------------------------------------------

    private val VENDOR_LABELED_RE = rx(
        """^\s*(?:vendor|supplier|seller|merchant|from|sold\s*by|name\s+of\s+supplier""" +
            """|supplying\s+dealer|party|company|firm)\s*(?:name)?\s*[:\-]\s*(.+?)\s*$""",
        ignoreCase = true,
        multiline = true,
    )

    private val VENDOR_STOP_RE = rx(
        """^\s*\d""" +
            """|\b(road|street|lane|avenue|cross|nagar|colony|park)\s*\d""" +
            """|\b(near|opposite|opp\.?|plot|phase|pin\s*code|zip\s*code""" +
            """|regd|registered|m\.?s\s*$)\b""",
        ignoreCase = true,
    )

    private val VENDOR_NOISE_RE = rx(
        """(?:\bgst\s*no\b|\bgstin\b|\bcin\b|\bpan\b|\bemailed?to\b|\bphone\b|\btel\b""" +
            """|\bfax\b|\bwebsite\b|www\.|@|regd\.|registered|m/s\s*$)""",
        ignoreCase = true,
    )

    private val TITLE_NOISE_RE = rx(
        """^(?:tax\s*)?(?:invoice|bill|pro-?forma|credit\s*note|debit\s*note|estimate""" +
            """|quotation|tax\s*credit\s*note|gst\s+invoice)""" +
            """(?:\s*(?:note|no|number))?\s*[:\-]?\s*$""",
        ignoreCase = true,
    )

    private val VENDOR_PREFIX_RE = rx("""^(?:m/s|mesa\s*services)\s*[,:\-]?\s*""", ignoreCase = true)
    private val MULTI_SPACE_RE = rx("""\s{2,}""")
    private val NUMERIC_LINE_RE = rx("""[\d\s\-/,.()A-Za-z]{0,3}\d{4,}""")
    private val HAS_WORD_RE = rx("""[A-Za-z]{3,}""")

    /** Python's `str.strip(chars)`. */
    private fun String.stripChars(chars: String): String = trim { it in chars }

    private fun cleanVendor(value: String): String {
        var v = value.trim().stripChars(":;-").trim()
        v = VENDOR_PREFIX_RE.replaceFirst(v, "")
        if (',' in v) {
            val head = v.split(",")[0].trim()
            if (head.length in 3..48) v = head
        }
        v = MULTI_SPACE_RE.replace(v, " ")
        if (v.length > 60) v = v.substring(0, 60).trimEnd()
        return v
    }

    private fun vendorFromHeader(lines: List<String>): String {
        for (line in lines.take(15)) {
            val s = line.trim()
            if (s.length < 3) continue
            if (TITLE_NOISE_RE.containsMatchAt(s)) continue
            if (GSTIN_RE.containsMatchIn(s.uppercase())) continue
            if (VENDOR_STOP_RE.containsMatchIn(s)) continue
            if (VENDOR_NOISE_RE.containsMatchIn(s)) continue
            if (NUMERIC_LINE_RE.matches(s)) continue
            if (!HAS_WORD_RE.containsMatchIn(s)) continue
            return cleanVendor(s)
        }
        return ""
    }

    /** Python's `regex.match(s)` - anchored at the start, not at the end. */
    private fun Regex.containsMatchAt(s: String): Boolean = toPattern().matcher(s).lookingAt()

    // ----------------------------------------------------------------------
    // Money labels
    // ----------------------------------------------------------------------

    private val TAXABLE_RE = rx(
        """\b(?:taxable\s+value|taxable\s+amount|total\s+taxable|assessable\s+value""" +
            """|assessable\s+amount|net\s+amount|net\s+total|sub-?total|total\s+before\s+tax)\b""",
        ignoreCase = true,
    )
    private val CGST_RE = rx("""\b(?:cgst|central\s+gst)\b""", ignoreCase = true)
    private val SGST_RE = rx("""\b(?:sgst|state\s+gst)\b""", ignoreCase = true)
    private val IGST_RE = rx("""\b(?:igst|integrated\s+gst)\b""", ignoreCase = true)

    private val TOTAL_RES = listOf(
        rx(
            """\b(?:grand\s+total|invoice\s+total|total\s+invoice|bill\s+total""" +
                """|total\s+amount\s+payable|amount\s+payable|total\s+payable""" +
                """|total\s+due|payable\s+amount|rounded\s+total)\b""",
            ignoreCase = true,
        ),
        rx("""^\s*total\s*(?:amount)?\s*[:\-]?""", ignoreCase = true, multiline = true),
    )

    private val SKIP_TOTAL_LINE = rx("""round\s*off|total\s+tax|tax\s+total|taxable""", ignoreCase = true)
    private val TABLE_HEADER_RE = rx(
        """\b(?:qty|quantity|rate|hsn|sac|description|particulars|part\s*no|item\s*no""" +
            """|s\.?\s?no)\b""",
        ignoreCase = true,
    )

    private val LABEL_RES = listOf(TAXABLE_RE, CGST_RE, SGST_RE, IGST_RE)

    /** Find the first line matching [regex] and return its trailing amount. */
    private fun findAmountFor(
        lines: List<String>,
        regex: Regex,
        lookAhead: Int = 2,
        skipRe: Regex? = null,
    ): Double? {
        for ((i, line) in lines.withIndex()) {
            if (skipRe != null && skipRe.containsMatchIn(line)) continue
            if (!regex.containsMatchIn(line)) continue
            var value = lastAmount(line)
            if (value == null && !TABLE_HEADER_RE.containsMatchIn(line)) {
                // Label present but amount on the next line(s).
                for (j in (i + 1) until minOf(i + 1 + lookAhead, lines.size)) {
                    val next = lines[j]
                    if (LABEL_RES.any { it.containsMatchIn(next) }) break
                    value = lastAmount(next)
                    if (value != null) break
                }
            } else if (value == null) {
                // A table header such as "HSN Qty Rate CGST SGST" - skip it.
                continue
            }
            if (value != null) return value
        }
        return null
    }

    // ----------------------------------------------------------------------
    // Public API
    // ----------------------------------------------------------------------

    private val LINE_SPLIT_RE = rx("""[\n\r]+""")

    /** Unicode spaces that Python's `\s` matches but Java's does not. */
    private val UNICODE_SPACES_RE = rx("[\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000]")

    /** Extract invoice fields from raw text (PDF text layer or OCR output). */
    fun parse(rawText: String?): InvoiceFields {
        if (rawText.isNullOrBlank()) return InvoiceFields()
        val text = UNICODE_SPACES_RE.replace(rawText, " ")

        val lines = LINE_SPLIT_RE.split(text).map { it.trim() }.filter { it.isNotEmpty() }
        val upperText = lines.joinToString("\n") { it.uppercase() }

        // --- GSTIN -------------------------------------------------------------
        val gstin = GSTIN_RE.find(upperText)?.groupValues?.get(1) ?: ""

        // --- Invoice number ----------------------------------------------------
        var invoiceNo = ""
        loop@ for (re in INV_NO_RES) {
            for (m in re.findAll(text)) {
                val v = cleanInvoiceNo(m.groupValues[1])
                if (v.isNotEmpty()) {
                    invoiceNo = v
                    break@loop
                }
            }
        }

        // --- Date ----------------------------------------------------------------
        var date = DATE_LABELED_RE.find(text)?.let { parseDateToken(it.groupValues[1]) } ?: ""
        if (date.isEmpty()) {
            for (line in lines.take(40)) {
                val m = DATE_STANDALONE_RE.matchEntire(line.trim()) ?: continue
                date = parseDateToken(m.groupValues[1]) ?: ""
                if (date.isNotEmpty()) break
            }
        }

        // --- Vendor --------------------------------------------------------------
        var vendor = VENDOR_LABELED_RE.find(text)?.let { cleanVendor(it.groupValues[1]) } ?: ""
        if (vendor.isEmpty()) vendor = vendorFromHeader(lines)

        // --- Amounts -------------------------------------------------------------
        var total: Double? = null
        for (re in TOTAL_RES) {
            total = findAmountFor(lines, re, skipRe = SKIP_TOTAL_LINE)
            if (total != null) break
        }

        return InvoiceFields(
            invoiceNo = invoiceNo,
            date = date,
            vendor = vendor,
            gstin = gstin,
            taxable = findAmountFor(lines, TAXABLE_RE),
            cgst = findAmountFor(lines, CGST_RE),
            sgst = findAmountFor(lines, SGST_RE),
            igst = findAmountFor(lines, IGST_RE),
            total = total,
        )
    }
}
