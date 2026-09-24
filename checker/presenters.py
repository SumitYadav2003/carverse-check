"""Turns the analysis report into exactly what the templates display:
formatted text, counts, the verdict and the mileage chart coordinates.
Keeping this out of the templates keeps them simple and makes it testable."""

from datetime import date

from .analysis import GAP_THRESHOLD_DAYS, HIGH

CHART_W, CHART_H = 310, 170
PLOT_LEFT, PLOT_RIGHT, PLOT_TOP, PLOT_BOTTOM = 14, 296, 12, 138
RETEST_WINDOW_DAYS = 10


def fmt_miles(value):
    return f"{value:,}" if value is not None else None


def fmt_day(d):
    return d.strftime("%d %b %Y")


def evidence_chips(finding):
    items = finding["evidence"]
    chips = []
    for e in items:
        d = date.fromisoformat(e["date"])
        label = f"MOT {e['test_number']} · {fmt_day(d)}" if len(items) == 1 else fmt_day(d)
        chips.append({"label": label, "anchor": f"t-{e['test_number']}"})
    return chips


def verdict(serious, ask):
    if serious:
        return "Go carefully — check the serious issue first." if serious == 1 else \
               f"Go carefully — check the {serious} serious issues first."
    if ask:
        return "Mostly fine — a few things to ask about."
    return "No red flags in the MOT history."


def timeline(tests):
    """Newest first, with a row for every long gap between tests."""
    rows = []
    previous = None
    for test in tests:  # oldest -> newest
        if previous is not None:
            days = (test["date"] - previous["date"]).days
            if days > GAP_THRESHOLD_DAYS:
                rows.append({"is_gap": True, "text": f"About {round(days / 30.44)} months with no MOT"})
        defects = test["defects"]
        dangerous = sum(1 for d in defects if d.get("dangerous") or str(d.get("type", "")).upper() == "DANGEROUS")
        advisories = sum(1 for d in defects if str(d.get("type", "")).upper() == "ADVISORY")
        failures = sum(1 for d in defects if str(d.get("type", "")).upper() in ("FAIL", "MAJOR", "PRS")
                       and not d.get("dangerous"))
        parts = [f"{fmt_miles(test['miles'])} mi" if test["miles"] is not None else "Mileage unreadable"]
        if dangerous:
            parts.append(f"{dangerous} dangerous")
        if failures:
            parts.append(f"{failures} failure item{'s' if failures != 1 else ''}")
        if advisories:
            parts.append(f"{advisories} advisor{'ies' if advisories != 1 else 'y'}")
        if not (dangerous or failures or advisories):
            parts.append("no defects")
        passed = test["result"] == "PASSED"
        is_retest = (passed and previous is not None and previous["result"] == "FAILED"
                     and (test["date"] - previous["date"]).days <= RETEST_WINDOW_DAYS)
        rows.append({
            "is_gap": False,
            "anchor": f"t-{test['test_number']}",
            "date": fmt_day(test["date"]),
            "result": ("Pass · retest" if is_retest else "Pass") if passed else "Fail",
            "passed": passed,
            "detail": " · ".join(parts),
        })
        previous = test
    rows.reverse()
    return rows


def mileage_chart(tests):
    readings = [t for t in tests if t["miles"] is not None]
    if len(readings) < 2:
        return None
    t0, t1 = readings[0]["date"], readings[-1]["date"]
    span = max((t1 - t0).total_seconds(), 1)
    lo = min(r["miles"] for r in readings)
    hi = max(r["miles"] for r in readings)
    pad = max((hi - lo) * 0.08, 500)
    lo, hi = max(lo - pad, 0), hi + pad

    def x(d):
        return round(PLOT_LEFT + (d - t0).total_seconds() / span * (PLOT_RIGHT - PLOT_LEFT), 1)

    def y(m):
        return round(PLOT_BOTTOM - (m - lo) / (hi - lo) * (PLOT_BOTTOM - PLOT_TOP), 1)

    points = [{"cx": x(r["date"]), "cy": y(r["miles"])} for r in readings]
    segments = []
    for (a, pa), (b, pb) in zip(zip(readings, points), zip(readings[1:], points[1:])):
        if b["miles"] < a["miles"]:
            kind = "drop"
        elif ((b["date"] - a["date"]).days > GAP_THRESHOLD_DAYS
              and not any(a["date"] < t["date"] < b["date"] for t in tests)):
            # dashed only for a real gap with no MOT at all, not for an unreadable reading
            kind = "gap"
        else:
            kind = "solid"
        segments.append({"d": f"M{pa['cx']},{pa['cy']} L{pb['cx']},{pb['cy']}", "kind": kind,
                         "delay_ms": 600 + len(segments) * 180})

    unreadable = [fmt_day(t["date"]) for t in tests if t["miles"] is None]
    first, last = readings[0], readings[-1]
    return {
        "width": CHART_W, "height": CHART_H,
        "baseline": PLOT_BOTTOM, "top": PLOT_TOP, "left": PLOT_LEFT, "right": PLOT_RIGHT,
        "points": points,
        "segments": segments,
        "start_year": t0.year, "end_year": t1.year,
        "top_label": f"{round(hi / 1000)}k", "bottom_label": f"{round(lo / 1000)}k",
        "has_drop": any(s["kind"] == "drop" for s in segments),
        "unreadable": unreadable,
        "description": (f"Mileage went from {fmt_miles(first['miles'])} in {t0.year} "
                        f"to {fmt_miles(last['miles'])} in {t1.year}."),
    }


def present(report, source):
    findings = []
    for i, f in enumerate(report["findings"]):
        findings.append({**f, "serious": f["severity"] == HIGH, "chips": evidence_chips(f),
                         "delay_ms": 200 + i * 60})
    serious = sum(1 for f in findings if f["serious"])
    ask = len(findings) - serious
    total = max(serious + ask, 1)
    v = report["vehicle"]
    s = report["summary"]
    return {
        "vehicle": v,
        "first_used": v["first_used"].strftime("%b %Y") if v["first_used"] else None,
        "is_sample": source == "sample",
        "serious_count": serious,
        "ask_count": ask,
        "serious_pct": round(serious / total * 100),
        "ask_pct": round(ask / total * 100),
        "verdict": verdict(serious, ask),
        "findings": findings,
        "stats": {
            "latest_miles": fmt_miles(s["latest_miles"]),
            "avg_miles": fmt_miles(s["avg_miles_per_year"]),
            "test_count": s["test_count"],
            "failed_count": s["failed_count"],
        },
        "chart": mileage_chart(report["tests"]),
        "timeline": timeline(report["tests"]),
    }
