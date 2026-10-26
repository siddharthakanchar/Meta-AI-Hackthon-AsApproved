"""Phase 1 spike — Meta Marketing API. Decides Path A / B / C by Tue 27 Oct 23:00 IST.

Steps:
  1. create a PAUSED campaign + ad set + ad with an image creative, enhancements
     explicitly OPT_IN  (paused throughout: no spend)
  2. read back degrees_of_freedom_spec.creative_features_spec, confirm the keys
  3. call previews for several ad_format values; inspect whether any rendered
     output reflects the AI enhancements  <- the actual question
  4. attempt to set one feature to OPT_OUT; capture the error if specs are immutable
  5. save every response under data/fixtures/, personal IDs stripped

Outcome:
  Path A  previews render enhancements      -> real Meta variants in the demo
  Path B  settings readable, previews don't -> real drift + SIMULATED variants
  Path C  access blocked                    -> fully SIMULATED + recorded fixtures

Record the decision and the evidence in DECISIONS.md and STATUS.md.
Run: python scripts/spike_marketing_api.py
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("Phase 1 — written once the Marketing API creds are in .env")


if __name__ == "__main__":
    main()
