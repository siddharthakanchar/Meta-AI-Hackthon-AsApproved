# VariantBench-UK results

Dataset: 48 variants (24 seeded violations, 24 benign) from 12 approved masters.
Labels frozen at `a5438e9388b45e81…`.

All creative is SIMULATED. Numbers are reported as measured, including where a baseline beats the full pipeline.

## Variant-level detection

| Baseline | Precision | Recall | F1 | False-block rate | Scored | Not evaluated | Mean s/variant |
|---|---|---|---|---|---|---|---|
| **B1** — pixel diff alone | 95% | 95% | 95% | 4% | 45 | 3 | 0.4 |
| **B2** — AsApproved | 96% | 100% | 98% | 4% | 45 | 3 | 2.6 |

**False-block rate** is the share of benign variants wrongly flagged. A tool that blocks compliant ads gets switched off, so it is reported beside recall rather than below it.

## Per-rule detection

### B2

| Rule | TP | FP | FN | Precision | Recall | F1 | Not evaluated |
|---|---|---|---|---|---|---|---|
| R1 | 3 | 19 | 0 | 14% | 100% | 24% | 0 |
| R3 | 5 | 1 | 0 | 83% | 100% | 91% | 0 |
| R4 | 3 | 3 | 0 | 50% | 100% | 67% | 0 |
| R5 | 3 | 10 | 0 | 23% | 100% | 38% | 0 |
| R6 | 3 | 1 | 0 | 75% | 100% | 86% | 0 |
| R7 | 1 | 0 | 0 | 100% | 100% | 100% | 1 |
| R8 | 2 | 0 | 0 | 100% | 100% | 100% | 0 |
| R9 | 0 | 0 | 0 | — | — | — | 0 |
| R10 | 0 | 0 | 0 | — | — | — | 2 |
| R11 | 2 | 1 | 0 | 67% | 100% | 80% | 0 |
| R12 | 2 | 5 | 0 | 29% | 100% | 44% | 0 |

Not evaluated:

- brightwell_loans_v1__v1_voiceover_drops_apr: requires audio, not evaluated
- northfield_card_v1__v0_voiceover_drops_apr: requires audio, not evaluated
- northfield_card_v2__v2_music_swap: requires audio, not evaluated

## Honesty notes

- **Inconclusive is never counted as a pass.** Where a rule could not be assessed (no transcript, no settings snapshot, OCR unavailable) the variant leaves that rule's denominator and is counted in *Not evaluated*.
- **R2 (settings drift) is excluded** from every vision baseline: it compares live API settings against the approval manifest and has no pixel expression.
- Thresholds (2% region change, 4.5:1 contrast, 98% visibility) are engineering choices stated in the rulebook, not figures the FCA prescribes.
- Region tracking in this run is normalised cross-correlation, not SAM 3.1. The comparison between the two is the point of §10's region-IoU metric.
