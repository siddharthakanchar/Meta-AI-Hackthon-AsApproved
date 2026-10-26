"""SAM 3.1 — region masks and video tracking (C4), via the Responses API.

Verified against dev.meta.ai/docs/sam/segmenting on 26 Oct 2026 (DECISIONS.md D-006):
  - model id `sam-3.1`, POST https://api.meta.ai/v1/responses, with "stream": true
  - content parts: {"type": "input_text"} + {"type": "input_image"|"input_video"}
    (image_url / video_url / file_id)
  - ONE noun phrase per request. No comma lists, no OR, no negation, no spatial
    phrases -- those return inconsistent results. Plurals/case/punctuation ignored.
    Concrete attributes ("red square") usefully narrow the match.
  - video: <=16 objects per frame, <=15,000 frames (~10 min) per request, one
    output line per frame, stable object IDs
  - box/point prompts name up to 16 objects, via a token grammar, and always come
    back as `one_bit` masks
  - metadata.include_confidence="true" adds a `c` field (0-1) per box and mask
  - ~$2.50 per 1,000 images; ~$0.20 per 1,000 video frames (50-frame minimum)

Response is a TOKEN STRING, not JSON -- one line per frame:
    <0f>0<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600|><|mask;x=0;y=0;data=122,376,~...|>

Masks are RLE, not base85 (the playbook had this wrong). Two encodings, chosen
with metadata.mask_encoding:
    lossless  default, marker `~`
    one_bit   marker `!`, several times smaller
`x`/`y` on the mask are an offset within the BOUNDING BOX, not the image origin --
decoding needs the box, which is why decode_mask takes one.

Meta documents a Python parser, `meta-sam-parser` (`decodeMaskToRaster`). Phase 1
tries it first; our own decoder stays as the fallback and keeps its unit test
either way, so we own the decode path if the package disappoints (V13).

Concept prompts we need, one request each: "risk warning box", "APR text",
"price", "headline", "person", "logo". Results cached by content hash.

If SAM misses thin text lines, try "text box" / "caption banner", then fall back
to OCR boxes for text regions and report the IoU honestly (§16).
"""

from __future__ import annotations

__all__ = ["RESPONSES_ENDPOINT", "CONCEPTS", "segment_image", "track_video", "decode_mask"]

RESPONSES_ENDPOINT = "https://api.meta.ai/v1/responses"

CONCEPTS: tuple[str, ...] = (
    "risk warning box",
    "APR text",
    "price",
    "headline",
    "person",
    "logo",
)


def segment_image(image_path, concept: str):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 1 spike, then Phase 4")


def track_video(video_path, concept: str):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 1 spike, then Phase 4")


def parse_response_line(line: str):  # noqa: ANN201
    """Split one `<Nf>id<|box;...|><|mask;...|>` line into frame, id, box and mask. Phase 1."""
    raise NotImplementedError("Phase 1")


def decode_mask(data: str, box, encoding: str = "lossless"):  # noqa: ANN001, ANN201
    """Decode an RLE SAM mask into a boolean numpy array, offset into `box`.

    `encoding` is "lossless" (marker ~) or "one_bit" (marker !). Unit-tested, Phase 1.
    """
    raise NotImplementedError("Phase 1")
