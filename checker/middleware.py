from django.http import HttpResponse

HEALTH_CHECK_PATH = "/healthz"


class HealthCheckMiddleware:
    """Answer Render's health check at /healthz before any other middleware runs.

    It comes first so the check passes whatever host name or protocol Render uses for it:
    later middleware would reject an unknown host or redirect plain http to https.

    It deliberately doesn't touch the database. Render checks every few seconds, and a
    database query each time would keep Neon's free database awake around the clock and use
    up its monthly allowance. If the database is down, the pages say so themselves.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_CHECK_PATH:
            response = HttpResponse("ok", content_type="text/plain")
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
