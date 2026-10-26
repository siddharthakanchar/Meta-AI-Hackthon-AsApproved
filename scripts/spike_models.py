"""Phase 1 spike — Meta Model API. Proves four things and records the quirks.

  1. Muse Spark structured output on an image (strict JSON Schema)
  2. SAM 3.1 on a still image, concept prompt "text box"
  3. SAM 3.1 video tracking on a short clip, stable object IDs
  4. Muse Voice Transcribe on a 10-15s WAV
  plus: decode a SAM base85 mask in Python and assert its shape

Writes latency, token/frame counts, computed cost and every surprise into
DECISIONS.md. Run: python scripts/spike_models.py
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("Phase 1 — written once META_MODEL_API_KEY is in .env")


if __name__ == "__main__":
    main()
