# Decisions and verified facts

Design decisions, plus the result of every **[VERIFY]** item from the playbook. Each entry is
dated. Facts carried over from the playbook's 24 Oct 2026 research are marked `unverified` until
a live doc check or a real API call confirms them.

---

## D-001 · Toolchain — Mon 26 Oct 2026
**Measured on the machine:** Windows 11 Pro 10.0.26200, Python 3.11.9, pip 26.2.1,
`venv` + `sqlite3` + `tkinter` present, winget 1.29.380.
`git`, `ffmpeg` and `docker` were absent from PATH and not installed anywhere obvious.

**Decision:** installed Git 2.56.0.3 and ffmpeg 9.0.2 (Gyan full build) via winget. Python 3.11
is kept as the target — it is the sweet spot for `opencv-python`, `scikit-image` and
`rapidocr-onnxruntime` wheels on Windows, so `requires-python = ">=3.11"`.

## D-002 · Dependency split — Mon 26 Oct 2026
Core install stays small enough to deploy on Streamlit Community Cloud. `neo4j`, `reportlab`,
`rapidocr-onnxruntime`, `pyvis` and `streamlit-image-comparison` are optional extras
(`asapproved[graph,pdf,ocr,viz]`), so the hosted demo can run without them if a wheel misbehaves.
`numpy` is pinned `<2.2` because OpenCV and scikit-image wheels lag the newest numpy ABI.

## D-003 · Demo mode is offline by default — Mon 26 Oct 2026
`ASAPPROVED_MODE=demo` makes a model-cache miss an **error**, not a network call. This is what
makes the §13 quality gate ("runs the hero case from a clean clone using cache only, no keys")
mechanically true rather than aspirational, and it protects the live demo from latency and credit
exhaustion.

## D-004 · Neo4j: Aura Free over Docker — Mon 26 Oct 2026 (provisional)
Docker is not installed. Docker Desktop needs admin rights, WSL2 and a reboot; Neo4j Aura Free
needs a browser and two minutes. The hosted demo has to render a precomputed graph JSON either
way (design note), so a local database buys little.
**Leaning Aura Free.** Confirm at USER INPUT 6.1. Revisit if Aura's free-tier limits bite.

## D-005 · Rulebook scaffolded as draft — Mon 26 Oct 2026
`asapproved/rules/rulebook_uk_v1.yaml` carries all 13 rules (R1–R12 + B1) with IDs, citations,
paraphrases, inputs, logic names, thresholds and severities, marked `status: draft` with
`sources_checked: null`. Logic is wired in Phase 5. **No scored run may happen until
`sources_checked` is set** — see the open VERIFY list below.

Two thresholds are engineering choices, not regulatory figures, and are labelled as such in the
UI and README:
- **R6 contrast 4.5:1** — WCAG AA for normal text, used as a proxy for "legible". The FCA
  prescribes prominence and legibility, not a ratio.
- **R1 tau = 2%** of mask area for "materially changed".

## D-006 · Model API facts verified against live docs — Mon 26 Oct 2026
Checked `dev.meta.ai/docs/models`, `/docs/pricing-rate-limits`, `/docs/sam/segmenting` and
`/docs/speech-to-text`. **No API key was needed for any of this.** Most of the playbook's 24 Oct
research holds; four things differ and change the build.

**Confirmed as written in the playbook:**
- Base URL `https://api.meta.ai/v1`, OpenAI-compatible SDKs. Model ids `muse-spark-1.3`,
  `sam-3.1`, `muse-voice-transcribe-1.0` all current.
- Spark 1.3: 1,048,576-token context; text/image/video/PDF; structured output; tool calling;
  reasoning effort minimal→max. Pricing exactly $1.25 in / $4.25 out per M tokens (Standard).
- SAM 3.1: one noun phrase per request (no comma lists, no OR, no negation, no spatial phrases);
  video tracks ≤16 objects per frame across ≤15,000 frames (~10 min); $2.50 / 1,000 images and
  $0.20 / 1,000 video frames with a 50-frame minimum per request.
- Voice Transcribe: 32 MB / 10 min caps, diarization, **turn-level timestamps only** — no
  word-level and no confidence scores. $0.18 per hour.
- Contributor tier is ~12x cheaper ($0.10/$0.20) because Meta trains on your content.
  **Standard tier stands** (§17).

**Deviations — four, all acted on:**

