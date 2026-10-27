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


def locate_text_region(
    result: OcrResult,
    reference_text: str,
    *,
    min_word_overlap: float = 0.4,
    exclude: list[tuple[int, int, int, int]] | None = None,
) -> tuple[int, int, int, int] | None:
    """Find where a known block of text ended up, by its words.

    Why this exists. Two earlier locators each failed on a case the other
    handled: template matching dies when a variant restyles the warning
    (grey-on-grey, shrunk, reworded), and falling back to "wherever the master
    had it" dies when a variant REFLOWS the layout — shrinking the warning moves
    everything below it, so the fallback measured empty background and reported
    no border, no contrast, and an occlusion that belonged to a different part
    of the frame.

    Text survives both. A warning that has been restyled or moved is still built
    from the same words, so the region is found by matching words rather than
    pixels or coordinates.

    Returns the union box of the matching lines, or None when too little of the
    reference text is found to be confident it is there at all.
    """
    if not result.available or not reference_text.strip():
        return None

    import re

    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9£%.]+", text.casefold()) if len(w) > 3}

    reference = words(reference_text)
    if not reference:
        return None

    excluded = exclude or []

    def overlaps_excluded(box) -> bool:
        x, y, w, h = box
        for ex, ey, ew, eh in excluded:
            ox = max(0, min(ex + ew, x + w) - max(ex, x))
            oy = max(0, min(ey + eh, y + h) - max(ey, y))
            if (w * h) and (ox * oy) / (w * h) >= 0.5:
                return True
        return False

    matched: list[TextBox] = []
    for tb in result.boxes:
        if overlaps_excluded(tb.box):
            continue
        tokens = words(tb.text)
        if not tokens:
            continue
        overlap = len(tokens & reference) / len(tokens)
        if overlap >= min_word_overlap:
            matched.append(tb)

    if not matched:
        return None

    # Require a reasonable share of the reference text to be accounted for, so a
    # single incidental word elsewhere in the creative cannot resurrect a
    # warning that was genuinely removed.
    # Keep only a vertically contiguous block, not every scattered match.
    # Words like "invest" and "money" also appear in body copy and small print,
    # so a plain union returned a box 499px tall for a 117px warning — and a box
    # that is not the box has no border at its perimeter, which is exactly how
    # R5 came to report "no border" on ten variants that plainly had one.
    matched.sort(key=lambda b: b.box[1])
    median_h = sorted(b.box[3] for b in matched)[len(matched) // 2]
    max_gap = max(8, int(median_h * 1.8))

    clusters: list[list[TextBox]] = [[matched[0]]]
    for tb in matched[1:]:
        previous = clusters[-1][-1]
        gap = tb.box[1] - (previous.box[1] + previous.box[3])
        if gap <= max_gap:
            clusters[-1].append(tb)
        else:
            clusters.append([tb])

    def cluster_score(cluster: list[TextBox]) -> tuple[int, int]:
        covered = set()
        for tb in cluster:
            covered |= words(tb.text) & reference
        return (len(covered), len(cluster))

    best = max(clusters, key=cluster_score)
    covered = set()
    for tb in best:
        covered |= words(tb.text) & reference
    if len(covered) / len(reference) < 0.35:
        return None

    # Drop horizontal outliers before taking the union. A block of warning text
    # has lines that start at the same margin; a line reaching far wider is
    # usually a neighbouring element the word filter happened to admit. Taking
    # a plain union let one such line widen the box by ~80px, and with the side
    # overlay bands only ~43px wide, that localisation error alone pushed the
    # box into them and produced R12 false positives.
    import statistics

    lefts = [b.box[0] for b in best]
    rights = [b.box[0] + b.box[2] for b in best]
    if len(best) >= 3:
        med_l, med_r = statistics.median(lefts), statistics.median(rights)
        spread = max(12, int((med_r - med_l) * 0.12))
        kept = [
            b
            for b in best
            if abs(b.box[0] - med_l) <= spread and abs(b.box[0] + b.box[2] - med_r) <= spread
        ]
        if kept:
            best = kept

    xs0 = min(b.box[0] for b in best)
    ys0 = min(b.box[1] for b in best)
    xs1 = max(b.box[0] + b.box[2] for b in best)
    ys1 = max(b.box[1] + b.box[3] for b in best)
    return (xs0, ys0, xs1 - xs0, ys1 - ys0)
