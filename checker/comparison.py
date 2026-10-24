"""
"Compared with other cars like this": looks up the dbt mart rows for a vehicle's make, model
and year of first use, and prepares what the report page shows.

The wording is deliberately careful. These figures describe how a model did across many
MOT tests; they say nothing certain about one particular car. Whether a model counts as
failing "more often" than its peers comes from the funnel limits worked out in dbt
(mart_model_year_fail_rates), not from a fixed gap, so a small group can't be called
better or worse on the strength of a few tests.

Two different questions are answered, both worked out in dbt:
  vs_peers         is this model really, and meaningfully, above or below the average for
                   cars of its age? (the adjusted estimate and its range)
  funnel_position  does it stand out from other models of its age, allowing for the normal
                   differences between models? (the funnel plot)
"""

import math

from .models import ModelYearFailRate

NOTABLY_HIGHER_PTS = 2.0     # a category must be at least this far above peers to be highlighted
TOP_CATEGORIES = 4
SMALL_GROUP_TESTS = 100      # below this, explain the uncertainty and show the adjusted estimate
MIN_MILEAGE_READINGS = 30    # fewer readings than this: no mileage comparison

VERDICTS = {
    "higher": "more often than",
    "lower": "less often than",
    "within": "about as often as",
}


def _verdict_note(row):
    if row.vs_peers == "within":
        if row.tests < SMALL_GROUP_TESTS:
            return "There are too few tests to tell whether any gap is real."
        return "Any gap is under a point or could be down to chance."
    note = "That's a real difference, not chance."
    if row.funnel_position == "inside":
        return note + " Models do differ, though, and this one is within the usual range for its age."
    return note + " It also stands out from other models of its age."


def _clean(text):
    return " ".join((text or "").split()).upper()


def _display_name(text):
    # FORD -> Ford and MERCEDES-BENZ -> Mercedes-Benz, but keep short codes such as BMW, MG
    # or 3 SERIES readable
    def word(w):
        if len(w) <= 3 or any(ch.isdigit() for ch in w):
            return w
        return "-".join(part.capitalize() for part in w.split("-"))
    return " ".join(word(w) for w in (text or "").split())


def _plural(name):
    # "Ford Fiesta" -> "Ford Fiestas"; "BMW 118", "MG ZS" or "BMW 3 Series" -> "... cars"
    last = name[-1:] if name else ""
    return f"{name}s" if last.islower() and last != "s" else f"{name} cars"


def find_model_year(make, model, first_used):
    if not (make and model and first_used):
        return None
    return (ModelYearFailRate.objects
            .filter(make=_clean(make), model=_clean(model), first_use_year=first_used.year)
            .first())


# ---------- funnel plot ----------

FUNNEL_W, FUNNEL_H = 420, 260
PLOT = {"left": 40, "right": 412, "top": 12, "bottom": 222}
X_TICKS = [10, 30, 100, 300, 1000, 3000, 10_000, 30_000, 100_000, 300_000]
Z95, Z998 = 1.959964, 3.090232


def _tick_label(n):
    return f"{n // 1000}k" if n >= 1000 else str(n)


def funnel_plot(row):
    """Coordinates for an SVG funnel plot of every model first used in the same year as
    `row`: failure rate (y) against number of tests (x, log scale), with the 95% and 99.8%
    limits around the peer rate. Returns None if there's nothing sensible to draw."""
    groups = list(ModelYearFailRate.objects
                  .filter(first_use_year=row.first_use_year)
                  .values_list("model_year_key", "tests", "initial_fail_rate_pct", "funnel_position"))
    if len(groups) < 5:
        return None

    target = row.peer_initial_fail_rate_pct / 100
    tau2 = (row.peer_between_model_sd_pts / 100) ** 2

    def limit(n, z):
        return 100 * (target + z * math.sqrt(target * (1 - target) / n + tau2))

    n_min = min(g[1] for g in groups)
    n_max = max(g[1] for g in groups)
    x_lo = math.log10(n_min) - 0.05
    x_hi = max(math.log10(n_max) + 0.05, x_lo + 1)

    # y range: every dot and the widest limits, rounded out to the nearest 10%
    rates = [g[2] for g in groups]
    y_top = min(100, math.ceil((max(max(rates), limit(n_min, Z998)) + 2) / 10) * 10)
    y_bottom = max(0, math.floor((min(min(rates), limit(n_min, -Z998)) - 2) / 10) * 10)

    def sx(n):
        return round(PLOT["left"] + (math.log10(n) - x_lo) / (x_hi - x_lo)
                     * (PLOT["right"] - PLOT["left"]), 1)

    def sy(pct):
        pct = min(max(pct, y_bottom), y_top)
        return round(PLOT["bottom"] - (pct - y_bottom) / (y_top - y_bottom)
                     * (PLOT["bottom"] - PLOT["top"]), 1)

    def curve(z):
        steps = 40
        points = []
        for i in range(steps + 1):
            n = 10 ** (math.log10(n_min) + (math.log10(n_max) - math.log10(n_min)) * i / steps)
            points.append(f"{sx(n)},{sy(limit(n, z))}")
        return "M" + " L".join(points)

    points = [{"x": sx(n), "y": sy(rate), "out": pos != "inside"}
              for key, n, rate, pos in groups if key != row.model_year_key]
    return {
        "width": FUNNEL_W, "height": FUNNEL_H, "plot": PLOT,
        "points": points,
        "this": {"x": sx(row.tests), "y": sy(row.initial_fail_rate_pct)},
        "peer_y": sy(row.peer_initial_fail_rate_pct),
        "inner": [curve(Z95), curve(-Z95)],
        "outer": [curve(Z998), curve(-Z998)],
        "x_ticks": [{"x": sx(t), "label": _tick_label(t)}
                    for t in X_TICKS if x_lo <= math.log10(t) <= x_hi],
        "y_ticks": [{"y": sy(v), "label": f"{v}%"}
                    for v in range(int(y_bottom), int(y_top) + 1, 10)],
        "models": len(groups),
        "outside": sum(1 for g in groups if g[3] != "inside"),
    }


