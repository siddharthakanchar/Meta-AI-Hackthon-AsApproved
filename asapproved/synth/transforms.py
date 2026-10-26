"""Variant transforms, each of which emits its own ground truth.

Two families:

**Re-render transforms** change the Layout and redraw. A warning shoved into the
Reels caption zone, set in grey-on-grey, stripped of its border or reworded is
rendered that way — so it looks like creative a design tool could plausibly have
produced, not like a rectangle pasted over a JPEG. Pasting would leave
compression seams that a pixel diff could latch onto for the wrong reason, and
the benchmark would flatter us.

**Geometry transforms** crop, pad, zoom or recolour the rendered frames, which is
what Meta's enhancements actually do to a delivered asset.

Every transform declares the rules it breaks and the regions it touches, and that
declaration IS the label. Nothing here is hand-labelled: hand labels would encode
the same assumptions the detector makes, and the benchmark would end up measuring
the tool's agreement with itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from asapproved.synth.render import Layout
from asapproved.synth.specs import MasterSpec, prescribed_text

__all__ = ["Transform", "TRANSFORMS", "transforms_for", "VariantPlan"]


@dataclass(frozen=True)
class FrameCtx:
    """What a geometry transform needs to know about the frame it is editing.

    Added because a transform that claims to remove the warning has to know where
    the warning IS. Fixed fractions were wrong the moment the layout became
    placement-aware: a 1.4x zoom drops a Feed warning at 80% and leaves a Reels
    warning at 45% fully on screen, so the label said "removed" while the pixels
    said otherwise. The generator's cross-check caught it; this is the fix.
    """

    spec: MasterSpec
    regions: dict[str, tuple[int, int, int, int]]
    size: tuple[int, int]  # (w, h)

    @property
    def warning_top(self) -> int:
        box = self.regions.get("warning")
        return box[1] if box else self.size[1]


@dataclass(frozen=True)
class Transform:
    """One edit, plus what it means for the rules."""

    name: str
    benign: bool
    # The Meta Advantage+ enhancement this stands in for. Variants are labelled
    # with it so the lineage graph (D2) and blast radius have a feature to group
    # on, exactly as the Marketing API would report.
    enhancement: str
    description: str
    rules: tuple[str, ...] = ()  # violated rule IDs; empty for benign
    regions: tuple[str, ...] = ()  # regions touched
    # Re-render path: produce a modified Layout (and optionally new warning text)
    layout_fn: Callable[[MasterSpec, Layout], Layout] | None = None
    text_fn: Callable[[MasterSpec], str] | None = None
    # Geometry path: transform an already-rendered frame
    frame_fn: Callable[[np.ndarray, int, int, FrameCtx], np.ndarray] | None = None
    # Video-only: per-frame visibility of the named region
    visibility_fn: Callable[[MasterSpec], dict[str, list[list[int]]]] | None = None
    applies_to: str = "any"  # "any" | "credit" | "investment" | "video"
    requires_audio: bool = False
    # True when the geometry changes over time, so region visibility must be
    # recomputed on every frame rather than once. A fixed crop does not vary;
    # a pan does.
    per_frame: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# violating transforms
# ---------------------------------------------------------------------------


def _into_overlay_zone(spec: MasterSpec, layout: Layout) -> Layout:
    """Push the warning down into the platform's caption block (R12).

    Only meaningful where the placement actually reserves a zone. An earlier
    version faked a 25% zone for Feed so the transform would "work" everywhere —
    which would have manufactured a violation that does not exist and scored the
    detector for failing to find it. Feed is excluded by eligibility instead.
    """
    from asapproved.vision.overlays import get_spec

    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    zone = get_spec(placement)
    if zone.bottom <= 0:
        raise ValueError(
            f"{spec.id}: placement {spec.placement!r} reserves no UI zone, so R12 "
            "cannot be seeded here"
        )
    return Layout(
        safe_top=layout.safe_top,
        safe_bottom=layout.safe_bottom,
        warning_top=1.0 - zone.bottom * 0.75 - layout.warning_height,
        warning_height=layout.warning_height,
    )


def _crop_out_warning(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Reframe to the content above the warning — the 'cropped for placement' edit (R3)."""
    h = frame.shape[0]
    cut = ctx.warning_top * h // ctx.size[1]  # scale if the frame was already resized
    return frame[: max(8, cut - 2), :]


