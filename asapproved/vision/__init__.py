"""Deterministic vision: alignment, diffing, OCR and placement overlay masks.

No model calls live in this package — that keeps C3/C5 unit-testable and keeps the
"rules decide" boundary clean.
"""
