# STATUS

Path: **undecided** (A/B/C decided after the Phase 1 Marketing API spike, due Tue 27 Oct 23:00 IST)
Hours: used 7.5 / planned 40–45
Updated: Mon 26 Oct 2026

## Phases
- [~] Phase 0 — Setup and rules (Mon 26 Oct, ~2 h) · repo scaffolded; awaiting USER INPUT 0.2
- [~] Phase 1 — Spikes and go/no-go (Mon 26 – Tue 27 Oct, ~4 h) · **model spike blocked on the
      key (D-008)**; V1–V3 already verified from public docs, so what remains is the key itself,
      V13, and the Marketing API spike (USER INPUT 1.2, unaffected by the key blocker)
- [x] Phase 2 — Deterministic core (**pulled forward**, needed no key) · 83 tests green, ruff clean
- [x] Phase 3 — Synthetic masters and variants (**pulled forward**, needed no key) · 12 masters,
      48 variants, ground truth generated not hand-written; audio pending USER INPUT 3.1
- [ ] Phase 4 — Meta models in the pipeline (Thu 29 – Fri 30 Oct, ~5 h)
- [ ] Phase 5 — Rules, explanations, review UI (Sat 31 Oct, ~9–10 h)
- [ ] Phase 6 — Graph, Act/Prove, precedents, benchmark (Sun 1 Nov, ~9–10 h)
- [ ] Phase 7 — Polish, hosting, stretch (Mon 2 – Tue 3 Nov, ~5 h)
- [ ] Phase 8 — Demo video and submission (Tue 3 – Wed 4 Nov, ~4 h)

## Today — Mon 26 Oct

**Done**
- Read the playbook; confirmed today is Phase 0 day and kickoff is tonight 22:30 IST.
- Probed the machine: Python 3.11.9, pip 26.2.1, venv + sqlite3 present, winget working.
  `git`, `ffmpeg` and `docker` were all absent; installed Git 2.56.0.3 and ffmpeg 9.0.2 via winget.
- Scaffolded the repo to playbook §5.3: package tree, CLI skeleton with a working `doctor`,
  launchable Streamlit shell, draft rulebook YAML (R1–R12 + B1), `.gitignore`/`.env.example`
  secret hygiene, MIT licence, pre-commit (ruff + gitleaks + detect-private-key), Phase 0 tests.
- Pulled V1/V2/V3 forward out of Phase 1 — the Meta model docs need no API key. Verified Spark,
  SAM and Voice Transcribe against the live docs and **found four deviations** from the
  playbook's 24 Oct research (DECISIONS.md D-006), all corrected in the stubs before any code
  was written on top of them:
  1. an official Python SAM parser exists (`meta-sam-parser`) — the playbook budgeted time to
     hand-write one;
  2. SAM masks are RLE (`lossless` / `one_bit`), not base85, and come back as a token string
     with the mask offset relative to the bounding box;
  3. Voice Transcribe has its own `/v1/asr/transcribe` endpoint, not the OpenAI-compatible one,
     and prefers **24 kHz** PCM, not 16 kHz;
  4. cached input is $0.15/M vs $1.25/M — the rulebook prefix is identical across all 48
     benchmark variants, so this materially changes the cost-per-variant we publish.

**Phase 2 delivered** (commit `bd70e0e`)
- `canonical.py` — canonical bytes for everything signed or chained; floats rejected outright.
- `manifest.py` (C1) — Ed25519 approval manifests. `verify-manifest` can pin a trusted signer and
  states plainly when it is proving integrity but not identity.
- `evidence.py` (C12) — hash chain whose digest covers `index` and `prev`, so reordering and
  deletion fail too, not just edits. Known limit pinned by test: truncation from the end is
  undetectable from the chain alone and needs an anchored head.
- `vision/align.py` (C3) — ORB + RANSAC homography across all five geometry cases, with a
  labelled scale-only fallback; `Alignment.ok` gates whether R1/R3 may fire at all.
