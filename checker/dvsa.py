"""
Client for the DVSA MOT history API.

    https://documentation.history.mot.api.gov.uk/

Authentication is OAuth 2.0 client credentials: we swap our client ID and secret for an
access token (valid about an hour), then send it with our API key on every request.
DVSA asks for the token to be cached, so it is kept until shortly before it expires.

Each vehicle's answer is also cached for an hour, so refreshing a report page doesn't spend
more of the daily quota. Credentials come from settings (loaded from .env) and are never
logged or shown. Nor are plates: the log says what happened, not which car was asked about.
"""

import http.client
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

from . import ratelimit

logger = logging.getLogger(__name__)

API_URL = "https://history.mot.api.gov.uk/v1/trade/vehicles/registration/{}"
TOKEN_CACHE_KEY = "dvsa:access_token"
VEHICLE_CACHE_SECONDS = 60 * 60
TOKEN_SAFETY_MARGIN_SECONDS = 120
TIMEOUT_SECONDS = 10
SLOW_SECONDS = 3


class DvsaNotConfigured(Exception):
    """The DVSA_* settings are missing, so live lookups are switched off."""


class VehicleNotFound(Exception):
    """DVSA has no record for this registration (or says the registration is invalid)."""


class DvsaUnavailable(Exception):
    """DVSA couldn't answer right now: busy, down, or our credentials were refused."""


def _settings():
    names = ["DVSA_CLIENT_ID", "DVSA_CLIENT_SECRET", "DVSA_API_KEY", "DVSA_SCOPE", "DVSA_TOKEN_URL"]
    values = {n: getattr(settings, n, "") for n in names}
    if not all(values.values()):
        raise DvsaNotConfigured()
    return values


def is_configured():
    try:
        _settings()
        return True
    except DvsaNotConfigured:
        return False


def _badly_pasted_settings():
    """Names of DVSA settings with line breaks, tabs or spaces at either end.

    Easy to do by accident when copying values from .env into a hosting dashboard, and
    otherwise only shows up as a confusing failure when the first real plate is checked.
    """
    names = ["DVSA_CLIENT_ID", "DVSA_CLIENT_SECRET", "DVSA_API_KEY", "DVSA_SCOPE", "DVSA_TOKEN_URL"]
    return [n for n in names
            if (value := getattr(settings, n, "")) != value.strip() or any(c in value for c in "\r\n\t")]


def _send(request):
    """Send a request; return (status, parsed JSON or None). Network failures raise DvsaUnavailable."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = None
        return exc.code, body
    # OSError covers network problems (URLError, timeouts, dropped connections) and
    # HTTPException covers malformed requests or replies. Either way DVSA can't answer.
    except (OSError, http.client.HTTPException, ValueError) as exc:
        logger.warning("Couldn't reach DVSA (%s)", type(exc).__name__)
        raise DvsaUnavailable("network") from exc


def get_access_token(force_refresh=False):
    if not force_refresh:
        token = cache.get(TOKEN_CACHE_KEY)
        if token:
            return token
    cfg = _settings()
    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": cfg["DVSA_CLIENT_ID"],
        "client_secret": cfg["DVSA_CLIENT_SECRET"],
        "scope": cfg["DVSA_SCOPE"],
    }).encode()
    request = urllib.request.Request(cfg["DVSA_TOKEN_URL"], data=form, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    status, body = _send(request)
    if status != 200 or not body or "access_token" not in body:
        # Usually means the credentials have expired or been revoked: worth knowing about.
        logger.error("DVSA refused our token request (HTTP %s). Check the DVSA_* credentials.", status)
        raise DvsaUnavailable(f"token request failed ({status})")
    lifetime = int(body.get("expires_in", 3599)) - TOKEN_SAFETY_MARGIN_SECONDS
    cache.set(TOKEN_CACHE_KEY, body["access_token"], max(lifetime, 60))
    return body["access_token"]


def _lookup(registration, token):
    cfg = _settings()
    url = API_URL.format(urllib.parse.quote(registration))
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "X-API-Key": cfg["DVSA_API_KEY"],
        "Accept": "application/json",
    })
    started = time.monotonic()
    status, body = _send(request)
    elapsed_ms = (time.monotonic() - started) * 1000
    if elapsed_ms > SLOW_SECONDS * 1000:
        logger.warning("Slow DVSA lookup: HTTP %s in %.0f ms", status, elapsed_ms)
    else:
        logger.debug("DVSA lookup: HTTP %s in %.0f ms", status, elapsed_ms)
    return status, body


def get_vehicle(registration):
    """Return the vehicle record (dict in DVSA's format) for a registration with no spaces."""
    cache_key = f"dvsa:vehicle:{registration}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not ratelimit.allow_dvsa_call():
        logger.warning("Site-wide limit of %s DVSA calls a minute reached", settings.DVSA_CALLS_PER_MINUTE)
        raise DvsaUnavailable("site-wide limit reached")

    if bad := _badly_pasted_settings():
        logger.error("These settings contain a line break or extra spaces, so DVSA can't be "
                     "contacted: %s. Fix them in the environment variables.", ", ".join(bad))
        raise DvsaUnavailable("badly pasted settings")

    status, body = _lookup(registration, get_access_token())
    if status in (401, 403):
        # most often an expired token: get a fresh one and try once more
        status, body = _lookup(registration, get_access_token(force_refresh=True))

    if status == 200 and isinstance(body, dict):
        cache.set(cache_key, body, VEHICLE_CACHE_SECONDS)
        return body
    if status in (400, 404):
        raise VehicleNotFound(registration)
    if status == 429:
        logger.warning("DVSA says we're sending too many requests (HTTP 429)")
        raise DvsaUnavailable("rate limited")
    logger.warning("Unexpected answer from DVSA (HTTP %s)", status)
    raise DvsaUnavailable(f"unexpected response ({status})")
