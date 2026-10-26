"""Synthetic ad creative: the 12 approved masters and the 48 variants.

Everything here is invented. Three fictional firms, original logos built from
plain geometry and type, no real brands, no real people, no stock photography of
anyone. The products, rates and representative examples are made up and are not
offers.

Two properties this package exists to guarantee:

1. **The masters are compliant.** They are the baseline that "approved" means, so
   each one carries its warning or representative APR at proper prominence — the
   prescribed wording read straight from the rulebook, in its own bordered box,
   bold and underlined, at high contrast. If a master were quietly
   non-compliant, every measurement taken against it would be meaningless.

2. **Ground truth is generated, never hand-written.** Each transform knows which
   regions it touched and which rules that breaks, and emits labels as it goes.
   Hand-labelling 48 variants would be slow and, worse, would encode the same
   assumptions the detector makes — the benchmark would then measure agreement
   with itself.
"""
