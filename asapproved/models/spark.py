"""Muse Spark 1.3 — claim extraction (C6) and compliance notes (C10).

Verified against dev.meta.ai/docs on 26 Oct 2026 (DECISIONS.md D-006):
  - OpenAI-compatible API at https://api.meta.ai/v1, model `muse-spark-1.3`
  - 1,048,576-token context; text / image / video / PDF input
  - structured output via JSON Schema (constrained decoding)
  - reasoning effort minimal..max — low/minimal for anything interactive, since
    high effort is 30-70s to first token
  - audio is not fully supported in 1.3; Voice Transcribe handles audio
  - $1.25 in / $4.25 out per M tokens, and **$0.15 per M cached input**

That cache price drives a design choice. The system prompt and the rulebook text
are byte-identical across all 48 benchmark variants, so they go FIRST in the
message list and unchanged, which is what lets the provider cache the prefix.
Publishing a cost-per-variant computed without that would be roughly 8x too high
on the input side.

What Spark is NOT allowed to do here: decide anything. It extracts claims into a
constrained schema and it writes prose. Every verdict comes from the rules
engine, and every sentence it writes passes `explain.validate_note` before a
human sees it.
"""

from __future__ import annotations

from typing import Any

from asapproved.config import settings
from asapproved.models.cache import cached_call

__all__ = ["CLAIM_SCHEMA", "SYSTEM_PROMPT", "SparkClient", "extract_claims", "complete_json"]

# Strict schema for C6. `additionalProperties: false` throughout, because a
# model that can invent a field can invent a finding.
CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "on_screen_text",
        "claims",
        "triggers",
        "cost_of_credit_present",
        "representative_example_present",
        "warning_text",
    ],
    "properties": {
        "on_screen_text": {
            "type": "string",
            "description": "All text visible in the creative, in reading order.",
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "type"],
                "properties": {
                    "text": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["rate", "price", "benefit", "risk", "eligibility", "other"],
                    },
                },
            },
        },
        "triggers": {
            "type": "array",
            "description": (
                "Phrases that require a representative APR under CONC 3.5, "
                "e.g. '0% for 12 months'."
            ),
            "items": {"type": "string"},
        },
        "cost_of_credit_present": {
            "type": "boolean",
            "description": "Is any rate, amount or cost-of-credit figure shown?",
        },
        "representative_example_present": {
            "type": "boolean",
            "description": "Is a representative example shown, as CONC 3.5.5R describes?",
        },
        "warning_text": {
            "type": ["string", "null"],
            "description": (
                "The risk warning or representative example verbatim, exactly as rendered, "
                "with no correction of spelling, spacing or punctuation. Null if absent."
            ),
        },
    },
}

SYSTEM_PROMPT = (
    "You extract what is literally present in an advertisement. You do not judge "
    "compliance, you do not infer intent, and you do not correct what you read. "
    "Transcribe text exactly as rendered, including any spacing or punctuation that "
    "looks wrong. If something is absent, say it is absent rather than supplying what "
    "you would expect to be there."
)


class SparkClient:
    """Thin wrapper over the OpenAI-compatible surface."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.models.api_key
        self.base_url = base_url or settings.models.base_url
        self.model = model or settings.models.spark_model
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        effort: str | None = None,
        max_tokens: int = 1200,
    ) -> tuple[str, dict[str, int]]:
        """Return (text, usage). Usage carries the token counts the ledger needs."""
        client = self._ensure()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        effort = effort or settings.models.spark_effort
        if effort:
            kwargs["reasoning_effort"] = effort
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "strict": True, "schema": schema},
            }

        response = client.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        counts = {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cached_input_tokens": getattr(
                getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0
            )
            or 0,
        }
        return response.choices[0].message.content or "", counts


def _image_part(data_url: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": data_url}}


def complete_json(
    prompt: str,
    schema: dict[str, Any],
    *,
    images: list[str] | None = None,
    client: SparkClient | None = None,
    effort: str | None = None,
    input_hashes: list[str] | None = None,
) -> dict[str, Any]:
    """One structured-output call, cached by content hash."""
    import json

    client = client or SparkClient()
    # System prompt first and unchanged, so the provider can cache the prefix.
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": ([{"type": "text", "text": prompt}] + [_image_part(i) for i in images or []])
            if images
            else prompt,
        },
    ]

    def call():
        text, counts = client.complete(messages, schema=schema, effort=effort)
        return {"text": text, "usage": counts}

    result = cached_call(
        client.model,
        {"schema": schema.get("required"), "prompt": prompt, "effort": effort or settings.models.spark_effort},
        input_hashes or [],
        call,
        cost_fields={},
    )
    return json.loads(result["text"])


def extract_claims(
    prompt_image_urls: list[str],
    *,
    client: SparkClient | None = None,
    input_hashes: list[str] | None = None,
) -> dict[str, Any]:
    """C6 — claims, triggers and the warning text, as a constrained JSON object."""
    return complete_json(
        "Extract every claim, trigger phrase and risk warning from this advertisement. "
        "Transcribe the warning exactly as rendered.",
        CLAIM_SCHEMA,
        images=prompt_image_urls,
        client=client,
        input_hashes=input_hashes,
    )
