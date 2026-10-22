"""
"Compared with other cars like this": looks up the dbt mart rows for a vehicle's make, model
and year of first use, and prepares what the report page shows.

The wording is deliberately careful. These figures describe how a model did across
thousands of MOT tests; they say nothing certain about one particular car.
"""

from .models import ModelYearFailRate

ABOUT_THE_SAME_PTS = 1.0     # within this many points of the peer rate, call it "about as often"
NOTABLY_HIGHER_PTS = 2.0     # a category this many points above peers is highlighted
TOP_CATEGORIES = 4


def _clean(text):
    return " ".join((text or "").split()).upper()


def _display_name(text):
    # FORD -> Ford, but keep short codes such as BMW, MG or 3 SERIES readable
    return " ".join(w if len(w) <= 3 or any(ch.isdigit() for ch in w) else w.capitalize()
                    for w in (text or "").split())


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


def build_comparison(vehicle):
    """vehicle: the 'vehicle' dict from analysis.build_report. Returns a dict for the template."""
    first_used = vehicle.get("first_used")
    name = f"{_display_name(vehicle.get('make'))} {_display_name(vehicle.get('model'))}".strip()
    base = {"name": name, "plural": _plural(name),
            "first_use_year": first_used.year if first_used else None}

    if not ModelYearFailRate.objects.exists():
        return None   # marts not loaded yet (load_mot_marts): hide the section, don't mislead
    row = find_model_year(vehicle.get("make"), vehicle.get("model"), first_used)
    if row is None:
        return {**base, "found": False}

    diff = row.initial_fail_rate_vs_peers_pts
    if diff >= ABOUT_THE_SAME_PTS:
        verdict = "more often than"
    elif diff <= -ABOUT_THE_SAME_PTS:
        verdict = "less often than"
    else:
        verdict = "about as often as"

    categories = []
    for c in row.defect_categories.order_by("-failure_share_pct")[:TOP_CATEGORIES]:
        categories.append({
            "name": c.defect_category,
            "share": round(c.failure_share_pct, 1),
            "peer_share": round(c.peer_failure_share_pct, 1),
            "higher": c.failure_share_pct - c.peer_failure_share_pct >= NOTABLY_HIGHER_PTS,
        })

    return {
        **base,
        "found": True,
        "test_year": row.test_year,
        "tests": f"{row.tests:,}",
        "rate": round(row.initial_fail_rate_pct, 1),
        "peer_rate": round(row.peer_initial_fail_rate_pct, 1),
        "diff": round(abs(diff), 1),
        "verdict": verdict,
        "worse": diff >= ABOUT_THE_SAME_PTS,
        "categories": categories,
    }
