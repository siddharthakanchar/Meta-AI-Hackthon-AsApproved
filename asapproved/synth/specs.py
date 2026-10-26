"""The 12 approved masters.

Composition follows the design notes: 5 credit stills, 3 credit videos, 2 high-risk
stills, 2 investment videos. The four investment masters between them use all
four prescribed warnings from COBS 4.12A.11R, so R11 gets exercised on every
variant of the text rather than on one.

Prescribed wording is READ FROM THE RULEBOOK, never retyped here. One copy of
quoted law in the repo, already pinned by test — a second copy would eventually
drift from the first, and the drift would be invisible.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from asapproved.synth.brands import BRANDS, Brand

__all__ = ["MasterSpec", "MASTERS", "prescribed_text", "SIZE_9_16", "SIZE_1_1"]

SIZE_9_16 = (720, 1280)
SIZE_1_1 = (720, 720)

_RULEBOOK = Path(__file__).resolve().parent.parent / "rules" / "rulebook_uk_v1.yaml"


@lru_cache(maxsize=1)
def _prescribed_texts() -> dict[str, str]:
    raw = yaml.safe_load(_RULEBOOK.read_text(encoding="utf-8"))
    return {k: " ".join(v.split()) for k, v in raw["prescribed_texts"].items()}


def prescribed_text(investment_type: str) -> str:
    texts = _prescribed_texts()
    if investment_type not in texts:
        raise KeyError(f"no prescribed text for {investment_type!r}; have {sorted(texts)}")
    return texts[investment_type]


@dataclass(frozen=True)
class MasterSpec:
    id: str
    brand_key: str
    kind: str  # "still" | "video"
    size: tuple[int, int]
    headline: str
    trigger: str
    apr_line: str
    # Credit products carry a representative example; investment products carry
    # one of the four prescribed warnings, selected by investment_type.
    investment_type: str | None = None
    representative_example: str | None = None
    duration_s: int = 15
    fps: int = 25
    placement: str = "reels"
    # Did the voiceover say the APR? Feeds R9 ground truth. Masters are compliant,
    # so this is True wherever there is a voiceover at all.
    vo_speaks_trigger: bool = True
    vo_speaks_apr: bool = True

    @property
    def brand(self) -> Brand:
        return BRANDS[self.brand_key]

    @property
    def is_credit(self) -> bool:
        return self.investment_type is None

    @property
    def apr_label(self) -> str:
        """An investment promotion has no representative APR — see render.draw_frame."""
        return "apr" if self.is_credit else "risk_note"

    @property
    def body_text(self) -> str:
        """Sector-appropriate small print.

        "Credit subject to status" on a crypto promotion is simply wrong copy, and
        wrong copy in the masters would train the claim extractor on nonsense.
        """
        if self.is_credit:
            return f"{self.brand.tagline}. Credit subject to status. 18+, UK residents only."
        return f"{self.brand.tagline}. Capital at risk. 18+, UK residents only."

    @property
    def warning_text(self) -> str:
        if self.investment_type:
            return prescribed_text(self.investment_type)
        assert self.representative_example, f"{self.id}: credit master needs a representative example"
        return self.representative_example

    @property
    def total_frames(self) -> int:
        return self.duration_s * self.fps if self.kind == "video" else 1

    @property
    def filename(self) -> str:
        return f"{self.id}.mp4" if self.kind == "video" else f"{self.id}.png"


_REP_EXAMPLE_NC = (
    "Representative example: £1,200 credit over 12 months at 0% p.a. fixed for 12 months, "
    "then 24.9% p.a. variable. Total amount payable £1,200. Representative 24.9% APR variable."
)
_REP_EXAMPLE_BL = (
    "Representative example: borrowing £5,000 over 36 months at 9.9% p.a. fixed. "
    "Monthly repayment £160.64. Total amount payable £5,783.04. Representative 9.9% APR."
)

MASTERS: list[MasterSpec] = [
    # ---- 5 credit stills --------------------------------------------
    MasterSpec(
        id="northfield_card_01",
        brand_key="northfield",
        kind="still",
        size=SIZE_1_1,
        headline="Move your balance. Keep your money.",
        trigger="0% for 12 months",
        apr_line="24.9% APR representative (variable)",
        representative_example=_REP_EXAMPLE_NC,
        placement="feed",
    ),
    MasterSpec(
        id="northfield_card_02",
        brand_key="northfield",
        kind="still",
        size=SIZE_9_16,
        headline="A balance transfer that gives you room to breathe.",
        trigger="0% for 12 months",
        apr_line="24.9% APR representative (variable)",
        representative_example=_REP_EXAMPLE_NC,
        placement="stories",
    ),
    MasterSpec(
        id="northfield_card_03",
        brand_key="northfield",
        kind="still",
        size=SIZE_1_1,
        headline="No annual fee. No surprises.",
        trigger="0% for 12 months",
        apr_line="24.9% APR representative (variable)",
        representative_example=_REP_EXAMPLE_NC,
        placement="feed",
    ),
    MasterSpec(
        id="brightwell_loans_01",
        brand_key="brightwell",
        kind="still",
        size=SIZE_9_16,
        headline="Borrow £5,000. Know the cost up front.",
        trigger="Loans from £1,000",
        apr_line="9.9% APR representative",
        representative_example=_REP_EXAMPLE_BL,
        placement="reels",
    ),
    MasterSpec(
        id="brightwell_loans_02",
        brand_key="brightwell",
        kind="still",
        size=SIZE_1_1,
        headline="A rate you can plan around.",
        trigger="Fixed for 36 months",
        apr_line="9.9% APR representative",
        representative_example=_REP_EXAMPLE_BL,
        placement="feed",
    ),
    # ---- 3 credit videos --------------------------------------------
    MasterSpec(
        id="northfield_card_v1",
        brand_key="northfield",
        kind="video",
        size=SIZE_9_16,
        headline="Move your balance. Keep your money.",
        trigger="0% for 12 months",
        apr_line="24.9% APR representative (variable)",
        representative_example=_REP_EXAMPLE_NC,
        placement="reels",
    ),
    MasterSpec(
        id="brightwell_loans_v1",
        brand_key="brightwell",
        kind="video",
        size=SIZE_1_1,
        headline="Borrow £5,000. Know the cost up front.",
        trigger="Loans from £1,000",
        apr_line="9.9% APR representative",
        representative_example=_REP_EXAMPLE_BL,
        placement="feed",
    ),
    MasterSpec(
        id="northfield_card_v2",
        brand_key="northfield",
        kind="video",
        size=SIZE_9_16,
        headline="Twelve months of breathing room.",
        trigger="0% for 12 months",
        apr_line="24.9% APR representative (variable)",
        representative_example=_REP_EXAMPLE_NC,
        placement="reels",
    ),
    # ---- 2 high-risk stills -----------------------------------------
    MasterSpec(
        id="kestrel_crypto_01",
        brand_key="kestrel",
        kind="still",
        size=SIZE_9_16,
        headline="Build a crypto portfolio, carefully.",
        trigger="Start from £25",
        apr_line="Capital at risk",
        investment_type="cryptoassets",
        placement="reels",
    ),
    MasterSpec(
        id="kestrel_nrrs_01",
        brand_key="kestrel",
        kind="still",
        size=SIZE_1_1,
        headline="Back the companies you believe in.",
        trigger="Invest from £100",
        apr_line="Capital at risk",
        investment_type="non_readily_realisable_securities",
        placement="feed",
    ),
    # ---- 2 investment videos ----------------------------------------
    MasterSpec(
        id="kestrel_p2p_v1",
        brand_key="kestrel",
        kind="video",
        size=SIZE_9_16,
        headline="Lend directly. See where it goes.",
        trigger="Target 6.2% a year",
        apr_line="Capital at risk",
        investment_type="p2p_agreements",
        placement="reels",
    ),
    MasterSpec(
        id="kestrel_ltaf_v1",
        brand_key="kestrel",
        kind="video",
        size=SIZE_1_1,
        headline="Long-term assets, for long-term investors.",
        trigger="Invest from £500",
        apr_line="Capital at risk",
        investment_type="long_term_asset_fund",
        placement="feed",
    ),
]


def by_id(master_id: str) -> MasterSpec:
    for spec in MASTERS:
        if spec.id == master_id:
            return spec
    raise KeyError(master_id)
