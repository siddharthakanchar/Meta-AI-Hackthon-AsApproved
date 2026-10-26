"""Meta Marketing API client. Every fact here is VERIFY-pending
until the Phase 1 spike; record the outcome in docs/DECISIONS.md.

Reads we need:
  - ads + creatives, including `degrees_of_freedom_spec.creative_features_spec`
    with per-feature `enroll_status` OPT_IN / OPT_OUT
  - previews: GET /{ad_id}/previews?ad_format=... and
    POST /act_{ad_account_id}/generatepreviews
    (unknown whether previews render AI enhancements — this is the spike)

Writes (Act, D3): set an enhancement to OPT_OUT; needs `ads_management`.

All responses are saved as fixtures under data/fixtures/, stripped of personal
IDs before anything is committed (§17).
"""

from __future__ import annotations

__all__ = ["MarketingClient", "FEATURE_KEYS"]

# VERIFY exact keys and API version in Phase 1.
FEATURE_KEYS: tuple[str, ...] = (
    "image_touchups",
    "image_background_gen",
    "image_animation",
    "text_optimizations",
    "text_translation",
    "adapt_to_placement",
    "site_extensions",
    "music_generation",
    "video_highlights",
    "translate_voiceover",
)


class MarketingClient:  # noqa: D101 - Phase 1 spike, then Phase 6
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN204
        raise NotImplementedError("Phase 1 spike")
