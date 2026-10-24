"""
"Explore models": browse the failure-rate marts without a number plate.

Rankings use the adjusted estimate (empirical Bayes), not the raw rate. Ranked by raw rate,
the top and bottom of any table fill up with models that had only a few dozen tests,
because small groups swing furthest by chance. The page shows how many small groups each
method would put in its top 10, so the difference is visible, not just claimed.
"""

from django.db.models import Count, Max, Min, Q, Sum

from .comparison import _display_name, _plural
from .models import ModelYearFailRate

RANKING_SIZE = 10
SMALL_GROUP_TESTS = 100
MIN_GROUPS_FOR_A_RANKING_YEAR = 50
POPULAR_MAKES = 30
SEARCH_RESULTS = 30
MIN_MAKE_TESTS = 1000      # makes with fewer tests than this aren't listed (rare imports, typos)


def display(make, model=""):
    return f"{_display_name(make)} {_display_name(model)}".strip()


def ranking_years():
    """Years of first use with enough models for a ranking to mean something."""
    return list(ModelYearFailRate.objects.values("first_use_year")
                .annotate(n=Count("pk")).filter(n__gte=MIN_GROUPS_FOR_A_RANKING_YEAR)
                .order_by("-first_use_year").values_list("first_use_year", flat=True))


def _ranking_row(r):
    return {"name": display(r.make, r.model), "make_slug": r.make_slug, "model_slug": r.model_slug,
            "tests": f"{r.tests:,}", "small": r.tests < SMALL_GROUP_TESTS,
            "estimate": round(r.estimated_initial_fail_rate_pct, 1),
            "low": round(r.estimated_low_pct, 1), "high": round(r.estimated_high_pct, 1),
            "raw": round(r.initial_fail_rate_pct, 1), "vs_peers": r.vs_peers}


def rankings(year):
    groups = ModelYearFailRate.objects.filter(first_use_year=year)
    if not groups.exists():
        return None
    by_estimate = groups.order_by("-estimated_initial_fail_rate_pct", "-tests")
    worst = list(by_estimate[:RANKING_SIZE])
    best = list(groups.order_by("estimated_initial_fail_rate_pct", "-tests")[:RANKING_SIZE])
    raw_worst = list(groups.order_by("-initial_fail_rate_pct")[:RANKING_SIZE])
    peer = worst[0]
    return {
        "year": year,
        "models": groups.count(),
        "peer_rate": round(peer.peer_initial_fail_rate_pct, 1),
        "worst": [_ranking_row(r) for r in worst],
        "best": [_ranking_row(r) for r in best],
        # the point of adjusting: how many small groups each method puts in its top 10
        "small_in_raw_top": sum(r.tests < SMALL_GROUP_TESTS for r in raw_worst),
        "small_in_adjusted_top": sum(r.tests < SMALL_GROUP_TESTS for r in worst),
        "small_tests": SMALL_GROUP_TESTS,
    }


def popular_makes():
    rows = (ModelYearFailRate.objects.values("make", "make_slug")
            .annotate(tests=Sum("tests"), models=Count("model_slug", distinct=True))
            .filter(tests__gte=MIN_MAKE_TESTS).order_by("-tests")[:POPULAR_MAKES])
    return [{"name": _display_name(r["make"]), "slug": r["make_slug"]} for r in rows]


def search(query):
    words = query.upper().split()
    if not words:
        return []
    matches = ModelYearFailRate.objects.all()
    for w in words:
        matches = matches.filter(Q(make__icontains=w) | Q(model__icontains=w))
    rows = (matches.values("make", "model", "make_slug", "model_slug")
            .annotate(tests=Sum("tests"), first=Min("first_use_year"), last=Max("first_use_year"))
            .order_by("-tests")[:SEARCH_RESULTS])
    return [{"name": display(r["make"], r["model"]), "make_slug": r["make_slug"],
             "model_slug": r["model_slug"], "tests": f"{r['tests']:,}",
             "years": f"{r['first']}" if r["first"] == r["last"] else f"{r['first']}–{r['last']}"}
            for r in rows]


