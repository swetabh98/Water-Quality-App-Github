# app/utils/ranges/power_range.py
"""
Power Plant range row extractor (Jindal)

Emits rows for the central checker:
    {"page": "power_plant_report.html", "system": <system>, "parameter": <param>, "value": <num>}

Matches inputs from power_plant_report.html:
  Feed Water:
    power_plant_feed_<PP1|PP2X55|PH2X25|PP3x25>_<Param>[_value]
  Condensate Water:
    power_plant_condensate_<PP1|PP2X55|PH2X25|PP3x25>_<Param>[_value]
  Industrial Cooling Water (ICW):
    power_plant_icw_<PP1|PP2X55|PH2X25|PP3x25>_<Param>[_value]

IMPORTANT: Power Plant JSON uses PP-specific tokens:
  Feed/Condensate:  pH->ph, Hard->hard, Conductivity->conductivity, SiO2->sio2, N2H4->n2h4, App.->app
  ICW:              pH->ph, T.- Hard->thard, Ca- Hard->cahard, Mg- Hard->mghard, Alk.->alk,
                    Conductivity->conductivity, TDS->tds, Cl- -> cl, Turbidity->turbidity,
                    SiO2->sio2, PO4-3->po43, COC->coc
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

# Keep this page key; your range loader normalizes it internally
PAGE = "power_plant_report.html"

# ----------------------------- helpers ------------------------------------ #

_NUM_PAT = re.compile(r"(?:(?:\d+(?:\.\d+)?)|(?:\d*\.\d+))")

def _coerce_float(token: Any) -> Optional[float]:
    """Best-effort numeric detector; tolerates typos like '9.F5' -> 9.55."""
    if token is None:
        return None
    s = str(token).replace("F", "5").replace("f", "5").strip()
    m = _NUM_PAT.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None

SECTION_TO_SYSTEM = {
    "feed": "Feed Water",
    "condensate": "Condensate Water",
    "icw": "Industrial Cooling Water",
}

# Accept names saved with or without the trailing "_value" (DB stores without)
RE_NAME = re.compile(
    r"^power_plant_(?P<section>feed|condensate|icw)_(?P<unit>PP1|PP2X55|PH2X25|PP3x25)_(?P<label>.+?)(?:_value)?$",
    re.IGNORECASE,
)

def _canon_param(section: str, label: str) -> Optional[str]:
    """
    Map UI labels to the exact tokens used in param_ranges_clean.json (Power Plant block).
    """
    raw = (label or "").strip()

    FEED_COND_MAP = {
        "pH": "ph",
        "Hard": "hard",
        "Conductivity": "conductivity",
        "SiO2": "sio2",
        "N2H4": "n2h4",
        "App.": "app",  # non-numeric; will be skipped by numeric check below
    }
    ICW_MAP = {
        "pH": "ph",
        "T.- Hard": "thard",
        "Ca- Hard": "cahard",
        "Mg- Hard": "mghard",
        "Alk.": "alk",
        "Conductivity": "conductivity",
        "TDS": "tds",
        "Cl-": "cl",
        "Turbidity": "turbidity",
        "SiO2": "sio2",
        "PO4-3": "po43",
        "COC": "coc",
    }

    # Exact hits first
    if section in ("feed", "condensate"):
        if raw in FEED_COND_MAP:
            return FEED_COND_MAP[raw]
    elif section == "icw":
        if raw in ICW_MAP:
            return ICW_MAP[raw]

    # Defensive fallbacks for tiny label variations
    n = re.sub(r"\s+", " ", raw).strip().lower()

    common = {
        "ph": "ph",
        "conductivity": "conductivity",
        "tds": "tds",
        "turbidity": "turbidity",
        "coc": "coc",
        "sio2": "sio2",
        "n2h4": "n2h4",
        "app.": "app",
        "app": "app",
        "cl-": "cl",
        "po4-3": "po43",
        "po43": "po43",
    }
    if n in common:
        return common[n]

    if section in ("feed", "condensate"):
        if n == "hard":
            return "hard"
        return None

    if section == "icw":
        # Normalize hyphen spacing
        n = n.replace("t.-hard", "t.- hard").replace("ca-hard", "ca- hard").replace("mg-hard", "mg- hard")
        icw_fallbacks = {
            "t.- hard": "thard",
            "ca- hard": "cahard",
            "mg- hard": "mghard",
            "alk.": "alk",
            "alk": "alk",
        }
        return icw_fallbacks.get(n)

    return None

# ----------------------------- extractor ---------------------------------- #

def extract_rows(report_obj: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not hasattr(report_obj, "sections"):
        return rows

    for sec in getattr(report_obj, "sections", []):
        for p in getattr(sec, "parameters", []) or []:
            name = getattr(p, "name", "") or ""
            value = getattr(p, "value", None)

            # Only numeric actuals participate in range checks (App. is text and will be skipped)
            if _coerce_float(value) is None:
                continue

            m = RE_NAME.match(name)
            if not m:
                continue

            section = m.group("section").lower()
            label = m.group("label")

            system = SECTION_TO_SYSTEM.get(section)
            if not system:
                continue

            param_key = _canon_param(section, label)
            if not param_key:
                # Unknown / not range-checked label
                continue

            rows.append({
                "page": PAGE,
                "system": system,
                "parameter": param_key,
                "value": value,
            })

    return rows
