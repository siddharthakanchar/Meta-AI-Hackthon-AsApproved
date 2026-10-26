# AsApproved

**Turn on Advantage+ without betting your licence.**

AsApproved measures, frame by frame, whether the APR and risk warnings in a regulated firm's
approved ad survive Meta's AI edits, and lets a compliance officer fix every affected ad in one
click, with evidence a regulator would accept.

> 🚧 **Phase 0 of 8.** The scaffold is up and the app launches; the pipeline is being built
> through 4 Nov 2026. This README gets the demo GIF, the architecture diagram and the measured
> benchmark numbers as they land. Nothing is claimed here that hasn't been measured.

---

## Why

From **20 November 2026**, Meta's revised Commercial and Self-Serve Ad Terms place "any and all
risks" from its AI creative features on the advertiser — including features Meta enables itself.
Advantage+ creative enhancements can generate up to 150 variations from an advertiser's assets,
Meta does not alert advertisers when it modifies creative, and previews are examples rather than
every variant served. Nearly 10 million advertisers used at least one Meta generative-AI creative
tool (Meta Q3 2026 earnings call, 21 Oct 2026).

For a UK lender that is a regulatory problem, not an aesthetic one. The FCA's FG24/1 says a firm
remains responsible for a promotion throughout its life (para 4.14) and that a prescribed warning
must not be "obscured or truncated by a design feature of the social media platform" (para 1.5).
COBS 4.12A.36R/.38R require the risk warning to be prominent, legible, in its own bordered box,
with nothing reducing its visibility. CONC 3.5.7R requires the representative APR to be no less
prominent than the trigger that forced it. In 2024, firms amended or withdrew **19,766**
promotions after FCA intervention.

So regulated advertisers switch Advantage+ off. **AsApproved exists to let them switch it on.**

## What it does

1. **Approve** a master. AsApproved stores its SHA-256, the approver, the timestamp, the rulebook
   version and the enhancement settings at approval, signed with an Ed25519 key.
2. **Sense.** Reads each ad's Advantage+ enhancement settings and previews, and flags drift
   against the signed manifest.
3. **Measure.** Aligns every variant to its master, diffs it, segments the regions that matter,
   and measures the warning and the APR: seconds on screen, size, contrast, border, clipping,
   and occlusion by the platform's own UI overlays in Feed / Stories / Reels.
4. **Decide.** A versioned YAML rulebook of 12 FCA-derived rules produces findings, each with the
   measured value, the threshold, the citation and the evidence frames. **Rules decide; the model
   only explains** — and a validator rejects any number, quote or rule ID in the explanation that
   isn't in the evidence.
5. **Act once, fix many.** A lineage graph finds every sibling ad sharing the asset and the
   enhancement: *fix once, opt out N.* Then it re-checks and proves the fix landed.
6. **Prove.** Every decision lands in a hash-chained, append-only evidence log, exportable, with
   retention framed against COBS 4.11.1R. Change one byte and verification fails.

## Built on Meta AI

| Model | Job |
|---|---|
| **SAM 3.1** | Masks and video-tracks the risk-warning box, APR text, price, headline, logo — frame by frame, with stable object IDs |
| **Muse Spark 1.3** | Structured claim and trigger extraction (strict JSON Schema); writes the compliance note; drives the read-only reviewer agent |
| **Muse Voice Transcribe** | Was the trigger spoken? Was the APR spoken? (CONC 3.5.7R parity in the audio channel) |
| **Meta Marketing API** | Advantage+ enhancement settings, ad previews, and the opt-out write for remediation |

Standard tier only. Muse Image is not used — it is unavailable in India under Meta's Geographic
Use Policy.

## Quick start

```bash
git clone https://github.com/siddharthakvss/asapproved.git
cd asapproved
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -e ".[dev]"

asapproved doctor                   # config + tool check, secrets masked
streamlit run app/streamlit_app.py
```

`ffmpeg` must be on PATH for anything involving video.

No API keys are needed to run the demo: `ASAPPROVED_MODE=demo` replays every model call from the
on-disk cache and treats a cache miss as an error rather than a network call. For live runs, copy
`.env.example` to `.env` and fill it in.

```bash
pytest            # tests
ruff check .      # lint
```

## Honesty notes

These stay in the README permanently.

- **Simulated data is labelled SIMULATED** — in the UI, in the dataset and here. Variants not
  fetched from Meta are generated locally by seeded transforms.
- **Previews are not served impressions.** A preview is an example of what Meta may render, not a
  record of what a given user saw.
- **Rule paraphrases are not legal advice.** AsApproved flags items for compliance review and
  cites the source; a qualified person decides.
- **Two thresholds are engineering choices, not regulatory figures:** the 4.5:1 contrast ratio
  (WCAG AA, used as a legibility proxy) and the 2%-of-mask-area "materially changed" threshold.
  Both are configurable and both are labelled in the UI.
- **The Clearcast hold-time check (B1) is a UK TV clearance convention**, not the legal test for
  online promotions. It is shown as a benchmark only.
- **Which data path the demo uses (A, B or C per the build plan) is stated on screen** once the
  Marketing API spike settles it.
- Benchmark numbers are published exactly as measured, including where a baseline beats the full
  pipeline.

AsApproved is not affiliated with or endorsed by Meta or the FCA. The brands in the dataset
(Northfield Card, Brightwell Loans, Kestrel Invest) are fictional.

## Licence

MIT — see [LICENSE](LICENSE).