- `vision/diff.py` (C3) — SSIM over the aligned pair, change intersected with the claim region.
- `vision/overlays.py` (C9) — placement safe zones as data; figures unverified (V11) and every
  finding carries the caveat.
- `measure.py` (C5) — WCAG contrast, size, border, clipping, occlusion, per-frame visibility.
  Integers in fixed units only; anything unmeasurable returns `None` and surfaces as
  `inconclusive` rather than as a pass or a fail.
- CLI wired and demonstrated end to end: `keygen → approve → verify-manifest`, plus both tamper
  demos (altered manifest → `INVALID`; flipped decision → `TAMPERED record 1 … line 2`).
- Found while testing: a Windows BOM made a re-saved manifest read as "unreadable", which in a
  compliance tool reads as a tamper alarm. Readers now accept a BOM so only changed content
  fails. Regression test added.

**Phase 3 delivered**
- 3 fictional firms (Northfield Card, Brightwell Loans, Kestrel Invest), original geometric
  logos, no real brands or people. **12 masters**: 5 credit stills, 3 credit videos, 2 high-risk
  stills, 2 investment videos — between them exercising all four COBS 4.12A.11R prescribed
  warnings, not just the crypto one.
- **48 variants**, 24 seeded violations / 24 benign, spanning R1 and R3–R12.
- Masters are **compliant by construction and tested for it**: warning outside the placement's UI
  zone, own border, bold, underlined, contrast ≥ 4.5:1, APR no less prominent than its trigger,
  no two regions overlapping.
- `text_norm.py` — R11 folds typographic variants (curly vs straight apostrophes, dashes, NBSP)
  but never wording. Pinned both ways, including that the crypto and NRRS texts stay distinct.
- Four self-inflicted bugs caught by the generator's own checks before they reached the
  benchmark — see DECISIONS.md **D-009**. The worst: two rules (R11, R4) had **no coverage at
  all**, so the per-rule table would have shipped with empty rows.

**Next**
- USER INPUT 3.1: voiceovers (needed to score R9) and a 2-minute look at three rendered masters.
- USER INPUT 0.1: confirm environment answers (Docker decision, GitHub username).
- USER INPUT 0.2: after the 22:30 IST kickoff, pull the Official Rules into `RULES_SUMMARY.md`.
- Phase 1: Meta Model API key -> `scripts/spike_models.py`; then the Marketing API assets.
- Phase 1 is now cheaper than planned: V1–V3 are done, so the spike only has to confirm the
  key works, settle V13 (`meta-sam-parser`), and measure real latency and cost.

**Risks**
- **Model API key is blocked (D-008).** `Create API key` is hard-disabled until a payment method
  is on file, and the $150 hackathon credit is **not** on the account — billing shows no credits
  section and no transactions. Not actioned: card entry is Siddhartha's call, and without the
  credit it is real personal spend. Chase the credit on the hackathon Discord.
  Mitigation: **Phases 2 and 3 need no key**, so the build order flips — deterministic core
  first, model spike when a key exists. Real deadline for the key is **Thu 29 Oct** (Phase 4),
  not today.
- Docker is not installed. Installing Docker Desktop needs admin + WSL2 + a reboot; Neo4j Aura
  Free is the lower-friction path and the hosted demo needs a precomputed graph JSON regardless
  (§16). Leaning Aura — see `DECISIONS.md` D-004, confirm at USER INPUT 6.1.
- Path A/B/C is unknown until the Phase 1 spike, and it shapes how much of the demo can use real
  Meta variants. Everything downstream is built to work under Path C.
- The $150 Model API credit has not been confirmed on the account yet.

**Inputs needed from Siddhartha**
1. ~~GitHub username~~ — `siddharthakvss`, wired into `pyproject.toml` and the README.
2. **Model API access (D-008)** — chase the $150 credit on the hackathon Discord; decide
   separately whether to put a personal card on file if the credit never lands. Needed by
   **Thu 29 Oct**, not today.
3. Docker: install it, or go with Neo4j Aura Free? Needed by Phase 6 (Sun 1 Nov).
4. Tonight after kickoff: the Official Rules link or paste.
