"""Raw streaming client for the Meta Responses API (`/v1/responses`).

SAM 3.1 does not speak the OpenAI chat surface. It answers on `/v1/responses`
as a server-sent-event stream whose text deltas carry the token grammar that
`sam.py` parses:

    <0f>0<|box;x1=52;y1=476;x2=668;y2=705;w=720;h=1280;c=0.706|><|mask;...|>

`sam.segment_image` and `sam.track_video` have always called
`client.stream_lines(...)`; this is that client. Verified against the live API
on 27 Oct 2026 — the event sequence is response.created, response.in_progress,
response.output_item.added, response.content_part.added, then one or more
response.output_text.delta, response.output_text.done, response.content_part.done,
response.output_item.done, response.completed.

Only the deltas are read. The `.done` events repeat the same text in full, so
consuming both would double every detection.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from asapproved.config import settings

__all__ = ["ResponsesClient", "ResponsesError"]

# One frame of 4K video can take a while to come back, and a clip takes longer.
DEFAULT_TIMEOUT = 300.0


class ResponsesError(RuntimeError):
    """The API refused the request or returned an unusable stream."""


class ResponsesClient:
    """POSTs a Responses-API body and yields the grammar lines it streams back."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ):
        # `None` means "use the configured key"; "" means "deliberately none".
        # `api_key or settings...` collapses those two, so a caller asking for an
        # unconfigured client silently got the real key from .env instead.
        self.api_key = settings.models.api_key if api_key is None else api_key
        self.timeout = timeout
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def stream_lines(self, endpoint: str, body: dict[str, Any]) -> Iterator[str]:
        """Yield each complete grammar line the model emits.

        Lines are assembled from the text deltas rather than taken from the
        final `.done` event, so a long video's frames arrive as they are
        produced instead of all at once at the end.
        """
        if not self.configured:
            raise ResponsesError("No META_MODEL_API_KEY: the Responses API needs a key.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        client = self._client or httpx.Client(timeout=self.timeout)
        close_after = self._client is None
        try:
            with client.stream("POST", endpoint, json=body, headers=headers) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")[:800]
                    raise ResponsesError(f"{endpoint} returned {response.status_code}: {detail}")

                buffer = ""
                for raw in response.iter_lines():
                    delta = _text_delta(raw)
                    if delta is None:
                        continue
                    buffer += delta
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line.strip():
                            yield line
                if buffer.strip():
                    yield buffer
        finally:
            if close_after:
                client.close()


def _text_delta(raw: str) -> str | None:
    """The text carried by one SSE line, or None if it carries none.

    `event:` lines, blank separators, the `[DONE]` sentinel and every event type
    other than `response.output_text.delta` return None.
    """
    line = raw.strip()
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if event.get("type") != "response.output_text.delta":
        return None
    delta = event.get("delta")
    return delta if isinstance(delta, str) else None
