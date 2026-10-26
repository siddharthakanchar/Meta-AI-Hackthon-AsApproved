"""OCR for on-screen text: word boxes, heights and text content.

Used for the text diff, for R7 (warning text vs median body-text height) and as
the fallback region source when SAM misses thin text lines (§16).

Engine choice is deferred to Phase 2: rapidocr-onnxruntime if it installs cleanly
on Windows + Python 3.11, else Tesseract. Record the choice in DECISIONS.md.
"""

from __future__ import annotations

__all__ = ["TextBox", "read_text"]


class TextBox:  # noqa: D101 - Phase 2
    pass


def read_text(image):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 2")
