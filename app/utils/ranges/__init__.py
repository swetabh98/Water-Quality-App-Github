# app/utils/ranges/__init__.py
"""
Jindal Steel | Range extractors package

Re-exports per-department row extractors and provides a small dispatcher
so callers can do get_extractor("SMS-2") -> extract_sms2, etc.
"""

from .sms2_range import extract_rows as extract_sms2
from .sms3_range import extract_rows as extract_sms3
from .plate_range import extract_rows as extract_plate
from .rail_range import extract_rows as extract_rail
from .spm_range  import extract_rows as extract_spm
from .power_range import extract_rows as extract_power

__all__ = [
    "extract_sms2",
    "extract_sms3",
    "extract_plate",
    "extract_rail",
    "extract_spm",
    "extract_power",
    "get_extractor",
]

def _norm_key(dept_name: str) -> str:
    """lowercase, strip spaces/hyphens/underscores to stabilize lookups."""
    return (dept_name or "").lower().replace(" ", "").replace("-", "").replace("_", "")

# Primary exact-map (after normalization)
_MAP = {
    "sms2": extract_sms2,
    "sms3": extract_sms3,
    "platemill": extract_plate,
    "railmill": extract_rail,
    "spm": extract_spm,
    "powerplant": extract_power,
    "power": extract_power,
}

# Common synonyms seen in UIs / logs
_SYNONYMS = {
    "platemilldivision": "platemill",
    "specialprofilemill": "spm",
    "spmdivision": "spm",
    "rail": "railmill",
    "raildivision": "railmill",
    "powerplantdivision": "powerplant",
    "powerdivision": "powerplant",
}

def get_extractor(dept_name: str):
    """
    Return the appropriate extract_rows function for a department label.
    Accepts flexible inputs like 'SMS-2', 'Plate Mill Division', 'Power Plant', etc.
    """
    k = _norm_key(dept_name)

    # synonym redirect
    k = _SYNONYMS.get(k, k)

    func = _MAP.get(k)
    if func:
        return func

    # forgiving fallback: startswith checks (covers e.g. 'platemilldept')
    if k.startswith("sms2"):
        return extract_sms2
    if k.startswith("sms3"):
        return extract_sms3
    if k.startswith("platemill"):
        return extract_plate
    if k.startswith("railmill") or k.startswith("rail"):
        return extract_rail
    if k.startswith("spm") or k.startswith("specialprofilemill"):
        return extract_spm
    if k.startswith("powerplant") or k.startswith("power"):
        return extract_power

    return None
