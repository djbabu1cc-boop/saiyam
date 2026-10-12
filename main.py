"""Launcher / PyInstaller entry point for the Invoice Extractor.

Run the GUI:        python main.py
Run the CLI:        python main.py invoice.pdf --out results.xlsx
"""
import sys

from invoice_extractor.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
