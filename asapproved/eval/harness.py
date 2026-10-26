"""Run B0 / B1 / B2 over the frozen label set and write eval/report.md."""

from __future__ import annotations

__all__ = ["run_baseline_b0", "run_baseline_b1", "run_asapproved_b2", "score", "write_report"]


def run_baseline_b0(variants):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 6")


def run_baseline_b1(variants):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 6")


def run_asapproved_b2(variants):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 6")


def score(predictions, labels):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 6")


def write_report(results, out_path):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 6")