1. **An official Python SAM parser exists: `meta-sam-parser`.** The playbook assumed the parser
   was TypeScript-only (`@meta-sam/parser`) and budgeted Phase 1 time to hand-write a Python
   decoder. The docs name a Python package and a `decodeMaskToRaster` function.
   → Try `pip install meta-sam-parser` first. Keep our own decoder as the fallback and keep its
   unit test either way (if the package is thin or unmaintained, we own the decode path).

2. **Masks are RLE, not base85.** Two encodings selected via `metadata.mask_encoding`:
   `lossless` (default, marker `~`) and `one_bit` (marker `!`, several times smaller). The `x`/`y`
   fields are an offset into the bounding box, not image origin. Box/point prompts always return
   `one_bit` regardless of the setting. The response is a token string, not JSON:
   `<0f>0<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|><|mask;x=0;y=0;data=122,376,~...|>` — one line
   per frame for video, and SAM wants `"stream": true`.
   → `models/sam.py` parses this token grammar. `decode_mask()`'s signature was wrong; it needs
   the box offset, not just width/height.

3. **Voice Transcribe is not on the OpenAI-compatible surface.** It has its own endpoints:
   `POST https://api.meta.ai/v1/asr/transcribe` (file, Bearer auth) and
   `wss://api.meta.ai/v1/asr/realtime` (streaming). Audio must be raw PCM, signed 16-bit
   little-endian, mono, in a RIFF/WAVE container.
   → **24 kHz is preferred, not 16 kHz**: `PCM_24KHZ` is the documented preference and 16 kHz gets
   resampled server-side. `to_wav_16k_mono()` is misnamed — ffmpeg target is
   `-ar 24000 -ac 1 -c:a pcm_s16le`.

4. **Prompt caching is cheap: $0.15 per M cached input tokens, vs $1.25 uncached.** Not mentioned
   in the playbook. The rulebook text and the system prompt are identical across all 48 benchmark
   variants, so the Muse Spark baseline in particular should reuse a cached prefix — materially changes
   the cost-per-variant figure we publish.

Also noted: rate limits are **per team, shared across every key** — Spark 3,000 RPM / 4M TPM,
SAM 3,000 RPM. Not a constraint for a solo build. `muse-spark-1.2` is documented as having
*better* audio support than 1.3, corroborating the playbook's "use Voice Transcribe for audio".

## D-007 · FCA prescribed warning text: four variants, not one — Mon 26 Oct 2026
Checked `handbook.fca.org.uk/handbook/COBS/4/12A.html`. Two corrections to the playbook, both
structural rather than cosmetic.

**1. The prescribed wording lives in COBS 4.12A.11R and there are FOUR variants, by investment
type.** The playbook (§6, R11) implies a single "prescribed text". Verbatim:

- *Non-readily realisable securities:* "Don't invest unless you're prepared to lose all the money
  you invest. This is a high-risk investment and you are unlikely to be protected if something
  goes wrong."
- *P2P agreements / portfolios:* "Don't invest unless you're prepared to lose money. This is a
  high-risk investment. You may not be able to access your money easily and are unlikely to be
  protected if something goes wrong."
- *Long-term asset fund units:* "This is a high-risk investment, and assets may take a long time
  to buy and sell. Only invest if you can wait (possibly several years) to get your money back.
  You do not have protection against poor performance."
- *Cryptoassets:* "Don't invest unless you're prepared to lose all the money you invest. This is
  a high-risk investment and you should not expect to be protected if something goes wrong."

Note how close the cryptoasset and NRRS variants are — they diverge only at
"**you should not expect to be protected**" vs "**you are unlikely to be protected**". A single
prescribed string would therefore make R11 fire on a *correct* crypto warning, or miss a
genuinely altered one. R11 must select the prescribed text by the asset type recorded on the
master, and the masters must each declare their type.

→ The four texts are now data in `rulebook_uk_v1.yaml` under `prescribed_texts`, and R11 takes
`investment_type` as an input. This is also a neat demonstration of rulebook-as-data for S3.

**2. COBS 4.12A.36R requires more than a border.** Full requirement: prominent "taking into
account the content, size and orientation", and "clearly legible, contained within its own border
and with **bold and underlined** text". The playbook's R5 only checks for a border.
→ R5 now carries three sub-checks (border, bold, underlined). Bold and underline detection from
pixels is harder than border detection; if detection proves unreliable in Phase 5 they get
reported as `inconclusive` rather than guessed, and that is stated in the UI. We never assert a
finding we cannot measure.

## D-008 · BLOCKER: Model API key needs a payment method; the $150 credit is absent — Mon 26 Oct 2026
Signed in to dev.meta.ai (personal account, already authenticated) and worked through to
`/api-keys`. Observed:

