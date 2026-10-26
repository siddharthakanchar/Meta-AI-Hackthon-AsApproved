"""Three fictional UK firms, their palettes, and the fonts we render with.

Names were chosen to be plausibly British and findably fake. None corresponds to
a real authorised firm; the FRNs below are obviously invalid placeholders and are
rendered only because a real financial promotion carries one, and its absence
would make the creative look unlike the thing we claim to measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

__all__ = ["Brand", "BRANDS", "load_font", "FontSet"]

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Brand:
    key: str
    name: str
    tagline: str
    # Palette. `ink_on_bg` must stay legible on `bg` — the masters are the
    # compliant baseline, so none of them may fail R6 by construction.
    bg: RGB
    bg_accent: RGB
    ink: RGB
    accent: RGB
    frn: str
    sector: str  # "credit" | "investment"


BRANDS: dict[str, Brand] = {
    "northfield": Brand(
        key="northfield",
        name="Northfield Card",
        tagline="A card that keeps up",
        bg=(18, 32, 58),
        bg_accent=(28, 52, 92),
        ink=(245, 247, 250),
        accent=(255, 196, 61),
        frn="FRN 000001 (fictional)",
        sector="credit",
    ),
    "brightwell": Brand(
        key="brightwell",
        name="Brightwell Loans",
        tagline="Straightforward borrowing",
        bg=(24, 54, 44),
        bg_accent=(36, 82, 66),
        ink=(244, 250, 246),
        accent=(120, 226, 164),
        frn="FRN 000002 (fictional)",
        sector="credit",
    ),
    "kestrel": Brand(
        key="kestrel",
        name="Kestrel Invest",
        tagline="Invest with your eyes open",
        bg=(40, 24, 56),
        bg_accent=(66, 38, 92),
        ink=(247, 243, 252),
        accent=(198, 156, 255),
        frn="FRN 000003 (fictional)",
        sector="investment",
    ),
}


@dataclass(frozen=True)
class FontSet:
    regular: Path
    bold: Path


def _find_fonts() -> FontSet:
    """Prefer Arial, fall back through common Windows faces.

    A bold face is not cosmetic here: COBS 4.12A.36R requires the warning in bold
    and underlined text, so a master rendered without a real bold face would be
    non-compliant by construction and would poison R5's ground truth.
    """
    root = Path("C:/Windows/Fonts")
    candidates = [
        ("arial.ttf", "arialbd.ttf"),
        ("segoeui.ttf", "segoeuib.ttf"),
        ("tahoma.ttf", "tahomabd.ttf"),
        ("verdana.ttf", "verdanab.ttf"),
        ("calibri.ttf", "calibrib.ttf"),
    ]
    for regular, bold in candidates:
        r, b = root / regular, root / bold
        if r.exists() and b.exists():
            return FontSet(regular=r, bold=b)
    raise RuntimeError(
        "No regular+bold TrueType pair found in C:/Windows/Fonts. The masters "
        "cannot be rendered compliantly without a real bold face (COBS 4.12A.36R)."
    )


@lru_cache(maxsize=1)
def font_set() -> FontSet:
    return _find_fonts()


@lru_cache(maxsize=64)
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    fonts = font_set()
    return ImageFont.truetype(str(fonts.bold if bold else fonts.regular), size)
