"""Meta Model API clients: Muse Spark 1.3, SAM 3.1, Muse Voice Transcribe.

Every call goes through `cache.py`. In demo mode a cache miss is an error, not a
network call — the hosted demo and the benchmark both replay from cache.

Not used: Muse Image (blocked from India under Meta's Geographic Use Policy).
Tier: Standard only, never Contributor.
"""
