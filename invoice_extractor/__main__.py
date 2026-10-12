"""Module entry point.

* ``python -m invoice_extractor``          -> launches the GUI
* ``python -m invoice_extractor a.pdf ...``-> runs the headless CLI
* ``python -m invoice_extractor --gui``    -> forces the GUI
"""
from __future__ import annotations

import sys

__all__ = ["main"]


def _show_fatal(exc: BaseException) -> None:
    """Show a visible error dialog when the GUI cannot start (windowed build)."""
    msg = f"Invoice Extractor failed to start:\n\n{type(exc).__name__}: {exc}"
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Invoice Extractor", msg)
        root.destroy()
        return
    except Exception:
        pass
    try:  # Windows MessageBox as a last resort
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "Invoice Extractor", 0x10)
        return
    except Exception:
        pass
    print(msg, file=sys.stderr)


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in {"--gui", "-g"}:
        from .app import run_gui

        try:
            run_gui()
        except Exception as exc:
            _show_fatal(exc)
            return 1
        return 0
    if args:
        from .cli import run as cli_run

        return cli_run(args)
    from .app import run_gui

    try:
        run_gui()
    except Exception as exc:
        _show_fatal(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
