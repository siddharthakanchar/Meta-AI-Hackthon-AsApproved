# AsApproved — submission copy

Paste-ready text for the official form. **Numbers marked `[BENCH]` must be
refreshed from `eval/report.md` before submitting** — never typed from memory.

---

## Project name

AsApproved

## Tagline

Turn on Advantage+ without betting your licence.

## Track

Indie Developer · Build for Your World

## Short description (~50 words)

AsApproved measures, frame by frame, whether the risk warning and representative
APR in a regulated firm's approved ad survive Meta's AI edits, then plans the
opt-out for every affected ad in one click with a hash-chained evidence record.
Built to run on SAM 3.1, Muse Spark 1.3 and Muse Voice Transcribe; the measured
results here came from the keyless fallback detector, labelled on every result.

---

## Long description

### The problem

From 20 November 2026, Meta's revised Ad Terms put "any and all risks" from its
AI creative features on the advertiser — including features Meta enables itself.
Advantage+ can generate up to 150 variations from an advertiser's assets, Meta
does not notify advertisers when it modifies creative, and previews are examples
rather than a record of what was served. Nearly 10 million advertisers used at
least one Meta generative-AI creative tool last quarter.

For a UK lender that is a licence problem. FG24/1 says a firm owns a promotion
for its whole life and that a prescribed warning must not be obscured by a
platform design feature. COBS 4.12A requires the warning prominent, legible,
bordered, bold and underlined. CONC 3.5.7R requires the representative APR to be
no less prominent than the trigger that forced it. In 2024 firms amended or
withdrew 19,766 promotions after FCA intervention.

So regulated advertisers switch Advantage+ off. AsApproved exists to let them
switch it on.

### What it does

**What has actually run:** no Meta model. The Model API credit is claimed but
not yet issued, so every number below came from the keyless fallback path —
template matching for regions, OCR for text, a deterministic template for notes.
The SAM 3.1 / Spark / Voice Transcribe integration is written and unit-tested
against the documented response formats and has never touched the live API. Each
screen in the UI shows which path produced its result.

Approve a master and AsApproved signs the approval — hash, approver, timestamp,
rulebook version and the enhancement settings in force. Then it watches what
Meta actually delivers: it aligns each variant back to the master, diffs it,
locates the warning and the APR, and measures them. Seconds on screen. Size
against the ad's own body copy. WCAG contrast. Border. Clipping. Occlusion by
the platform's own caption and CTA chrome.

Twelve FCA-derived rules in a versioned YAML rulebook turn those measurements
into findings, each carrying the measured value, the threshold, the citation and
the evidence frame. On Block, a lineage graph finds every sibling ad sharing the
asset *and* enrolled in the enhancement — fix once, opt out N — then re-checks
and refuses to close until the fix is proven. Every decision lands in a
hash-chained log where altering one byte names the exact record that broke.

### How it works, and what each Meta model does

- **SAM 3.1** masks and video-tracks the risk-warning box, APR and trigger frame
  by frame with stable object IDs. One noun phrase per request, per the docs.
- **Muse Spark 1.3** extracts claims and trigger phrases into a strict JSON
  Schema, and writes the compliance note.
- **Muse Voice Transcribe** answers whether the trigger was spoken and whether
  the APR was — CONC 3.5.7R prominence parity in the audio channel, which no
  pixel check can see.
- **Meta Marketing API** supplies Advantage+ enhancement settings and previews,
  and carries the opt-out write.

The architectural commitment: **rules decide, the model explains.** Every verdict
comes from deterministic code. Spark's prose passes a validator that rejects any
number, rule ID, quotation or citation absent from the evidence, retries once,
then falls back to a deterministic template. A fabricated audit trail is worse
than no audit trail.

### Results

VariantBench-UK: 12 approved masters → 48 variants, 24 seeded violations across
R1 and R3–R12, 24 benign edits. Ground truth is computed, not hand-written —
each region's mask is pushed through the same transform that made the variant,
so a label cannot disagree with its pixels.

`[BENCH]` — paste the table from `eval/report.md`.

The honest headline: a plain pixel diff nearly matches the full pipeline at
answering "did something change?". It scores zero at answering "which rule
broke, by how much, against which threshold" — which is the only thing that can
go in a compliance record. The per-rule table is where the two separate.

### Limits, stated up front

- All creative is synthetic. Three fictional firms, no real brands or people.
- Previews are not served impressions.
- Rule paraphrases are not legal advice, and the citations are not all settled:
  COBS 4.12A.11R and .36R were checked against the live handbook; the FG24/1 and
  CONC references were not. FG24/1 is guidance, not binding rules.
- **Development-set numbers, no held-out split.** Thresholds were fitted on
  these 48 variants.
- **Act has never written to Meta.** It is always a labelled dry run over
  synthetic lineage, and three API prerequisites remain unverified.
- R1 is true by construction on 22 of 24 seeded violations and carries most of
  the variant-level recall; the per-rule table is the honest measure.
- Three thresholds are engineering choices, not regulatory figures: 4.5:1
  contrast (WCAG AA as a legibility proxy), 2%-of-region "materially changed",
  98% visibility.
- Placement safe-zone percentages come from secondary sources, not Meta's own
  spec pages, and every finding that uses them says so.
- A hash chain cannot detect records removed from the end; that needs an
  anchored head.
- Manifest verification proves integrity, not identity, unless a trusted key is
  pinned.
- R9 cannot be scored without voiceover audio; those variants report as *not
  evaluated*, never as passes.

### What's next

Jurisdiction packs (the rulebook is data, so a US FTC or EU AI Act Art. 50 pack
is a YAML file), on-prem mode via Muse Glimmer for firms that cannot send
creative off-premises, and a webhook into existing finprom approval tools rather
than replacing them.

---

## Meta products used

| Product | Role |
|---|---|
| SAM 3.1 | Region masks and stable-ID video tracking of warning, APR and trigger |
| Muse Spark 1.3 | Structured claim extraction (JSON Schema); compliance note generation |
| Muse Voice Transcribe | Spoken-trigger vs spoken-APR parity (R9) |
| Meta Marketing API | Advantage+ enhancement settings, previews, opt-out write |

Standard tier throughout. Muse Image is not used — unavailable in India under
Meta's Geographic Use Policy.

**None of these has run.** The table above is the designed integration. What
produced the results: aligned template matching + normalised cross-correlation
for regions, RapidOCR for text, a deterministic template for compliance notes,
and nothing at all for R9, which reports *not evaluated*.

## Links

- Repository: `https://github.com/siddharthakvss/asapproved` (MIT)
- Hosted demo: `[FILL IN after deploy]`
- Demo video: `[FILL IN]`

## Built with

Python · OpenCV · scikit-image · Streamlit · Neo4j · Ed25519 · RapidOCR ·
SAM 3.1 · Muse Spark 1.3 · Muse Voice Transcribe · Meta Marketing API

---

## Pre-submission checklist

- [ ] `[BENCH]` numbers pasted from `eval/report.md`, matching the README
- [ ] Hosted demo opens in an incognito window
- [ ] Video within the official length limit and publicly viewable
- [ ] Repo public, MIT licence, no secrets (`gitleaks detect`)
- [ ] SIMULATED labelled everywhere; Path A/B/C stated
- [ ] No employer or client names, data or branding anywhere
- [ ] Submitted by Wed 4 Nov 22:00 IST; confirmation saved