def _expand_pushes_warning_off(
    frame: np.ndarray, index: int, total: int, ctx: FrameCtx
) -> np.ndarray:
    """Outpaint-style expansion: canvas grows, lower content is pushed out (R3)."""
    h, w = frame.shape[:2]
    # Scale so the warning's top edge lands past the bottom of the kept window.
    warn_top = max(1, ctx.warning_top * h // ctx.size[1])
    scale = min(3.0, max(1.35, (h / warn_top) * 1.06))
    scaled = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
    return scaled[:h, :w]


def _zoom_centre(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Zoom on the headline until the warning leaves the frame (R3).

    The scale is derived from where the warning actually sits rather than fixed:
    a Feed warning at 80% of the frame goes at 1.4x, a Reels warning at 45% needs
    about 2.3x. A fixed factor silently mislabelled the Reels masters.
    """
    h, w = frame.shape[:2]
    warn_top = max(1, ctx.warning_top * h // ctx.size[1])
    scale = min(3.0, max(1.4, (h / warn_top) * 1.06))
    big = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
    x = (big.shape[1] - w) // 2
    return big[:h, x : x + w]


APR_HOLD_SECONDS = 1.0
APR_PAN_SECONDS = 0.25


def _apr_pan_frames(spec: MasterSpec) -> tuple[int, int]:
    fps = spec.fps or 25
    return max(1, int(fps * APR_HOLD_SECONDS)), max(1, int(fps * APR_PAN_SECONDS))


def _animate_apr_away(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Slide the representative APR out of frame, leaving everything else (R8).

    The hero case: frame zero previews perfectly compliant, and for the rest of
    the delivered clip the trigger ("0% for 12 months") is still on screen while
    the APR that qualifies it is gone.

    An earlier version panned the WHOLE frame upward, which took the trigger off
    screen too — so trigger and APR both measured 8% visibility, R8 correctly
    found no disparity, and the demo's central claim was not true of its own
    data. Only the APR band moves now.
    """
    hold, pan = _apr_pan_frames(ctx.spec)
    if index < hold:
        return frame

    box = ctx.regions.get(ctx.spec.apr_label)
    if box is None:
        return frame

    x, y, w, h = box
    h_img, w_img = frame.shape[:2]
    y0, y1 = max(0, y - 2), min(h_img, y + h + 2)
    if y1 <= y0:
        return frame

    progress = min(1.0, (index - hold + 1) / pan)
    shift = int(progress * (x + w + 8))
    if shift <= 0:
        return frame

    out = frame.copy()
    band = out[y0:y1]
    # Fill from the band's own right edge so the vacated area keeps the
    # background gradient rather than showing a black bar, which would be an
    # obvious artefact rather than a plausible animation.
    fill = band[:, -1:, :].repeat(band.shape[1], axis=1)
    moved = np.concatenate([band[:, shift:, :], fill[:, :shift, :]], axis=1)
    out[y0:y1] = moved[:, : band.shape[1], :]
    return out


def _warning_appears_late(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Hide the warning until the final seconds — the "end card" pattern (R4).

    FG24/1 Table 1 expects the warning on screen throughout a short-form video.
    A warning that only appears in the last few seconds is a common real design
    and a clean R4 breach, which the APR animation above does not provide
    because it never touches the warning.
    """
    reveal_at = int(total * 0.72)
    if index >= reveal_at:
        return frame

    box = ctx.regions.get("warning")
    if box is None:
        return frame

    x, y, w, h = box
    h_img, w_img = frame.shape[:2]
    y0, y1 = max(0, y - 2), min(h_img, y + h + 2)
    x0, x1 = max(0, x - 2), min(w_img, x + w + 2)
    if y1 <= y0 or x1 <= x0:
        return frame

    out = frame.copy()
    # Paint over with the background sampled just above the box, so it reads as
    # "the warning has not appeared yet" rather than "a rectangle was deleted".
    source_y = max(0, y0 - (y1 - y0))
    patch = out[source_y : source_y + (y1 - y0), x0:x1]
    if patch.shape[0] == (y1 - y0):
        out[y0:y1, x0:x1] = patch
    return out


def _warning_late_visibility(spec: MasterSpec) -> dict[str, list[list[int]]]:
    total = spec.total_frames
    return {"warning": [[int(total * 0.72), total - 1]]}


def _apr_visibility(spec: MasterSpec) -> dict[str, list[list[int]]]:
    hold, pan = _apr_pan_frames(spec)
    return {spec.apr_label: [[0, hold + pan - 1]], "warning": [[0, spec.total_frames - 1]]}


def _warning_visibility_none(spec: MasterSpec) -> dict[str, list[list[int]]]:
    return {"warning": []}


# A plausible machine rewrite per investment type: it keeps the gist, loses the
# prescribed wording. Written per type rather than by string replacement because
# a replace-based rewrite silently did NOTHING to the long-term-asset-fund text —
# none of its target phrases occur there — leaving a variant labelled as an R11
# violation while being byte-identical to a compliant master. The benchmark would
# have marked the detector wrong for correctly passing it.
_REWORDINGS: dict[str, str] = {
    "cryptoassets": (
        "Only invest what you can comfortably afford to lose. Crypto is a high-risk "
        "investment and you may not be covered if things go wrong."
    ),
    "non_readily_realisable_securities": (
        "Only invest what you can comfortably afford to lose. This is a high-risk "
        "investment and you may not be covered if things go wrong."
    ),
    "p2p_agreements": (
        "Only lend what you can comfortably afford to lose. This is a high-risk "
        "investment, your money may be tied up, and you may not be covered if things "
        "go wrong."
    ),
    "long_term_asset_fund": (
        "A high-risk, long-term investment. Your money may be tied up for years and "
        "returns are not guaranteed."
    ),
}


def _reword_warning(spec: MasterSpec) -> str:
    """A softer paraphrase that loses the prescribed wording (R11).

    Models what text_optimizations or translate_voiceover plausibly does — the
    failure mode that makes R11 necessary rather than pedantic.

    Raises if the rewrite leaves the text unchanged. A no-op rewrite produces a
    variant labelled as a violation that does not violate anything, which
    poisons the benchmark in the least visible way possible.
    """
    if not spec.investment_type:
        return "Representative APR applies. Credit subject to status."

    rewritten = _REWORDINGS.get(spec.investment_type)
    if rewritten is None:
        raise KeyError(
            f"no rewording defined for investment type {spec.investment_type!r}; "
            "R11 cannot be seeded without one"
        )

    from asapproved.text_norm import same_prescribed_text

    if same_prescribed_text(rewritten, prescribed_text(spec.investment_type)):
        raise AssertionError(
            f"{spec.id}: the R11 rewrite is identical to the prescribed wording, so the "
            "variant would be labelled a violation while being perfectly compliant"
        )
    return rewritten


# ---------------------------------------------------------------------------
# benign transforms
# ---------------------------------------------------------------------------


def _brightness(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    return cv2.convertScaleAbs(frame, alpha=1.06, beta=14)


def _touch_up(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Mild sharpen + saturation, i.e. image_touchups."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.int16)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.18, 0, 255)
    out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    blur = cv2.GaussianBlur(out, (0, 0), 1.2)
    return cv2.addWeighted(out, 1.35, blur, -0.35, 0)


def _background_hue(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Shift background hue while leaving the white warning box alone.

    The mask keeps near-white pixels untouched, so the warning's contrast and
    wording survive. This is the benign case that a naive pixel diff gets wrong
    and that the region intersection in R1 is supposed to get right — it is here
    to make the false-block rate on benign edits a real measurement.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.int16)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    protect = gray > 200
    hsv[..., 0] = (hsv[..., 0] + 16) % 180
    out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    out[protect] = frame[protect]
    return out


def _recompress(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Re-encode at lower quality — every delivered asset gets this."""
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else frame


def _safe_crop(frame: np.ndarray, index: int, total: int, ctx: FrameCtx) -> np.ndarray:
    """Trim a sliver of empty margin — geometry changes, no claim is touched."""
    h, w = frame.shape[:2]
    return frame[: int(h * 0.97), int(w * 0.02) : int(w * 0.98)]


TRANSFORMS: list[Transform] = [
    # ---- violations -------------------------------------------------
    Transform(
        name="crop_removes_warning",
        benign=False,
        enhancement="adapt_to_placement",
        description="Reframed for a shorter placement; the warning box is cropped away.",
        rules=("R1", "R3"),
        regions=("warning",),
        frame_fn=_crop_out_warning,
        visibility_fn=_warning_visibility_none,
    ),
    Transform(
        name="expand_pushes_warning_offframe",
        benign=False,
        enhancement="image_background_gen",
        description="Canvas expanded; content pushed until the warning leaves the frame.",
        rules=("R1", "R3"),
        regions=("warning",),
        frame_fn=_expand_pushes_warning_off,
        visibility_fn=_warning_visibility_none,
    ),
    Transform(
        name="zoom_drops_warning",
        benign=False,
        enhancement="image_animation",
        description="Zoomed on the headline; the warning falls outside the frame.",
        rules=("R1", "R3"),
        regions=("warning",),
        frame_fn=_zoom_centre,
        visibility_fn=_warning_visibility_none,
    ),
    Transform(
        name="warning_border_removed",
        benign=False,
        enhancement="text_optimizations",
        description="Warning redrawn without its own border.",
        rules=("R5",),
        regions=("warning",),
        layout_fn=lambda s, lay: Layout(
            safe_top=lay.safe_top,
            safe_bottom=lay.safe_bottom,
            warning_border=False,
            warning_underline=False,
            warning_fill=False,
        ),
        notes=(
            "Drops the outline, the underline AND the panel. Removing only the "
            "outline leaves a white box whose edge reads as a container, which "
            "makes the variant ambiguous against COBS 4.12A.36R."
        ),
    ),
    Transform(
        name="warning_low_contrast",
        benign=False,
        enhancement="image_background_gen",
        description="Background generation leaves the warning grey-on-grey.",
        rules=("R6",),
        regions=("warning",),
        layout_fn=lambda s, lay: Layout(
            safe_top=lay.safe_top,
            safe_bottom=lay.safe_bottom,
            warning_bg=(126, 126, 126),
            warning_ink=(150, 150, 150),
        ),
    ),
    Transform(
        name="warning_shrunk",
        benign=False,
        enhancement="text_optimizations",
        description="Warning text reflowed smaller than the body copy.",
        rules=("R7",),
        regions=("warning",),
        layout_fn=lambda s, lay: Layout(
            safe_top=lay.safe_top, safe_bottom=lay.safe_bottom, warning_scale=0.5
        ),
        applies_to="body",
    ),
    Transform(
        name="warning_into_overlay_zone",
        benign=False,
        enhancement="adapt_to_placement",
        description="Warning repositioned under the platform's caption and CTA block.",
        rules=("R12",),
        regions=("warning",),
        layout_fn=_into_overlay_zone,
        applies_to="overlay_placement",
        notes="FG24/1 para 1.5 — obscured by a design feature of the platform.",
    ),
    Transform(
        name="warning_reworded",
        benign=False,
        enhancement="text_translation",
        description="Prescribed wording rewritten into a softer paraphrase.",
        rules=("R11",),
        regions=("warning",),
        text_fn=_reword_warning,
        applies_to="investment",
    ),
    Transform(
        name="apr_shrunk_below_trigger",
        benign=False,
        enhancement="text_optimizations",
        description="Representative APR set much smaller than the trigger it qualifies.",
        rules=("R8",),
        regions=("apr", "trigger"),
        layout_fn=lambda s, lay: Layout(
            safe_top=lay.safe_top, safe_bottom=lay.safe_bottom, apr_scale=0.42
        ),
        applies_to="credit",
    ),
    Transform(
        name="representative_example_removed",
        benign=False,
        enhancement="text_optimizations",
        description="Cost-of-credit figures remain; the representative example is dropped.",
        rules=("R10", "R3"),
        regions=("warning",),
        layout_fn=lambda s, lay: Layout(
            safe_top=lay.safe_top, safe_bottom=lay.safe_bottom, show_warning=False
        ),
        applies_to="credit",
        visibility_fn=_warning_visibility_none,
    ),
    Transform(
        name="apr_animates_offscreen",
        benign=False,
        enhancement="image_animation",
        description="APR holds for about a second, then slides out of frame for the rest.",
        rules=("R8",),
        regions=("apr",),
        frame_fn=_animate_apr_away,
        visibility_fn=_apr_visibility,
        applies_to="credit+video",
        per_frame=True,
        notes="The hero case: frame zero previews clean, delivery does not.",
    ),
    Transform(
        name="warning_appears_late",
        benign=False,
        enhancement="video_highlights",
        description="Warning is held back until the closing seconds of the clip.",
        rules=("R4",),
        regions=("warning",),
        frame_fn=_warning_appears_late,
        visibility_fn=_warning_late_visibility,
        applies_to="video",
        per_frame=True,
        notes="FG24/1 Table 1 expects the warning on screen throughout short-form video.",
    ),
    Transform(
        name="voiceover_drops_apr",
        benign=False,
        enhancement="translate_voiceover",
        description="Voiceover states the trigger but no longer states the APR.",
        rules=("R9",),
        regions=(),
        applies_to="credit+video",
        requires_audio=True,
        notes="Audio-only: visually identical to the master by design.",
    ),
    # ---- benign ------------------------------------------------------
    Transform(
        name="brightness_lift",
        benign=True,
        enhancement="image_touchups",
        description="Global brightness and contrast lift.",
        frame_fn=_brightness,
    ),
    Transform(
        name="image_touchup",
        benign=True,
        enhancement="image_touchups",
        description="Saturation and sharpening pass.",
        frame_fn=_touch_up,
    ),
    Transform(
        name="background_hue_shift",
        benign=True,
        enhancement="image_background_gen",
        description="Background recoloured; claim and warning regions untouched.",
        frame_fn=_background_hue,
    ),
    Transform(
        name="recompressed",
        benign=True,
        enhancement="adapt_to_placement",
        description="Re-encoded at lower quality for delivery.",
        frame_fn=_recompress,
    ),
    Transform(
        name="margin_trim",
        benign=True,
        enhancement="adapt_to_placement",
        description="A sliver of empty margin trimmed; no claim region affected.",
        frame_fn=_safe_crop,
    ),
    Transform(
        name="music_swap",
        benign=True,
        enhancement="music_generation",
        description="Backing track replaced; spoken content unchanged.",
        applies_to="video",
        requires_audio=True,
    ),
]


def _has_body_copy(spec: MasterSpec) -> bool:
    """Does this master actually render body copy?

    On a tight placement band (Reels reserves 54% of the frame) the layout drops
    body copy rather than shrinking it. R7 compares the warning against body
    copy, so on such a master R7 is genuinely unassessable — and seeding a
    warning_shrunk variant there produces a labelled violation the rules
    correctly report as `inconclusive`, which scores as a miss against a
    detector that did nothing wrong.
    """
    from asapproved.synth.build import render_master_frame

    return "body" in render_master_frame(spec).regions


_PREDICATES = {
    "credit": lambda s: s.is_credit,
    "investment": lambda s: not s.is_credit,
    "video": lambda s: s.kind == "video",
    "body": _has_body_copy,
    "overlay_placement": lambda s: _reserves_ui_space(s),
}


def _reserves_ui_space(spec: MasterSpec) -> bool:
    from asapproved.vision.overlays import get_spec

    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    return get_spec(placement).bottom > 0


def _eligible(t: Transform, spec: MasterSpec) -> bool:
    """A transform may only be seeded where its own rule can actually be assessed.

    `applies_to` was a single axis, which could not express "a credit promotion
    that is also a video" — so the APR animation was allocated to an investment
    master, where R8 is not applicable by definition, and the benchmark recorded
    a miss for a verdict that was exactly right.
    """
    if t.applies_to == "any":
        return True
    for requirement in t.applies_to.split("+"):
        predicate = _PREDICATES.get(requirement.strip())
        if predicate is None or not predicate(spec):
            return False
    return True


@dataclass(frozen=True)
class VariantPlan:
    master: MasterSpec
    transform: Transform
    index: int

    @property
    def variant_id(self) -> str:
        return f"{self.master.id}__v{self.index}_{self.transform.name}"


def _allocate(
    pool: list[Transform], masters: list[MasterSpec], slots: int
) -> dict[str, list[Transform]]:
    """Assign transforms to masters so every transform is used at least once.

    Rotating by master index looked reasonable and silently dropped R11 and R4:
    the reworded warning only applies to investment masters and the APR
    animation only to videos, so modulo arithmetic over each master's own
    eligibility list never reached them. The benchmark would have published
    empty rows for two rules and an F1 averaged over the rest.

    So: most-constrained-first. A transform that fits few masters claims its slot
    before one that fits anywhere; the remainder is filled by rotation. Fully
    deterministic — no RNG, identical assignment on every run.
    """
    assigned: dict[str, list[Transform]] = {m.id: [] for m in masters}
    capacity = {m.id: slots for m in masters}
    eligible = {t.name: [m for m in masters if _eligible(t, m)] for t in pool}

    for transform in sorted(pool, key=lambda t: (len(eligible[t.name]), t.name)):
        candidates = [m for m in eligible[transform.name] if capacity[m.id] > 0]
        if not candidates:
            continue
        # Prefer the emptiest master so later transforms still have somewhere to go.
        host = max(candidates, key=lambda m: (capacity[m.id], m.id))
        assigned[host.id].append(transform)
        capacity[host.id] -= 1

    # Fill the remaining slots by whichever RULE is currently least covered, not
    # by rotation. Rotation left R1 on 10 variants and R4, R9, R10, R11 and R12
    # on one each — and a per-rule precision/recall computed over a single
    # variant can only read 0% or 100%, which is not a measurement. Transforms
    # carrying several rules (the geometry ones are all R1+R3) stop being picked
    # once those rules are well covered.
    rule_count: dict[str, int] = {}
    for transforms in assigned.values():
        for t in transforms:
            for r in t.rules:
                rule_count[r] = rule_count.get(r, 0) + 1

    def scarcity(t: Transform) -> tuple[int, int, str]:
        counts = [rule_count.get(r, 0) for r in t.rules] or [99]
        return (min(counts), sum(counts), t.name)

    for master in masters:
        while capacity[master.id] > 0:
            options = [
                t for t in pool if _eligible(t, master) and t not in assigned[master.id]
            ]
            if not options:
                break
            pick = min(options, key=scarcity)
            assigned[master.id].append(pick)
            capacity[master.id] -= 1
            for r in pick.rules:
                rule_count[r] = rule_count.get(r, 0) + 1
    return assigned


@lru_cache(maxsize=1)
def _assignment() -> tuple[dict[str, list[Transform]], dict[str, list[Transform]]]:
    from asapproved.synth.specs import MASTERS

    bad = [t for t in TRANSFORMS if not t.benign]
    good = [t for t in TRANSFORMS if t.benign]
    return _allocate(bad, MASTERS, 2), _allocate(good, MASTERS, 2)


def transforms_for(spec: MasterSpec) -> list[Transform]:
    """This master's four variants: two seeded violations, then two benign edits."""
    violations, benign = _assignment()
    return violations[spec.id] + benign[spec.id]
