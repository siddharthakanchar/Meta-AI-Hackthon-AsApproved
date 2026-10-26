# AsApproved

**Turn on Advantage+ without betting your licence.**

AsApproved measures, frame by frame, whether the APR and risk warnings in a
regulated firm's approved ad survive Meta's AI edits — then fixes every affected
ad in one click, with a tamper-evident evidence trail a compliance officer can
hand to a regulator.

> Built for the Meta Global AI Developer Hackathon 2026 · Indie track.
> All creative in this repo is **synthetic**: three fictional firms, no real
> brands, no real people.

---

## Why this exists

From **20 November 2026**, Meta's revised Commercial and Self-Serve Ad Terms put
"any and all risks" from its AI creative features on the advertiser — including
features Meta switches on itself. Advantage+ can generate up to 150 variations
from an advertiser's assets, Meta does not alert advertisers when it modifies
creative, and previews are examples rather than a record of what was served.
Nearly 10 million advertisers used at least one Meta generative-AI creative tool
(Meta Q3 2026 earnings call, 21 Oct 2026).

For a UK lender that is a regulatory problem, not an aesthetic one:

- **FG24/1 para 4.14** — a firm stays responsible for a promotion throughout its life.
- **FG24/1 para 1.5** — a prescribed warning must not be "obscured or truncated by a design feature of the social media platform".
- **COBS 4.12A.36R / .38R** — the risk warning must be prominent, clearly legible, in its own bordered box, bold and underlined, with nothing reducing its visibility.
- **CONC 3.5.7R** — the representative APR must be no less prominent than the trigger that required it.
- In 2024, firms amended or withdrew **19,766** promotions after FCA intervention.

So regulated advertisers switch Advantage+ off. **AsApproved exists to let them
switch it on.**

## What it does

1. **Approve** a master — SHA-256, approver, timestamp, rulebook version and the
   enhancement settings in force, signed with Ed25519.
2. **Sense** — read each ad's Advantage+ settings and previews; flag drift
   against the signed manifest.
3. **Measure** — align every variant to its master, diff it, locate the regions
   that matter, and measure the warning and APR: seconds on screen, size, WCAG
   contrast, border, clipping, and occlusion by the platform's own UI overlays.
4. **Decide** — a versioned YAML rulebook of twelve FCA-derived rules produces
   findings, each with the measured value, the threshold, the citation and the
   evidence frames.
5. **Act once, fix many** — a lineage graph finds every sibling ad sharing the
   asset *and* enrolled in the enhancement: *fix once, opt out N*. Then it
   re-checks and refuses to close until the fix is proven.
6. **Prove** — every decision lands in a hash-chained, append-only evidence log.
   Change one byte and verification names the exact record that broke.

## Three ideas that hold it together

**Rules decide; the model explains.** Every verdict comes from deterministic code
over a YAML rulebook. Muse Spark extracts claims into a constrained schema and
writes prose — it never changes an outcome. Before any generated sentence
reaches a human it passes a validator that rejects **any number, rule ID,
quotation or citation not present in the evidence**, retries once, then falls
back to a deterministic template. A fabricated audit trail is worse than no
audit trail.

**"Could not measure" is a third outcome.** Every rule input may be unknown. A
rule with an unknown input returns `inconclusive` — never `pass`, which would
wave through a real breach, and never `fail`, which would accuse an advertiser
on a guess. There is a test asserting an empty context produces **zero**
failures across all twelve rules.

**The baseline must be clean.** The approved masters are generated to satisfy the
rulebook and tested against it. Writing that test caught three real breaches in
our own "compliant" masters — including every Reels master sitting inside the
caption zone it was meant to be the clean comparison for.

## Built on Meta AI

| Model | Job |
|---|---|
| **SAM 3.1** | Masks and video-tracks the risk-warning box, APR, trigger and logo, frame by frame with stable IDs |
| **Muse Spark 1.3** | Structured claim and trigger extraction (strict JSON Schema); writes the compliance note |
| **Muse Voice Transcribe** | Was the trigger spoken? Was the APR spoken? — CONC 3.5.7R parity in the audio channel |
| **Meta Marketing API** | Advantage+ enhancement settings, ad previews, and the opt-out write |

