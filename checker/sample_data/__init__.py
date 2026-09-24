"""Sample vehicles in the DVSA MOT history API format, used until live API access is set up.
The registrations (SAMPLE1-3) are deliberately not real number plates."""

import json
from pathlib import Path

SAMPLE_DIR = Path(__file__).parent


def load_sample(registration):
    """Return the sample vehicle for a registration, or None if there isn't one."""
    path = SAMPLE_DIR / f"{registration.strip().replace(' ', '').lower()}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
