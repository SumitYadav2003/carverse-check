"""
Limits that protect our DVSA quota from runaway scripts and bots.

Two limits, each counted over fixed one-minute windows:

- Per visitor: how many real plates one visitor can look up a minute (the demo cars don't
  count). Visitors are told apart by IP address, which is hashed with the secret key before
  use, so the address itself is never stored.
- Whole site: how many calls we make to DVSA a minute, whoever is asking. An IP address can
  be faked, so this is the limit that really protects the quota.

The counts live in the cache, which is each server process's own memory (see CACHES in the
settings). With two gunicorn workers each limit applies per worker, so it's approximate.
That's fine: it's here to stop abuse, not to meter fair use exactly.
"""

import hashlib
import hmac
import time

from django.conf import settings
from django.core.cache import cache

WINDOW_SECONDS = 60


def _count(name):
    """Add one to this window's count for `name` and return the new count."""
    key = f"ratelimit:{name}:{int(time.time() // WINDOW_SECONDS)}"
    cache.add(key, 0, WINDOW_SECONDS * 2)
    try:
        return cache.incr(key)
    except ValueError:  # the key expired between add() and incr()
        cache.set(key, 1, WINDOW_SECONDS * 2)
        return 1


def visitor_id(request):
    # Behind Render's proxy the visitor's address is the first one in X-Forwarded-For.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    address = forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    return hmac.new(settings.SECRET_KEY.encode(), address.encode(), hashlib.sha256).hexdigest()[:32]


def allow_lookup(request):
    return _count(f"visitor:{visitor_id(request)}") <= settings.PLATE_LOOKUPS_PER_MINUTE


def allow_dvsa_call():
    return _count("dvsa") <= settings.DVSA_CALLS_PER_MINUTE


def seconds_until_reset():
    return WINDOW_SECONDS - int(time.time() % WINDOW_SECONDS)
