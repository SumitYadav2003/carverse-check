import re

from django.shortcuts import redirect, render
from django.urls import reverse

from .analysis import build_report
from .presenters import present
from .services import get_vehicle

PLATE_RE = re.compile(r"^[A-Z0-9]{1,8}$")


def normalise_plate(raw):
    return re.sub(r"\s+", "", raw or "").upper()


def home(request):
    return render(request, "checker/home.html")


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
    vehicle, source = get_vehicle(plate)
    if vehicle is None:
        return render(request, "checker/not_found.html", {"plate": plate}, status=404)
    context = present(build_report(vehicle), source)
    return render(request, "checker/report.html", context)
