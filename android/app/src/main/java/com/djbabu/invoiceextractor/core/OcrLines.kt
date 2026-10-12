package com.djbabu.invoiceextractor.core

import kotlin.math.abs
import kotlin.math.max

/** One recognised text fragment with its bounding box (pixels). */
data class OcrBox(
    val left: Double,
    val top: Double,
    val right: Double,
    val bottom: Double,
    val text: String,
)

/**
 * Cluster OCR text boxes into visual lines, top to bottom.
 *
 * Port of `_lines_from_boxes` in `invoice_extractor/ocr.py`. The parser is
 * line-based ("Taxable Value: 26,000.00"), but OCR engines often return the
 * label and the amount as separate fragments - this puts fragments that
 * share a baseline back on one line, left to right.
 */
object OcrLines {

    fun group(boxes: List<OcrBox>): List<String> {
        data class Row(val y: Double, val h: Double, val x: Double, val text: String)

        val rows = boxes
            .filter { it.text.isNotBlank() }
            .map { b ->
                val top = minOf(b.top, b.bottom)
                val bottom = maxOf(b.top, b.bottom)
                Row((top + bottom) / 2.0, bottom - top, minOf(b.left, b.right), b.text.trim())
            }
            .sortedWith(compareBy<Row>({ it.y }, { it.x }))
        if (rows.isEmpty()) return emptyList()

        val heights = rows.map { it.h }.filter { it > 0.0 }
        val medianH = if (heights.isEmpty()) 12.0 else median(heights)
        val tolerance = max(medianH * 0.6, 6.0)

        val lines = mutableListOf<Pair<Double, MutableList<Pair<Double, String>>>>()
        for (r in rows) {
            val last = lines.lastOrNull()
            if (last != null && abs(r.y - last.first) <= tolerance) {
                val n = last.second.size
                val avg = (last.first * n + r.y) / (n + 1)
                last.second += r.x to r.text
                lines[lines.size - 1] = avg to last.second
            } else {
                lines += r.y to mutableListOf(r.x to r.text)
            }
        }
        return lines.map { (_, seg) ->
            seg.sortedWith(compareBy<Pair<Double, String>>({ it.first }, { it.second }))
                .joinToString(" ") { it.second }
        }
    }

    /** Python's `statistics.median`. */
    private fun median(values: List<Double>): Double {
        val s = values.sorted()
        val n = s.size
        return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2.0
    }
}
