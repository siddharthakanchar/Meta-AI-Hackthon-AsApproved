"""Muse Spark 1.3 — claim extraction (C6) and compliance notes (C10).

Verified against dev.meta.ai/docs on 26 Oct 2026 (DECISIONS.md D-006):
  - OpenAI-compatible API, base URL https://api.meta.ai/v1
  - model id `muse-spark-1.3`; 1,048,576-token context
  - text / image / video / PDF input (MP4 via Files API to 1 GiB, inline to ~50 MB)
  - structured output via JSON Schema (constrained decoding)
  - tool calling, parallel by default
  - reasoning effort minimal..max; use low/minimal for anything interactive
    (high effort is 30-70s to first token)
  - audio not fully supported in 1.3 (1.2 is documented as better) -> we use
    Voice Transcribe for audio instead
  - $1.25 in / $4.25 out per M tokens (Standard tier), and **$0.15 per M CACHED
    input tokens**

That cache price matters: the system prompt and the rulebook text are byte-identical
across all 48 benchmark variants, so the prefix should be cached rather than re-sent.
It is the difference between a published cost-per-variant that is honest and one that
is 8x too high. Measure both and report the cached figure with the mechanism named.

Video is sampled at 2 fps for Spark; full frame rate goes to SAM only.
"""

from __future__ import annotations

__all__ = ["extract_claims", "complete_json", "CLAIM_SCHEMA"]

# Strict schema for C6: on-screen text, claims, triggers, representative example
# present, warning text as read. Filled in Phase 4.
CLAIM_SCHEMA: dict = {}


def complete_json(prompt: str, schema: dict, images=None, video=None, effort: str | None = None):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 1 spike, then Phase 4")


def extract_claims(frames, audio_transcript=None):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 4")
