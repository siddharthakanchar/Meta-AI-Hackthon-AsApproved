"""Shared rendering helpers for the review UI.

Design rules from the design notes, applied here rather than restated per screen:
one accent colour reserved for failures, numbers big and plain, and every claim
on screen carrying its source (a measurement, a rule, a frame).
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

ACCENT_FAIL = "#e5484d"
ACCENT_WARN = "#f5a524"
ACCENT_OK = "#30a46c"
ACCENT_UNKNOWN = "#8b8d98"

STATUS_COLOUR = {
    "fail": ACCENT_FAIL,
    "pass": ACCENT_OK,
    "inconclusive": ACCENT_WARN,
    "not_applicable": ACCENT_UNKNOWN,
}

STATUS_LABEL = {
    "fail": "FAIL",
    "pass": "pass",
    "inconclusive": "can't tell",
    "not_applicable": "n/a",
}


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def heatmap_overlay(frame_bgr: np.ndarray, ssim_map: np.ndarray, alpha: float = 0.55) -> np.ndarray:
    """Red where the variant diverges structurally from the master."""
    inverted = np.clip((1.0 - ssim_map) * 255.0, 0, 255).astype(np.uint8)
    coloured = cv2.applyColorMap(inverted, cv2.COLORMAP_INFERNO)
    if coloured.shape[:2] != frame_bgr.shape[:2]:
        coloured = cv2.resize(coloured, (frame_bgr.shape[1], frame_bgr.shape[0]))
    return cv2.addWeighted(frame_bgr, 1 - alpha, coloured, alpha, 0)


def draw_region(
    frame_bgr: np.ndarray,
    box,
    label: str,
    colour_hex: str,
    thickness: int = 3,
) -> np.ndarray:
    out = frame_bgr.copy()
    if not box:
        return out
    x, y, w, h = [int(v) for v in box]
    bgr = _hex_to_bgr(colour_hex)
    cv2.rectangle(out, (x, y), (x + w, y + h), bgr, thickness)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    ty = max(0, y - th - 6)
    cv2.rectangle(out, (x, ty), (x + tw + 8, ty + th + 8), bgr, -1)
    cv2.putText(
        out, label, (x + 4, ty + th + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
        cv2.LINE_AA,
    )
    return out


def draw_overlay_zone(frame_bgr: np.ndarray, placement: str) -> np.ndarray:
    """Shade the area the platform's own chrome can cover."""
    from asapproved.vision.overlays import overlay_mask

    out = frame_bgr.copy()
    h, w = out.shape[:2]
    try:
        mask = overlay_mask(placement, w, h)
    except KeyError:
        return out
    tint = np.zeros_like(out)
    tint[mask] = (120, 120, 120)
    return cv2.addWeighted(out, 0.75, tint, 0.25, 0)


def _hex_to_bgr(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


def visibility_bar_html(visible: list[bool], fps: float, label: str) -> str:
    """A timeline strip: green where the region is on screen, red where it is not.

    The point of the hero screen in one widget — "present at frame zero" and
    "present throughout" are different claims, and a preview can only show the
    first.
    """
    if not visible:
        return ""
    total = len(visible)
    segments: list[str] = []
    start = 0
    for i in range(1, total + 1):
        if i == total or visible[i] != visible[start]:
            width = (i - start) / total * 100
            colour = ACCENT_OK if visible[start] else ACCENT_FAIL
            segments.append(
                f'<div style="width:{width:.4f}%;background:{colour};height:100%;"></div>'
            )
            start = i
    seconds = sum(visible) / fps if fps else 0.0
    total_s = total / fps if fps else 0.0
    return (
        f'<div class="aa-muted" style="margin-bottom:.25rem;">{label} on screen '
        f"<b>{seconds:.1f}s</b> of {total_s:.0f}s</div>"
        f'<div style="display:flex;height:16px;border-radius:3px;overflow:hidden;'
        f'border:1px solid rgba(128,128,128,.35);">{"".join(segments)}</div>'
    )


def finding_card_html(finding: dict[str, Any]) -> str:
    colour = STATUS_COLOUR.get(finding["status"], ACCENT_UNKNOWN)
    badge = STATUS_LABEL.get(finding["status"], finding["status"])
    measured = finding.get("measured_display") or "—"
    threshold = finding.get("threshold_display") or "—"

    caveats = "".join(
        f'<div class="aa-caveat">⚠ {c}</div>' for c in (finding.get("caveats") or [])
    )
    subs = finding.get("sub_results") or {}
    sub_html = ""
    if subs:
        chips = " ".join(
            f'<span class="aa-chip" style="border-color:{STATUS_COLOUR.get(v, ACCENT_UNKNOWN)};'
            f'color:{STATUS_COLOUR.get(v, ACCENT_UNKNOWN)}">{k}: {STATUS_LABEL.get(v, v)}</span>'
            for k, v in subs.items()
        )
        sub_html = f'<div style="margin-top:.4rem">{chips}</div>'

    return f"""
    <div class="aa-finding" style="border-left:4px solid {colour}">
      <div class="aa-finding-head">
        <span class="aa-badge" style="background:{colour}">{badge}</span>
        <b>{finding["rule_id"]}</b>
        <span class="aa-muted">{finding["citation"]}</span>
      </div>
      <div class="aa-detail">{finding["detail"]}</div>
      <div class="aa-numbers">
        measured <b>{measured}</b> &nbsp;·&nbsp; threshold <b>{threshold}</b>
      </div>
      {sub_html}
      {caveats}
    </div>
    """


CSS = f"""
<style>
  .block-container {{ padding-top: 2rem; max-width: 1500px; }}
  .aa-metric {{ font-size: 2.6rem; font-weight: 680; line-height: 1.05; }}
  .aa-metric-sub {{ font-size: .8rem; opacity: .7; }}
  .aa-fail {{ color: {ACCENT_FAIL}; }}
  .aa-ok {{ color: {ACCENT_OK}; }}
  .aa-warn {{ color: {ACCENT_WARN}; }}
  .aa-muted {{ opacity: .68; font-size: .85rem; }}
  .aa-sim {{
    display:inline-block; padding:.12rem .5rem; border-radius:.25rem;
    border:1px solid currentColor; font-size:.68rem; letter-spacing:.07em;
    text-transform:uppercase; opacity:.85;
  }}
  .aa-finding {{
    padding:.7rem .9rem; margin-bottom:.6rem; border-radius:.3rem;
    background: rgba(128,128,128,.07);
  }}
  .aa-finding-head {{ display:flex; gap:.5rem; align-items:center; margin-bottom:.3rem; }}
  .aa-badge {{
    color:#fff; padding:.05rem .45rem; border-radius:.2rem;
    font-size:.68rem; font-weight:700; letter-spacing:.04em;
  }}
  .aa-detail {{ font-size:.92rem; margin-bottom:.35rem; }}
  .aa-numbers {{ font-size:.8rem; opacity:.8; }}
  .aa-caveat {{ font-size:.76rem; opacity:.75; margin-top:.35rem; font-style:italic; }}
  .aa-chip {{
    display:inline-block; border:1px solid; border-radius:.9rem;
    padding:.03rem .5rem; font-size:.7rem; margin-right:.25rem;
  }}
  .aa-provenance {{
    font-size:.74rem; opacity:.66; border-top:1px solid rgba(128,128,128,.25);
    padding-top:.5rem; margin-top:.75rem; line-height:1.5;
  }}
</style>
"""
