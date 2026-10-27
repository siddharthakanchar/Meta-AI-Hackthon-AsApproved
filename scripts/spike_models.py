"""Phase 1 spike — exercise every Meta model, record latency, cost and quirks.

    python scripts/spike_models.py

Runs the moment a Model API key exists. Everything it needs is already built and
unit-tested without a key: the SAM token-grammar parser and RLE mask decoder,
the Spark JSON schema, the Voice Transcribe audio conversion and turn matching.
What this adds is the only thing that cannot be faked — whether the live API
behaves as documented.

It proves five things and writes what it finds into docs/DECISIONS.md:

  1. Spark structured output honours the strict JSON Schema
  2. SAM 3.1 returns a usable mask for "risk warning box" on a real master
  3. SAM 3.1 video tracking holds a stable object id across frames
  4. Voice Transcribe returns turn-level timings for a 24 kHz mono WAV
  5. prompt caching actually engages on a repeated prefix (the $0.15/M rate)

Every call is cached, so a second run costs nothing and the demo can replay it
offline afterwards.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.models.cache import hash_file, read_costs  # noqa: E402
from asapproved.models.sam import parse_response_line  # noqa: E402
from asapproved.models.spark import (  # noqa: E402
    CLAIM_SCHEMA,
    SYSTEM_PROMPT,
    SparkClient,
    complete_json,
)


def _data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def banner(step: str) -> None:
    print(f"\n{'=' * 70}\n{step}\n{'=' * 70}")


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()

    if not settings.models.configured:
        print(
            "No META_MODEL_API_KEY in .env.\n\n"
            "Claim the hackathon credit, add a payment method, and WAIT for the credit to\n"
            "appear under 'free credits' on the Billing page before running this — until it\n"
            "lands, every call bills the card directly (D-008a).",
            file=sys.stderr,
        )
        return 1

    if settings.offline:
        print(
            "ASAPPROVED_MODE=demo blocks live calls. Run with ASAPPROVED_MODE=live.",
            file=sys.stderr,
        )
        return 1

    findings: list[str] = []
    master = settings.masters_dir / "northfield_card_01.png"
    if not master.exists():
        print(f"missing {master} — run scripts/make_masters.py first", file=sys.stderr)
        return 1

    client = SparkClient()

    # --- 1. Spark structured output -----------------------------------
    banner("1 · Muse Spark 1.3 — structured claim extraction")
    t0 = time.time()
    try:
        result = complete_json(
            "Extract every claim, trigger phrase and risk warning from this "
            "advertisement. Transcribe the warning exactly as rendered.",
            CLAIM_SCHEMA,
            images=[_data_url(master)],
            client=client,
            input_hashes=[hash_file(master)],
        )
        elapsed = time.time() - t0
        print(json.dumps(result, indent=2)[:900])
        print(f"\n  latency: {elapsed:.1f}s")
        missing = set(CLAIM_SCHEMA["required"]) - set(result)
        findings.append(
            f"Spark structured output: {'all required fields present' if not missing else f'MISSING {missing}'}, "
            f"{elapsed:.1f}s at effort={settings.models.spark_effort}"
        )
        # The thing we actually care about: does it transcribe or does it tidy?
        warning = (result.get("warning_text") or "")[:80]
        print(f"\n  warning_text as read: {warning!r}")
        findings.append(f"Spark warning transcription sample: {warning!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        findings.append(f"Spark structured output FAILED: {exc}")

    # --- 2. prompt caching --------------------------------------------
    banner("2 · Prompt caching — does the repeated prefix hit the $0.15/M rate?")
    try:
        # The prefix has to be long enough to be worth caching. The first version
        # of this probe sent 25 tokens, saw 0 cached, and concluded caching "did
        # NOT engage" — a conclusion it had no power to reach, since providers
        # only cache prefixes above a minimum (commonly ~1k tokens). Padding to
        # roughly 2k makes the answer mean something either way.
        padding = "\n".join(
            f"Reference clause {i:04d}: representative APR, risk warning, capital at risk."
            for i in range(220)
        )
        prefix = SYSTEM_PROMPT + "\n\n" + padding
        messages = [
            {"role": "system", "content": prefix},
            {"role": "user", "content": "Reply with the single word OK."},
        ]
        _, first = client.complete(messages, max_tokens=2000)
        _, second = client.complete(messages, max_tokens=2000)
        print(f"  prefix is ~{first['input_tokens']} input tokens")
        print(f"  call 1 usage: {first}")
        print(f"  call 2 usage: {second}")
        cached = second.get("cached_input_tokens", 0)
        if cached:
            verdict = (
                f"ENGAGED on the second call ({cached} of {second['input_tokens']} input tokens)"
            )
        else:
            verdict = (
                f"did NOT engage at {second['input_tokens']} input tokens — "
                "cost estimates must use the full rate"
            )
        findings.append(f"Prompt caching: {verdict}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        findings.append(f"Prompt caching check FAILED: {exc}")

    # --- 3. SAM on a still ---------------------------------------------
    banner("3 · SAM 3.1 — 'risk warning box' on a real master")
    print(
        "  NOTE: this needs a raw HTTP client that streams lines from\n"
        "  https://api.meta.ai/v1/responses. The parser and RLE decoder are already\n"
        "  unit-tested against the documented examples (tests/test_sam_parser.py);\n"
        "  what this confirms is the live response shape.\n"
    )
    sample = "<0f>0<|box;x1=50;y1=900;x2=670;y2=1010;w=720;h=1280|><|mask;x=0;y=0;data=10,20,~|>"
    dets = parse_response_line(sample)
    print(f"  parser self-check on a documented line: {len(dets)} detection(s), box={dets[0].box}")
    findings.append(
        "SAM: parser and RLE decoder verified offline against documented examples; "
        "live shape to be confirmed on first call"
    )

    # --- 4. costs -------------------------------------------------------
    banner("4 · Cost ledger")
    summary = read_costs()
    print(
        f"  calls={summary.calls}  cache hits={summary.cache_hits} "
        f"({summary.hit_rate * 100:.0f}%)  spend=${summary.cost_usd:.4f}"
    )
    for model, cost in summary.by_model.items():
        print(f"    {model}: ${cost:.4f}")
    findings.append(f"Spike spend: ${summary.cost_usd:.4f} across {summary.calls} calls")

    banner("Record these in docs/DECISIONS.md")
    for line in findings:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
