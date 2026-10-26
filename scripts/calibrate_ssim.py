"""Calibrate the diff's change-detection floor against real benign variants.

R1 asks whether a claim region was materially changed. Its 2% threshold is a
statement about CONTENT. Our SSIM map, though, also flags JPEG and H.264
artefacts, so a benign re-encode was measuring 11.5% changed area and tripping
a rule it has no business tripping.

The fix belongs in the detector, not the rule: tightening R1's threshold to
hide the noise would quietly redefine "materially changed". So this measures,
at several SSIM floors, how much of the warning region reads as changed on
BENIGN variants versus seeded ones, and reports where the two populations
separate.

    python scripts/calibrate_ssim.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.pipeline import load_master, sample_frames  # noqa: E402
from asapproved.vision.align import align_to_master  # noqa: E402
from asapproved.vision.diff import changed_in_region, diff_pair  # noqa: E402

FLOORS = [0.90, 0.85, 0.80, 0.75, 0.70, 0.60]


def main() -> int:
    labels = json.loads(
        (settings.labels_dir / "variantbench_uk.json").read_text(encoding="utf-8")
    )
    results: dict[float, dict[str, list[int]]] = {f: {"benign": [], "seeded": []} for f in FLOORS}

    for lab in labels["labels"]:
        vp = settings.variants_dir / lab["file"]
        if not vp.exists() or lab.get("requires_audio"):
            continue
        master = load_master(lab["master_id"], settings.masters_dir)
        if "warning" not in master.regions:
            continue

        mframes, _, _ = sample_frames(master.path)
        vframes, _, _ = sample_frames(vp)
        alignment = align_to_master(mframes[0], vframes[0])

        x, y, w, h = master.regions["warning"]
        mask = np.zeros(mframes[0].shape[:2], dtype=bool)
        mask[max(0, y) : y + h, max(0, x) : x + w] = True

        for floor in FLOORS:
            diff = diff_pair(mframes[0], vframes[0], alignment, ssim_threshold=floor)
            bp = changed_in_region(diff, mask, "warning").fraction_bp
            results[floor]["benign" if lab["benign"] else "seeded"].append(bp)

    print(f"{'floor':>6}  {'benign max':>11}  {'benign p90':>11}  {'seeded median':>14}  separation")
    best = None
    for floor in FLOORS:
        b = sorted(results[floor]["benign"])
        s = sorted(results[floor]["seeded"])
        if not b or not s:
            continue
        b_max = b[-1]
        b_p90 = b[int(len(b) * 0.9) - 1]
        s_med = s[len(s) // 2]
        sep = s_med - b_max
        flag = ""
        if b_max < 200 <= s_med:
            flag = "  <- benign below the 2% rule threshold"
            if best is None:
                best = floor
        print(f"{floor:>6.2f}  {b_max:>11}  {b_p90:>11}  {s_med:>14}  {sep:>+8}{flag}")

    if best is None:
        print(
            "\nNo floor puts every benign variant under the 2% rule threshold. "
            "Report the false-block rate honestly rather than tuning it away."
        )
    else:
        print(f"\nSuggested SSIM_CHANGED_BELOW = {best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