# ---------- mileage ----------

def mileage_comparison(row, miles_per_year, label):
    """Place one car's average yearly mileage within the spread for its model and age."""
    p = [row.miles_per_year_p10, row.miles_per_year_p25, row.miles_per_year_p50,
         row.miles_per_year_p75, row.miles_per_year_p90]
    if miles_per_year is None or row.mileage_readings < MIN_MILEAGE_READINGS or None in p:
        return None
    p10, p25, p50, p75, p90 = p
    if miles_per_year < p10:
        band, text = "low", (f"Lower than 9 in 10 {label}. Genuinely low mileage is good news, "
                             "but ask for service records or old receipts that show the mileage, "
                             "so you can see it's real.")
    elif miles_per_year < p25:
        band, text = "below", f"Lower than most {label}."
    elif miles_per_year <= p75:
        band, text = "typical", f"Typical for {label}."
    elif miles_per_year <= p90:
        band, text = "above", (f"Higher than most {label}. More miles usually means more wear, "
                               "so the service history matters more.")
    else:
        band, text = "high", (f"Higher than 9 in 10 {label}. More miles usually means more wear, "
                              "so the service history matters more.")

    scale = max(p90 * 1.25, miles_per_year * 1.08)

    def pos(value):
        return round(100 * value / scale, 1)

    return {
        "miles": f"{miles_per_year:,}", "band": band, "text": text,
        "typical_low": f"{p25:,}", "typical_high": f"{p75:,}", "median": f"{p50:,}",
        "readings": f"{row.mileage_readings:,}",
        "pos": {"p10": pos(p10), "p25": pos(p25), "p50": pos(p50), "p75": pos(p75),
                "p90": pos(p90), "car": pos(miles_per_year)},
        "widths": {"outer": round(pos(p90) - pos(p10), 1), "inner": round(pos(p75) - pos(p25), 1)},
    }


# ---------- the section ----------

def clearly_higher(category):
    """A real gap of at least NOTABLY_HIGHER_PTS, and even the bottom of the category's
    95% range is above the rate for all cars of that age."""
    return (category.failure_share_pct - category.peer_failure_share_pct >= NOTABLY_HIGHER_PTS
            and category.failure_share_low_pct > category.peer_failure_share_pct)


def build_comparison(vehicle, summary=None):
    """vehicle and summary: the 'vehicle' and 'summary' dicts from analysis.build_report.
    Returns a dict for the template, or None to hide the section."""
    first_used = vehicle.get("first_used")
    name = f"{_display_name(vehicle.get('make'))} {_display_name(vehicle.get('model'))}".strip()
    base = {"name": name, "plural": _plural(name),
            "first_use_year": first_used.year if first_used else None}

    if not ModelYearFailRate.objects.exists():
        return None   # marts not loaded yet (load_mot_marts): hide the section, don't mislead
    row = find_model_year(vehicle.get("make"), vehicle.get("model"), first_used)
    if row is None:
        return {**base, "found": False}

    verdict = VERDICTS.get(row.vs_peers, VERDICTS["within"])
    if row.vs_peers == "within" and row.tests < SMALL_GROUP_TESTS:
        verdict = "not clearly more or less often than"

    all_categories = list(row.defect_categories.order_by("-failure_share_pct"))
    categories = [{"name": c.defect_category, "share": round(c.failure_share_pct, 1),
                   "peer_share": round(c.peer_failure_share_pct, 1), "higher": clearly_higher(c)}
                  for c in all_categories[:TOP_CATEGORIES]]

    label = f"{first_used.year} {base['plural']}"
    return {
        **base,
        "found": True,
        "test_year": row.test_year,
        "tests": f"{row.tests:,}",
        "small_group": row.tests < SMALL_GROUP_TESTS,
        "rate": round(row.initial_fail_rate_pct, 1),
        "low": round(row.initial_fail_rate_low_pct, 1),
        "high": round(row.initial_fail_rate_high_pct, 1),
        "estimate": round(row.estimated_initial_fail_rate_pct, 1),
        "estimate_low": round(row.estimated_low_pct, 1),
        "estimate_high": round(row.estimated_high_pct, 1),
        "peer_rate": round(row.peer_initial_fail_rate_pct, 1),
        "verdict": verdict,
        "verdict_note": _verdict_note(row),
        "worse": row.vs_peers == "higher",
        "categories": categories,
        # every category this model clearly fails on more often (used by the seller checklist)
        "weak_spots": [c.defect_category for c in all_categories if clearly_higher(c)],
        "make_slug": row.make_slug, "model_slug": row.model_slug,
        "funnel": funnel_plot(row),
        "mileage": mileage_comparison(row, (summary or {}).get("miles_per_year_since_new"), label),
    }