- **No API keys exist** on the account.
- **"Create API key" is hard-disabled** — `aria-disabled="true"`, opacity 0.5, confirmed in the
  DOM, not just visually greyed.
- Persistent banner: *"No payment method on file. Add one to make API requests."*
- Billing → **Pay as you go**: *"No payment methods added. Add a payment method to start building
  with Model API."* and *"Your credit card information also helps us confirm your age."*
- Billing → **Payment activity**: *"No transactions yet."*
- **There is no credits section on the billing page at all, and no sign of the $150 hackathon
  credit.** Team id is on the account; the credit is simply not applied to it.

**So the playbook's Phase 1 assumption is wrong in two ways:** the key is not free to create (it
is gated on a card), and the credit is not "probably already there, just confirm it".

**Not actioned, deliberately.** Adding a payment method means entering card details, which is out
of scope for automation and is Siddhartha's financial decision. Without the credit this is real
spend on a personal card, not hackathon credit — so the decision should be made knowingly, after
the credit is chased.

**Impact on the plan: smaller than it looks.** The critical path does not need a key yet:
- Phase 2 (deterministic core: align, diff, OCR, measure, overlays, manifests, hash chain) needs
  **no key at all** and is ~5 h of the budget.
- Phase 3 (synthetic masters and variants) needs **no key**.
- V1–V3 were verified from public docs with no key (D-006), and V9 from the FCA handbook (D-007).
- The first hard dependency is Phase 4 (SAM/Spark/Transcribe in the pipeline, Thu 29 Oct).

→ **Re-ordering: start Phase 2 now rather than idling on Phase 1.** The model spike
(`scripts/spike_models.py`) runs the moment a key exists. Deadline for the key is Thu 29 Oct, not
today. If no credit materialises, estimated real cost is still small — the §7 estimate is under
$0.10 per variant and the benchmark is 48 variants — but that estimate is unverified and should
be measured on the first real calls before committing to a card.

**Chase the credit first:** hackathon Discord / the Cerebral Valley organisers. The credit is
presumably issued against a registered participant account, so it may need the registration email
to match, or may simply not have been distributed yet on day 1.

### D-008a · Model API access: how it actually works — Mon 26 Oct 2026
The organisers' guidance (paraphrased, not reproduced) settles both halves of D-008:

- The hackathon credit is **claimed through an application form**; it is not applied
  automatically to an accepted participant's account. That is why billing showed nothing — not a
  fault, and not something the Discord would have resolved.
- **A payment method on the account is required by design** before any API call. The disabled
  "Create API key" button is documented behaviour, not a bug. My Phase 1 reading — that the card
  requirement was an obstacle worth questioning — was wrong.
- **Credits are distributed in batches**, so there is a lag between applying and the credit
  appearing. That lag, not the card, is the scheduling risk.
- The Billing page offers a **spend-limit notification**. Read the wording: it is an *alert*, not
  a cap. Treating it as a hard ceiling would be exactly the assumed-safety this project exists to
  argue against.
- Until the credit is applied, calls bill the payment method directly. So the operating rule
  below is about sequencing, not thrift.
- Each participant claims their own credit; it cannot be delegated. The form was submitted on
  26 Oct.

**Plan impact.** The card is expected rather than optional, so the question is *when*, not
*whether*, and the batch lag makes "early" the answer. Phase 4 (SAM, Spark, Voice Transcribe)
remains the first hard dependency. Phases 2, 3 and 5 were all completed without a key.

**Operating rule until the credit is visible:** make no live model calls.
`ASAPPROVED_MODE=demo` enforces this in code — a cache miss raises rather than reaching the
network (D-003) — so the safe posture is the default and going live is a deliberate act.

## D-009 · Phase 3: seven defects the dataset found in itself — Mon 26 Oct 2026
Building the masters and variants surfaced seven defects, each of which would have
corrupted the benchmark silently rather than loudly. Recorded because the *way* they were
caught is the design point: the generator checks itself against the Phase 2 measurement
primitives, so a label that the pixels do not support is an error, not a quiet wrong answer.

**1. The "compliant" masters were not compliant (R12).** The warning box sat at 78% of frame
height. Reels reserves the bottom 35%, and 40% once the creative carries a disclaimer — which a
prescribed risk warning is. Every Reels master therefore breached the rule it was supposed to be
the clean baseline for. Fixed by deriving the warning's position from the placement's safe band
rather than a constant; pinned by `test_warning_sits_outside_the_placement_overlay_zone`.

