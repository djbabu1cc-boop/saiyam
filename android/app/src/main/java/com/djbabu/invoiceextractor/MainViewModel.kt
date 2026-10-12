package com.djbabu.invoiceextractor

import android.app.Application
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import com.djbabu.invoiceextractor.core.ResultRow
import com.djbabu.invoiceextractor.core.XlsxExporter
import com.djbabu.invoiceextractor.extract.InvoiceTextExtractor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.atomic.AtomicLong

/** One invoice in the batch. */
data class InvoiceItem(
    val id: Long,
    val uri: Uri,
    val name: String,
    val state: State = State.PENDING,
    val progress: String = "",
    val row: ResultRow? = null,
    val text: String = "",
) {
    enum class State { PENDING, RUNNING, DONE }
}

/** One-shot UI message. */
class Event<T>(private val content: T) {
    private var handled = false
    fun take(): T? = if (handled) null else content.also { handled = true }
}

class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val ids = AtomicLong()
    private val extractorDelegate = lazy { InvoiceTextExtractor(app) }
    private val extractor by extractorDelegate
    private var job: Job? = null

    private val _items = MutableLiveData<List<InvoiceItem>>(emptyList())
    val items: LiveData<List<InvoiceItem>> = _items

    private val _busy = MutableLiveData(false)
    val busy: LiveData<Boolean> = _busy

    private val _messages = MutableLiveData<Event<String>>()
    val messages: LiveData<Event<String>> = _messages

    // Authoritative batch state. Background extraction and UI actions both
    // mutate it under a lock; LiveData only ever receives full snapshots, so
    // no update can be lost to postValue() coalescing.
    private val lock = Any()
    private var state: List<InvoiceItem> = emptyList()

    private fun current(): List<InvoiceItem> = synchronized(lock) { state }

    private fun mutate(change: (List<InvoiceItem>) -> List<InvoiceItem>) {
        synchronized(lock) {
            state = change(state)
            _items.postValue(state)
        }
    }

    private fun message(text: String) = _messages.postValue(Event(text))

    private fun update(id: Long, change: (InvoiceItem) -> InvoiceItem) {
        mutate { list -> list.map { if (it.id == id) change(it) else it } }
    }

    // ------------------------------------------------------------------
    // Building the batch
    // ------------------------------------------------------------------

    fun addUris(uris: List<Uri>) {
        if (uris.isEmpty()) return
        viewModelScope.launch {
            val resolved = withContext(Dispatchers.IO) {
                uris.map { it to InvoiceTextExtractor.displayName(getApplication(), it) }
            }
            addResolved(resolved)
        }
    }

    fun addFolder(treeUri: Uri) {
        viewModelScope.launch {
            val found = withContext(Dispatchers.IO) {
                val root = DocumentFile.fromTreeUri(getApplication(), treeUri)
                val out = mutableListOf<Pair<Uri, String>>()
                fun walk(dir: DocumentFile?, depth: Int) {
                    if (dir == null || depth > 3) return
                    for (f in dir.listFiles().sortedBy { it.name?.lowercase() }) {
                        if (f.isDirectory) {
                            walk(f, depth + 1)
                        } else {
                            val name = f.name ?: continue
                            if (InvoiceTextExtractor.isSupported(name, f.type)) out += f.uri to name
                        }
                    }
                }
                walk(root, 0)
                out
            }
            if (found.isEmpty()) {
                message(getApplication<Application>().getString(R.string.msg_no_invoices_in_folder))
            }
            addResolved(found)
        }
    }

    private fun addResolved(files: List<Pair<Uri, String>>) {
        var skipped = 0
        mutate { list ->
            val existing = list.map { it.uri }.toSet()
            val added = files.filter { it.first !in existing }
                .distinctBy { it.first }
                .map { (uri, name) -> InvoiceItem(ids.incrementAndGet(), uri, name) }
            skipped = files.size - added.size
            list + added
        }
        if (skipped > 0) message(getApplication<Application>().getString(R.string.msg_duplicates_skipped, skipped))
    }

    fun remove(id: Long) {
        if (_busy.value == true) return
        mutate { list -> list.filterNot { it.id == id } }
    }

    fun clear() {
        if (_busy.value == true) return
        mutate { emptyList() }
    }

    // ------------------------------------------------------------------
    // Extraction
    // ------------------------------------------------------------------

    fun extractAll() {
        if (_busy.value == true) return
        val all = current()
        if (all.isEmpty()) return
        // Like the desktop app: (re)process files that have no data yet; if
        // everything already succeeded, run the whole batch again.
        var targets = all.filter { it.row == null || it.row.isProblem }
        if (targets.isEmpty()) targets = all
        val targetIds = targets.map { it.id }.toSet()
        mutate { list ->
            list.map {
                if (it.id in targetIds) it.copy(state = InvoiceItem.State.PENDING, row = null, text = "", progress = "") else it
            }
        }
        _busy.value = true
        job = viewModelScope.launch(Dispatchers.Default) {
            try {
                for (item in targets) {
                    ensureActive()
                    update(item.id) { it.copy(state = InvoiceItem.State.RUNNING, progress = "") }
                    val outcome = extractor.extract(item.uri, item.name) { p ->
                        update(item.id) { it.copy(progress = p) }
                    }
                    val row = if (!outcome.ok) {
                        ResultRow.error(item.name, outcome.error)
                    } else {
                        ResultRow.fromExtraction(item.name, outcome.text, outcome.method, outcome.ocrEngine)
                    }
                    update(item.id) {
                        it.copy(state = InvoiceItem.State.DONE, row = row, text = outcome.text, progress = "")
                    }
                }
                val done = current()
                val ok = done.count { it.row != null && !it.row.isProblem }
                message(getApplication<Application>().getString(R.string.msg_extraction_done, ok, done.size))
            } finally {
                _busy.postValue(false)
                // anything left RUNNING (cancelled) goes back to pending
                mutate { list ->
                    list.map {
                        if (it.state == InvoiceItem.State.RUNNING) it.copy(state = InvoiceItem.State.PENDING) else it
                    }
                }
            }
        }
    }

    fun cancel() {
        job?.cancel()
    }

    // ------------------------------------------------------------------
    // Export
    // ------------------------------------------------------------------

    fun results(): List<ResultRow> = current().mapNotNull { it.row }

    fun suggestedFileName(): String =
        "invoices_" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss")) + ".xlsx"

    fun exportTo(uri: Uri) {
        val rows = results()
        viewModelScope.launch {
            val app = getApplication<Application>()
            val ok = withContext(Dispatchers.IO) {
                try {
                    val stream = try {
                        app.contentResolver.openOutputStream(uri, "wt")
                    } catch (_: Exception) {
                        app.contentResolver.openOutputStream(uri, "w")
                    }
                    stream?.use { XlsxExporter.write(rows, it) } != null
                } catch (_: Exception) {
                    false
                }
            }
            message(app.getString(if (ok) R.string.msg_saved else R.string.msg_save_failed))
        }
    }

    /** Write the workbook to the app cache for sharing; returns the file. */
    suspend fun exportForSharing(): File? = withContext(Dispatchers.IO) {
        val dir = File(getApplication<Application>().cacheDir, "exports").apply {
            mkdirs()
            listFiles()?.forEach { it.delete() }
        }
        val file = File(dir, suggestedFileName())
        try {
            file.outputStream().use { XlsxExporter.write(results(), it) }
            file
        } catch (_: Exception) {
            null
        }
    }

    override fun onCleared() {
        job?.cancel()
        if (extractorDelegate.isInitialized()) extractor.close()
    }
}
