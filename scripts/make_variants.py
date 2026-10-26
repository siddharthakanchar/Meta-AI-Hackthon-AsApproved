"""Phase 3 — build 48 SIMULATED variants with automatic ground truth.

Deterministic, seeded transforms (OpenCV / Pillow / ffmpeg). Each transform
records the rules it violates, the region boxes it touched and the frame ranges
where the warning is visible, so labels are generated, not hand-written.

24 seeded violations, spread across R1-R12:
  crop-out; expand pushing the warning past the frame; zoom/animation sliding the
  APR off-screen; background swap killing contrast; warning text rewrite;
  translation; VO line removed; warning moved into the Reels overlay zone.

24 benign edits:
  brightness; touch-ups; background change away from claim regions; music swap.

Labels are frozen before the first scored run; the label-file hash goes in
DECISIONS.md. Siddhartha spot-checks 10 random labels (USER INPUT 6.2).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("Phase 3")


if __name__ == "__main__":
    main()