**2. The APR ran 458px off a 720px frame on 9:16 masters.** Font size scaled with frame height,
so the 1:1 masters hid it. That is precisely the clipping R3 exists to detect, in our own
baseline. Trigger and APR are now fitted *together* to the content width — fitted separately, the
longer of the two would shrink on its own and the pair would stop being equally prominent, which
is the CONC 3.5.7R breach itself.

**3. Bottom-aligning the warning dropped it on top of the APR.** Region boxes are ground truth;
two regions claiming the same pixels would corrupt both R8's prominence comparison and SAM's IoU
score. The layout now measures the whole stack and shrinks until it fits, dropping body copy
before it ever shrinks the warning. Caught by a new overlap test, which the earlier
"regions stay in frame" test could not see.

**4. Two rules had no coverage at all.** Transform-to-master assignment rotated by index, which
never reached `warning_reworded` (investment masters only) or `apr_animates_offscreen` (videos
only). The benchmark would have published **empty rows for R11 and R4** and an F1 averaged over
the rest. Replaced with a most-constrained-first allocation that guarantees every transform is
used; asserted by `test_seeded_violations_span_the_rulebook`.

Also removed: a "fake a 25% overlay zone for Feed" fallback in the R12 transform, which would
have manufactured a violation that does not exist and then scored the detector for missing it.
Feed is excluded by eligibility instead.

**5. Coverage was lopsided even once it existed.** The fix for defect 4 guaranteed every rule had
*at least* one variant and then stopped: the first full build produced R1 on 10 variants and R3
on 11, against exactly one each for R4, R9, R10, R11 and R12. A per-rule precision/recall
computed over a single variant can only read 0% or 100% — five of eleven rows in the §10 table
would have been noise presented as measurement. Remaining slots are now filled by whichever rule
is currently least covered, so the multi-rule geometry transforms (all R1+R3) stop being picked
once those rules are well served. Guarded by `test_no_rule_is_covered_by_only_one_variant`.

**6. The hero case did not match its own demo line.** The video script (§14) says the APR is "on
screen 1.2 seconds of 15". The first build measured **4.0 s of 15** — the pan was slow enough
that the APR stayed partly visible for 101 frames. The timing now derives from the clip's fps and
the pan distance from where the APR actually sits, so the measured figure lands near the intended
1.2 s. Worth being explicit about the direction of travel: the *data* was tuned to tell the story,
and the number quoted on screen remains the measured one. Tuning synthetic data is legitimate;
quoting an intended number instead of a measured one would not be.

**7. Odd frame dimensions broke H.264 encoding.** `margin_trim` produced 691x1241 and libx264
with yuv420p rejects odd width or height. The fix matters beyond "make it even": frames and their
region masks are evened in the *same* place, because trimming the video by a row while leaving
the mask untrimmed would shift every ground-truth box by a pixel relative to the pixels it
describes. `write_video` now refuses odd input with a message that says so, rather than letting
a future transform reintroduce the desync quietly.

**Ground truth is computed, not declared.** Region boxes and per-frame visibility come from
pushing each region's mask through the very transform that made the variant. Where a transform
*also* declares its expected visibility, the two are cross-checked and a mismatch aborts the
build — that is how defect 4's sibling (a zoom that did not actually remove the warning) was
caught on the first run.

**Known gap: R9 and the audio transforms are labelled but not yet realised.**
`voiceover_drops_apr` and `music_swap` carry `requires_audio: true`. `scripts/make_voiceovers.py`
does now generate 10 synthetic voiceovers into `data/masters/audio/` — but **nothing muxes them
into the masters or the variants**, so `ffprobe` finds a single H.264 stream and no audio on all
three audio-dependent assets. Corrected 27 Oct 2026: an earlier version of this note said "no
audio exists yet", which stopped being true the moment the voiceover script ran and was never
updated. The audio exists; the assets do not carry it.

Muxing is deliberately deferred rather than forgotten. It would change every affected asset's
bytes and therefore the label digest, invalidating the published numbers and the clean-clone
reproducibility result — and R9 would still read *not evaluated*, because scoring it needs a
transcriber and no Model API key exists. Both halves land together in Phase 4: mux the audio,
then transcribe. Until then those variants are reported as **not evaluated**, never as passes.

**R2 has no pixel expression and deliberately has no variant.** Settings drift is manifest vs
live API. Pinned by test so nobody later invents a pixel proxy for it.

