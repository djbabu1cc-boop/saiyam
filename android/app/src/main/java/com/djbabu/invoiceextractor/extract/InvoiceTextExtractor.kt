package com.djbabu.invoiceextractor.extract

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import androidx.exifinterface.media.ExifInterface
import com.djbabu.invoiceextractor.core.OcrBox
import com.djbabu.invoiceextractor.core.OcrLines
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import com.tom_roush.pdfbox.android.PDFBoxResourceLoader
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.encryption.InvalidPasswordException
import com.tom_roush.pdfbox.text.PDFTextStripper
import java.io.Closeable
import java.io.File
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Result of turning one file into text (mirrors `ExtractionOutcome` in extractor.py). */
data class ExtractionOutcome(
    val text: String = "",
    /** "pdf-text" | "pdf-ocr" | "image-ocr" */
    val method: String = "",
    val pages: Int = 0,
    val ocrEngine: String = "",
    val error: String = "",
) {
    val ok: Boolean get() = error.isEmpty()
}

/**
 * Android counterpart of `invoice_extractor/extractor.py`:
 *
 * * PDFs with a real text layer are read directly with PDFBox (no OCR).
 * * Scanned PDFs are rendered with [PdfRenderer] and sent through OCR.
 * * Image invoices are OCR'd directly with ML Kit (on-device, offline).
 *
 * All methods block - call them from a background thread.
 */
class InvoiceTextExtractor(context: Context) : Closeable {

    private val appContext = context.applicationContext
    private var recognizer: TextRecognizer? = null

    init {
        PDFBoxResourceLoader.init(appContext)
    }

    companion object {
        const val ENGINE = "mlkit"
        const val MIN_TEXT_CHARS = 40 // shorter than this, a PDF is treated as scanned
        private const val RENDER_SCALE = 3f // 72 dpi * 3 ~= 216 dpi, same as the desktop app
        private const val MAX_RENDER_SIDE = 3000
        private const val MAX_IMAGE_SIDE = 4096
        private const val MIN_OCR_WIDTH = 1600

        val IMAGE_EXTENSIONS = setOf("png", "jpg", "jpeg", "webp", "bmp", "heic", "heif")
        val SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS + "pdf"
        private val UNSUPPORTED_HINTS = mapOf(
            "tif" to "TIFF images can't be decoded on Android - convert them to PDF, PNG or JPG",
            "tiff" to "TIFF images can't be decoded on Android - convert them to PDF, PNG or JPG",
        )

        /** MIME types offered in the file picker. */
        val PICKER_MIME_TYPES = arrayOf("application/pdf", "image/*")

        fun extensionOf(name: String): String = name.substringAfterLast('.', "").lowercase()

        fun isSupported(name: String, mime: String?): Boolean =
            extensionOf(name) in SUPPORTED_EXTENSIONS ||
                mime == "application/pdf" ||
                (mime != null && mime.startsWith("image/") && mime != "image/tiff")

        /** Best-effort display name for a content:// or file:// Uri. */
        fun displayName(context: Context, uri: Uri): String {
            if (uri.scheme == "content") {
                try {
                    context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                        ?.use { c ->
                            if (c.moveToFirst() && !c.isNull(0)) return c.getString(0)
                        }
                } catch (_: Exception) {
                    // fall through
                }
            }
            return uri.lastPathSegment?.substringAfterLast('/') ?: "invoice"
        }
    }

    /** Extract text from a single invoice. Never throws. */
    fun extract(uri: Uri, name: String, log: (String) -> Unit = {}): ExtractionOutcome {
        val ext = extensionOf(name)
        val mime = try {
            appContext.contentResolver.getType(uri)
        } catch (_: Exception) {
            null
        }
        UNSUPPORTED_HINTS[ext]?.let { return ExtractionOutcome(error = it) }
        val isPdf = ext == "pdf" || mime == "application/pdf"
        if (!isPdf && !isSupported(name, mime)) {
            return ExtractionOutcome(
                error = "Unsupported file type '${if (ext.isEmpty()) "<none>" else ".$ext"}'. " +
                    "Supported: " + SUPPORTED_EXTENSIONS.sorted().joinToString(", ") { ".$it" },
            )
        }
        return try {
            if (isPdf) extractPdf(uri, log) else extractImage(uri, log)
        } catch (e: OutOfMemoryError) {
            ExtractionOutcome(error = "File is too large to process on this device")
        } catch (e: Exception) {
            ExtractionOutcome(error = "${e.javaClass.simpleName}: ${e.message}")
        }
    }

    // ------------------------------------------------------------------
    // PDF
    // ------------------------------------------------------------------

