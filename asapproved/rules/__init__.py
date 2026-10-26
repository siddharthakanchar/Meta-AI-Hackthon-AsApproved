"""C8 — the rules engine and the versioned YAML rulebook.

Rules decide. The LLM only explains. Every finding carries the rule ID, the
rulebook version, the measured value, the threshold, and refs to the evidence
frames and masks — plus a "not legal advice" flag.
"""
