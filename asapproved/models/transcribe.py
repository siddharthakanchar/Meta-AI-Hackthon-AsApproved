"""Muse Voice Transcribe — C7: was the trigger spoken? Was the APR/warning spoken?

Verified against dev.meta.ai/docs/speech-to-text on 26 Oct 2026 (DECISIONS.md D-006):
  - model id `muse-voice-transcribe-1.0`
  - NOT on the OpenAI-compatible surface. Own endpoints:
        POST  https://api.meta.ai/v1/asr/transcribe   (file, Authorization: Bearer)
        wss://api.meta.ai/v1/asr/realtime             (streaming; we don't need it)
  - audio must be raw PCM, signed 16-bit little-endian, mono, RIFF/WAVE container
  - PCM_24KHZ is preferred; 16 kHz is accepted but resampled server-side, so we
    send 24 kHz (this corrects the playbook, which said 16 kHz)
  - 32 MB / 10 min caps; billed down to whole seconds; ~$0.18 per hour
  - diarization gives speaker labels per turn, session-scoped
  - TURN-LEVEL timestamps only (startMs / endMs). No word-level timings and no
    confidence scores -- so R9 reasons about turns, never about word offsets.

Feeds R9: trigger spoken but representative APR not spoken (CONC 3.5.7R).
"""

from __future__ import annotations

__all__ = ["ASR_ENDPOINT", "SAMPLE_RATE", "to_pcm_wav", "transcribe", "spoken_check"]

ASR_ENDPOINT = "https://api.meta.ai/v1/asr/transcribe"
SAMPLE_RATE = 24_000  # PCM_24KHZ — the documented preference


def to_pcm_wav(src, dst):  # noqa: ANN001, ANN201
    """ffmpeg -i <src> -ar 24000 -ac 1 -c:a pcm_s16le <dst>. Phase 4."""
    raise NotImplementedError("Phase 4")


def transcribe(wav_path):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 1 spike, then Phase 4")


def spoken_check(turns, phrases: list[str]):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 4")
