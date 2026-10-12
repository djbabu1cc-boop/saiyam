package com.djbabu.invoiceextractor

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.djbabu.invoiceextractor.extract.InvoiceTextExtractor
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

// TEMPORARY: reports the first OCR lines at several render scales.
@RunWith(AndroidJUnit4::class)
class OcrDiagnosticTest {
    @Test
    fun renderScales() {
        val inst = InstrumentationRegistry.getInstrumentation()
        val app = inst.targetContext
        val out = File(app.cacheDir, "diag.pdf")
        inst.context.assets.open("invoice_4_scanned.pdf").use { i -> out.outputStream().use { o -> i.copyTo(o) } }
        val report = StringBuilder()
        for (scale in listOf(1.0f, 1.5f, 2.0f, 2.5f, 3.0f, 4.0f, 5.0f)) {
            InvoiceTextExtractor(app, scale).use { ex ->
                val o = ex.extract(Uri.fromFile(out), out.name)
                report.append("scale=$scale -> ${o.text.lines().take(2)} err=${o.error}\n")
            }
        }
        fail("DIAG\n$report")
    }
}
