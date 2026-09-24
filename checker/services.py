"""Where vehicle data comes from.

For now this reads the sample vehicles. When DVSA access arrives, a live
lookup gets added here and nothing else in the app has to change.
"""

from .sample_data import load_sample

SOURCE_SAMPLE = "sample"


def get_vehicle(registration):
    """Return (vehicle, source) for a registration, or (None, None) if not found."""
    vehicle = load_sample(registration)
    if vehicle is not None:
        return vehicle, SOURCE_SAMPLE
    return None, None
