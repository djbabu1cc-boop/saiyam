package com.djbabu.invoiceextractor

import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.djbabu.invoiceextractor.databinding.ItemInvoiceBinding
import java.text.NumberFormat
import java.util.Locale

class InvoiceAdapter(
    private val onClick: (InvoiceItem) -> Unit,
) : ListAdapter<InvoiceItem, InvoiceAdapter.Holder>(DIFF) {

    class Holder(val binding: ItemInvoiceBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
        Holder(ItemInvoiceBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val item = getItem(position)
        val ctx = holder.itemView.context
        val b = holder.binding
        b.name.text = item.name
        b.root.setOnClickListener { onClick(item) }

        val row = item.row
        val (label, color) = when {
            item.state == InvoiceItem.State.RUNNING -> ctx.getString(R.string.state_running) to R.color.status_running
            row == null -> ctx.getString(R.string.state_pending) to R.color.status_pending
            row.status == "OK" && row.note.isEmpty() -> row.status to R.color.status_ok
            row.status == "OK" -> row.status to R.color.status_partial
            else -> row.status to R.color.status_error
        }
        b.status.text = label
        b.status.setTextColor(ContextCompat.getColor(ctx, color))

        val details = when {
            item.state == InvoiceItem.State.RUNNING -> item.progress.ifEmpty { ctx.getString(R.string.state_running) }
            row == null -> ""
            else -> describe(ctx, item)
        }
        b.details.text = details
        b.details.visibility = if (details.isEmpty()) View.GONE else View.VISIBLE
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<InvoiceItem>() {
            override fun areItemsTheSame(a: InvoiceItem, b: InvoiceItem) = a.id == b.id
            override fun areContentsTheSame(a: InvoiceItem, b: InvoiceItem) = a == b
        }

        private val money: NumberFormat = NumberFormat.getNumberInstance(Locale("en", "IN")).apply {
            minimumFractionDigits = 2
            maximumFractionDigits = 2
        }

        private fun fmt(v: Double?): String = if (v == null) "–" else money.format(v)

        /** Human readable summary of an extracted invoice. */
        fun describe(ctx: Context, item: InvoiceItem): String {
            val row = item.row ?: return ""
            val f = row.fields ?: return row.note
            return buildString {
                appendLine(ctx.getString(R.string.field_invoice_no, f.invoiceNo.ifEmpty { "–" }, f.date.ifEmpty { "–" }))
                appendLine(ctx.getString(R.string.field_vendor, f.vendor.ifEmpty { "–" }))
                appendLine(ctx.getString(R.string.field_gstin, f.gstin.ifEmpty { "–" }))
                appendLine(ctx.getString(R.string.field_taxes, fmt(f.taxable), fmt(f.cgst), fmt(f.sgst), fmt(f.igst)))
                append(ctx.getString(R.string.field_total, fmt(f.total)))
                if (row.methodEngine.isNotEmpty()) append("   ·   ").append(row.methodEngine)
                if (row.note.isNotEmpty()) append("\n").append(row.note)
            }
        }
    }
}
