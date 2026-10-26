"""Calibrate R11's OCR similarity bands against the real dataset.

R11 asks whether prescribed wording was altered. When the text comes from OCR,
exact comparison is wrong: the engine drops spaces and misreads currency glyphs,
so a correct advertiser would be accused of rewriting the warning.

This measures, on every investment master and its variants:
  - similarity(OCR text of a CORRECT warning, prescribed)   -> should be high
  - similarity(OCR text of a REWORDED warning, prescribed)  -> should be low

The gap between those two populations is where the bands belong. If they
overlap, R11 cannot separate OCR noise from rewriting on this creative and the
honest response is a wider `uncertain` band, not a tighter guess.

    python scripts/calibrate_ocr_bands.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.synth.build import render_master_frame  # noqa: E402
from asapproved.synth.specs import MASTERS, prescribed_text  # noqa: E402
from asapproved.synth.transforms import TRANSFORMS  # noqa: E402
from asapproved.synth.variants import _render_variant_frame  # noqa: E402
from asapproved.text_norm import similarity  # noqa: E402
from asapproved.vision.ocr import read_text, text_in_box  # noqa: E402


def ocr_warning(bgr, box) -> str:
    return text_in_box(read_text(bgr), box).text()


def main() -> int:
    reword = next(t for t in TRANSFORMS if t.name == "warning_reworded")
    correct: list[tuple[str, float]] = []
    altered: list[tuple[str, float]] = []

    for spec in MASTERS:
        if spec.is_credit:
            continue
        prescribed = prescribed_text(spec.investment_type)

        rendered = render_master_frame(spec)
        text = ocr_warning(rendered.to_bgr(), rendered.regions["warning"])
        correct.append((spec.id, similarity(text, prescribed)))

        rv = _render_variant_frame(spec, reword, 0)
        rtext = ocr_warning(rv.to_bgr(), rv.regions["warning"])
        altered.append((spec.id, similarity(rtext, prescribed)))

    print("CORRECT warnings (OCR vs prescribed) — want these high:")
    for name, r in correct:
        print(f"  {r:.4f}  {name}")
    print("\nREWORDED warnings (OCR vs prescribed) — want these low:")
    for name, r in altered:
        print(f"  {r:.4f}  {name}")

    lo_correct = min(r for _, r in correct)
    hi_altered = max(r for _, r in altered)
    print(f"\nworst correct : {lo_correct:.4f}")
    print(f"best altered  : {hi_altered:.4f}")
    print(f"separation    : {lo_correct - hi_altered:+.4f}")

    if lo_correct > hi_altered:
        print(
            f"\nSuggested bands:\n"
            f"  OCR_MATCH_ABOVE   = {hi_altered + (lo_correct - hi_altered) * 0.66:.2f}\n"
            f"  OCR_ALTERED_BELOW = {hi_altered + (lo_correct - hi_altered) * 0.33:.2f}"
        )
    else:
        print("\nPOPULATIONS OVERLAP — OCR cannot separate these. R11 must widen `uncertain`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
