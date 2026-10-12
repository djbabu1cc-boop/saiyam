"""Simple, professional Tkinter GUI for the Invoice Extractor."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from . import __version__
from .exporter import build_row, export_results
from .extractor import SUPPORTED_EXTENSIONS, extract_file_text
from .ocr import Ocr, available_engines
from .parser import parse_invoice_text

ACCENT = "#1F4E79"
ACCENT_HOVER = "#2E6DA4"
OK_GREEN = "#2E7D32"
ERR_RED = "#C62828"

_FILE_COLUMNS = ("file", "status", "method", "message")
_FILE_TITLES = ("Invoice file", "Status", "Method", "Message")
_FILE_WIDTHS = (320, 110, 110, 420)

_RES_COLUMNS = ("no", "invoice_no", "date", "vendor", "gstin", "taxable",
                "cgst", "sgst", "igst", "total", "file")
_RES_TITLES = ("#", "Invoice No", "Date", "Vendor / Supplier", "GSTIN",
               "Taxable", "CGST", "SGST", "IGST", "Total", "Source file")
_RES_WIDTHS = (34, 120, 90, 240, 150, 100, 90, 90, 90, 100, 200)

__all__ = ["run_gui"]


def _enable_high_dpi() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def _fmt_money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.ocr = Ocr(log=lambda m: self.queue.put(("log", m)))
        self.file_order: List[str] = []
        self.file_items: Dict[str, str] = {}
        self.results_by_path: Dict[str, dict] = {}
        self.queue: "queue.Queue" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self._extract_total = 0
        self._extract_done = 0
        self._build_ui()
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = self.root
        root.title(f"Invoice Extractor v{__version__}  —  PDF & Image GST invoices")
        root.geometry("1240x760")
        root.minsize(1020, 620)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#F5F7FA")
        style.configure("TLabelframe", background="#F5F7FA")
        style.configure("TLabelframe.Label", background="#F5F7FA", font=("Segoe UI", 9, "bold"))
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        padding=(16, 7), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER), ("disabled", "#9DB4C8")])
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 9),
                        background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("TNotebook.Tab", padding=(14, 6))

        self._build_menu()
        self._build_toolbar()
        self._build_file_table()
        self._build_result_table()
        self._build_statusbar()

    def _build_menu(self) -> None:
        root = self.root
        menu = tk.Menu(root)
        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Add Files…", underline=0, command=self.add_files,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Add Folder…", command=self.add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Clear List", command=self.clear_all)
        file_menu.add_separator()
        file_menu.add_command(label="Export Excel (.xlsx)…", underline=0,
                              command=self.export_excel, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="About Invoice Extractor", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        root.config(menu=menu)

        root.bind_all("<Control-o>", lambda _e: self.add_files())
        root.bind_all("<Control-s>", lambda _e: self.export_excel())

    def _build_toolbar(self) -> None:
        root = self.root
        bar = ttk.Frame(root, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Button(bar, text="Add Files", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="Add Folder", command=self.add_folder).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Clear", command=self.clear_all).pack(side="left", padx=(6, 0))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10, pady=2)
        ttk.Button(bar, text="Re-run Failed", command=self.rerun_failed).pack(side="left")
        self.extract_btn = ttk.Button(bar, text="Extract All", style="Accent.TButton",
                                      command=self.start_extraction)
        self.extract_btn.pack(side="left", padx=(6, 12))
        self.export_btn = ttk.Button(bar, text="Export Excel (.xlsx)",
                                     command=self.export_excel, state="disabled")
        self.export_btn.pack(side="left")

        engines = available_engines()
        eng_label = ", ".join(
            f"{e.name} ({'✓' if e.available else '✗'})" for e in engines
        )
        ttk.Label(bar, text=f"OCR engines: {eng_label}",
                  foreground="#5A6B7B").pack(side="right")

    def _build_file_table(self) -> None:
        root = self.root
        wrap = ttk.Labelframe(root, text="  Invoice files (batch)  ")
        wrap.pack(fill="both", expand=False, padx=10, pady=(0, 4))

        outer = ttk.Frame(wrap)
        outer.pack(fill="both", expand=True, padx=6, pady=4)

        self.file_tree = ttk.Treeview(outer, columns=_FILE_COLUMNS, show="headings",
                                      height=6)
        for col, title, width in zip(_FILE_COLUMNS, _FILE_TITLES, _FILE_WIDTHS):
            self.file_tree.heading(col, text=title)
            anchor = "w" if col in ("file", "message") else "center"
            self.file_tree.column(col, width=width, anchor=anchor, stretch=(col == "message"))
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=vsb.set)
        self.file_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.file_tree.bind("<Double-1>", self._on_file_double_click)

    def _build_result_table(self) -> None:
        root = self.root
        wrap = ttk.Labelframe(root, text="  Extracted data  ")
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        outer = ttk.Frame(wrap)
        outer.pack(fill="both", expand=True, padx=6, pady=4)

        self.res_tree = ttk.Treeview(outer, columns=_RES_COLUMNS, show="headings")
        for col, title, width in zip(_RES_COLUMNS, _RES_TITLES, _RES_WIDTHS):
            self.res_tree.heading(col, text=title)
            anchor = "w" if col in ("vendor", "file") else "e"
            self.res_tree.column(col, width=width, anchor=anchor, stretch=(col == "vendor"))
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self.res_tree.yview)
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=self.res_tree.xview)
        self.res_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.res_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        self.res_tree.bind("<Double-1>", self._on_res_double_copy)

    def _build_statusbar(self) -> None:
        root = self.root
        bar = ttk.Frame(root, padding=(10, 4))
        bar.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_var = tk.StringVar(value="Ready — add invoice files and press Extract All.")
        ttk.Label(bar, textvariable=self.status_var, foreground="#37474F",
                  padding=(10, 0)).pack(side="right")
        self.log_text = tk.Text(root, height=4, state="disabled", relief="flat",
                                font=("Consolas", 8), background="#EEF2F6")
        self.log_text.pack(fill="x", padx=10, pady=(0, 6))

    # ------------------------------------------------------------- helpers

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _add_files(self, paths: List[str]) -> None:
        added = 0
        for path in paths:
            path = os.path.normpath(path)
            ext = os.path.splitext(path)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            if path in self.file_items:
                continue
            item = self.file_tree.insert(
                "", "end",
                values=(os.path.basename(path), "Pending", "", ""),
                tags=("pending",),
            )
            self.file_items[path] = item
            self.file_order.append(path)
            added += 1
        if added:
            self._log(f"Added {added} file(s).")
            self._set_status(f"{len(self.file_order)} file(s) in the batch.")
        else:
            messagebox.showinfo(
                "Add files",
                "No supported invoice files were added.\n\nSupported: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS)),
            )

    def _set_file_row(self, path: str, status: str, method: str = "",
                      message: str = "", tag: str = "") -> None:
        item = self.file_items.get(path)
        if not item:
            return
        self.file_tree.item(item, values=(os.path.basename(path), status, method, message))
        if tag:
            self.file_tree.item(item, tags=(tag,))
            if tag == "ok":
                self.file_tree.item(item, tags=("ok",))

    # --------------------------------------------------------------- actions

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select invoice files",
            filetypes=[
                ("Invoice files", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"),
                ("PDF files", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._add_files(list(paths))

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select a folder of invoices")
        if not folder:
            return
        paths = []
        for name in sorted(os.listdir(folder)):
            ext = os.path.splitext(name)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                paths.append(os.path.join(folder, name))
        if not paths:
            messagebox.showinfo("Add folder", "No supported invoice files found in that folder.")
        self._add_files(paths)

    def clear_all(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Clear", "Extraction is still running.")
            return
        self.file_tree.delete(*self.file_tree.get_children())
        self.res_tree.delete(*self.res_tree.get_children())
        self.file_items.clear()
        self.file_order.clear()
        self.results_by_path.clear()
        self.export_btn.config(state="disabled")
        self.progress["value"] = 0
        self._set_status("Ready — add invoice files and press Extract All.")

    def start_extraction(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.file_order:
            messagebox.showinfo("Extract", "Add some invoice files first.")
            return
        targets = [p for p in self.file_order if p not in self.results_by_path]
        if not targets:
            messagebox.showinfo(
                "Extract",
                "All listed files have already been processed.\n"
                "Use 'Clear' to start over or 'Re-run Failed' for failed ones.",
            )
            return
        self._begin_extraction(targets)

    def rerun_failed(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        targets = [
            p for p in self.file_order
            if p in self.results_by_path
            and str(self.results_by_path[p].get("Status", "")).lower()
            in {"error", "no data found"}
        ]
        if not targets:
            messagebox.showinfo("Re-run failed", "No failed files to re-run.")
            return
        for p in targets:
            del self.results_by_path[p]
        self._begin_extraction(targets)

    def _begin_extraction(self, targets: List[str]) -> None:
        for p in targets:
            self._set_file_row(p, "Extracting…", "", "", "busy")
        self.extract_btn.config(state="disabled")
        self._extract_total = len(targets)
        self._extract_done = 0
        self.progress["maximum"] = len(targets)
        self.progress["value"] = 0
        self._set_status(f"Extracting {len(targets)} file(s)…")
        self.worker = threading.Thread(target=self._worker, args=(targets,), daemon=True)
        self.worker.start()

    def _worker(self, targets: List[str]) -> None:
        try:
            self._worker_inner(targets)
        except Exception as exc:  # never leave the UI stuck
            self.queue.put(("log", f"Worker error: {type(exc).__name__}: {exc}"))
            self.queue.put(("progress", self._extract_total, self._extract_total))

    def _worker_inner(self, targets: List[str]) -> None:
        self.queue.put(("log", f"OCR engine in use: {self.ocr.engine_name}"))
        for path in targets:
            self._set_status(f"Processing {os.path.basename(path)} …")
            try:
                outcome = extract_file_text(
                    path,
                    self.ocr,
                    log=lambda m, p=path: self.queue.put(("log", f"{os.path.basename(p)}: {m}")),
                )
                if outcome.error:
                    row = build_row(path, status="Error", note=outcome.error)
                    self.queue.put(("done", path, row, "Error", ""))
                else:
                    fields = parse_invoice_text(outcome.text)
                    missing = fields.missing()
                    status = "OK" if not fields.missing() or (fields.invoice_no or fields.total) \
                        else "No data found"
                    note = ("Missing: " + ", ".join(missing)) if missing else ""
                    row = build_row(
                        path,
                        fields=fields,
                        status=status,
                        method=outcome.method,
                        engine=outcome.ocr_engine,
                        note=note,
                    )
                    self.queue.put(("done", path, row, status, outcome.method))
            except Exception as exc:
                row = build_row(path, status="Error", note=f"{type(exc).__name__}: {exc}")
                self.queue.put(("done", path, row, "Error", ""))
            self._extract_done += 1
            self.queue.put(("progress", self._extract_done, self._extract_total))

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    self.progress["value"] = msg[1]
                    if msg[1] >= msg[2]:
                        self.extract_btn.config(state="normal")
                        self.export_btn.config(state="normal")
                        ok = sum(
                            1 for r in self.results_by_path.values()
                            if str(r.get("Status", "")).lower() not in {"error", "no data found"}
                        )
                        self._set_status(
                            f"Done — {ok}/{msg[2]} file(s) extracted. "
                            "Use 'Export Excel' to save the results."
                        )
                        self._log(f"Batch finished: {ok}/{msg[2]} file(s) with data.")
                elif kind == "done":
                    _kind, path, row, status, method = msg
                    self.results_by_path[path] = row
                    tag = "ok" if status == "OK" else ("error" if status == "Error" else "warn")
                    self._set_file_row(path, status, method, row.get("Notes", ""), tag)
                    self._refresh_results()
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _refresh_results(self) -> None:
        self.res_tree.delete(*self.res_tree.get_children())
        for idx, path in enumerate(self.file_order, start=1):
            row = self.results_by_path.get(path)
            if not row:
                continue
            self.res_tree.insert(
                "",
                "end",
                values=(
                    idx,
                    row["Invoice No"],
                    row["Invoice Date"],
                    row["Vendor / Supplier"],
                    row["GSTIN"],
                    _fmt_money(row["Taxable Amount"]),
                    _fmt_money(row["CGST"]),
                    _fmt_money(row["SGST"]),
                    _fmt_money(row["IGST"]),
                    _fmt_money(row["Total Invoice Amount"]),
                    row["File"],
                ),
                tags=(row["Status"],),
            )
        self.res_tree.tag_configure("OK", foreground=OK_GREEN)
        self.res_tree.tag_configure("Error", foreground=ERR_RED)
        self.res_tree.tag_configure("No data found", foreground="#B26A00")

    # ---------------------------------------------------------------- export

    def export_excel(self) -> None:
        rows = [self.results_by_path[p] for p in self.file_order if p in self.results_by_path]
        if not rows:
            messagebox.showinfo("Export", "Nothing to export yet — run an extraction first.")
            return
        default_name = f"invoices_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Save Excel file",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not path:
            return
        try:
            export_results(rows, path)
        except Exception as exc:
            messagebox.showerror("Export failed", f"{type(exc).__name__}: {exc}")
            return
        self._log(f"Exported {len(rows)} row(s) to {path}")
        messagebox.showinfo("Export complete", f"Saved {len(rows)} invoice(s) to:\n\n{path}")

    def show_about(self) -> None:
        messagebox.showinfo(
            "About Invoice Extractor",
            f"Invoice Extractor v{__version__}\n\n"
            "Batch-extracts invoice number, date, vendor, GSTIN, taxable value, "
            "CGST / SGST / IGST and total amount from PDF and image invoices "
            "(text layer + OCR), then exports everything to a formatted Excel "
            "workbook.\n\n"
            "Extracted data is heuristic — always verify it against the "
            "original invoice before use.",
        )

    # ---------------------------------------------------------------- events

    def _on_file_double_click(self, _event) -> None:
        item = self.file_tree.focus()
        if not item:
            return
        values = self.file_tree.item(item, "values")
        if not values:
            return
        name = str(values[0])
        path = next((p for p in self.file_items if os.path.basename(p) == name), None)
        if path:
            try:
                if hasattr(os, "startfile"):  # Windows
                    os.startfile(path)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception:
                pass

    def _on_res_double_copy(self, _event) -> None:
        item = self.res_tree.focus()
        if not item:
            return
        values = [str(v) for v in self.res_tree.item(item, "values")]
        self.root.clipboard_clear()
        self.root.clipboard_append("\t".join(values))
        self._set_status("Row copied to clipboard (tab-separated).")


def run_gui() -> None:
    """Create and run the Tkinter GUI (blocking)."""
    _enable_high_dpi()
    root = tk.Tk()
    App(root)  # noqa: F841 (kept alive by the main loop)
    root.mainloop()
