"""SAM 3.1 — region masks and video tracking (C4), via the Responses API.

Verified against dev.meta.ai/docs/sam/segmenting on 26 Oct 2026 (docs/DECISIONS.md
D-006):
  - model id `sam-3.1`, POST https://api.meta.ai/v1/responses, "stream": true
  - content parts: {"type": "input_text"} + {"type": "input_image"|"input_video"}
  - ONE noun phrase per request. No comma lists, no OR, no negation, no spatial
    phrases — those return inconsistent results.
  - video: <=16 objects per frame across <=15,000 frames, one output line per frame
  - metadata.include_confidence="true" adds a `c` field per box and mask
  - ~$2.50 per 1,000 images; ~$0.20 per 1,000 video frames, 50-frame minimum

The response is a TOKEN STRING, not JSON — one line per frame:

    <0f>0<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600|><|mask;x=0;y=0;data=122,376,~...|>

Masks are run-length encoded (the playbook had them as base85). Two encodings
selected by metadata.mask_encoding: `lossless` (marker ~) and `one_bit`
(marker !). The mask's x/y are an offset **within the bounding box**, not the
image origin — decoding against image origin silently misplaces every mask.

Meta documents a Python parser (`meta-sam-parser`). We parse and decode here
anyway, because the format is small, the failure mode of getting it wrong is
invisible misplacement rather than an exception, and owning the decode path
means the unit tests below can run with no API key and no package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

__all__ = [
    "RESPONSES_ENDPOINT",
    "CONCEPTS",
    "SamBox",
    "SamMask",
    "SamDetection",
    "parse_response_line",
    "decode_rle",
    "decode_mask",
    "segment_image",
    "track_video",
]

RESPONSES_ENDPOINT = "https://api.meta.ai/v1/responses"

# One noun phrase per request — the docs are explicit that comma lists and
# boolean OR return inconsistent results, so these are six separate calls.
CONCEPTS: tuple[str, ...] = (
    "risk warning box",
    "APR text",
    "price",
    "headline",
    "person",
    "logo",
)

LOSSLESS_MARKER = "~"
ONE_BIT_MARKER = "!"

_FRAME_RE = re.compile(r"<(\d+)f>")
_OBJ_RE = re.compile(r"(?:<(\d+)f>)?(\d+)((?:<\|[^|]*\|>)+)")
_PART_RE = re.compile(r"<\|([^|]*)\|>")


@dataclass(frozen=True)
class SamBox:
    x1: int
    y1: int
    x2: int
    y2: int
    w: int
    h: int
    confidence: float | None = None

    @property
    def xywh(self) -> tuple[int, int, int, int]:
        """x2/y2 are INCLUSIVE per the docs, so width is x2 - x1 + 1."""
        return (self.x1, self.y1, self.x2 - self.x1 + 1, self.y2 - self.y1 + 1)


@dataclass(frozen=True)
class SamMask:
    x: int  # offset WITHIN the bounding box, not the image
    y: int
    data: str
    encoding: str
    confidence: float | None = None


@dataclass(frozen=True)
class SamDetection:
    frame: int
    object_id: int
    box: SamBox | None
    mask: SamMask | None


def _kv(part: str) -> dict[str, str]:
    bits = part.split(";")
    out: dict[str, str] = {"_kind": bits[0]}
    for bit in bits[1:]:
        if "=" in bit:
            key, _, value = bit.partition("=")
            out[key] = value
    return out


def parse_response_line(line: str) -> list[SamDetection]:
    """Parse one `<Nf>id<|box;...|><|mask;...|>` line into detections.

    A line may carry several objects. The frame marker appears once at the start
    and applies to everything after it.
    """
    line = line.strip()
    if not line:
        return []

    frame = 0
    m = _FRAME_RE.match(line)
    if m:
        frame = int(m.group(1))

    detections: list[SamDetection] = []
    for match in _OBJ_RE.finditer(line):
        if match.group(1) is not None:
            frame = int(match.group(1))
        object_id = int(match.group(2))

        box: SamBox | None = None
        mask: SamMask | None = None
        for part in _PART_RE.findall(match.group(3)):
            fields = _kv(part)
            kind = fields.get("_kind")
            if kind == "box":
                box = SamBox(
                    x1=int(fields["x1"]),
                    y1=int(fields["y1"]),
                    x2=int(fields["x2"]),
                    y2=int(fields["y2"]),
                    w=int(fields["w"]),
                    h=int(fields["h"]),
                    confidence=float(fields["c"]) if "c" in fields else None,
                )
            elif kind == "mask":
                raw = fields.get("data", "")
                encoding = "one_bit" if ONE_BIT_MARKER in raw else "lossless"
                mask = SamMask(
                    x=int(fields.get("x", 0)),
                    y=int(fields.get("y", 0)),
                    data=raw,
                    encoding=encoding,
                    confidence=float(fields["c"]) if "c" in fields else None,
                )
        detections.append(SamDetection(frame=frame, object_id=object_id, box=box, mask=mask))
    return detections


def decode_rle(data: str, width: int, height: int) -> np.ndarray:
    """Decode a run-length mask payload into a boolean array of (height, width).

    The payload is a comma-separated run list with a marker character. Runs
    alternate background/foreground starting with background, which is the
    conventional RLE layout and what the documented samples show.

    Raises on a run list that does not fill the region: a short payload would
    otherwise decode to a silently truncated mask, and a mask that is wrong by
    construction is worse than one that fails loudly.
    """
    payload = data.replace(LOSSLESS_MARKER, "").replace(ONE_BIT_MARKER, "")
    runs = [int(token) for token in payload.split(",") if token.strip().lstrip("-").isdigit()]
    total = width * height
    flat = np.zeros(total, dtype=bool)

    pos = 0
    value = False
    for run in runs:
        if run < 0:
            raise ValueError(f"negative run length in mask payload: {run}")
        end = min(pos + run, total)
        if value and end > pos:
            flat[pos:end] = True
        pos = end
        value = not value
        if pos >= total:
            break

    if pos < total:
        raise ValueError(
            f"mask payload covers {pos} of {total} pixels for a {width}x{height} region — "
            "a truncated mask would be silently misplaced rather than reported"
        )
    return flat.reshape(height, width)


def decode_mask(mask: SamMask, box: SamBox, image_shape: tuple[int, int]) -> np.ndarray:
    """Place a decoded mask into full-image coordinates.

    `mask.x` / `mask.y` are offsets inside the BOX. Treating them as image
    coordinates is the specific mistake this signature exists to prevent: it
    produces a plausible mask in the wrong place, which no test of "did we get a
    mask" would catch.
    """
    img_h, img_w = image_shape[:2]
    bx, by, bw, bh = box.xywh

    region = decode_rle(mask.data, bw, bh)

    out = np.zeros((img_h, img_w), dtype=bool)
    x0 = bx + mask.x
    y0 = by + mask.y
    x1 = min(img_w, x0 + bw)
    y1 = min(img_h, y0 + bh)
    if x0 >= img_w or y0 >= img_h or x1 <= 0 or y1 <= 0:
        return out

    out[max(0, y0) : y1, max(0, x0) : x1] = region[: y1 - max(0, y0), : x1 - max(0, x0)]
    return out


# ---------------------------------------------------------------------------
# API calls (exercised in Phase 1, once a key exists)
# ---------------------------------------------------------------------------


def _build_request(concept: str, media_key: str, media_value: str, *, stream: bool = True) -> dict:
    return {
        "model": "sam-3.1",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": concept},
                    {"type": media_key, media_key.replace("input_", "") + "_url": media_value},
                ],
            }
        ],
        "stream": stream,
        "metadata": {"include_confidence": "true", "mask_encoding": "lossless"},
    }


def segment_image(image_url: str, concept: str, *, client=None) -> list[SamDetection]:
    """Segment one image for one noun phrase."""
    if client is None:
        raise RuntimeError(
            "SAM 3.1 needs a Model API client. In demo mode the pipeline uses "
            "asapproved.vision.track instead, which is labelled as such in the UI."
        )
    body = _build_request(concept, "input_image", image_url)
    detections: list[SamDetection] = []
    for line in client.stream_lines(RESPONSES_ENDPOINT, body):
        detections.extend(parse_response_line(line))
    return detections


def track_video(video_url: str, concept: str, *, client=None) -> dict[int, list[SamDetection]]:
    """Track one concept across a clip, returning detections keyed by frame."""
    if client is None:
        raise RuntimeError("SAM 3.1 needs a Model API client.")
    body = _build_request(concept, "input_video", video_url)
    by_frame: dict[int, list[SamDetection]] = {}
    for line in client.stream_lines(RESPONSES_ENDPOINT, body):
        for det in parse_response_line(line):
            by_frame.setdefault(det.frame, []).append(det)
    return by_frame
