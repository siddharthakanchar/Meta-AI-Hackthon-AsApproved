"""C9 — placement safe-zone overlay masks, and occlusion measurement.

FG24/1 para 1.5: a prescribed warning must not be "obscured or truncated by a
design feature of the social media platform". A warning that is perfectly legible
in the asset can still be sitting under the Reels caption block when a user sees
it — which is why this is measured against the delivered placement, not the file.

Zone percentages live in `placements.yaml` and are currently UNVERIFIED (V11).
`PlacementSpec.verified` carries that fact through to every finding so the UI can
label it, rather than quietly presenting secondary figures as Meta's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

__all__ = [
    "PLACEMENTS",
    "PlacementSpec",
    "load_placements",
    "overlay_mask",
    "occlusion",
    "Occlusion",
]

_SPEC_PATH = Path(__file__).with_name("placements.yaml")
PLACEMENTS: tuple[str, ...] = ("feed", "stories", "reels")


@dataclass(frozen=True)
class PlacementSpec:
    name: str
    top: float
    bottom: float
    left: float
    right: float
    verified: bool
    source: str

    def caveat(self) -> str | None:
        """Text the UI must show alongside any finding derived from this spec."""
        if self.verified:
            return None
        return (
            f"Safe-zone figures for '{self.name}' are unverified "
            f"({self.source}); treat as a flag for review, not a measured breach."
        )


@lru_cache(maxsize=1)
def load_placements(path: str | None = None) -> dict[str, PlacementSpec]:
    raw = yaml.safe_load(Path(path or _SPEC_PATH).read_text(encoding="utf-8"))
    verified = raw.get("status") == "verified"
    source = raw.get("source", "unknown")
    specs: dict[str, PlacementSpec] = {}
    for name, cfg in raw["placements"].items():
        specs[name] = PlacementSpec(
            name=name,
            top=float(cfg.get("top", 0.0)),
            bottom=float(cfg.get("bottom", 0.0)),
            left=float(cfg.get("left", 0.0)),
            right=float(cfg.get("right", 0.0)),
            verified=verified,
            source=source,
        )
    for name, cfg in (raw.get("variants") or {}).items():
        specs[name] = PlacementSpec(
            name=name,
            top=float(cfg.get("top", 0.0)),
            bottom=float(cfg.get("bottom", 0.0)),
            left=float(cfg.get("left", 0.0)),
            right=float(cfg.get("right", 0.0)),
            verified=verified,
            source=source,
        )
    return specs


def get_spec(placement: str) -> PlacementSpec:
    specs = load_placements()
    if placement not in specs:
        raise KeyError(f"unknown placement {placement!r}; known: {sorted(specs)}")
    return specs[placement]


def overlay_mask(placement: str, width: int, height: int) -> np.ndarray:
    """Boolean mask, True where platform UI may cover the creative.

    Rounds reserved bands OUTWARD (ceil). A half-pixel of warning under the Reels
    caption is still obscured, and under-reporting occlusion is the failure mode
    that matters here.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"bad frame size: {width}x{height}")
    spec = get_spec(placement)
    mask = np.zeros((height, width), dtype=bool)

    top = int(np.ceil(spec.top * height))
    bottom = int(np.ceil(spec.bottom * height))
    left = int(np.ceil(spec.left * width))
    right = int(np.ceil(spec.right * width))

    if top:
        mask[:top, :] = True
    if bottom:
        mask[height - bottom :, :] = True
    if left:
        mask[:, :left] = True
    if right:
        mask[:, width - right :] = True
    return mask


@dataclass(frozen=True)
class Occlusion:
    """How much of a region the platform chrome may cover.

    `fraction_bp` is in basis points (1/10000) rather than a float, so it can go
    into a signed manifest or the evidence chain unchanged — see
    `asapproved.canonical.assert_no_floats`.
    """

    placement: str
    region_pixels: int
    occluded_pixels: int
    fraction_bp: int
    verified_spec: bool
    caveat: str | None

    @property
    def any_occluded(self) -> bool:
        return self.occluded_pixels > 0


def occlusion(region_mask: np.ndarray, placement: str) -> Occlusion:
    """Measure overlap between a region and the placement's reserved zones.

    R12's threshold is zero: any occluded pixel in any frame is a finding.
    """
    if region_mask.dtype != bool:
        region_mask = region_mask.astype(bool)
    height, width = region_mask.shape[:2]
    ui = overlay_mask(placement, width, height)
    spec = get_spec(placement)

    region_pixels = int(region_mask.sum())
    occluded = int(np.logical_and(region_mask, ui).sum())
    fraction_bp = int(round(10_000 * occluded / region_pixels)) if region_pixels else 0

    return Occlusion(
        placement=placement,
        region_pixels=region_pixels,
        occluded_pixels=occluded,
        fraction_bp=fraction_bp,
        verified_spec=spec.verified,
        caveat=spec.caveat(),
    )
