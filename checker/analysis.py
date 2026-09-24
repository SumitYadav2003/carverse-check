"""
Analysis of a vehicle's MOT history.

Input: one vehicle record in the DVSA MOT history API format
(vehicle fields plus a "motTests" list, newest test first).
Output: a report dict with the vehicle summary, the tests in date order,
and a list of findings. Every finding carries "evidence": the MOT test
numbers and dates it is based on, so any claim shown to the user (or
written by the AI summary later) can be traced back to a DVSA record.

This module has no Django imports on purpose, so it can be tested and
reused on its own (for example by the bulk-data pipeline later).
"""

import re
from datetime import datetime

KM_TO_MILES = 0.621371

# A normal MOT gap is about 12 months (a test can be done up to a month early).
# Longer than this and we point it out.
GAP_THRESHOLD_DAYS = 426  # roughly 14 months

HIGH = "high"
MEDIUM = "medium"
INFO = "info"


# ---------- parsing ----------

def parse_datetime(value):
    """Parse DVSA dates. Handles '2016-06-21 11:26:02', '2013.11.03 09:33:08',
    '2023-11-03T09:33:08.000Z' and plain dates like '2017-06-28'."""
    if not value:
        return None
    text = value.strip().replace("T", " ")
    date_part = text[:10].replace(".", "-")
    time_part = text[11:19] if len(text) >= 19 else "00:00:00"
    return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")


def mileage_in_miles(test):
    """Return the odometer reading in miles, or None if it wasn't readable."""
    if test.get("odometerResultType", "READ") != "READ":
        return None
    raw = test.get("odometerValue")
    if raw in (None, ""):
        return None
    value = int(raw)
    if str(test.get("odometerUnit", "MI")).upper() == "KM":
        value = round(value * KM_TO_MILES)
    return value


def normalise_defect_text(text):
    """Make the same advisory comparable across years:
    drop the MOT manual reference at the end, e.g. ' (1.1.11 (c))',
    lowercase it and tidy the spacing."""
    text = re.sub(r"\s*\(\d[\d.]*.*$", "", text or "")
    text = re.sub(r"\s+", " ", text).strip().strip(".,;").lower()
    return text


def tests_in_date_order(vehicle):
    tests = []
    for raw in vehicle.get("motTests") or []:
        tests.append({
            "test_number": str(raw.get("motTestNumber", "")),
            "date": parse_datetime(raw.get("completedDate")),
            "result": raw.get("testResult", ""),
            "expiry": parse_datetime(raw.get("expiryDate")),
            "miles": mileage_in_miles(raw),
            "odometer_status": raw.get("odometerResultType", "READ"),
            "defects": raw.get("defects") or raw.get("rfrAndComments") or [],
        })
    tests.sort(key=lambda t: t["date"])
    return tests


def evidence(test):
    return {"test_number": test["test_number"], "date": test["date"].date().isoformat()}


# ---------- checks ----------

def check_mileage_went_down(tests):
    """Flag every point where a recorded mileage is lower than the one before it."""
    findings = []
    readings = [t for t in tests if t["miles"] is not None]
    for earlier, later in zip(readings, readings[1:]):
        if later["miles"] < earlier["miles"]:
            drop = earlier["miles"] - later["miles"]
            findings.append({
                "code": "mileage_decrease",
                "severity": HIGH,
                "title": "Recorded mileage went down",
                "detail": (
                    f"Mileage was {earlier['miles']:,} at the test on "
                    f"{earlier['date']:%d %b %Y} but {later['miles']:,} on "
                    f"{later['date']:%d %b %Y}, {drop:,} miles lower. This can be a "
                    "typing error at the test centre, a replaced instrument cluster, "
                    "or a sign the mileage was wound back. Ask the seller to explain it."
                ),
                "evidence": [evidence(earlier), evidence(later)],
            })
    return findings


