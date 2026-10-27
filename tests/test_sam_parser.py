"""SAM 3.1 response parsing and mask decoding — tested with no API key.

This is the part of the Meta integration that can be got wrong *silently*. A
mask decoded against the image origin instead of the bounding box still
produces a mask of the right size and the right shape, just in the wrong place,
and every "did we get a mask?" check passes. The measurement engine would then
report confident contrast and occlusion figures for a region that is not the
warning.

So the format is pinned here against the documented examples, before a single
real call is made.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from asapproved.config import REPO_ROOT
from asapproved.models.sam import (
    CONCEPTS,
    MaskEncodingUnsupported,
    SamBox,
    SamMask,
    decode_mask,
    decode_rle,
    mask_encoding,
    parse_response_line,
    split_mask_payload,
)

# The exact image example from dev.meta.ai/docs/sam/segmenting.
IMAGE_LINE = "<0f>0<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600|><|mask;x=0;y=0;data=122,376,~|>"
VIDEO_LINE = "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~|>"


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def test_parses_the_documented_image_line():
    dets = parse_response_line(IMAGE_LINE)
    assert len(dets) == 1
    det = dets[0]
    assert det.frame == 0
    assert det.object_id == 0
    assert det.box == SamBox(x1=181, y1=365, x2=556, y2=486, w=1516, h=1600)
    assert det.mask is not None
    assert det.mask.encoding == "lossless"


def test_box_width_treats_x2_as_inclusive():
    """The docs say x2/y2 are inclusive. Off by one here is off by one everywhere."""
    det = parse_response_line(IMAGE_LINE)[0]
    assert det.box.xywh == (181, 365, 556 - 181 + 1, 486 - 365 + 1)


def test_parses_a_video_frame_marker():
    line = VIDEO_LINE.replace("<0f>", "<42f>")
    det = parse_response_line(line)[0]
    assert det.frame == 42


def test_parses_several_objects_on_one_line():
    line = (
        "<3f>0<|box;x1=1;y1=1;x2=10;y2=10;w=100;h=100|>1<|box;x1=20;y1=20;x2=30;y2=30;w=100;h=100|>"
    )
    dets = parse_response_line(line)
    assert [d.object_id for d in dets] == [0, 1]
    assert all(d.frame == 3 for d in dets)


def test_parses_confidence_when_requested():
    line = "<0f>0<|box;x1=1;y1=1;x2=4;y2=4;w=10;h=10;c=0.93|><|mask;x=0;y=0;data=1,15,~|>"
    det = parse_response_line(line)[0]
    assert det.box.confidence == pytest.approx(0.93)


def test_detects_the_one_bit_encoding_marker():
    line = "<0f>0<|box;x1=0;y1=0;x2=3;y2=3;w=10;h=10|><|mask;x=0;y=0;data=4,12,!|>"
    det = parse_response_line(line)[0]
    assert det.mask.encoding == "one_bit"


def test_empty_line_yields_nothing():
    assert parse_response_line("") == []
    assert parse_response_line("   ") == []


def test_concepts_are_single_noun_phrases():
    """The docs forbid comma lists and boolean OR — one concept per request."""
    for concept in CONCEPTS:
        assert "," not in concept
        assert " or " not in concept.lower()
        assert len(concept.split()) <= 4


# --------------------------------------------------------------------------
# RLE decoding
# --------------------------------------------------------------------------


def test_rle_alternates_starting_with_background():
    # 4x2 = 8 pixels: 2 off, 3 on, 3 off
    mask = decode_rle("2,4~2,3,3", 4, 2)
    assert mask.shape == (2, 4)
    assert mask.flatten().tolist() == [False, False, True, True, True, False, False, False]


def test_rle_ignores_the_encoding_marker():
    assert decode_rle("2,4~2,3,3", 4, 2).sum() == 3
    assert decode_rle("2,4!2,3,3", 4, 2).sum() == 3


def test_rle_fully_background():
    assert decode_rle("2,4~8", 4, 2).sum() == 0


def test_rle_rejects_a_truncated_payload():
    """A short run list would decode to a silently truncated mask."""
    with pytest.raises(ValueError, match="covers 4 of 8"):
        decode_rle("2,4~2,2", 4, 2)


def test_rle_rejects_negative_runs():
    with pytest.raises(ValueError, match="negative run"):
        decode_rle("2,4~2,-3,9", 4, 2)


def test_rle_tolerates_an_overlong_final_run():
    """Encoders commonly pad the last run; that must not raise."""
    mask = decode_rle("2,4~2,3,99", 4, 2)
    assert mask.flatten().tolist()[:5] == [False, False, True, True, True]


# --------------------------------------------------------------------------
# placement — the silent-failure case
# --------------------------------------------------------------------------


def test_mask_is_placed_at_the_box_not_the_image_origin():
    """The mistake this whole module exists to prevent.

    Decoding against the image origin yields a correctly shaped mask in the
    wrong location, which every "did we get a mask" assertion would pass while
    the measurement engine reported contrast for the wrong pixels.
    """
    box = SamBox(x1=100, y1=50, x2=103, y2=51, w=400, h=300)  # 4x2 at (100, 50)
    mask = SamMask(x=0, y=0, data="2,4~2,3,3", encoding="lossless")

    placed = decode_mask(mask, box, (300, 400))
    ys, xs = np.nonzero(placed)

    assert placed.shape == (300, 400)
    assert xs.min() >= 100 and ys.min() >= 50, "mask landed at the image origin"
    assert placed[50, 102] and placed[50, 103] and placed[51, 100]
    assert not placed[0, 0]


def test_mask_offset_inside_the_box_is_applied():
    box = SamBox(x1=10, y1=10, x2=13, y2=11, w=100, h=100)
    mask = SamMask(x=5, y=3, data="2,4~2,3,3", encoding="lossless")

    placed = decode_mask(mask, box, (100, 100))
    # 4x2 region, runs 2-off/3-on/3-off, so the on-pixels are (row0: x=2,3) and
    # (row1: x=0) — the run wraps onto the second row.
    expected = {(10 + 3, 10 + 5 + 2), (10 + 3, 10 + 5 + 3), (10 + 3 + 1, 10 + 5)}
    got = set(zip(*(a.tolist() for a in np.nonzero(placed)), strict=True))
    assert got == expected


def test_mask_entirely_off_frame_returns_empty_rather_than_raising():
    box = SamBox(x1=500, y1=500, x2=503, y2=501, w=100, h=100)
    mask = SamMask(x=0, y=0, data="2,4~2,3,3", encoding="lossless")
    placed = decode_mask(mask, box, (100, 100))
    assert placed.sum() == 0


def test_mask_clipped_at_the_frame_edge():
    box = SamBox(x1=98, y1=0, x2=101, y2=1, w=100, h=100)
    mask = SamMask(x=0, y=0, data="2,4~2,3,3", encoding="lossless")
    placed = decode_mask(mask, box, (100, 100))
    assert placed.shape == (100, 100)
    assert placed[:, 98:].sum() >= 1


def test_the_documented_samples_header_is_the_box_size_not_run_lengths():
    """`data=122,376,~` is a 376x122 header, and the box is 376x122.

    Reading those two numbers as run lengths is what made a real 617x230 mask
    decode to 847 set pixels. Both documented samples give it away once checked
    against their own boxes; the payload itself is elided in the docs.
    """
    for line, (want_w, want_h) in ((IMAGE_LINE, (376, 122)), (VIDEO_LINE, (60, 27))):
        det = parse_response_line(line)[0]
        _, _, bw, bh = det.box.xywh
        assert (bw, bh) == (want_w, want_h)

        h, w, marker, body = split_mask_payload(det.mask.data)
        assert (w, h) == (want_w, want_h), "header does not match the box it describes"
        assert marker == "~"
        assert body == "", "the documented sample elides the payload"

    # With no body there is nothing to decode, and an empty mask must be
    # reported rather than returned as all-background.
    det = parse_response_line(IMAGE_LINE)[0]
    with pytest.raises(ValueError, match="covers 0 of 45872"):
        decode_mask(det.mask, det.box, (1600, 1516))


# --------------------------------------------------------------------------
# the live format — recorded from the real API, not assumed
# --------------------------------------------------------------------------

LIVE_STREAM = REPO_ROOT / "data" / "fixtures" / "sam_responses_stream.sse"


def _live_detection():
    text = LIVE_STREAM.read_text(encoding="utf-8")
    line = re.search(r'"delta":"(<0f>.*?)"', text).group(1)
    return parse_response_line(line.encode().decode("unicode_escape"))[0]


def test_a_live_lossless_mask_is_not_labelled_one_bit():
    """Encoding was decided by `"!" in raw`, and "!" occurs all through the body.

    Nearly every lossless mask was therefore labelled `one_bit`. The marker is
    positional: the one character that follows the dimensions.
    """
    det = _live_detection()
    assert det.mask.encoding == "lossless"
    assert mask_encoding(det.mask.data) == "lossless"
    assert "!" in det.mask.data, "this payload no longer exercises the old bug"


def test_a_live_mask_header_matches_its_box():
    det = _live_detection()
    _, _, bw, bh = det.box.xywh
    h, w, _, body = split_mask_payload(det.mask.data)
    assert (w, h) == (bw, bh) == (617, 230)
    assert len(body) > 1000, "expected a real payload, not an elided one"


def test_an_unreadable_live_body_says_so_instead_of_decoding_garbage():
    """The live body is an 85-character encoding this decoder cannot read.

    Its alphabet includes `z` and `{`, so it is neither Ascii85 nor Z85, and it
    runs 1.58x the length of the packed bitmap, which matches no packed-bitmap
    encoding. Guessing would produce a plausible mask in the wrong shape —
    exactly what `decode_mask` exists to prevent. Callers use the bounding box,
    which is parsed and verified, and record that the mask was unavailable.
    """
    det = _live_detection()
    with pytest.raises(MaskEncodingUnsupported, match="not a decimal run list"):
        decode_mask(det.mask, det.box, (1280, 720))


def test_a_payload_with_no_marker_is_rejected():
    with pytest.raises(MaskEncodingUnsupported, match="no encoding marker"):
        split_mask_payload("230,617,0,5,5")


def test_a_header_that_is_not_two_numbers_is_rejected():
    with pytest.raises(MaskEncodingUnsupported, match="not '<h>,<w>'"):
        split_mask_payload("230~0,5")
    with pytest.raises(MaskEncodingUnsupported, match="not '<h>,<w>'"):
        split_mask_payload("230,617,99~0,5")


def test_a_header_that_contradicts_the_box_is_rejected():
    """A mask decoded at the wrong dimensions is misplaced, not merely wrong."""
    with pytest.raises(ValueError, match="header says 617x230 but the box is 4x2"):
        decode_rle("230,617~8", 4, 2)
