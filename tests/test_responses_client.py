"""The Responses-API streaming client, checked against a real recorded response.

`data/fixtures/sam_responses_stream.sse` is the verbatim server-sent-event
stream SAM 3.1 returned for the concept "risk warning box" on
`data/masters/brightwell_loans_01.png`, captured 27 Oct 2026. Testing against a
recording rather than a hand-written sample is the point: a client written to a
guess about the event sequence passes its own invented fixture.
"""

from __future__ import annotations

import json

import httpx
import pytest

from asapproved.config import REPO_ROOT
from asapproved.models.responses import ResponsesClient, ResponsesError, _text_delta
from asapproved.models.sam import parse_response_line

RECORDING = REPO_ROOT / "data" / "fixtures" / "sam_responses_stream.sse"


@pytest.fixture(scope="module")
def recorded() -> str:
    return RECORDING.read_text(encoding="utf-8")


def _client_replaying(body: str, status: int = 200) -> ResponsesClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    return ResponsesClient("test-key", client=httpx.Client(transport=transport))


def test_the_recording_is_a_real_sam_stream(recorded: str) -> None:
    """Guard the fixture itself: a truncated or re-saved file would silently weaken
    every test below."""
    assert "event: response.created" in recorded
    assert "event: response.completed" in recorded
    assert "response.output_text.delta" in recorded
    assert "<|box;" in recorded and "<|mask;" in recorded


def test_lines_parse_into_detections_with_a_box_and_a_mask(recorded: str) -> None:
    client = _client_replaying(recorded)
    lines = list(client.stream_lines("https://api.meta.ai/v1/responses", {}))

    assert lines, "no grammar lines were recovered from the stream"
    detections = [d for line in lines for d in parse_response_line(line)]
    assert detections, "the recorded stream parsed to nothing"

    first = detections[0]
    assert first.box is not None, "no bounding box"
    assert first.mask is not None, "no mask"
    assert first.box.w == 720 and first.box.h == 1280
    assert 0.0 < first.box.confidence <= 1.0


def test_done_events_are_not_read_as_well_as_the_deltas(recorded: str) -> None:
    """`.done` repeats the whole text. Consuming both doubles every detection."""
    client = _client_replaying(recorded)
    detections = [
        d
        for line in client.stream_lines("https://api.meta.ai/v1/responses", {})
        for d in parse_response_line(line)
    ]

    ids = [(d.frame, d.object_id) for d in detections]
    assert len(ids) == len(set(ids)), f"the same object came back twice: {ids}"


def test_a_multi_line_delta_is_split_into_separate_lines() -> None:
    """Video tracking emits one line per frame; they must not be glued together."""
    stream = "".join(
        "event: response.output_text.delta\n"
        f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': chunk})}\n\n"
        for chunk in (
            "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|>\n<1f>0<|box;",
            "x1=5;y1=6;x2=7;y2=8;w=10;h=10|>",
        )
    )
    client = _client_replaying(stream)
    lines = list(client.stream_lines("https://api.meta.ai/v1/responses", {}))

    assert len(lines) == 2, f"expected one line per frame, got {lines}"
    frames = [d.frame for line in lines for d in parse_response_line(line)]
    assert frames == [0, 1]


def test_a_line_split_across_two_deltas_is_rejoined() -> None:
    """SSE chunk boundaries fall wherever they like, including mid-token."""
    parts = ("<0f>0<|box;x1=1;y1=2;", "x2=3;y2=4;w=10;h=10|>")
    stream = "".join(
        f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': p})}\n\n" for p in parts
    )
    detections = [
        d
        for line in _client_replaying(stream).stream_lines("https://x/v1/responses", {})
        for d in parse_response_line(line)
    ]
    assert len(detections) == 1
    # x2/y2 are inclusive, so 1..3 is three pixels wide.
    assert detections[0].box.xywh == (1, 2, 3, 3)


def test_an_http_error_names_the_status_and_the_body() -> None:
    client = _client_replaying('{"error":{"message":"bad concept"}}', status=422)
    with pytest.raises(ResponsesError) as exc:
        list(client.stream_lines("https://api.meta.ai/v1/responses", {}))
    assert "422" in str(exc.value)
    assert "bad concept" in str(exc.value)


def test_a_missing_key_fails_before_any_network_call() -> None:
    client = ResponsesClient("")
    assert not client.configured
    with pytest.raises(ResponsesError, match="META_MODEL_API_KEY"):
        list(client.stream_lines("https://api.meta.ai/v1/responses", {}))


@pytest.mark.parametrize(
    "line",
    [
        "event: response.completed",
        "",
        "data: [DONE]",
        'data: {"type":"response.created","response":{}}',
        'data: {"type":"response.output_text.done","text":"<0f>0<|box;x1=1|>"}',
        "data: not json at all",
        'data: {"type":"response.output_text.delta"}',
        'data: {"type":"response.output_text.delta","delta":null}',
    ],
)
def test_lines_that_carry_no_text_are_ignored(line: str) -> None:
    assert _text_delta(line) is None


def test_a_delta_line_yields_its_text() -> None:
    payload = {"type": "response.output_text.delta", "delta": "<0f>0"}
    assert _text_delta(f"data: {json.dumps(payload)}") == "<0f>0"
