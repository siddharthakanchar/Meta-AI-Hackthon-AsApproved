# STATUS

**Last session: Tue 27 Oct 2026.**
Deadline: Thu 5 Nov 07:30 IST. Target submission: Wed 4 Nov 22:00 IST.

> Every figure on this page is measured, with the command that measures it.
> The previous version of this file claimed "478 tests green" — a number that
> had never been counted on any commit. It is corrected below, and the test
> count is now the only number here that is not machine-generated, so it stays
> beside its command.

---

## Where things stand

| Phase | State |
|---|---|
| 0 · Setup | done |
| 1 · Spikes | **blocked on the Model API key.** V1–V3 and V9 verified from public docs without one |
| 2 · Deterministic core | done |
| 3 · Masters and variants | done — 12 masters, 48 variants, 10 synthetic voiceovers (**not yet muxed into the assets** — see DECISIONS D-010) |
| 4 · Meta models in the pipeline | **not started — needs the key.** Clients written and unit-tested against documented formats |
| 5 · Rules, explanations, UI | done |
| 6 · Graph, Act/Prove, benchmark | done, keyless. Neo4j load and live Act await access |
| 7 · Polish, hosting | README/ARCHITECTURE/DEPLOY/submission written; **deploy needs a GitHub push** |
| 8 · Video and submission | script written (`submission/VIDEO.md`); recording and form are yours |

```powershell
python -m pytest -q                              # 492 passed
python -m ruff check .                           # all checks passed
python scripts/publish_numbers.py --check        # every published number agrees
asapproved demo                                  # hero case from cache, 0 ms, no key
```

---

## Verified this session

**Reproducible bit for bit.** The committed tree was cloned to a scratch
directory, the dataset rebuilt from scratch, and the result compared:

- label digest `d18da5ad9012…` — identical
- all 60 generated assets (12 masters, 48 variants) — **byte for byte
  identical**, H.264 encodes included
- `eval/results.json` — every TP/FP/FN identical on both baselines
- `eval/report.md` — identical except mean seconds per variant (3.1 here, 3.3
  in the clone), which is wall clock, not a result

So a judge who rebuilds gets the same files and the same score, not merely a
matching answer key. Measured timings for that rebuild, on this machine:

| Step | Time |
|---|---|
| `make_masters.py` | 2m26 |
| `make_variants.py` | 10m31 |
| `precompute.py` | 2m56 |
| `run_bench.py` | 2m42 |

**The UI now has tests.** `tests/test_app_ui.py` drives the real Streamlit
script through `streamlit.testing.v1.AppTest`: all six screens, all 48 cached
variants, the Block/Accept/Escalate decision loop end to end, the evidence
chain's tamper detection, and the empty-data path. Verified non-vacuous by
mutation — renaming a CSS class and reworking the visibility-bar label each
produce a failure.

**Published numbers are generated, not transcribed.**
`scripts/publish_numbers.py` renders the results blocks in `README.md`,
`docs/DECISIONS.md` and `submission/SUBMISSION.md` from `eval/results.json`;
`--check` is enforced by `tests/test_published_numbers.py`. The generator used
to live outside the repo, which made the README's own claim unverifiable.

---

## Pick up here

**1. Push to GitHub.** No remote exists, so the Demo criterion (25%) has
nothing behind it and the clone URL in the README is unverifiable.

```powershell
pre-commit run --all-files          # let gitleaks confirm independently
git remote add origin https://github.com/siddharthakvss/asapproved.git
git push -u origin main
```

Then deploy per `DEPLOY.md` (~3 min) and paste the real URLs into `README.md`,
`DEPLOY.md` and `submission/SUBMISSION.md`.

**2. When the credits land** — check "free credits" on the dev.meta.ai Billing
page first; until it shows, calls bill the card directly.

```powershell
# .env: META_MODEL_API_KEY=...
$env:ASAPPROVED_MODE="live"; python scripts/spike_models.py
```

Then wire **SAM 3.1 only**, on the five variants that produce the R5/R7/R12
false positives, and publish the region-IoU delta against the template
detector. That is worth more than integrating all three models: it measures
what Meta's model adds over a real classical control, and the README already
promised that metric before the numbers existed.

Mux the voiceovers in the same pass (`ffmpeg -i video -i wav -c:v copy
-c:a aac -shortest`) and transcribe. Both halves have to land together: muxing
alone changes every affected asset's bytes and therefore the label digest,
which would invalidate the published numbers and the reproducibility result
above for no gain, because R9 still cannot be scored without a transcriber.

---

## Open risks

- **No Meta model has run.** 25% of the rubric. Everything published came from
  the keyless fallback, labelled as such throughout. Decision point if nothing
  has arrived by **Thu 29 Oct**.
- **No real Advantage+ output has ever been through this.** One sandbox ad with
  enhancements on, and a screenshot of what Meta returns, would convert the
  project from plausible to demonstrated. Cheapest high-value item left.
- **Development-set results, no held-out split.** Thresholds were fitted on
  these 48 variants. Disclosed in the README.
- Per-rule precision is below 100% on two rules and R12 carries the one false
  negative — localisation, not logic. Figures in the README's Results table,
  which is generated; this page deliberately does not restate them.

## Waiting on you

1. GitHub repo created, so the push and deploy can happen.
2. Official Rules → `docs/RULES_SUMMARY.md` (kickoff was 22:30 IST Mon 26 Oct).
3. Docker vs Neo4j Aura — needed only if the live graph backend is wanted;
   the in-memory one is what the demo uses and it is not a blocker.
4. Record the demo video from `submission/VIDEO.md`, or accept the synthetic
   voiceovers for it.

## Local file kept out of the repo

`C:\Users\siddh\Desktop\home\asapproved-playbook-local-KEEP.md` — the build
playbook. Purged from the repo and from git history because it named the
employer and discussed prior-project IP. Do not re-add it.