def make_models(make_slug):
    rows = list(ModelYearFailRate.objects.filter(make_slug=make_slug)
                .values("make", "model", "model_slug")
                .annotate(tests=Sum("tests"), first=Min("first_use_year"), last=Max("first_use_year"))
                .order_by("-tests"))
    if not rows:
        return None
    return {"name": _display_name(rows[0]["make"]), "slug": make_slug,
            "models": [{"name": _display_name(r["model"]), "slug": r["model_slug"],
                        "tests": f"{r['tests']:,}",
                        "years": f"{r['first']}" if r["first"] == r["last"] else f"{r['first']}–{r['last']}"}
                       for r in rows]}


# ---------- one model, every year ----------

CHART_W, CHART_H = 640, 260
PLOT = {"left": 44, "right": 628, "top": 14, "bottom": 222}


def year_chart(rows):
    """SVG coordinates: the model's adjusted failure rate by year of first use, with its
    95% range as a band, and the rate for all cars of each age as a dashed line."""
    if len(rows) < 2:
        return None
    years = [r.first_use_year for r in rows]
    values = ([r.estimated_low_pct for r in rows] + [r.estimated_high_pct for r in rows]
              + [r.peer_initial_fail_rate_pct for r in rows])
    top = min(100, (int(max(values)) // 10 + 1) * 10)
    bottom = max(0, (int(min(values)) // 10) * 10)
    x_lo, x_hi = min(years), max(years)
    if x_lo == x_hi or top == bottom:
        return None

    def sx(year):
        return round(PLOT["left"] + (year - x_lo) / (x_hi - x_lo) * (PLOT["right"] - PLOT["left"]), 1)

    def sy(pct):
        return round(PLOT["bottom"] - (pct - bottom) / (top - bottom) * (PLOT["bottom"] - PLOT["top"]), 1)

    def line(points):
        return "M" + " L".join(f"{x},{y}" for x, y in points)

    band = ([(sx(r.first_use_year), sy(r.estimated_high_pct)) for r in rows]
            + [(sx(r.first_use_year), sy(r.estimated_low_pct)) for r in reversed(rows)])
    step = 1 if len(years) <= 12 else 2
    return {
        "width": CHART_W, "height": CHART_H, "plot": PLOT,
        "band": line(band) + " Z",
        "model": line([(sx(r.first_use_year), sy(r.estimated_initial_fail_rate_pct)) for r in rows]),
        "peer": line([(sx(r.first_use_year), sy(r.peer_initial_fail_rate_pct)) for r in rows]),
        "points": [{"x": sx(r.first_use_year), "y": sy(r.estimated_initial_fail_rate_pct)} for r in rows],
        "x_ticks": [{"x": sx(y), "label": y} for y in years[::step]],
        "y_ticks": [{"y": sy(v), "label": f"{v}%"} for v in range(bottom, top + 1, 10)],
    }


def model_detail(make_slug, model_slug):
    rows = list(ModelYearFailRate.objects.filter(make_slug=make_slug, model_slug=model_slug)
                .order_by("first_use_year", "model"))
    if not rows:
        return None
    name = display(rows[0].make, rows[0].model)
    years = [{
        "year": r.first_use_year, "tests": f"{r.tests:,}", "small": r.tests < SMALL_GROUP_TESTS,
        "estimate": round(r.estimated_initial_fail_rate_pct, 1),
        "low": round(r.estimated_low_pct, 1), "high": round(r.estimated_high_pct, 1),
        "raw": round(r.initial_fail_rate_pct, 1), "peer": round(r.peer_initial_fail_rate_pct, 1),
        "vs_peers": r.vs_peers,
        "miles": f"{r.miles_per_year_p50:,}" if r.miles_per_year_p50 else None,
    } for r in reversed(rows)]                                  # newest first in the table
    counts = {v: sum(1 for r in rows if r.vs_peers == v) for v in ("higher", "lower", "within")}
    return {"name": name, "plural": _plural(name), "make": _display_name(rows[0].make),
            "make_slug": make_slug, "years": years, "chart": year_chart(rows),
            "counts": counts, "test_year": rows[0].test_year,
            "total_tests": f"{sum(r.tests for r in rows):,}"}
