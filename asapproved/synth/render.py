"""Draw a master frame, and report exactly where everything landed.

The regions this returns are ground truth. They are what SAM 3.1's masks get
scored against (region IoU, §10), and what the variant transforms use to decide
which rules a given edit breaks. So the renderer does not just draw — it records
the box of every element it draws, in pixels, in frame coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from asapproved.synth.brands import Brand, load_font

__all__ = ["Region", "RenderedFrame", "draw_frame", "Layout"]

Box = tuple[int, int, int, int]  # x, y, w, h


@dataclass(frozen=True)
class Region:
    label: str
    box: Box

    def as_list(self) -> list[int]:
        return [int(v) for v in self.box]


@dataclass
class RenderedFrame:
    image: Image.Image
    regions: dict[str, Box] = field(default_factory=dict)

    def to_bgr(self) -> np.ndarray:
        import cv2

        return cv2.cvtColor(np.array(self.image.convert("RGB")), cv2.COLOR_RGB2BGR)

    def region_list(self) -> list[dict]:
        return [{"label": k, "box": [int(v) for v in b]} for k, b in sorted(self.regions.items())]


@dataclass(frozen=True)
class Layout:
    """Where the warning sits and how big things are, as fractions of the frame.

    Exposed so variants can re-render with a nudged layout rather than pasting
    pixels — a warning moved into the Reels zone should be *rendered* there, so
    it looks like creative rather than like a cut-and-paste artefact.

    Content flows inside [safe_top, safe_bottom], which the placement dictates.
    The warning is bottom-aligned to that band rather than pinned to a fixed
    fraction: on Reels the usable band ends at 60% of the frame, and a fixed
    position either sat under the caption block or collided with the APR line
    above it. `warning_top` overrides the flow — that is how the R12 variant
    deliberately pushes the warning into the reserved zone.
    """

    safe_top: float = 0.0
    safe_bottom: float = 1.0
    warning_top: float | None = None  # None = bottom-align within the safe band
    warning_height: float = 0.165
    warning_scale: float = 1.0  # multiplier on warning text size (R7 lever)
    warning_border: bool = True  # R5 lever
    # Removing only the drawn outline leaves the white panel, whose edge
    # against a dark ad is indistinguishable from a border — and arguably IS
    # a container for the purposes of COBS 4.12A.36R. A variant meant to
    # breach that rule has to drop the panel too, or it is ambiguous.
    warning_fill: bool = True
    warning_underline: bool = True  # R5 lever
    warning_bg: tuple[int, int, int] | None = None  # None = white (R6 lever)
    warning_ink: tuple[int, int, int] | None = None  # None = near-black
    apr_scale: float = 1.0  # R8 lever
    apr_dy: float = 0.0  # vertical offset as fraction of H (R8/R4 lever)
    show_apr: bool = True
    show_warning: bool = True


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_size(
    draw: ImageDraw.ImageDraw,
    texts: list[str],
    max_width: int,
    start: int,
    *,
    bold: bool = False,
    floor: int = 10,
) -> int:
    """Largest size at which EVERY text fits on one line within max_width.

    Fitting the set rather than each string separately is what preserves
    prominence parity: if the trigger and the APR were sized independently, the
    longer one would shrink and the pair would no longer be equally prominent —
    which is the breach CONC 3.5.7R describes.
    """
    size = start
    while size > floor:
        font = load_font(size, bold=bold)
        if all(draw.textlength(t, font=font) <= max_width for t in texts):
            return size
        size -= 1
    return floor


def _background(brand: Brand, w: int, h: int, phase: float = 0.0) -> Image.Image:
    """Abstract brand background. No photography, no people.

    A vertical gradient plus a few large soft shapes: enough structure for ORB to
    find corners (otherwise the alignment tests in C3 would be measuring nothing)
    without competing with the type.
    """
    top = np.array(brand.bg, dtype=np.float64)
    bottom = np.array(brand.bg_accent, dtype=np.float64)
    ramp = np.linspace(0.0, 1.0, h)[:, None]
    grad = (top[None, None, :] * (1 - ramp[:, :, None]) + bottom[None, None, :] * ramp[:, :, None])
    img = Image.fromarray(np.repeat(grad.astype(np.uint8), w, axis=1), mode="RGB")

    draw = ImageDraw.Draw(img, "RGBA")
    accent = (*brand.accent, 38)
    # Deterministic shapes; `phase` lets video frames drift them slowly.
    for i in range(5):
        cx = int(w * (0.15 + 0.17 * i) + 0.04 * w * np.sin(phase + i))
        cy = int(h * (0.12 + 0.11 * i) + 0.03 * h * np.cos(phase * 0.7 + i))
        r = int(min(w, h) * (0.10 + 0.03 * ((i * 7) % 4)))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
    return img


def _draw_logo(draw: ImageDraw.ImageDraw, brand: Brand, x: int, y: int, size: int) -> Box:
    """A mark built from plain geometry plus the wordmark. Original by construction."""
    font = load_font(int(size * 0.62), bold=True)
    if brand.sector == "credit":
        draw.rounded_rectangle([x, y, x + size, y + size], radius=size // 5, fill=brand.accent)
        draw.rectangle(
            [x + size // 5, y + size // 2 - size // 12, x + size - size // 5, y + size // 2 + size // 12],
            fill=brand.bg,
        )
    else:
        draw.ellipse([x, y, x + size, y + size], fill=brand.accent)
        draw.polygon(
            [(x + size // 2, y + size // 5), (x + size * 4 // 5, y + size * 3 // 4), (x + size // 5, y + size * 3 // 4)],
            fill=brand.bg,
        )
    tx = x + size + int(size * 0.35)
    ty = y + (size - font.size) // 2 - int(size * 0.06)
    draw.text((tx, ty), brand.name, font=font, fill=brand.ink)
    width = int(tx + draw.textlength(brand.name, font=font) - x)
    return (x, y, width, size)


def draw_frame(
    *,
    brand: Brand,
    width: int,
    height: int,
    headline: str,
    trigger: str,
    apr_line: str,
    warning_text: str,
    body_text: str | None = None,
    apr_label: str = "apr",
    layout: Layout | None = None,
    phase: float = 0.0,
) -> RenderedFrame:
    """Render one frame and return it with the box of every element.

    `apr_label` exists because an investment promotion has no representative APR.
    Labelling its risk line "apr" would assert a region that does not exist, and
    R8 (APR vs trigger prominence) would then be scored against a master it does
    not apply to. Credit masters emit "apr"; investment masters emit "risk_note".
    """
    layout = layout or Layout()
    img = _background(brand, width, height, phase)
    draw = ImageDraw.Draw(img)
    regions: dict[str, Box] = {}

    margin = int(width * 0.07)
    content_w = width - 2 * margin

    band_top = int(height * layout.safe_top)
    band_bottom = int(height * layout.safe_bottom)
    band_h = band_bottom - band_top

    body = body_text or f"{brand.tagline}. 18+, UK residents only."
    small_text = f"{brand.frn} · SIMULATED creative for AsApproved — not a real offer"

    plan = _plan(
        draw,
        layout=layout,
        width=width,
        height=height,
        band_h=band_h,
        content_w=content_w,
        headline=headline,
        trigger=trigger,
        apr_line=apr_line,
        warning_text=warning_text,
        body=body,
        small_text=small_text,
    )
    gap = plan["gap"]
    cursor = band_top + gap

    # --- logo ---------------------------------------------------------
    regions["logo"] = _draw_logo(draw, brand, margin, cursor, plan["logo_size"])
    cursor += plan["logo_size"] + gap

    # --- headline -----------------------------------------------------
    head_font = load_font(plan["head_size"], bold=True)
    line_h = int(plan["head_size"] * 1.22)
    for i, line in enumerate(plan["head_lines"]):
        draw.text((margin, cursor + i * line_h), line, font=head_font, fill=brand.ink)
    regions["headline"] = (margin, cursor, content_w, len(plan["head_lines"]) * line_h)
    cursor += len(plan["head_lines"]) * line_h + gap

    # --- trigger ------------------------------------------------------
    # CONC 3.5.7R: the representative APR must be no less prominent than the
    # trigger. In a compliant master that means same size, same weight, adjacent
    # — so trigger and APR share a font deliberately, not incidentally, and are
    # fitted together so the longer of the two cannot shrink on its own.
    trig_font = load_font(plan["trig_size"], bold=True)
    draw.text((margin, cursor), trigger, font=trig_font, fill=brand.accent)
    regions["trigger"] = (
        margin,
        cursor,
        int(draw.textlength(trigger, font=trig_font)),
        int(plan["trig_size"] * 1.2),
    )
    cursor += int(plan["trig_size"] * 1.32)

    # --- representative APR -------------------------------------------
    if layout.show_apr:
        apr_size = max(8, int(plan["trig_size"] * layout.apr_scale))
        apr_font = load_font(apr_size, bold=True)
        apr_y = int(cursor + layout.apr_dy * height)
        draw.text((margin, apr_y), apr_line, font=apr_font, fill=brand.ink)
        regions[apr_label] = (
            margin,
            apr_y,
            int(draw.textlength(apr_line, font=apr_font)),
            int(apr_size * 1.2),
        )
        cursor = apr_y + int(apr_size * 1.32)

    # --- body copy (the comparator for R7) ----------------------------
    # Dropped entirely when the band is too tight rather than squashed: R7
    # compares warning text height against median BODY height, so shrinking the
    # body would quietly move the baseline R7 is measured against.
    if plan["body_lines"]:
        body_font = load_font(plan["body_size"])
        bline = int(plan["body_size"] * 1.3)
        for i, line in enumerate(plan["body_lines"]):
            draw.text((margin, cursor + i * bline), line, font=body_font, fill=brand.ink)
        regions["body"] = (margin, cursor, content_w, len(plan["body_lines"]) * bline)
        cursor += len(plan["body_lines"]) * bline + gap

    # --- warning, then small print -------------------------------------
    warning_h = plan["warning_h"]
    if layout.warning_top is not None:
        warning_y = int(height * layout.warning_top)  # variants push it into the UI zone
    else:
        warning_y = band_bottom - plan["small_h"] - gap - warning_h
        warning_y = max(warning_y, cursor)

    if layout.show_warning:
        regions["warning"] = _draw_warning(
            draw,
            brand,
            plan["warning_lines"],
            plan["warning_size"],
            margin,
            content_w,
            warning_y,
            warning_h,
            layout,
        )
        small_y = warning_y + warning_h + gap
    else:
        small_y = band_bottom - plan["small_h"] - gap

    small_y = min(small_y, height - plan["small_h"] - int(height * 0.008))
    small_font = load_font(plan["small_size"])
    sline = int(plan["small_size"] * 1.25)
    for i, line in enumerate(plan["small_lines"]):
        draw.text((margin, small_y + i * sline), line, font=small_font, fill=brand.ink)
    regions["small_print"] = (margin, small_y, content_w, plan["small_h"])

    return RenderedFrame(image=img, regions=regions)


def _plan(
    draw: ImageDraw.ImageDraw,
    *,
    layout: Layout,
    width: int,
    height: int,
    band_h: int,
    content_w: int,
    headline: str,
    trigger: str,
    apr_line: str,
    warning_text: str,
    body: str,
    small_text: str,
) -> dict:
    """Measure everything, then shrink until it fits the usable band.

    Written because bottom-aligning the warning inside a narrow Reels band put
    the box straight on top of the APR line. Overlapping elements are not a
    cosmetic problem here: the region boxes are ground truth, and two regions
    claiming the same pixels would corrupt both R8's prominence comparison and
    SAM's IoU score.

    So nothing is drawn until the whole stack is known to fit. If it cannot fit
    even at the smallest scale, the body copy is dropped — never the warning.
    """
    for step in range(0, 11):
        scale = 1.0 - step * 0.06
        drop_body = step >= 7

        gap = max(4, int(band_h * 0.030 * scale))
        logo_size = max(12, int(min(height * 0.045, band_h * 0.075) * scale))

        head_size = max(12, int(min(height * 0.040, band_h * 0.068) * scale))
        head_lines = _wrap(draw, headline, load_font(head_size, bold=True), content_w)
        head_h = len(head_lines) * int(head_size * 1.22)

        trig_size = _fit_size(
            draw,
            [trigger, apr_line],
            content_w,
            max(12, int(min(height * 0.052, band_h * 0.088) * scale)),
            bold=True,
            floor=max(10, int(height * 0.018)),
        )
        trig_h = int(trig_size * 1.32)
        apr_h = int(max(8, trig_size * layout.apr_scale) * 1.32) if layout.show_apr else 0

        body_size = max(10, int(min(height * 0.022, band_h * 0.037) * scale))
        body_lines = [] if drop_body else _wrap(draw, body, load_font(body_size), content_w)
        body_h = (len(body_lines) * int(body_size * 1.3) + gap) if body_lines else 0

        # The warning must not be set smaller than the ad's own body copy
        # (COBS 4.12A prominence, our R7). It was: 0.0205 of frame height against
        # the body's 0.022, so every "compliant" master carried a standing R7
        # breach and the pipeline rightly flagged it on first run. The warning now
        # leads the body, and `warning_scale` is the lever a variant uses to break
        # that deliberately.
        warning_size = max(8, int(height * 0.030 * layout.warning_scale * scale))
        pad = int(content_w * 0.035)
        warning_lines = _wrap(
            draw, warning_text, load_font(warning_size, bold=True), content_w - 2 * pad
        )
        warning_h = (
            2 * pad + len(warning_lines) * int(warning_size * 1.34) if layout.show_warning else 0
        )

        small_size = max(9, int(min(height * 0.0155, band_h * 0.026) * scale))
        small_lines = _wrap(draw, small_text, load_font(small_size), content_w)
        small_h = len(small_lines) * int(small_size * 1.25)

        total = (
            gap
            + logo_size
            + gap
            + head_h
            + gap
            + trig_h
            + apr_h
            + body_h
            + (gap + warning_h if layout.show_warning else 0)
            + gap
            + small_h
            + gap
        )
        if total <= band_h or step == 10:
            return {
                "gap": gap,
                "logo_size": logo_size,
                "head_size": head_size,
                "head_lines": head_lines,
                "trig_size": trig_size,
                "body_size": body_size,
                "body_lines": body_lines,
                "warning_size": warning_size,
                "warning_lines": warning_lines,
                "warning_h": warning_h,
                "small_size": small_size,
                "small_lines": small_lines,
                "small_h": small_h,
            }
    raise AssertionError("unreachable")


def _draw_warning(
    draw: ImageDraw.ImageDraw,
    brand: Brand,
    lines: list[str],
    size: int,
    margin: int,
    content_w: int,
    box_y: int,
    box_h: int,
    layout: Layout,
) -> Box:
    """The prescribed warning, in its own bordered box, bold and underlined.

    COBS 4.12A.36R wants prominent, clearly legible, own border, bold AND
    underlined. All three are drawn here and each is a lever the variant
    transforms can switch off individually, so R5's three sub-checks get
    independent ground truth rather than one combined "bad box" case.
    """
    box_x = margin
    box_w = content_w
    bg = layout.warning_bg or (255, 255, 255)
    ink = layout.warning_ink or (10, 10, 10)

    if layout.warning_fill:
        draw.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], fill=bg)
    else:
        # No panel: the warning sits directly on the creative. Use the brand's
        # own ink so the text stays legible — otherwise this would breach R6 as
        # well and the two rules could not be told apart in the benchmark.
        ink = brand.ink
    if layout.warning_border:
        draw.rectangle(
            [box_x, box_y, box_x + box_w, box_y + box_h],
            outline=ink,
            width=max(2, size // 7),
        )

    font = load_font(size, bold=True)
    pad = int(box_w * 0.035)
    line_h = int(size * 1.34)
    ty = box_y + pad
    for line in lines:
        draw.text((box_x + pad, ty), line, font=font, fill=ink)
        if layout.warning_underline:
            line_w = draw.textlength(line, font=font)
            uy = ty + size + max(1, size // 10)
            draw.line(
                [(box_x + pad, uy), (box_x + pad + line_w, uy)],
                fill=ink,
                width=max(1, size // 12),
            )
        ty += line_h

    return (box_x, box_y, box_w, box_h)
