"""OCR engine abstraction.

Two engines are supported:

* **RapidOCR**  - bundled ONNX models, works out of the box (default).
* **Tesseract** - used automatically when the ``tesseract`` executable is
  installed (usually gives the best accuracy).

The rest of the application only talks to :class:`Ocr`, so adding another
engine later is a one-class change.
"""
from __future__ import annotations

import shutil
import statistics
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image

try:  # numpy is required by RapidOCR
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

try:
    import pytesseract
    _HAS_PYTESSERACT = True
except ImportError:  # pragma: no cover
    _HAS_PYTESSERACT = False

__all__ = [
    "Ocr",
    "OcrEngineInfo",
    "available_engines",
    "default_engine_name",
]


@dataclass
class OcrEngineInfo:
    """Describes an OCR engine and whether it can be used right now."""

    name: str
    available: bool
    detail: str = ""


def available_engines() -> List[OcrEngineInfo]:
    """Return every known OCR engine with its availability status."""
    engines: List[OcrEngineInfo] = []
    if _HAS_PYTESSERACT and shutil.which("tesseract"):
        engines.append(
            OcrEngineInfo("tesseract", True, f"binary: {shutil.which('tesseract')}")
        )
    else:
        reason = (
            "tesseract executable not found on PATH"
            if _HAS_PYTESSERACT
            else "pytesseract package not installed"
        )
        engines.append(OcrEngineInfo("tesseract", False, reason))

    if np is None:
        engines.append(OcrEngineInfo("rapidocr", False, "numpy not installed"))
    else:
        try:
            import rapidocr_onnxruntime  # noqa: F401

            engines.append(OcrEngineInfo("rapidocr", True, "bundled ONNX model"))
        except Exception as exc:  # pragma: no cover
            engines.append(OcrEngineInfo("rapidocr", False, str(exc)))
    return engines


def default_engine_name() -> str:
    """Prefer Tesseract when installed, otherwise fall back to RapidOCR."""
    engines = available_engines()
    for engine in engines:
        if engine.name == "tesseract" and engine.available:
            return "tesseract"
    for engine in engines:
        if engine.name == "rapidocr" and engine.available:
            return "rapidocr"
    return "rapidocr"


class _RapidEngine:
    """Thin wrapper around ``rapidocr_onnxruntime``."""

    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self._ocr = RapidOCR()

    def image_to_text(self, image: Image.Image) -> str:
        arr = np.array(image.convert("RGB"))
        try:
            result, _elapse = self._ocr(arr)
        except Exception:
            return ""
        if not result:
            return ""
        return "\n".join(_lines_from_boxes(result))


def _lines_from_boxes(result: List) -> List[str]:
    """Cluster RapidOCR text boxes into visual lines, top to bottom."""
    rows: List[Tuple[float, float, float, str]] = []
    for item in result:
        try:
            box, text, _score = item[0], item[1], item[2]
            ys = [float(p[1]) for p in box]
            xs = [float(p[0]) for p in box]
        except Exception:
            continue
        if not text or not text.strip():
            continue
        rows.append(((min(ys) + max(ys)) / 2.0, max(ys) - min(ys), min(xs), str(text).strip()))
    if not rows:
        return []
    rows.sort(key=lambda r: (r[0], r[2]))

    heights = [r[1] for r in rows if r[1] > 0]
    median_h = statistics.median(heights) if heights else 12.0
    tolerance = max(median_h * 0.6, 6.0)

    # each line: (running_average_y, [(x, text), ...])
    lines: List[Tuple[float, List[Tuple[float, str]]]] = []
    for y, _h, x, text in rows:
        if lines and abs(y - lines[-1][0]) <= tolerance:
            avg = (lines[-1][0] * len(lines[-1][1]) + y) / (len(lines[-1][1]) + 1)
            lines[-1] = (avg, lines[-1][1] + [(x, text)])
        else:
            lines.append((y, [(x, text)]))
    return [" ".join(t for _x, t in sorted(seg)) for _avg, seg in lines]


class _TesseractEngine:
    """Wrapper around Tesseract via pytesseract."""

    name = "tesseract"

    def __init__(self) -> None:
        if not shutil.which("tesseract"):
            raise RuntimeError(
                "tesseract executable not found. Install Tesseract 5 or use the "
                "built-in RapidOCR engine."
            )

    def image_to_text(self, image: Image.Image) -> str:
        return pytesseract.image_to_text(image, config="--psm 4") or ""


class Ocr:
    """High-level OCR facade used by the extractor.

    Parameters
    ----------
    engine:
        ``"auto"`` (default), ``"rapidocr"`` or ``"tesseract"``.
    log:
        Optional callback receiving human readable log lines.
    """

    def __init__(self, engine: Optional[str] = None, log=print) -> None:
        self._log = log
        wanted = (engine or "auto").lower()
        if wanted == "auto":
            wanted = default_engine_name()
        self.engine_name = wanted
        info = next((e for e in available_engines() if e.name == wanted), None)
        if info is None or not info.available:
            fallback = next(
                (e.name for e in available_engines() if e.available), None
            )
            if fallback:
                self._log(
                    f"OCR engine '{wanted}' is unavailable ({info.detail if info else 'unknown'}); "
                    f"falling back to '{fallback}'."
                )
                self.engine_name = fallback
        self._engine = None
        self._engine_class = _TesseractEngine if self.engine_name == "tesseract" else _RapidEngine

    @property
    def available(self) -> bool:
        info = next((e for e in available_engines() if e.name == self.engine_name), None)
        return bool(info is not None and info.available)

    def warmup(self) -> None:
        """Load the (potentially heavy) engine model up front."""
        if self._engine is None and self.available:
            self._engine = self._engine_class()

    def text(self, image: Image.Image) -> str:
        """Run OCR on a PIL image and return the recognised text."""
        if not self.available:
            raise RuntimeError(f"OCR engine '{self.engine_name}' is not available")
        self.warmup()
        return self._engine.image_to_text(self._prepare(image)).strip()

    @staticmethod
    def _prepare(image: Image.Image) -> Image.Image:
        img = image.convert("RGB")
        if 0 < img.width < 1600:
            scale = min(2.0, 1600.0 / img.width)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        return img
