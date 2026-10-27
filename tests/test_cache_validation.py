"""A response the caller cannot use must never become a cached result.

The first live Spark call was cut short by its token budget and came back as
half-written JSON. `cached_call` stored it, and from then on every run replayed
the same broken text and failed with the same `JSONDecodeError` — without
touching the network, so nothing in the output suggested the cache was the
cause. These tests pin both halves of the fix: a bad response is not written,
and a bad entry already on disk is not served.
"""

from __future__ import annotations

import json

import pytest

from asapproved.config import Settings
from asapproved.models import cache


@pytest.fixture()
def cache_dir(monkeypatch, tmp_path):
    # Settings is a frozen dataclass and both of these are properties, so they
    # are patched on the class rather than the instance.
    monkeypatch.setattr(Settings, "cache_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(Settings, "offline", property(lambda self: False))
    monkeypatch.setattr(cache, "log_cost", lambda **_: None)
    return tmp_path


def must_parse(response):
    json.loads(response["text"])


TRUNCATED = {"text": '{"claims": [{"text": "0% for 12 months", "type": "rate'}
WHOLE = {"text": '{"claims": []}'}


def test_a_response_that_fails_validation_is_not_cached(cache_dir):
    calls = []

    def fn():
        calls.append(1)
        return TRUNCATED

    with pytest.raises(json.JSONDecodeError):
        cache.cached_call("m", {"p": 1}, [], fn, validate=must_parse)

    assert list(cache_dir.rglob("*.json")) == [], "a truncated response reached the disk"

    # The failure must not be sticky either: the next call tries again rather
    # than replaying a stored error.
    with pytest.raises(json.JSONDecodeError):
        cache.cached_call("m", {"p": 1}, [], fn, validate=must_parse)
    assert len(calls) == 2


def test_a_poisoned_entry_already_on_disk_is_dropped_and_recomputed(cache_dir):
    key = cache.cache_key("m", {"p": 2}, [])
    cache.put(key, TRUNCATED, meta={"model": "m"})
    assert cache.get(key) == TRUNCATED, "setup failed to plant the bad entry"

    calls = []

    def fn():
        calls.append(1)
        return WHOLE

    got = cache.cached_call("m", {"p": 2}, [], fn, validate=must_parse)

    assert got == WHOLE
    assert calls == [1], "the poisoned entry was served instead of being replaced"
    assert cache.get(key) == WHOLE, "the good response did not replace the bad one"


def test_a_valid_entry_is_still_served_without_calling(cache_dir):
    key = cache.cache_key("m", {"p": 3}, [])
    cache.put(key, WHOLE, meta={"model": "m"})

    def fn():
        raise AssertionError("cache hit should not call the model")

    assert cache.cached_call("m", {"p": 3}, [], fn, validate=must_parse) == WHOLE


def test_validation_is_optional_and_off_by_default(cache_dir):
    """Callers without a validator keep the old behaviour: anything is cacheable."""
    got = cache.cached_call("m", {"p": 4}, [], lambda: TRUNCATED)
    assert got == TRUNCATED
    assert cache.get(cache.cache_key("m", {"p": 4}, [])) == TRUNCATED


def test_cost_fields_may_be_computed_from_the_response(cache_dir, monkeypatch):
    """Token prices are only knowable after the reply arrives.

    `complete_json` passed a fixed `cost_fields={}` because the counts do not
    exist when the call is constructed, so every Spark call was logged at $0.00
    and the ledger's total was zero no matter how much was spent.
    """
    logged = []
    monkeypatch.setattr(cache, "log_cost", lambda **fields: logged.append(fields))

    usage = {"input_tokens": 3606, "output_tokens": 739, "cached_input_tokens": 0}
    cache.cached_call(
        "muse-spark-1.3",
        {"p": 6},
        [],
        lambda: {"text": "{}", "usage": usage},
        cost_fields=lambda response: response["usage"],
        validate=must_parse,
    )

    assert len(logged) == 1
    assert logged[0]["cost_usd"] > 0, "a metered call was logged as free"
    assert logged[0]["cost_usd"] == pytest.approx(cache.estimate_cost("muse-spark-1.3", usage))


def test_a_dict_of_cost_fields_still_works(cache_dir, monkeypatch):
    """SAM bills per image, which is known up front — that path must not regress."""
    logged = []
    monkeypatch.setattr(cache, "log_cost", lambda **fields: logged.append(fields))

    cache.cached_call("sam-3.1", {"p": 7}, [], lambda: {"ok": 1}, cost_fields={"images": 4})

    assert logged[0]["cost_usd"] == pytest.approx(4 / 1000 * 2.50)


def test_drop_reports_whether_anything_was_removed(cache_dir):
    key = cache.cache_key("m", {"p": 5}, [])
    assert cache.drop(key) is False
    cache.put(key, WHOLE, meta={"model": "m"})
    assert cache.drop(key) is True
    assert cache.get(key) is None
