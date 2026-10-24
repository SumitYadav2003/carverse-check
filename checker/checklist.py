"""
"Questions to ask the seller": one checklist that joins the two halves of the report.

  1. Questions from this car's own findings (mileage drops, dangerous defects, repeated
     warnings, gaps), quoting the record.
  2. This car's latest advisories, cross-referenced with the areas its model fails on more
     often than other cars of its age (from the comparison marts). A brake advisory on a
     model with a brake weakness is worth more attention than either fact alone.
  3. The model's other weak spots, with a practical check for a viewing.
  4. Questions for any used car.

Advisories are matched to defect categories through their MOT manual reference: the
"1" in "(1.1.13 (a))" is section 1 of the manual, Brakes. Only tests from 20 May 2018 are
used, when the current manual numbering started. Category names come from DVSA's data,
so they're matched on keywords; if one doesn't match, that link is left out, not guessed.
"""

import re
from datetime import date

NEW_MANUAL_FROM = date(2018, 5, 20)
MANUAL_REF = re.compile(r"\((\d+)\.\d")
MAX_LATEST_ADVISORIES = 3
MAX_WEAK_SPOTS = 3

# MOT inspection manual sections for cars, and words that identify the matching category
SECTION_KEYWORDS = {
    1: ("brake",),
    2: ("steering",),
    3: ("visibility", "windscreen", "wiper"),
    4: ("lamp", "light", "electrical"),
    5: ("axle", "wheel", "tyre", "suspension"),
    6: ("body", "chassis", "structure"),
    7: ("seat belt", "restraint", "other equipment"),
    8: ("nuisance", "emission", "exhaust", "noise"),
}

# something a buyer can actually do at a viewing, for each kind of weak spot
PRACTICAL_CHECKS = [
    (("brake",), "On the test drive, check it stops straight without grinding, and that the handbrake holds on a slope."),
    (("tyre", "wheel", "axle", "suspension"), "Look at the tread on all four tyres, and listen for knocks over bumps."),
    (("lamp", "light", "electrical"), "Check every light works, including the brake lights, indicators and number plate light."),
    (("steering",), "Check the steering has no play and the car doesn't pull to one side."),
    (("visibility", "windscreen", "wiper"), "Look for chips in the windscreen, and check the wipers and washers work."),
    (("body", "chassis", "structure"), "Look underneath for rust, especially around the sills and suspension mounts."),
    (("nuisance", "emission", "exhaust", "noise"), "Watch for smoke from the exhaust when the engine starts and when you accelerate."),
    (("seat belt", "restraint"), "Check every seat belt pulls out, locks and goes back in properly."),
]

FOR_ANY_CAR = [
    "Can I see the V5C logbook? The keeper's name and address should match the seller's, and the VIN on it should match the car.",
    "Is there any outstanding finance on the car? A paid history check can confirm it.",
    "Can I see the service history, and receipts for any recent work?",
]


def _day(d):
    return d.strftime("%d %b %Y")


def manual_section(text):
    match = MANUAL_REF.search(text or "")
    return int(match.group(1)) if match else None


def category_for_section(section, categories):
    keywords = SECTION_KEYWORDS.get(section, ())
    for category in categories:
        if any(k in category.lower() for k in keywords):
            return category
    return None


def practical_check(category):
    name = category.lower()
    for keywords, advice in PRACTICAL_CHECKS:
        if any(k in name for k in keywords):
            return advice
    return f"Ask a mechanic to look at the {name} in particular."


def _finding_question(finding, tests_by_number):
    ev = finding["evidence"]
    days = [_day(date.fromisoformat(e["date"])) for e in ev]
    code = finding["code"]
    if code == "mileage_decrease":
        before, after = (tests_by_number.get(e["test_number"], {}).get("miles") for e in ev[:2])
        if before is None or after is None:
            return (f"The recorded mileage went down between {days[0]} and {days[1]}. "
                    "Why, and is there paperwork that explains it?")
        return (f"The recorded mileage fell from {before:,} on {days[0]} to {after:,} on {days[1]}. "
                "Why, and is there paperwork that explains it?")
    if code == "dangerous_defect":
        return (f"The MOT on {days[0]} recorded a dangerous defect: “{finding['subject']}”. "
                "Can I see the receipt for the repair?")
    if code == "repeated_advisory":
        return (f"“{finding['subject']}” was noted at {len(ev)} MOTs. "
                "Has it been fixed, and is there a receipt?")
    if code == "test_gap":
        return (f"There's no MOT between {days[0]} and {days[-1]}. "
                "Was the car declared off the road (SORN), stored, or used without an MOT?")
    return None


def build_checklist(report, comparison):
    """report: from analysis.build_report. comparison: from comparison.build_comparison
    (may be None or not found). Returns the groups of questions for the template."""
    from .analysis import normalise_defect_text

    tests = report["tests"]
    by_number = {t["test_number"]: t for t in tests}
    found = comparison if comparison and comparison.get("found") else None
    weak_spots = list(found["weak_spots"]) if found else []
    label = f"{found['first_use_year']} {found['plural']}" if found else ""
    year = found["first_use_year"] if found else None

    from_history = []
    for finding in report["findings"]:
        question = _finding_question(finding, by_number)
        if question:
            from_history.append({"text": question, "serious": finding["severity"] == "high"})

    # the latest test's advisories, linked to the model's weak spots where they match
    already_asked = {f.get("subject", "").lower() for f in report["findings"]}
    used_spots = set()
    latest_items = []
    latest = tests[-1] if tests else None
    if latest and latest["date"].date() >= NEW_MANUAL_FROM:
        for defect in latest["defects"]:
            if len(latest_items) >= MAX_LATEST_ADVISORIES:
                break
            if str(defect.get("type", "")).upper() not in ("ADVISORY", "MINOR"):
                continue
            subject = normalise_defect_text(defect.get("text")).capitalize()
            if not subject or subject.lower() in already_asked:
                continue
            already_asked.add(subject.lower())
            spot = category_for_section(manual_section(defect.get("text")), weak_spots)
            if spot:
                used_spots.add(spot)
                latest_items.append({"text": (
                    f"Its last MOT ({_day(latest['date'])}) noted “{subject}”, and {label} fail on "
                    f"{spot.lower()} more often than other {year} cars. Has it been fixed? "
                    "Worth having it checked either way."), "linked": True})
            else:
                latest_items.append({"text": (
                    f"Its last MOT ({_day(latest['date'])}) noted “{subject}”. Has it been fixed?"),
                    "linked": False})
    # questions linked to a weak spot first: they combine both kinds of evidence
    latest_items.sort(key=lambda item: not item["linked"])

    model_items = [{"text": f"{label} fail on {spot.lower()} more often than other {year} cars. "
                            f"{practical_check(spot)}"}
                   for spot in weak_spots if spot not in used_spots][:MAX_WEAK_SPOTS]

    return {
        "from_history": from_history + [{"text": i["text"], "serious": False, "linked": i["linked"]}
                                        for i in latest_items],
        "from_model": model_items,
        "for_any_car": FOR_ANY_CAR,
        "model_label": label,
    }
