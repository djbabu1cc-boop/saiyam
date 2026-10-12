"""Convert invoice files (PDF / images) into plain text.

* PDFs with a real text layer are read directly with ``pypdf`` (fast, no OCR).
* Scanned PDFs are rendered with ``pypdfium2`` and sent through OCR.
* Image invoices (PNG/JPG/TIFF/BMP/WEBP) are OCR'd directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional

from PIL import Image

SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
}
IMAGE_EXTENSIONS = SUPPORTED_EXTENSIONS - {".pdf"}

MIN_TEXT_CHARS = 40   # shorter than this, a PDF is treated as scanned
RENDER_SCALE = 3.0    # 72 dpi * 3 ~= 216 dpi rendering for OCR

LogFn = Callable[[str], None]

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "ExtractionOutcome",
    "extract_file_text",
]


@dataclass
class ExtractionOutcome:
    """Result of turning one file into text."""

    path: str
    text: str = ""
    method: str = ""          # "pdf-text" | "pdf-ocr" | "image-ocr"
    pages: int = 0
    ocr_engine: str = ""      # engine used, if OCR was needed
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def extract_file_text(
    path: str,
    ocr,  # invoice_extractor.ocr.Ocr
    log: Optional[LogFn] = None,
) -> ExtractionOutcome:
    """Extract text from a single invoice file. Never raises."""
    if log is None:
        log = lambda _m: None  # noqa: E731

    outcome = ExtractionOutcome(path=path)
    if not os.path.exists(path):
        outcome.error = "File not found"
        return outcome

    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        outcome.error = (
            f"Unsupported file type '{ext or '<none>'}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
        return outcome

    try:
        if ext == ".pdf":
            outcome = _extract_pdf(path, ocr, log)
        else:
            outcome = _extract_image(path, ocr, log)
    except Exception as exc:
        outcome = ExtractionOutcome(path=path)
        outcome.error = f"{type(exc).__name__}: {exc}"
    return outcome


def _extract_pdf(path: str, ocr, log: LogFn) -> ExtractionOutcome:
    import pypdf

    outcome = ExtractionOutcome(path=path)
    reader = pypdf.PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")  # try the empty password
        except Exception:
            outcome.error = "PDF is password-protected and could not be opened"
            return outcome

    page_texts: List[str] = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:
            page_texts.append("")
    outcome.pages = len(page_texts)

    combined = "\n\n".join(page_texts)
    if len(combined.strip()) >= MIN_TEXT_CHARS:
        outcome.text = combined
        outcome.method = "pdf-text"
        return outcome

    # No usable text layer -> render pages and OCR them.
    if not ocr.available:
        outcome.error = (
            "PDF contains no embedded text and no OCR engine is available "
            "(install onnxruntime + rapidocr-onnxruntime)"
        )
        return outcome

    log(f"PDF appears to be scanned - OCR-ing with {ocr.engine_name} …")
    ocr.warmup()
    outcome.ocr_engine = ocr.engine_name
    page_ocr_texts: List[str] = []
    for i, page_image in enumerate(_iter_pdf_page_images(path), start=1):
        log(f"OCR page {i} of {outcome.pages} …")
        page_ocr_texts.append(ocr.text(page_image))
    outcome.text = "\n\n".join(page_ocr_texts)
    outcome.method = "pdf-ocr"
    if not outcome.text.strip():
        outcome.error = "OCR could not read any text from this PDF"
    return outcome


def _iter_pdf_page_images(path: str) -> Iterator[Image.Image]:
    """Render every page of a PDF to a PIL image."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        for page in pdf:
            bitmap = page.render(scale=RENDER_SCALE)
            yield bitmap.to_pil()
    finally:
        pdf.close()


def _extract_image(path: str, ocr, log: LogFn) -> ExtractionOutcome:
    outcome = ExtractionOutcome(path=path)
    if not ocr.available:
        outcome.error = "No OCR engine is available for image files"
        return outcome

    with Image.open(path) as im:
        im.load()
        ocr.warmup()
        outcome.ocr_engine = ocr.engine_name
        outcome.text = ocr.text(im)
    outcome.method = "image-ocr"
    outcome.pages = 1
    if not outcome.text.strip():
        outcome.error = "OCR could not read any text from this image"
    return outcome