    private fun extractPdf(uri: Uri, log: (String) -> Unit): ExtractionOutcome {
        val tmp = copyToCache(uri, "pdf") ?: return ExtractionOutcome(error = "File not found")
        try {
            val pageTexts = mutableListOf<String>()
            try {
                PDDocument.load(tmp).use { doc ->
                    val stripper = PDFTextStripper().apply {
                        sortByPosition = true
                        lineSeparator = "\n"
                    }
                    for (p in 1..doc.numberOfPages) {
                        stripper.startPage = p
                        stripper.endPage = p
                        pageTexts += try {
                            stripper.getText(doc) ?: ""
                        } catch (_: Exception) {
                            ""
                        }
                    }
                }
            } catch (_: InvalidPasswordException) {
                return ExtractionOutcome(error = "PDF is password-protected and could not be opened")
            }

            val combined = pageTexts.joinToString("\n\n")
            if (combined.trim().length >= MIN_TEXT_CHARS) {
                return ExtractionOutcome(text = combined, method = "pdf-text", pages = pageTexts.size)
            }

            // No usable text layer -> render pages and OCR them.
            log("PDF appears to be scanned - running OCR…")
            val ocrTexts = mutableListOf<String>()
            ParcelFileDescriptor.open(tmp, ParcelFileDescriptor.MODE_READ_ONLY).use { pfd ->
                val renderer = PdfRenderer(pfd)
                try {
                    for (i in 0 until renderer.pageCount) {
                        log("OCR page ${i + 1} of ${renderer.pageCount}…")
                        val page = renderer.openPage(i)
                        val bitmap = try {
                            val scale = min(
                                RENDER_SCALE,
                                MAX_RENDER_SIDE.toFloat() / max(page.width, page.height).coerceAtLeast(1),
                            )
                            val w = (page.width * scale).roundToInt().coerceAtLeast(1)
                            val h = (page.height * scale).roundToInt().coerceAtLeast(1)
                            Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888).also {
                                it.eraseColor(Color.WHITE) // PdfRenderer leaves the background transparent
                                page.render(it, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                            }
                        } finally {
                            page.close()
                        }
                        try {
                            ocrTexts += ocr(bitmap)
                        } finally {
                            bitmap.recycle()
                        }
                    }
                } finally {
                    renderer.close()
                }
            }
            val text = ocrTexts.joinToString("\n\n")
            return ExtractionOutcome(
                text = text,
                method = "pdf-ocr",
                pages = ocrTexts.size,
                ocrEngine = ENGINE,
                error = if (text.isBlank()) "OCR could not read any text from this PDF" else "",
            )
        } finally {
            tmp.delete()
        }
    }

    // ------------------------------------------------------------------
    // Images
    // ------------------------------------------------------------------

    private fun extractImage(uri: Uri, log: (String) -> Unit): ExtractionOutcome {
        log("Running OCR…")
        val bitmap = decodeForOcr(uri) ?: return ExtractionOutcome(error = "Could not decode this image")
        val text = try {
            ocr(bitmap)
        } finally {
            bitmap.recycle()
        }
        return ExtractionOutcome(
            text = text,
            method = "image-ocr",
            pages = 1,
            ocrEngine = ENGINE,
            error = if (text.isBlank()) "OCR could not read any text from this image" else "",
        )
    }

    /** Decode with EXIF rotation applied, bounded in size, small images upscaled. */
    private fun decodeForOcr(uri: Uri): Bitmap? {
        val resolver = appContext.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) } ?: return null
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / sample > MAX_IMAGE_SIDE) sample *= 2
        val opts = BitmapFactory.Options().apply {
            inSampleSize = sample
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        var bmp = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) } ?: return null

        val rotation = try {
            resolver.openInputStream(uri)?.use { ExifInterface(it).rotationDegrees } ?: 0
        } catch (_: Exception) {
            0
        }
        val matrix = Matrix()
        if (rotation != 0) matrix.postRotate(rotation.toFloat())
        // Same pre-processing as the desktop app: upscale narrow images (<1600 px) up to 2x.
        val width = if (rotation % 180 == 0) bmp.width else bmp.height
        if (width in 1 until MIN_OCR_WIDTH) {
            val s = min(2f, MIN_OCR_WIDTH.toFloat() / width)
            matrix.postScale(s, s)
        }
        if (!matrix.isIdentity) {
            val transformed = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, matrix, true)
            if (transformed !== bmp) bmp.recycle()
            bmp = transformed
        }
        return bmp
    }

    // ------------------------------------------------------------------
    // OCR
    // ------------------------------------------------------------------

    private fun recognizer(): TextRecognizer =
        recognizer ?: TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS).also { recognizer = it }

    private fun ocr(bitmap: Bitmap): String {
        val result = Tasks.await(recognizer().process(InputImage.fromBitmap(bitmap, 0)), 120, TimeUnit.SECONDS)
        val boxes = mutableListOf<OcrBox>()
        val unplaced = mutableListOf<String>()
        for (block in result.textBlocks) {
            for (line in block.lines) {
                val r = line.boundingBox
                if (r == null) {
                    unplaced += line.text
                } else {
                    boxes += OcrBox(
                        r.left.toDouble(), r.top.toDouble(), r.right.toDouble(), r.bottom.toDouble(), line.text,
                    )
                }
            }
        }
        return (OcrLines.group(boxes) + unplaced).joinToString("\n").trim()
    }

    private fun copyToCache(uri: Uri, ext: String): File? {
        val dir = File(appContext.cacheDir, "extract").apply { mkdirs() }
        val out = File.createTempFile("invoice_", ".$ext", dir)
        val input = try {
            appContext.contentResolver.openInputStream(uri)
        } catch (_: Exception) {
            null
        }
        if (input == null) {
            out.delete()
            return null
        }
        input.use { i -> out.outputStream().use { o -> i.copyTo(o) } }
        return out
    }

    override fun close() {
        recognizer?.close()
        recognizer = null
    }
}
