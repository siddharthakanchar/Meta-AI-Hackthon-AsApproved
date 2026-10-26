"""OCR for on-screen text: word boxes, heights, and the text itself.

Feeds the text diff, R7 (warning height vs body height) and R11 (prescribed
wording). Engine: rapidocr-onnxruntime, which installs cleanly on Windows and
needs no system binary.

**The thing to know about OCR here.** It does not return the text that was
rendered; it returns its best reading of it. On our own masters it emits
`Representativeexample:f1,200creditover` for "Representative example: £1,200
credit over" — spaces dropped, £ read as f, at 0.97 confidence. Any rule that
compares OCR output to prescribed wording character-for-character will therefore
accuse a perfectly correct advertiser. R11 compares with an explicit similarity
band instead, and says so in the finding (see `text_norm.compare_prescribed`).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

__all__ = ["TextBox", "OcrResult", "read_text", "ocr_available", "text_in_box"]


@dataclass(frozen=True)
class TextBox:
    text: str
    box: tuple[int, int, int, int]  # x, y, w, h
    confidence: float

    @property
    def height(self) -> int:
        return self.box[3]


@dataclass(frozen=True)
class OcrResult:
    boxes: list[TextBox]
    engine: str

    @property
    def available(self) -> bool:
        return self.engine != "none"

    def text(self) -> str:
        return " ".join(b.text for b in self.boxes)

    def median_height(self) -> int | None:
        heights = [b.height for b in self.boxes if b.height > 0]
        if not heights:
            return None
        return int(np.median(heights))


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()
    except Exception:  # noqa: BLE001 - absence is a reported state, not a crash
        return None


def ocr_available() -> bool:
    return _engine() is not None


def read_text(image_bgr: np.ndarray) -> OcrResult:
    """Read all text in an image. Returns an empty result when OCR is unavailable.

    An unavailable engine must surface as `available=False` so the rules report
    `inconclusive`, never as empty text that would look like "no warning found".
    """
    engine = _engine()
    if engine is None:
        return OcrResult(boxes=[], engine="none")

    try:
        raw, _ = engine(image_bgr)
    except Exception:  # noqa: BLE001
        return OcrResult(boxes=[], engine="none")

    boxes: list[TextBox] = []
    for item in raw or []:
        poly, text, score = item[0], item[1], item[2]
        pts = np.asarray(poly, dtype=np.float64).reshape(-1, 2)
        x0, y0 = pts[:, 0].min(), pts[:, 1].min()
        x1, y1 = pts[:, 0].max(), pts[:, 1].max()
        boxes.append(
            TextBox(
                text=str(text),
                box=(int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)),
                confidence=float(score),
            )
        )
    return OcrResult(boxes=boxes, engine="rapidocr")


def text_in_box(result: OcrResult, box: tuple[int, int, int, int], *, min_overlap: float = 0.5) -> OcrResult:
    """Keep only the text boxes mostly inside `box` — e.g. the warning region."""
    bx, by, bw, bh = box
    kept: list[TextBox] = []
    for tb in result.boxes:
        tx, ty, tw, th = tb.box
        ox = max(0, min(bx + bw, tx + tw) - max(bx, tx))
        oy = max(0, min(by + bh, ty + th) - max(by, ty))
        area = tw * th
        if area and (ox * oy) / area >= min_overlap:
            kept.append(tb)
    return OcrResult(boxes=kept, engine=result.engine)
