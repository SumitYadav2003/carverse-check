import logging
import re

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import cache_control

from .analysis import build_report
from .checklist import build_checklist
from .comparison import build_comparison
from . import explore, ratelimit
from .presenters import present
from .dvsa import DvsaUnavailable
from .models import ModelYearFailRate, OdometerRounding
from .sample_data import load_sample
from .services import get_vehicle

logger = logging.getLogger(__name__)

PLATE_RE = re.compile(r"^[A-Z0-9]{1,8}$")


def normalise_plate(raw):
    return re.sub(r"\s+", "", raw or "").upper()


# Figures from the author's pipeline run on DVSA's 2024 anonymised MOT data (dbt marts and the
# reconciliation test in transform/tests). Fixed text, so they're kept in one place.
PIPELINE_FACTS = {
    "tests": "42.6 million",
    "defects": "91.8 million",
    "models": "66,000",
    "dvsa_tests_ours": "24,136,921",
    "dvsa_tests_theirs": "24,157,139",
    "dvsa_initial_ours": "28.18%",
    "dvsa_initial_theirs": "28.17%",
    "dvsa_final_ours": "22.73%",
    "dvsa_final_theirs": "22.72%",
}
CONTACT_EMAIL = "culinaai.project@gmail.com"


def home(request):
    return render(request, "checker/home.html", {"facts": PIPELINE_FACTS})


def page(request, template):
    """The plain content pages (about, help, privacy and so on)."""
    return render(request, f"checker/pages/{template}.html",
                  {"facts": PIPELINE_FACTS, "contact_email": CONTACT_EMAIL})


def methodology(request):
    digits = list(OdometerRounding.objects.filter(check_name="last_digit").order_by("pattern"))
    endings = {r.pattern: r for r in OdometerRounding.objects.filter(check_name="ends_with")}
    top = max((d.share_pct for d in digits), default=0) or 1
    for d in digits:
        d.bar = round(100 * d.share_pct / max(top, 10.0), 1)
        d.diff = round(d.share_pct - d.expected_share_pct, 2)
        d.readings_text = f"{d.readings:,}"
    return render(request, "checker/pages/methodology.html", {
        "facts": PIPELINE_FACTS, "contact_email": CONTACT_EMAIL,
        "digits": digits, "ends_00": endings.get("00"), "ends_000": endings.get("000"),
        "total_readings": f"{digits[0].total_readings:,}" if digits else None,
        "groups": ModelYearFailRate.objects.count(),
    })


@cache_control(max_age=86400)
def robots_txt(request):
    # Reports are about individual number plates: keep them out of search engines.
    return HttpResponse("User-agent: *\nDisallow: /report/\nDisallow: /check/\nDisallow: /admin/\n",
                        content_type="text/plain")


def check(request):
    plate = normalise_plate(request.GET.get("reg"))
    if not PLATE_RE.match(plate):
        return render(request, "checker/home.html", {
            "error": "That doesn't look like a UK number plate. Use letters and numbers only, like AB12 CDE.",
            "value": request.GET.get("reg", ""),
        }, status=400)
    return redirect(reverse("checker:report", args=[plate]))


def report(request, registration):
    plate = normalise_plate(registration)
    if not PLATE_RE.match(plate):
        return render(request, "checker/not_found.html", {"plate": plate[:10]}, status=404)
    if load_sample(plate) is None and not ratelimit.allow_lookup(request):
        logger.warning("A visitor reached the limit of %s plate lookups a minute", settings.PLATE_LOOKUPS_PER_MINUTE)
        response = render(request, "checker/too_many.html", {"plate": plate}, status=429)
        response["Retry-After"] = str(ratelimit.seconds_until_reset())
        return response
    try:
        vehicle, source = get_vehicle(plate)
    except DvsaUnavailable:
        return render(request, "checker/unavailable.html", {"plate": plate}, status=503)
    if vehicle is None:
        return render(request, "checker/not_found.html", {"plate": plate}, status=404)
    report = build_report(vehicle)
    context = present(report, source, today=timezone.localdate())
    context["comparison"] = build_comparison(report["vehicle"], report["summary"])
    context["checklist"] = build_checklist(report, context["comparison"])
    return render(request, "checker/report.html", context)


# ---------- explore models ----------

def models_index(request):
    years = explore.ranking_years()
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        year = None
    if year not in years:
        year = 2016 if 2016 in years else (years[0] if years else None)
    query = request.GET.get("q", "").strip()[:60]
    return render(request, "checker/explore/index.html", {
        "query": query, "results": explore.search(query) if query else None,
        "makes": explore.popular_makes(), "years": years,
        "ranking": explore.rankings(year) if year else None,
    })


def models_make(request, make_slug):
    make = explore.make_models(make_slug)
    if make is None:
        raise Http404("No such make")
    return render(request, "checker/explore/make.html", {"make": make})


def models_model(request, make_slug, model_slug):
    detail = explore.model_detail(make_slug, model_slug)
    if detail is None:
        raise Http404("No such model")
    return render(request, "checker/explore/model.html", {"m": detail})
