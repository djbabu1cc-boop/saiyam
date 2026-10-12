# Invoice Extractor

A simple, professional desktop app that **batch-extracts key data from GST
invoices** (PDFs and images) and exports it to a **formatted Excel `.xlsx`
workbook**.

![Build Windows EXE](https://github.com/djbabu1cc-boop/saiyam/actions/workflows/build-invoice-extractor.yml/badge.svg)

| | |
|---|---|
| **Fields extracted** | Invoice No · Invoice Date · Vendor/Supplier · GSTIN · Taxable Amount · CGST · SGST · IGST · Total Invoice Amount |
| **Input** | `.pdf` (text or scanned), `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp` |
| **Batch** | Yes — add files or a whole folder, one click |
| **OCR** | Built-in RapidOCR (ONNX, works out of the box) + optional Tesseract |
| **Output** | Formatted `.xlsx` (data sheet + summary sheet, filters, frozen header, number formats) |
| **Platforms** | Windows (ready-to-run `.exe`), plus any OS via Python |

---

## Contents

1. [Downloading the Windows .exe](#1-downloading-the-windows-exe)
2. [Running from source](#2-running-from-source)
3. [Command line usage](#3-command-line-usage)
4. [How it works](#4-how-it-works)
5. [Sample invoices](#5-sample-invoices)
6. [Optional: Tesseract for better OCR](#6-optional-tesseract-for-better-ocr)
7. [Project structure](#7-project-structure)
8. [CI/CD — how the .exe is built](#8-cicd--how-the-exe-is-built)
9. [Releasing a new version](#9-releasing-a-new-version)
10. [Troubleshooting](#10-troubleshooting)
11. [License](#11-license)

---

## 1. Downloading the Windows .exe

The `.exe` is **built automatically by GitHub Actions** — nothing is compiled
or uploaded by hand.

* **Latest release** → open the [Releases page](../../releases). Each version
  tag (e.g. `v1.0.0`) pushes a release with the
  `InvoiceExtractor-vX.Y.Z-win64.zip` attached.
* **Any build** → open [Actions → Build Invoice Extractor EXE](../../actions/workflows/build-invoice-extractor.yml)
  and download the `InvoiceExtractor-windows` artifact from any successful run.

To run it:

1. Download the zip and extract it somewhere (e.g. `C:\Tools\InvoiceExtractor`).
2. Double-click **`InvoiceExtractor.exe`** in the extracted folder — no
   installation required.
3. First launch takes a few seconds (the OCR model loads once at startup).

> The zip contains a folder (not a single .exe) on purpose: the built-in OCR
> engine ships its model files next to the executable.

## 2. Running from source

Python **3.9 – 3.12** (3.11 recommended).

```bat
:: Windows
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The GUI window opens — that is all there is to it.

**GUI tour**

1. **Add Files** / **Add Folder** — build your batch (PDFs and images can be mixed).
2. **Extract All** — runs the whole batch in the background; the status column
   updates per file (Pending → Extracting → OK / Error).
3. The bottom table shows every field extracted, live.
4. **Export Excel (.xlsx)** — saves a formatted workbook (data + summary
   sheet, auto-filter, frozen header, `#,##0.00` number formats).
5. **Re-run Failed** retries errored files; **Clear** resets the batch.
6. Double-click a result row to copy it as tab-separated text.

## 3. Command line usage

The same engine works headless — handy for scripts and cron jobs:

```bash
# Single invoice -> JSON on stdout
python main.py samples/invoice_1_gst.pdf --json

# A whole folder -> Excel file
python main.py invoices/ --out results.xlsx

# Force a specific OCR engine
python main.py . --engine tesseract --out results.xlsx
```

`--out` omitted → writes `invoices_<timestamp>.xlsx` in the current directory.
Exit code is `0` when at least one invoice was extracted, `1` otherwise.

## 4. How it works

```
┌────────────┐   text layer?   ┌──────────────┐
│  PDF file  │ ───────────────►│  pypdf text  │──┐
└────────────┘                 └──────────────┘  │
     │ no text (scanned)                          │
     ▼                                            │
┌──────────────────┐                              ▼
│ pypdfium2 render │ ──► OCR engine ──► raw text ─┤
└──────────────────┘      (RapidOCR /             │
                          Tesseract)              │
┌────────────┐                              ┌─────▼─────────┐
│ PNG/JPG/…  │ ───────────────► OCR engine ─►│ regex parser  │
└────────────┘                              │ (fields)      │
                                            └─────┬─────────┘
                                                  ▼
                                          formatted .xlsx
```

* **PDF with a text layer** is read directly (fast, no OCR).
* **Scanned PDF** pages are rendered at ~216 dpi and OCR'd.
* **Image invoices** are OCR'd directly.
* The **parser** then looks for labelled fields with tolerant regular
  expressions (Indian date formats, Indian *and* western digit grouping,
  `CGST @ 9%: 2,340.00` style lines, vendor header heuristics, …).
* Anything it cannot find is left **empty** — the parser never invents data.
  Review the *Notes* column (`Missing: …`) in the exported sheet.

## 5. Sample invoices

The `samples/` folder contains four invoices covering every extraction path —
perfect for a first test run:

| File | Type | Path exercised |
|---|---|---|
| `invoice_1_gst.pdf` | text PDF, intrastate | PDF text layer, CGST + SGST |
| `invoice_2_igst.pdf` | text PDF, interstate | PDF text layer, IGST, Indian `1,45,000.00` grouping |
| `invoice_3_image.png` | image invoice | OCR |
| `invoice_4_scanned.pdf` | image-only ("scanned") PDF | render + OCR |

Run the test suite (also used by CI):

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests
```

## 6. Optional: Tesseract for better OCR

The built-in **RapidOCR** engine works out of the box (its ONNX models ship
with the app). For the highest accuracy on messy scans you can install
[Tesseract 5](https://github.com/UB-Mannheim/tesseract/wiki) — when the app
sees a `tesseract` executable on `PATH` it uses it automatically, and the
toolbar shows which engine is active.

```bat
:: Windows (winget)
winget install --id UB Mannheim.TesseractOCR.OCR
```

## 7. Project structure

```
├── (repo root) .github/workflows/
│   └── build-invoice-extractor.yml # CI: build .exe, artifacts, releases
├── InvoiceExtractor.spec                 # PyInstaller specification
├── main.py                               # launcher / PyInstaller entry point
├── requirements.txt                      # runtime dependencies
├── requirements-dev.txt                  # + PyInstaller, ReportLab
├── invoice_extractor/
│   ├── __init__.py                       # version
│   ├── __main__.py                       # python -m invoice_extractor
│   ├── app.py                            # Tkinter GUI
│   ├── cli.py                            # headless CLI
│   ├── extractor.py                      # file → text (pypdf / pypdfium2 / OCR)
│   ├── ocr.py                            # OCR engines (RapidOCR, Tesseract)
│   ├── parser.py                         # text → invoice fields (regex)
│   └── exporter.py                       # results → formatted .xlsx
├── samples/                              # 4 sample invoices (all paths)
├── scripts/generate_samples.py           # regenerates the samples
├── assets/icon.ico                       # app icon
└── tests/                                # unit + end-to-end tests
```

## 8. CI/CD — how the .exe is built

`.github/workflows/build-windows.yml`:

| Trigger | What happens |
|---|---|
| Every push / PR | Build the `.exe` on `windows-latest`, run the test suite, upload a **`InvoiceExtractor-windows` artifact** (90-day retention) |
| Push a tag `v*` (e.g. `v1.0.0`) | Same build **plus** a **GitHub Release** with the zip attached |
| Manual (Workflow dispatch) | Same as a push |

Build steps: `checkout → Python 3.11 → pip install → unittest → PyInstaller
(one-folder, windowed, icon) → zip → upload`.

## 9. Releasing a new version

1. Bump `__version__` in `invoice_extractor/__init__.py` (and `pyproject.toml`).
2. Commit and push:

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

3. GitHub Actions builds the `.exe` and automatically creates a GitHub
   Release named `v1.1.0` with the zip attached.

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| A field comes out empty | Invoices vary — check the *Notes* column (`Missing: …`), then correct the value in Excel. Better-quality scans improve results. |
| OCR is slow on the first file | The OCR model loads once per launch; subsequent files are fast. |
| `No OCR engine available` | Reinstall dependencies: `pip install -r requirements.txt` (needs `onnxruntime` + `rapidocr-onnxruntime`). |
| Wrong vendor name extracted | The vendor heuristic reads the top of the invoice; labelled invoices (`Vendor: …`, `Supplier: …`) are always preferred. |
| `.exe` says "cannot find DLL" | Run the exe from the extracted folder (don't move just the `.exe` out of it). |
| SmartScreen warning on Windows | Expected for unsigned builds → *More info → Run anyway*. |

> **Disclaimer** — extracted data is heuristic. Always verify values against
> the original invoice before using them for accounting or GST filing.

## 11. License

MIT — see [LICENSE](LICENSE).