**Render resolution is 720x1280 / 720x720, not 1080p.** Every measurement is normalised by frame
height (basis points, HD-line equivalents), so resolution does not affect any reported figure —
and the whole 60-asset set stays small enough to regenerate end to end in about 13 minutes
(masters 2m26, variants 10m31, measured 27 Oct 2026). Corrected 27 Oct: this note said "about two
minutes", which was the masters-only figure and understated the full rebuild by six times.

---

## Open [VERIFY] items

| # | Item | Needed by | Status |
|---|---|---|---|
| V1 | Muse Spark 1.3: model id, base URL, JSON-Schema structured output, reasoning-effort values, pricing | Phase 1 | **verified** 26 Oct · D-006 |
| V2 | SAM 3.1: model id, Responses API shape, one-noun-phrase constraint, 16-object / 15,000-frame limits, mask format, pricing | Phase 1 | **verified** 26 Oct · D-006 (mask format differs: RLE, not base85) |
| V3 | Muse Voice Transcribe: model id, 10 min / 32 MB limits, turn-level-only timestamps, pricing | Phase 1 | **verified** 26 Oct · D-006 (own endpoint; 24 kHz preferred) |
| V13 | Does `meta-sam-parser` exist on PyPI and decode `lossless` + `one_bit` masks usably? | Phase 1 | open · D-006 item 1 |
| V4 | $150 hackathon Model API credit present on the account; Standard tier selected | Phase 1 | unconfirmed |
| V5 | Marketing API: exact `creative_features_spec` feature keys and current Graph API version | Phase 1 | unverified |
| V6 | Whether ad previews render AI creative enhancements — **this decides Path A/B/C** | Tue 27 Oct 23:00 IST | unverified |
| V7 | Whether creative specs are mutable post-creation, i.e. can Act set OPT_OUT in place | Phase 1 | unverified |
| V8 | Whether a development-mode app can act on ad accounts the developer owns | Phase 1 | unverified |
| V9 | Exact prescribed COBS 4.12A high-risk investment warning wording (needed verbatim for R11 and for the crypto/investment masters) | Phase 3 | **verified** 26 Oct · D-007 (it is 4.12A.**11R**, and there are four variants) |
| V10 | CONC 3.5.5R is the right citation for "cost-of-credit figure without a representative example" (R10) | Phase 5 | unverified |
| V14 | Can bold and underline be detected reliably enough from pixels for R5, or must those sub-checks report `inconclusive`? | Phase 5 | open · D-007 item 2 |
| V11 | Meta's current published safe-zone percentages for Feed / Stories / Reels (C9, R12) | Phase 7 | unverified |
| V12 | Official hackathon rules: submission fields, video length limit, repo/licence rules, judging criteria, prior-work and track rules | after 22:30 IST kickoff tonight | pending |

<!-- publish_numbers:decisions start — generated, do not edit by hand -->

## VariantBench-UK coverage (48 variants)

Ground truth is DERIVED — every rule a variant actually breaks, computed from
what the generator drew. The transform's own declaration is kept as
`intended_rules` so the difference is visible.

| | R1 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | R10 | R11 | R12 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **derived** (ground truth) | 22 | 5 | 4 | 3 | 3 | 2 | 2 | 2 | 2 | 2 | 5 |
| **intended** (by design) | 3 | 5 | 3 | 3 | 3 | 2 | 2 | 2 | 2 | 2 | 2 |

The gap on R1 is not an error: any seeded edit to a claim region materially
changes it, so R1 is true by construction on 22 of 24 violations while only 3
were designed to test it. That is why the per-rule table, not the
variant-level score, is the honest measure — and why the README leads with it.

3 variants are audio-dependent and carry no audio track, so they are reported
as **not evaluated**, never as passes, and their rules appear in the
not-evaluated column rather than vanishing from the table.

Label digest for this build:
`d18da5ad90127363ec9436bc0cd5b514cc6ab0ef1fc4ca5df4e30c5b4242a369`.

**The labels are NOT frozen, and that matters.** They and the detector were
both changed during development. Roughly half the apparent "detector failures"
in this project turned out to be defects in the benchmark itself — which is a
good argument for deriving labels and a bad argument for treating these
numbers as a held-out evaluation. The rulebook also remains `status: draft`
with `sources_checked: null`. Published results are development-set results
and the README says so.

**Last measured run.** AsApproved 100%/100%/100% (precision/recall/F1) at
variant level with 0/23 false blocks, against a pixel diff at 95%/95%/95% and
1/23. Per-rule, the weakest are R5 (50% precision), R7 (67% precision). R12 is
the only rule(s) with a false negative.

<!-- publish_numbers:decisions end -->
