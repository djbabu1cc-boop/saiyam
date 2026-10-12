package com.djbabu.invoiceextractor.core

/**
 * One output row - mirrors `build_row()` in `invoice_extractor/exporter.py`
 * so the Android workbook has exactly the same columns as the desktop one.
 */
data class ResultRow(
    val file: String,
    val status: String,
    val fields: InvoiceFields? = null,
    val method: String = "",
    val engine: String = "",
    val note: String = "",
) {
    val methodEngine: String get() = listOf(method, engine).filter { it.isNotEmpty() }.joinToString(" / ")

    /** "Error" / "No data found" rows are highlighted and not counted as data. */
    val isProblem: Boolean get() = status.lowercase() in setOf("error", "no data found")

    companion object {
        const val STATUS_OK = "OK"
        const val STATUS_NO_DATA = "No data found"
        const val STATUS_ERROR = "Error"

        /** Same status/notes rules as the desktop CLI (`cli.py`). */
        fun fromExtraction(file: String, text: String, method: String, engine: String): ResultRow {
            val fields = InvoiceParser.parse(text)
            val missing = fields.missing()
            return ResultRow(
                file = file,
                status = if (fields.hasData) STATUS_OK else STATUS_NO_DATA,
                fields = fields,
                method = method,
                engine = engine,
                note = if (missing.isEmpty()) "" else "Missing: " + missing.joinToString(", "),
            )
        }

        fun error(file: String, message: String) = ResultRow(file = file, status = STATUS_ERROR, note = message)
    }
}
