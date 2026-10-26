# STATUS

**Last session: Mon 26 Oct 2026.** Hours used ~20 of 40–45.
Deadline: Thu 5 Nov 07:30 IST. Target submission: Wed 4 Nov 22:00 IST.

---

## Where things stand

| Phase | State |
|---|---|
| 0 · Setup | done |
| 1 · Spikes | **blocked on the Model API key.** V1–V3 and V9 verified from public docs without one |
| 2 · Deterministic core | done |
| 3 · Masters and variants | done — 12 masters, 48 variants, 10 synthetic voiceovers |
| 4 · Meta models in the pipeline | **not started — needs the key.** Clients written and unit-tested against documented formats |
| 5 · Rules, explanations, UI | done |
| 6 · Graph, Act/Prove, benchmark | done, keyless. Neo4j load and live Act await access |
| 7 · Polish, hosting | README/ARCHITECTURE/DEPLOY/submission written; **deploy needs a GitHub push** |
| 8 · Video and submission | script written (`submission/VIDEO.md`); recording and form are yours |

478 tests green, ruff clean, `asapproved demo` loads from cache in 0 ms with no key.

---

## Pick up here tomorrow

**1. Finish the pending rebuild** (it was running when the session ended).

```powershell
python scripts/make_variants.py
python scripts/precompute.py
asapproved bench
```

Then update three things with the fresh numbers — they must agree exactly:
- `README.md` → Results tables and the labels digest
- `docs/DECISIONS.md` → the coverage table and label hash
- `submission/SUBMISSION.md` → the `[BENCH]` placeholder

The digest **will have changed**: `synth/derive.py` now checks the left/right
overlay bands, so ground truth differs from the committed `ee290d4b…`. Worth
re-verifying the reproducibility claim afterwards — a fresh clone regenerating
the dataset previously reproduced the committed digest exactly, which is a
strong thing to be able to say.

**2. Push to GitHub.** No remote exists, so the Demo criterion (25%) currently
has nothing behind it and the clone URL in the README is unverifiable.

```powershell
pre-commit run --all-files          # let gitleaks confirm independently
git remote add origin https://github.com/<you>/asapproved.git
git push -u origin main
```

Then deploy per `DEPLOY.md` (~3 min) and paste the real URLs into `README.md`,
`DEPLOY.md` and `submission/SUBMISSION.md`.

**3. When the credits land** — check "free credits" on the dev.meta.ai Billing
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
- Per-rule precision on R5/R7/R12 is 50–57% — localisation, not logic.

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
