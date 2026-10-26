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
way (playbook §16), so a local database buys little.
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
   variants, so the B0 baseline in particular should reuse a cached prefix — materially changes
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

## Frozen artefacts
| Artefact | Hash | Frozen |
|---|---|---|
| VariantBench-UK labels | — | not yet (before the first scored run, Phase 6) |
