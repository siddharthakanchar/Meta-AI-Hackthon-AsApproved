"""Muse Voice Transcribe — C7: was the trigger spoken? Was the APR spoken?

Verified against dev.meta.ai/docs/speech-to-text on 26 Oct 2026 (D-006):
  - model `muse-voice-transcribe-1.0`, NOT on the OpenAI-compatible surface
  - POST https://api.meta.ai/v1/asr/transcribe, Authorization: Bearer
  - raw PCM, signed 16-bit little-endian, mono, RIFF/WAVE container
  - **PCM_24KHZ is preferred**; 16 kHz is accepted but resampled server-side
    (the playbook specified 16 kHz — corrected here)
  - 32 MB / 10 min caps; diarization; ~$0.18 per hour
  - **turn-level timestamps only** — no word timings, no confidences

That last point shapes R9 entirely. With only turn boundaries we can say "the
trigger and the APR were spoken in the same turn" or "the APR never appears in
any turn", but never "the APR was spoken 4.2 seconds in". R9 is written to the
granularity the API actually provides rather than to the granularity we would
prefer, and `spoken_check` returns the turn index so a reviewer can listen to
the exact turn rather than being asked to trust a boolean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asapproved.ffmpeg import run_ffmpeg
from asapproved.text_norm import normalise

__all__ = [
    "ASR_ENDPOINT",
    "SAMPLE_RATE",
    "Turn",
    "Transcript",
    "to_pcm_wav",
    "transcribe",
    "spoken_check",
    "SpokenResult",
]

ASR_ENDPOINT = "https://api.meta.ai/v1/asr/transcribe"
SAMPLE_RATE = 24_000  # PCM_24KHZ, the documented preference
MAX_SECONDS = 600
MAX_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class Turn:
    index: int
    speaker: str
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Transcript:
    turns: list[Turn]
    available: bool = True

    def text(self) -> str:
        return " ".join(t.text for t in self.turns)


@dataclass(frozen=True)
class SpokenResult:
    spoken: bool
    turn_index: int | None = None
    matched_phrase: str | None = None

    def __bool__(self) -> bool:
        return self.spoken


def to_pcm_wav(src: str | Path, dst: str | Path) -> Path:
    """Convert any audio or video to the exact format the API accepts."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(src),
            "-vn",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(dst),
        ]
    )
    size = dst.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(
            f"{dst.name} is {size / 1e6:.1f} MB, above the API's 32 MB limit — "
            "split the audio before transcribing"
        )
    return dst


def transcribe(wav_path: str | Path, *, client=None) -> Transcript:
    """Transcribe a prepared WAV. Returns an unavailable Transcript with no client.

    Unavailable is distinct from empty: an empty transcript would make R9 read
    "the APR was not spoken", which is a finding against the advertiser based on
    our own missing capability.
    """
    if client is None:
        return Transcript(turns=[], available=False)

    payload = client.transcribe_file(ASR_ENDPOINT, Path(wav_path))
    return parse_transcript(payload)


def parse_transcript(payload: dict[str, Any]) -> Transcript:
    turns: list[Turn] = []
    for i, raw in enumerate(payload.get("turns") or []):
        turns.append(
            Turn(
                index=i,
                speaker=str(raw.get("speaker", "A")),
                text=str(raw.get("text", "")),
                start_ms=int(raw.get("startMs", 0)),
                end_ms=int(raw.get("endMs", 0)),
            )
        )
    return Transcript(turns=turns, available=True)


def _spoken_number_variants(phrase: str) -> list[str]:
    """Numbers are spoken, not written: "24.9%" is said "twenty-four point nine percent".

    A literal substring match would miss every spoken rate, so a handful of
    forms are generated. This is deliberately shallow — it covers the shapes our
    scripts use and no more, and `spoken_check` reports which phrase matched so
    a reviewer can confirm rather than trust it.
    """
    out = [phrase]
    digits = re.sub(r"[^\d.]", "", phrase)
    if digits:
        out.append(digits)
        if "." in digits:
            whole, _, frac = digits.partition(".")
            out.append(f"{whole} point {frac}")
    if "%" in phrase:
        out.append(phrase.replace("%", " percent"))
        out.append(phrase.replace("%", " per cent"))
    if "APR" in phrase.upper():
        out.append(phrase.upper().replace("APR", "A P R"))
    return [o for o in out if o.strip()]


def spoken_check(transcript: Transcript, phrases: list[str]) -> SpokenResult | None:
    """Was any of these phrases spoken? None when there is no transcript at all."""
    if not transcript.available:
        return None

    for turn in transcript.turns:
        haystack = normalise(turn.text)
        for phrase in phrases:
            for variant in _spoken_number_variants(phrase):
                needle = normalise(variant)
                if needle and needle in haystack:
                    return SpokenResult(True, turn_index=turn.index, matched_phrase=variant)
    return SpokenResult(False)
