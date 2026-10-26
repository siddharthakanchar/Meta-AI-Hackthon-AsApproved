"""Generate the voiceovers the video masters and their R9 variants need.

R9 asks whether the trigger was spoken but the representative APR was not —
CONC 3.5.7R prominence parity in the audio channel, which no pixel check can
see. It needs two things: audio on the clip, and a transcript of it. This script
supplies the first. The second needs Muse Voice Transcribe, so R9 stays
**not evaluated** until a Model API key exists — it is never counted as a pass.

Offline Windows SAPI via pyttsx3, so it works with no network and no key. The
audio is SYNTHETIC SPEECH and labelled as such in every sidecar: a reader should
know the voice is generated, the same way they know the creative is.

    python scripts/make_voiceovers.py [--list]

Each video master gets a compliant read (trigger AND representative APR spoken).
Its `voiceover_drops_apr` variant gets a read that keeps the trigger and drops
the APR — identical in every other respect, so R9 is the only thing separating
them. That isolation is the point: if the two clips differed visually as well,
a detector could appear to find R9 while actually seeing something else.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.ffmpeg import ffmpeg_path, run_ffmpeg  # noqa: E402
from asapproved.synth.specs import MASTERS  # noqa: E402

# Keep the trigger wording identical across each pair. Only the APR sentence
# differs, so R9 is isolated.
SCRIPTS: dict[str, dict[str, str]] = {
    "northfield_card_v1": {
        "compliant": (
            "Move your balance to Northfield Card and pay zero percent for twelve months. "
            "Representative twenty four point nine percent A P R, variable. "
            "Credit subject to status."
        ),
        "apr_dropped": (
            "Move your balance to Northfield Card and pay zero percent for twelve months. "
            "Apply in minutes. Credit subject to status."
        ),
    },
    "northfield_card_v2": {
        "compliant": (
            "Twelve months of breathing room with Northfield Card. Zero percent for twelve "
            "months. Representative twenty four point nine percent A P R, variable."
        ),
        "apr_dropped": (
            "Twelve months of breathing room with Northfield Card. Zero percent for twelve "
            "months. Apply in minutes."
        ),
    },
    "brightwell_loans_v1": {
        "compliant": (
            "Borrow five thousand pounds from Brightwell Loans and know the cost up front. "
            "Nine point nine percent A P R representative."
        ),
        "apr_dropped": (
            "Borrow five thousand pounds from Brightwell Loans and know the cost up front. "
            "Check your eligibility today."
        ),
    },
    "kestrel_p2p_v1": {
        "compliant": (
            "Lend directly with Kestrel Invest and see where your money goes. "
            "Target six point two percent a year. Capital at risk."
        ),
        "apr_dropped": (
            "Lend directly with Kestrel Invest and see where your money goes. "
            "Target six point two percent a year."
        ),
    },
    "kestrel_ltaf_v1": {
        "compliant": (
            "Long term assets for long term investors, with Kestrel Invest. "
            "Invest from five hundred pounds. Capital at risk."
        ),
        "apr_dropped": (
            "Long term assets for long term investors, with Kestrel Invest. "
            "Invest from five hundred pounds."
        ),
    },
}

RATE = 165  # words per minute; the default gabbles


def synthesise(text: str, out_wav: Path) -> Path:
    import pyttsx3

    engine = pyttsx3.init()
    engine.setProperty("rate", RATE)
    voices = engine.getProperty("voices")
    if voices:
        engine.setProperty("voice", voices[0].id)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    engine.save_to_file(text, str(out_wav))
    engine.runAndWait()
    engine.stop()
    return out_wav


def to_pcm_24k(src: Path, dst: Path) -> Path:
    """24 kHz mono signed 16-bit — exactly what Voice Transcribe accepts (D-006)."""
    run_ffmpeg(["-i", str(src), "-vn", "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return dst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Print the scripts and exit.")
    args = parser.parse_args()

    if args.list:
        for master_id, takes in SCRIPTS.items():
            print(f"\n{master_id}")
            for take, text in takes.items():
                print(f"  [{take}] {text}")
        return 0

    if ffmpeg_path(required=False) is None:
        print("ffmpeg not found — needed to normalise the audio.", file=sys.stderr)
        return 1

    video_masters = {s.id for s in MASTERS if s.kind == "video"}
    missing = video_masters - set(SCRIPTS)
    if missing:
        print(f"no script written for: {sorted(missing)}", file=sys.stderr)
        return 1

    out_dir = settings.masters_dir / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with tempfile.TemporaryDirectory() as tmp:
        for master_id, takes in SCRIPTS.items():
            for take, text in takes.items():
                raw = Path(tmp) / f"{master_id}_{take}_raw.wav"
                synthesise(text, raw)
                if not raw.exists() or raw.stat().st_size < 1024:
                    print(f"  [fail] {master_id}/{take}: TTS produced nothing", file=sys.stderr)
                    continue
                final = out_dir / f"{master_id}_{take}.wav"
                to_pcm_24k(raw, final)
                written.append(final)
                kb = final.stat().st_size / 1024
                print(f"  {final.name}  ({kb:,.0f} KB)")

    manifest = out_dir / "README.md"
    manifest.write_text(
        "# Voiceovers\n\n"
        "**SYNTHETIC SPEECH.** Generated offline with Windows SAPI via pyttsx3 "
        "(`scripts/make_voiceovers.py`), not recorded by a person. Labelled here and in the "
        "master sidecars so a listener knows the voice is generated, the same way they know "
        "the creative is.\n\n"
        "Format: 24 kHz mono signed 16-bit PCM WAV — what Muse Voice Transcribe accepts "
        "(docs/DECISIONS.md D-006; the build plan specified 16 kHz, which was wrong).\n\n"
        "Each master has two takes that differ in ONE respect: `compliant` speaks the trigger "
        "and the representative APR; `apr_dropped` speaks the trigger and omits the APR. "
        "Everything else is identical, so R9 is the only thing separating them.\n\n"
        "R9 cannot be scored from these alone — it needs a transcript, which needs Muse Voice "
        "Transcribe. Until then R9 reports **not evaluated**, never a pass.\n\n"
        + "\n".join(
            f"- `{master_id}_{take}.wav` — {text}"
            for master_id, takes in SCRIPTS.items()
            for take, text in takes.items()
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"\n{len(written)} voiceovers in {out_dir}")
    print("SYNTHETIC SPEECH — labelled in the sidecar README.")
    print("R9 remains NOT EVALUATED until Voice Transcribe can read them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
