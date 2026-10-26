"""Synthetic ad creative for the deterministic-core tests.

Built in numpy rather than loaded from disk so the tests are hermetic and the
repo stays light. Deterministic seed: these must not be flaky, because they are
the tests that justify every number the tool reports.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

FRAME_W, FRAME_H = 640, 1138  # 9:16-ish, the shape that matters for Reels


def _rng() -> np.random.Generator:
    return np.random.default_rng(20261026)


def make_master(width: int = FRAME_W, height: int = FRAME_H) -> np.ndarray:
    """A mock credit-card ad: textured background, headline, APR box, warning box.

    The texture matters — ORB needs corners, and a flat gradient would make the
    alignment tests pass or fail for reasons unrelated to the code under test.
    """
    rng = _rng()
    img = np.full((height, width, 3), 28, dtype=np.uint8)

    # Background texture: scattered rectangles give ORB plenty to latch onto.
    for _ in range(220):
        x = int(rng.integers(0, width - 40))
        y = int(rng.integers(0, height - 40))
        w = int(rng.integers(8, 40))
        h = int(rng.integers(8, 40))
        colour = tuple(int(c) for c in rng.integers(40, 210, size=3))
        cv2.rectangle(img, (x, y), (x + w, y + h), colour, -1)

    # Headline band
    cv2.rectangle(img, (40, 120), (width - 40, 230), (240, 240, 240), -1)
    cv2.putText(img, "0% for 12 months", (56, 196), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3)

    # Representative APR, high contrast
    cv2.rectangle(img, (40, 300), (width - 40, 380), (255, 255, 255), -1)
    cv2.putText(img, "24.9% APR repr.", (56, 358), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (10, 10, 10), 2)

    # Risk warning in its own bordered box, near the bottom
    cv2.rectangle(img, (40, height - 260), (width - 40, height - 150), (255, 255, 255), -1)
    cv2.rectangle(img, (40, height - 260), (width - 40, height - 150), (0, 0, 0), 3)  # border
    cv2.putText(
        img, "Your home may be", (58, height - 215), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2
    )
    cv2.putText(
        img, "repossessed", (58, height - 178), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2
    )
    return img


def region_mask(width: int, height: int, box: tuple[int, int, int, int]) -> np.ndarray:
    """Boolean mask for an (x, y, w, h) box — stands in for a SAM mask."""
    mask = np.zeros((height, width), dtype=bool)
    x, y, w, h = box
    mask[y : y + h, x : x + w] = True
    return mask


def warning_box(width: int = FRAME_W, height: int = FRAME_H) -> tuple[int, int, int, int]:
    return (40, height - 260, width - 80, 110)


def apr_box(width: int = FRAME_W, height: int = FRAME_H) -> tuple[int, int, int, int]:
    return (40, 300, width - 80, 80)


@pytest.fixture()
def master() -> np.ndarray:
    return make_master()


@pytest.fixture()
def warning_mask() -> np.ndarray:
    return region_mask(FRAME_W, FRAME_H, warning_box())


@pytest.fixture()
def apr_mask() -> np.ndarray:
    return region_mask(FRAME_W, FRAME_H, apr_box())