Standard tier only. Muse Image is not used — unavailable in India under Meta's
Geographic Use Policy.

**Running without a key.** Each model has a declared fallback, and the UI shows
which was used on every result:

- SAM 3.1 → aligned template + normalised cross-correlation (a real detector, not a mock)
- Muse Spark → OCR for text, deterministic template for the note
- Voice Transcribe → **no fallback exists**, so R9 reports `inconclusive` and those variants are reported as *not evaluated*, never as passes
- Marketing API → R2 `inconclusive`; Act runs as a labelled dry run

## Quick start

```bash
git clone https://github.com/siddharthakvss/asapproved.git
cd asapproved
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -e ".[dev,ocr,graph,pdf,viz]"

# build the synthetic dataset and cache every check (~20 min, no API key)
python scripts/make_masters.py
python scripts/make_variants.py
python scripts/precompute.py

asapproved demo                      # hero case from cache, no network
streamlit run app/streamlit_app.py
```

`ffmpeg` must be on PATH for anything involving video
(`winget install Gyan.FFmpeg`).

No API keys are needed. `ASAPPROVED_MODE=demo` is the default and makes a model
cache miss **raise** rather than reach the network, so the demo cannot silently
depend on a live call.

```bash
pytest                               # the full suite
ruff check .
asapproved doctor                    # config + tooling, secrets masked
asapproved check data/variants/<file> # one variant, end to end
asapproved bench                     # VariantBench-UK → eval/report.md
```

## Results

VariantBench-UK: 12 approved masters → 48 variants (24 seeded violations across
R1 and R3–R12, 24 benign edits). Ground truth is **computed, not hand-written** —
each region's mask is pushed through the same transform that made the variant,
so a label cannot disagree with its pixels.

Measured numbers live in [`eval/report.md`](eval/report.md), regenerated by
`asapproved bench`. They are published as measured, including where a baseline
beats the full pipeline.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full flow.

## Honesty notes

These stay here permanently.

- **Simulated data is labelled SIMULATED** — in the UI, in the dataset sidecars and here.
- **Previews are not served impressions.** A preview is an example of what Meta
  may render, not a record of what a user saw.
- **Rule paraphrases are not legal advice.** AsApproved flags items for
  compliance review and cites the source; a qualified person decides.
- **Three thresholds are engineering choices, not regulatory figures**: the 4.5:1
  contrast ratio (WCAG AA as a legibility proxy), the 2%-of-region "materially
  changed" threshold, and the 98% visibility ratio. All three are in the
  rulebook YAML and labelled in the UI.
- **The placement safe-zone percentages are unverified.** They come from
  secondary 2026 spec round-ups, not Meta's own published guidance, and every
  R12 finding carries that caveat until it is confirmed.
- **The Clearcast hold-time check (B1) is a UK TV clearance convention**, not the
  legal test for online promotions. It never blocks.
- **R11 compares OCR text with a calibrated similarity band, not exact
  equality.** OCR reads our own masters as `Representativeexample:f1,200` at 0.97
  confidence — spaces dropped, £ read as f — so exact comparison would accuse
  correct advertisers. The bands were set by measuring both populations; the
  middle band reports `inconclusive`.
- **A hash chain cannot detect records removed from the end.** That needs an
  anchored head, which a real deployment would ship off-box daily.
- **Manifest verification proves integrity, not identity**, unless a trusted
  public key is pinned. The UI says which.
- The rulebook is marked **draft** until every citation is re-checked against the
  live FCA handbook.

AsApproved is not affiliated with or endorsed by Meta or the FCA. Northfield
Card, Brightwell Loans and Kestrel Invest are fictional.

## Licence

MIT — see [LICENSE](LICENSE).
