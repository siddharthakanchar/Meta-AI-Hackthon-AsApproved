"""Render the architecture diagram to PNG for the submission.

Drawn with Pillow rather than Mermaid-to-image so it needs no node toolchain and
no network — the same constraint the rest of the project works under.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.synth.brands import load_font  # noqa: E402

W, H = 1800, 960
BG = (14, 17, 23)
INK = (232, 234, 237)
MUTED = (150, 155, 165)
META = (24, 119, 242)
GUARD = (229, 72, 77)
DET = (48, 164, 108)
PANEL = (26, 29, 38)


def box(d, xy, label, sub="", fill=PANEL, edge=None, title_size=22, sub_size=15):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=fill, outline=edge or fill, width=3)
    f = load_font(title_size, bold=True)
    d.text((x0 + 16, y0 + 12), label, font=f, fill=INK)
    if sub:
        fs = load_font(sub_size)
        for i, line in enumerate(sub.split("\n")):
            d.text((x0 + 16, y0 + 16 + title_size + 6 + i * (sub_size + 5)), line, font=fs, fill=MUTED)


def arrow(d, start, end, colour=MUTED, width=3):
    d.line([start, end], fill=colour, width=width)
    import math

    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    for s in (-0.5, 0.5):
        d.line(
            [end, (end[0] - 14 * math.cos(ang + s), end[1] - 14 * math.sin(ang + s))],
            fill=colour,
            width=width,
        )


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((50, 36), "AsApproved", font=load_font(40, bold=True), fill=INK)
    d.text(
        (50, 86),
        "Does the approved ad survive Meta's AI edits?  ·  rules decide, the model explains",
        font=load_font(19),
        fill=MUTED,
    )

    y = 160
    box(d, (50, y, 430, y + 120), "1 · APPROVE",
        "SHA-256 + approver + timestamp\n+ rulebook version + settings\nsigned Ed25519", edge=DET)
    box(d, (470, y, 850, y + 120), "2 · SENSE",
        "Marketing API: enhancement\nsettings + ad previews\n→ settings drift (R2)", edge=META)
    box(d, (890, y, 1270, y + 120), "Meta models",
        "SAM 3.1 · masks + video tracks\nMuse Spark 1.3 · claims, JSON\nVoice Transcribe · spoken APR",
        edge=META)
    box(d, (1310, y, 1750, y + 120), "No key? labelled fallbacks",
        "template+NCC · OCR · template note\nR9 reports NOT EVALUATED,\nnever a pass", edge=GUARD)

    y2 = 340
    box(d, (50, y2, 850, y2 + 150), "3 · MEASURE — deterministic, no model decides",
        "align (ORB + RANSAC)  →  diff (SSIM)  →  locate region  →  measure\n"
        "seconds on screen · size vs body copy · WCAG contrast · border\n"
        "clipping · occlusion by the platform's own caption and CTA chrome",
        edge=DET)
    box(d, (890, y2, 1750, y2 + 150), "geometry trust gate",
        "alignment unreliable → R1/R3 return INCONCLUSIVE\n"
        "region located by: template → its own text → alignment\n"
        "appearance measured on a frame where the region exists",
        edge=GUARD)

    y3 = 540
    box(d, (50, y3, 850, y3 + 140), "4 · DECIDE — rulebook uk_v1 (YAML, 12 rules + 1 benchmark)",
        "R1 changed claim · R2 drift · R3 removed · R4 throughout · R5 bordered/bold\n"
        "R6 contrast · R7 vs body · R8 APR parity · R9 spoken · R10 example\n"
        "R11 prescribed wording · R12 platform overlay      B1 Clearcast (TV only)",
        edge=DET)
    box(d, (890, y3, 1750, y3 + 140), "every input may be UNKNOWN",
        "unmeasured → inconclusive. Never pass (waves through a breach),\n"
        "never fail (accuses on a guess). An empty context produces\n"
        "zero failures — asserted by test, per rule.",
        edge=GUARD)

    y4 = 720
    box(d, (50, y4, 600, y4 + 130), "5 · EXPLAIN",
        "Muse Spark writes the note\n→ validator rejects any number, rule ID,\n"
        "quote or citation not in evidence\n→ retry once → deterministic template",
        edge=GUARD)
    box(d, (640, y4, 1190, y4 + 130), "6 · ACT, THEN PROVE",
        "blast radius = asset ∩ feature ∩ OPT_IN\n\"Fix once, opt out N\"\n"
        "dry run by default; closes only when settings\nread back AND the preview re-checks",
        edge=META)
    box(d, (1230, y4, 1750, y4 + 130), "7 · REMEMBER",
        "hash-chained evidence log — the digest covers\nindex and prev, so edits, reordering\n"
        "and deletion all break it\nprecedent memory per feature × rule",
        edge=DET)

    for a, b in (
        ((430, y + 60), (470, y + 60)),
        ((850, y + 60), (890, y + 60)),
        ((1270, y + 60), (1310, y + 60)),
        ((440, y + 120), (440, y2)),
        ((440, y2 + 150), (440, y3)),
        ((440, y3 + 140), (440, y4)),
        ((600, y4 + 65), (640, y4 + 65)),
        ((1190, y4 + 65), (1230, y4 + 65)),
    ):
        arrow(d, a, b)

    legend_y = H - 60
    for i, (colour, text) in enumerate(
        ((META, "Meta AI"), (DET, "deterministic"), (GUARD, "guard — can only make it say less"))
    ):
        x = 50 + i * 300
        d.rounded_rectangle([x, legend_y, x + 22, legend_y + 22], radius=4, fill=colour)
        d.text((x + 32, legend_y + 1), text, font=load_font(16), fill=MUTED)

    d.text(
        (W - 640, legend_y + 1),
        "All creative SIMULATED · findings flag for review, not legal advice",
        font=load_font(15),
        fill=MUTED,
    )

    out = REPO_ROOT / "submission" / "architecture.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
