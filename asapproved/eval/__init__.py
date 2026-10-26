"""D5 — VariantBench-UK: 12 masters -> 48 variants (24 seeded violations, 24 benign).

Baselines:
  B0  Muse Spark alone (master + variant + rulebook text in one prompt -> JSON)
  B1  pixel diff alone (changed area in any claim-ish region -> flag)
  B2  AsApproved, full pipeline

Metrics: per-rule and overall precision/recall/F1, false-block rate on benign
edits, hold-time MAE in seconds, region IoU vs labels, latency per variant, cost
per variant.

Labels are frozen before the first scored run and their file hash recorded in
DECISIONS.md. Numbers get published as measured — including the bad ones.
"""
