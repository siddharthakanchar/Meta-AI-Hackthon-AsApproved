"""The model cache and cost ledger — the machinery that makes the demo keyless.

The property under test is the one the §13 quality gate depends on: in demo mode
a cache miss must RAISE, not quietly reach the network. A demo that silently
falls back to a live call is a demo that can fail on stage for reasons nobody
can debug in the moment.
"""

from __future__ import annotations

import json

import pytest

from asapproved.models import cache as mc


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point the cache and cost log at a temp dir for every test."""
    from asapproved.config import settings

    monkeypatch.setattr(type(settings), "cache_dir", property(lambda self: tmp_path / "cache"))
    monkeypatch.setattr(type(settings), "costs_log", property(lambda self: tmp_path / "costs.jsonl"))
    yield


def _offline(monkeypatch, value: bool):
    from asapproved.config import settings

    monkeypatch.setattr(type(settings), "offline", property(lambda self: value))


# --------------------------------------------------------------------------
# keys
# --------------------------------------------------------------------------


def test_key_is_stable_across_param_order():
    a = mc.cache_key("sam-3.1", {"b": 2, "a": 1}, ["h1", "h2"])
    b = mc.cache_key("sam-3.1", {"a": 1, "b": 2}, ["h2", "h1"])
    assert a == b, "ordering must not change the key or the cache never hits"


def test_key_changes_with_model_params_and_inputs():
    base = mc.cache_key("sam-3.1", {"a": 1}, ["h1"])
    assert base != mc.cache_key("muse-spark-1.3", {"a": 1}, ["h1"])
    assert base != mc.cache_key("sam-3.1", {"a": 2}, ["h1"])
    assert base != mc.cache_key("sam-3.1", {"a": 1}, ["h2"])


# --------------------------------------------------------------------------
# demo mode must never call out
# --------------------------------------------------------------------------


def test_demo_mode_raises_on_a_miss_instead_of_calling(monkeypatch):
    _offline(monkeypatch, True)
    called = {"n": 0}

    def fn():
        called["n"] += 1
        return {"ok": True}

    with pytest.raises(mc.CacheMiss, match="demo mode|ASAPPROVED_MODE=demo"):
        mc.cached_call("sam-3.1", {"concept": "risk warning box"}, ["h1"], fn)
    assert called["n"] == 0, "demo mode reached the network"


def test_demo_mode_serves_a_hit(monkeypatch):
    _offline(monkeypatch, False)
    mc.cached_call("sam-3.1", {"c": 1}, ["h1"], lambda: {"masks": 3})

    _offline(monkeypatch, True)
    assert mc.cached_call("sam-3.1", {"c": 1}, ["h1"], lambda: {"never": True}) == {"masks": 3}


def test_live_mode_calls_once_then_replays(monkeypatch):
    _offline(monkeypatch, False)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return {"n": calls["n"]}

    first = mc.cached_call("sam-3.1", {"c": 1}, ["h1"], fn)
    second = mc.cached_call("sam-3.1", {"c": 1}, ["h1"], fn)
    assert calls["n"] == 1
    assert first == second


def test_corrupt_cache_entry_is_treated_as_a_miss(monkeypatch):
    _offline(monkeypatch, False)
    key = mc.cache_key("sam-3.1", {"c": 1}, ["h1"])
    path = mc._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert mc.get(key) is None


# --------------------------------------------------------------------------
# costing
# --------------------------------------------------------------------------


def test_spark_cost_uses_the_cached_input_rate():
    """Cached input is $0.15/M against $1.25/M — the difference the README quotes."""
    fresh = mc.estimate_cost("muse-spark-1.3", {"input_tokens": 1_000_000, "output_tokens": 0})
    cached = mc.estimate_cost(
        "muse-spark-1.3", {"cached_input_tokens": 1_000_000, "output_tokens": 0}
    )
    assert fresh == pytest.approx(1.25)
    assert cached == pytest.approx(0.15)
    assert fresh > cached * 8


def test_sam_video_billing_applies_the_fifty_frame_minimum():
    """10 frames are billed as 50. Ignoring that understates the benchmark cost."""
    ten = mc.estimate_cost("sam-3.1", {"video_frames": 10})
    fifty = mc.estimate_cost("sam-3.1", {"video_frames": 50})
    assert ten == pytest.approx(fifty)
    assert fifty == pytest.approx(50 / 1000 * 0.20)


def test_sam_image_cost():
    assert mc.estimate_cost("sam-3.1", {"images": 1000}) == pytest.approx(2.50)


def test_transcribe_cost_per_hour():
    assert mc.estimate_cost("muse-voice-transcribe-1.0", {"audio_seconds": 3600}) == pytest.approx(0.18)


def test_unknown_model_costs_zero_rather_than_guessing():
    assert mc.estimate_cost("some-future-model", {"input_tokens": 10**9}) == 0.0


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------


def test_every_call_is_logged(monkeypatch):
    _offline(monkeypatch, False)
    mc.cached_call(
        "sam-3.1", {"c": 1}, ["h1"], lambda: {"ok": 1}, cost_fields={"images": 1}
    )
    mc.cached_call("sam-3.1", {"c": 1}, ["h1"], lambda: {"ok": 1})  # hit

    summary = mc.read_costs()
    assert summary.calls == 2
    assert summary.cache_hits == 1
    assert summary.hit_rate == pytest.approx(0.5)
    assert summary.cost_usd == pytest.approx(2.50 / 1000)


def test_cost_log_lines_are_json(monkeypatch):
    _offline(monkeypatch, False)
    mc.cached_call("sam-3.1", {"c": 1}, ["h1"], lambda: {"ok": 1}, cost_fields={"images": 1})
    from asapproved.config import settings

    for line in settings.costs_log.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        assert "ts" in row and "model" in row


def test_read_costs_on_a_missing_log_is_empty():
    summary = mc.read_costs()
    assert summary.calls == 0 and summary.cost_usd == 0.0