def check_gaps_between_tests(tests):
    """Flag long gaps with no MOT test recorded."""
    findings = []
    for earlier, later in zip(tests, tests[1:]):
        days = (later["date"] - earlier["date"]).days
        if days > GAP_THRESHOLD_DAYS:
            months = round(days / 30.44)
            findings.append({
                "code": "test_gap",
                "severity": MEDIUM,
                "title": f"No MOT recorded for about {months} months",
                "detail": (
                    f"There is no MOT test between {earlier['date']:%d %b %Y} and "
                    f"{later['date']:%d %b %Y}. The car may have been off the road "
                    "(declared SORN), or used without a valid MOT. Ask the seller why."
                ),
                "evidence": [evidence(earlier), evidence(later)],
            })
    return findings


def check_repeated_advisories(tests, min_tests=2):
    """Flag advisories that were noted at several different tests,
    i.e. warnings that were probably never fixed."""
    seen = {}  # normalised text -> {"text": original, "tests": [...]}
    for test in tests:
        texts_this_test = set()
        for defect in test["defects"]:
            if str(defect.get("type", "")).upper() != "ADVISORY":
                continue
            key = normalise_defect_text(defect.get("text"))
            if not key or key in texts_this_test:
                continue
            texts_this_test.add(key)
            entry = seen.setdefault(key, {"text": defect.get("text"), "tests": []})
            entry["tests"].append(test)

    findings = []
    for entry in seen.values():
        if len(entry["tests"]) >= min_tests:
            first, last = entry["tests"][0], entry["tests"][-1]
            findings.append({
                "code": "repeated_advisory",
                "severity": MEDIUM,
                "title": f"Same warning at {len(entry['tests'])} MOTs",
                "detail": (
                    f"\"{normalise_defect_text(entry['text']).capitalize()}\" was noted at "
                    f"{len(entry['tests'])} tests between {first['date']:%b %Y} and "
                    f"{last['date']:%b %Y}. It may never have been repaired."
                ),
                "evidence": [evidence(t) for t in entry["tests"]],
            })
    return findings


def check_dangerous_defects(tests):
    findings = []
    for test in tests:
        dangerous = [d for d in test["defects"]
                     if d.get("dangerous") or str(d.get("type", "")).upper() == "DANGEROUS"]
        for defect in dangerous:
            findings.append({
                "code": "dangerous_defect",
                "severity": HIGH,
                "title": "Dangerous defect recorded",
                "detail": (
                    f"On {test['date']:%d %b %Y} the tester recorded a dangerous defect: "
                    f"\"{normalise_defect_text(defect.get('text')).capitalize()}\". "
                    "Check it was properly repaired, ideally with a receipt."
                ),
                "evidence": [evidence(test)],
            })
    return findings


# ---------- report ----------

def build_report(vehicle):
    tests = tests_in_date_order(vehicle)
    readings = [t for t in tests if t["miles"] is not None]

    avg_miles_per_year = None
    if len(readings) >= 2:
        years = (readings[-1]["date"] - readings[0]["date"]).days / 365.25
        if years > 0:
            avg_miles_per_year = round((readings[-1]["miles"] - readings[0]["miles"]) / years)

    findings = (
        check_mileage_went_down(tests)
        + check_dangerous_defects(tests)
        + check_repeated_advisories(tests)
        + check_gaps_between_tests(tests)
    )
    # an average is meaningless if the readings themselves are inconsistent
    if any(f["code"] == "mileage_decrease" for f in findings):
        avg_miles_per_year = None

    order = {HIGH: 0, MEDIUM: 1, INFO: 2}
    findings.sort(key=lambda f: order[f["severity"]])

    return {
        "vehicle": {
            "registration": vehicle.get("registration"),
            "make": vehicle.get("make"),
            "model": vehicle.get("model"),
            "fuel_type": vehicle.get("fuelType"),
            "colour": vehicle.get("primaryColour"),
            "engine_size": vehicle.get("engineSize"),
            "first_used": parse_datetime(vehicle.get("firstUsedDate")),
        },
        "tests": tests,
        "summary": {
            "test_count": len(tests),
            "failed_count": sum(1 for t in tests if t["result"] == "FAILED"),
            "latest_miles": readings[-1]["miles"] if readings else None,
            "avg_miles_per_year": avg_miles_per_year,
        },
        "findings": findings,
    }
