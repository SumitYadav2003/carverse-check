"""Where vehicle data comes from: the sample cars, or the live DVSA MOT history API."""

from . import dvsa
from .sample_data import load_sample

SOURCE_SAMPLE = "sample"
SOURCE_DVSA = "dvsa"


def get_vehicle(registration):
    """Return (vehicle, source), or (None, None) if there is no such vehicle.

    Raises dvsa.DvsaUnavailable when DVSA can't answer right now.
    """
    vehicle = load_sample(registration)
    if vehicle is not None:
        return vehicle, SOURCE_SAMPLE
    if not dvsa.is_configured():
        return None, None
    try:
        return dvsa.get_vehicle(registration), SOURCE_DVSA
    except dvsa.VehicleNotFound:
        return None, None
