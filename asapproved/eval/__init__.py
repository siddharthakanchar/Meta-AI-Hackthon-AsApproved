"""VariantBench-UK: 12 masters -> 48 variants (24 seeded violations, 24 benign).

Baselines, named as the reports name them:
  SPARK       Muse Spark alone (master + variant + rulebook text in one prompt
              -> JSON). Needs a Model API key; reported as "not run", never as a
              zero.
  PIXEL       pixel diff alone (changed area in any claim-ish region -> flag)
  ASAPPROVED  the full pipeline

Metrics: per-rule and overall precision/recall/F1, false-block rate on benign
edits, hold-time MAE in seconds, region IoU vs labels, latency per variant, cost
per variant.

The labels are NOT frozen, and the earlier version of this docstring claiming
they were is corrected here (27 Oct 2026). Labels and detector were both changed
during development — roughly half the apparent detector failures turned out to
be defects in the benchmark itself. What *is* fixed is that the label file's hash
is recorded with every published result, and that a clean-clone rebuild
reproduces both the hash and the generated assets byte for byte, so a reader can
tell which answer key a number came from. Numbers get published as measured,
including the bad ones.
"""
