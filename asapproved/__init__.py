"""AsApproved — does the approved ad survive Meta's AI edits?

Pipeline (design note):
    approve master -> sense -> align/diff -> segment -> measure -> rules decide
    -> LLM explains -> human approves -> act -> prove -> remember

Nothing in this package gives legal advice. Findings flag items for compliance
review against paraphrased regulation, with citations.
"""

__version__ = "0.1.0"
RULEBOOK_VERSION = "uk_v1"
