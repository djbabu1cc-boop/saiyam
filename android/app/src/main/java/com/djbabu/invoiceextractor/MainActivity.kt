package com.djbabu.invoiceextractor

import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.djbabu.invoiceextractor.databinding.ActivityMainBinding
import com.djbabu.invoiceextractor.extract.InvoiceTextExtractor
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val viewModel: MainViewModel by viewModels()
    private val adapter = InvoiceAdapter { showDetails(it) }

    private val pickFiles = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        viewModel.addUris(uris)
    }

    private val pickFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        uri?.let { viewModel.addFolder(it) }
    }

    private val saveWorkbook = registerForActivityResult(
        ActivityResultContracts.CreateDocument(XLSX_MIME),
    ) { uri ->
        uri?.let { viewModel.exportTo(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            v.updatePadding(left = bars.left, top = bars.top, right = bars.right, bottom = bars.bottom)
            insets
        }

        binding.toolbar.subtitle = getString(R.string.app_subtitle, BuildConfig.VERSION_NAME)
        binding.list.layoutManager = LinearLayoutManager(this)
        binding.list.adapter = adapter

        binding.addFiles.setOnClickListener { pickFiles.launch(InvoiceTextExtractor.PICKER_MIME_TYPES) }
        binding.addFolder.setOnClickListener { pickFolder.launch(null) }
        binding.clear.setOnClickListener { viewModel.clear() }
        binding.extract.setOnClickListener {
            if (viewModel.busy.value == true) viewModel.cancel() else viewModel.extractAll()
        }
        binding.save.setOnClickListener { saveWorkbook.launch(viewModel.suggestedFileName()) }
        binding.share.setOnClickListener { shareWorkbook() }

        viewModel.items.observe(this) { items ->
            adapter.submitList(items)
            render()
        }
        viewModel.busy.observe(this) { render() }
        viewModel.messages.observe(this) { event ->
            event.take()?.let { Toast.makeText(this, it, Toast.LENGTH_LONG).show() }
        }

        if (savedInstanceState == null) handleIncoming(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIncoming(intent)
    }

    /** Invoices shared to the app from WhatsApp, Gmail, Files, … */
    private fun handleIncoming(intent: Intent?) {
        intent ?: return
        val uris = mutableListOf<Uri>()
        when (intent.action) {
            Intent.ACTION_SEND -> intent.streamExtra()?.let { uris += it }
            Intent.ACTION_SEND_MULTIPLE -> uris += intent.streamExtras()
            Intent.ACTION_VIEW -> intent.data?.let { uris += it }
        }
        intent.clipData?.let { clip ->
            for (i in 0 until clip.itemCount) clip.getItemAt(i).uri?.let { if (it !in uris) uris += it }
        }
        viewModel.addUris(uris)
    }

    @Suppress("DEPRECATION")
    private fun Intent.streamExtra(): Uri? =
        if (Build.VERSION.SDK_INT >= 33) getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun Intent.streamExtras(): List<Uri> =
        (if (Build.VERSION.SDK_INT >= 33) getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else getParcelableArrayListExtra(Intent.EXTRA_STREAM)).orEmpty()

    private fun render() {
        val items = viewModel.items.value.orEmpty()
        val busy = viewModel.busy.value == true
        val results = items.count { it.row != null }
        val withData = items.count { it.row != null && !it.row.isProblem }

        binding.empty.visibility = if (items.isEmpty()) View.VISIBLE else View.GONE
        binding.progress.visibility = if (busy) View.VISIBLE else View.GONE
        binding.addFiles.isEnabled = !busy
        binding.addFolder.isEnabled = !busy
        binding.clear.isEnabled = !busy && items.isNotEmpty()
        binding.extract.isEnabled = items.isNotEmpty()
        binding.extract.setText(if (busy) R.string.action_cancel else R.string.action_extract)
        binding.save.isEnabled = !busy && results > 0
        binding.share.isEnabled = !busy && results > 0

        if (busy && items.isNotEmpty()) {
            val done = items.count { it.state == InvoiceItem.State.DONE }
            binding.progress.max = items.size
            binding.progress.setProgressCompat(done, true)
        }
        binding.status.text = when {
            items.isEmpty() -> getString(R.string.status_ready)
            busy -> getString(R.string.status_extracting, items.count { it.state == InvoiceItem.State.DONE }, items.size)
            results == 0 -> resources.getQuantityString(R.plurals.status_files, items.size, items.size)
            else -> getString(R.string.status_results, withData, items.size)
        }
    }

    private fun showDetails(item: InvoiceItem) {
        val body = buildString {
            append(InvoiceAdapter.describe(this@MainActivity, item))
            if (item.text.isNotBlank()) {
                append("\n\n")
                append(getString(R.string.details_extracted_text))
                append("\n")
                append(item.text.trim().take(4000))
            }
        }
        MaterialAlertDialogBuilder(this)
            .setTitle(item.name)
            .setMessage(body)
            .setPositiveButton(android.R.string.ok, null)
            .apply {
                if (viewModel.busy.value != true) {
                    setNegativeButton(R.string.action_remove) { _, _ -> viewModel.remove(item.id) }
                }
            }
            .show()
    }

    private fun shareWorkbook() {
        lifecycleScope.launch {
            val file = viewModel.exportForSharing()
            if (file == null) {
                Toast.makeText(this@MainActivity, R.string.msg_save_failed, Toast.LENGTH_LONG).show()
                return@launch
            }
            val uri = FileProvider.getUriForFile(this@MainActivity, "$packageName.fileprovider", file)
            val send = Intent(Intent.ACTION_SEND).apply {
                type = XLSX_MIME
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_SUBJECT, file.name)
                clipData = ClipData.newRawUri(file.name, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(send, getString(R.string.action_share)))
        }
    }

    companion object {
        const val XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
}
