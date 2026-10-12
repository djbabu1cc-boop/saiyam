package com.djbabu.invoiceextractor.core

/**
 * Tiny JSON reader for the test fixtures (org.json is only a stub in local
 * unit tests, and the fixtures need nothing beyond plain JSON values).
 */
class MiniJson private constructor(private val s: String) {
    private var i = 0

    companion object {
        fun parse(text: String): Any? = MiniJson(text).run {
            val v = value()
            ws()
            require(i == s.length) { "Trailing data at $i" }
            v
        }
    }

    private fun ws() {
        while (i < s.length && s[i].isWhitespace()) i++
    }

    private fun value(): Any? {
        ws()
        return when (val c = s[i]) {
            '{' -> obj()
            '[' -> arr()
            '"' -> str()
            't' -> literal("true", true)
            'f' -> literal("false", false)
            'n' -> literal("null", null)
            else -> if (c == '-' || c.isDigit()) number() else error("Unexpected '$c' at $i")
        }
    }

    private fun literal(word: String, v: Any?): Any? {
        require(s.startsWith(word, i)) { "Expected $word at $i" }
        i += word.length
        return v
    }

    private fun number(): Double {
        val start = i
        while (i < s.length && (s[i].isDigit() || s[i] in "+-.eE")) i++
        return s.substring(start, i).toDouble()
    }

    private fun str(): String {
        val sb = StringBuilder()
        i++ // opening quote
        while (true) {
            val c = s[i++]
            when (c) {
                '"' -> return sb.toString()
                '\\' -> {
                    when (val e = s[i++]) {
                        '"', '\\', '/' -> sb.append(e)
                        'b' -> sb.append('\b')
                        'f' -> sb.append('\u000C')
                        'n' -> sb.append('\n')
                        'r' -> sb.append('\r')
                        't' -> sb.append('\t')
                        'u' -> {
                            sb.append(s.substring(i, i + 4).toInt(16).toChar())
                            i += 4
                        }
                        else -> error("Bad escape \\$e at $i")
                    }
                }
                else -> sb.append(c)
            }
        }
    }

    private fun arr(): List<Any?> {
        val out = mutableListOf<Any?>()
        i++
        ws()
        if (s[i] == ']') { i++; return out }
        while (true) {
            out += value()
            ws()
            when (s[i++]) {
                ',' -> continue
                ']' -> return out
                else -> error("Expected , or ] at ${i - 1}")
            }
        }
    }

    private fun obj(): Map<String, Any?> {
        val out = linkedMapOf<String, Any?>()
        i++
        ws()
        if (s[i] == '}') { i++; return out }
        while (true) {
            ws()
            val k = str()
            ws()
            require(s[i++] == ':') { "Expected : at ${i - 1}" }
            out[k] = value()
            ws()
            when (s[i++]) {
                ',' -> continue
                '}' -> return out
                else -> error("Expected , or } at ${i - 1}")
            }
        }
    }
}
