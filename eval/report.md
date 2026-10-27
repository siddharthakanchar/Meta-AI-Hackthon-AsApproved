# VariantBench-UK results

Dataset: 48 variants (24 seeded violations, 24 benign) from 12 approved masters.
Labels digest `d18da5ad90127363…` — a content hash, not a freeze. The labels and the detector were both changed during development; see the README's Limits section.

All creative is SIMULATED. Numbers are reported as measured, including where a baseline beats the full pipeline.

## Variant-level detection

| Baseline | Precision | Recall | F1 | False-block rate | Scored | Not evaluated | Mean s/variant |
|---|---|---|---|---|---|---|---|
| **PIXEL** — pixel diff alone | 95% | 95% | 95% | 4% | 45 | 3 | 0.4 |
| **ASAPPROVED** — full pipeline | 100% | 100% | 100% | 0% | 45 | 3 | 3.1 |

**False-block rate** is the share of benign variants wrongly flagged. A tool that blocks compliant ads gets switched off, so it is reported beside recall rather than below it.

### Reading this table honestly

A pixel diff scores close to the full pipeline on *variant-level detection*, and that is a real result, not a flaw in the baseline. The question it answers — "did something change?" — is the easy one, and almost any edit to a claim region trips it.

It is also not the question a compliance officer can act on. They need to know **which rule broke, by how much, against which threshold, and with which frame as evidence** — because that is what goes in the record and what a regulator asks about. The per-rule table below is where the two separate: B1 can only ever assert R1, so every other rule is a miss it cannot even attempt.

## Per-rule attribution

### PIXEL

| Rule | TP | FP | FN | Precision | Recall | F1 | Not evaluated |
|---|---|---|---|---|---|---|---|
| R1 | 21 | 1 | 1 | 95% | 95% | 95% | 0 |
| R3 | 0 | 0 | 5 | — | 0% | — | 0 |
| R4 | 0 | 0 | 4 | — | 0% | — | 0 |
| R5 | 0 | 0 | 3 | — | 0% | — | 0 |
| R6 | 0 | 0 | 3 | — | 0% | — | 0 |
| R7 | 0 | 0 | 2 | — | 0% | — | 0 |
| R8 | 0 | 0 | 2 | — | 0% | — | 0 |
| R9 | 0 | 0 | 0 | — | — | — | 2 |
| R10 | 0 | 0 | 2 | — | 0% | — | 0 |
| R11 | 0 | 0 | 2 | — | 0% | — | 0 |
| R12 | 0 | 0 | 5 | — | 0% | — | 0 |

Not evaluated:

- brightwell_loans_v1__v1_voiceover_drops_apr: requires audio, not evaluated
- northfield_card_v1__v0_voiceover_drops_apr: requires audio, not evaluated
- northfield_card_v2__v2_music_swap: requires audio, not evaluated

### ASAPPROVED

| Rule | TP | FP | FN | Precision | Recall | F1 | Not evaluated |
|---|---|---|---|---|---|---|---|
| R1 | 22 | 0 | 0 | 100% | 100% | 100% | 0 |
| R3 | 5 | 0 | 0 | 100% | 100% | 100% | 0 |
| R4 | 4 | 0 | 0 | 100% | 100% | 100% | 0 |
| R5 | 3 | 3 | 0 | 50% | 100% | 67% | 0 |
| R6 | 3 | 0 | 0 | 100% | 100% | 100% | 0 |
| R7 | 2 | 1 | 0 | 67% | 100% | 80% | 0 |
| R8 | 2 | 0 | 0 | 100% | 100% | 100% | 0 |
| R9 | 0 | 0 | 0 | — | — | — | 2 |
| R10 | 0 | 0 | 0 | — | — | — | 2 |
| R11 | 2 | 0 | 0 | 100% | 100% | 100% | 0 |
| R12 | 4 | 0 | 1 | 100% | 80% | 89% | 0 |

Not evaluated:

- brightwell_loans_v1__v1_voiceover_drops_apr: requires audio, not evaluated
- northfield_card_v1__v0_voiceover_drops_apr: requires audio, not evaluated
- northfield_card_v2__v2_music_swap: requires audio, not evaluated

## Honesty notes

- **Inconclusive is never counted as a pass.** Where a rule could not be assessed (no transcript, no settings snapshot, OCR unavailable) the variant leaves that rule's denominator and is counted in *Not evaluated*.
- **R2 (settings drift) is excluded** from every vision baseline: it compares live API settings against the approval manifest and has no pixel expression.
- Thresholds (2% region change, 4.5:1 contrast, 98% visibility) are engineering choices stated in the rulebook, not figures the FCA prescribes.
- Region tracking in this run is normalised cross-correlation, not SAM 3.1. The comparison between the two is the point of §10's region-IoU metric.
