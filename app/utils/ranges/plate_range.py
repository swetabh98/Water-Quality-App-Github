# app/utils/ranges/plate_range.py
"""
Plate Mill range row extractor (aligned to param_ranges_clean.json)

JSON structure (excerpt):
{
  "Plate Mill": {
    "plate_mill.html": {
      "Plate Mill (Spec)": {
        "pH": "7.2to 7.8",
        "Conductivity": "<450",
        "TDS": "<290",
        "TH": "<120",
        "Ca-H": "<72",
        "Mg-H": "<48",
        "Chloride": "<50",
        "P-Alkalinity": "NIL",
        "M-Alkalinity": "<120",
        "Silica": "<15",
        "O-Phosphate": "NA",
        "TSS": "NIL",
        "Turbidity": "<10",
        "Iron": "<0.1",
        "NITRITE": "NA",
        "COC": "NA"
      }
    }
  }
}

→ To match the JSON, ALL Plate Mill readings are emitted with:
   page="plate_mill.html", system="Plate Mill (Spec)",
   parameter exactly as shown in the HTML/JSON (e.g., "pH", "Ca-H", "O-Phosphate").

Form input names from plate_mill.html:
  POND07_ACTUAL_<Param>_value
  MAKEUP_TANK_<Param>_value
  DCW_ACTUAL_<Param>_value
  ACC_ACTUAL_<Param>_value
  FCW_ACTUAL_<Param>_value
  ICW_ACTUAL_<Param>_value
  RHF_ACTUAL_<Param>_value

We accept optional trailing "_value" and only keep numeric values.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

PAGE = "plate_mill.html"
SYSTEM = "Plate Mill (Spec)"  # SINGLE system as per param_ranges_clean.json

# ----------------------------- helpers ------------------------------------ #

_NUM_PAT = re.compile(r"(?:(?:\d+(?:\.\d+)?)|(?:\d*\.\d+))")

def _coerce_float(token: Any) -> Optional[float]:
    """Best-effort numeric detection; tolerates typos like '9.F5' -> 9.55."""
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

# Parameters exactly as shown in HTML / JSON
_PARAM_ALT = (
    r"pH|Conductivity|TDS|TH|Ca-H|Mg-H|Chloride|P-Alkalinity|M-Alkalinity|"
    r"Silica|O-Phosphate|TSS|Turbidity|Iron|NITRITE|COC"
)

# Accept any of the Plate Mill input prefixes, capture the <Param>, ignore optional _value suffix
RE_NAME = re.compile(
    rf"^(?:(?:POND07_ACTUAL|MAKEUP_TANK|DCW_ACTUAL|ACC_ACTUAL|FCW_ACTUAL|ICW_ACTUAL|RHF_ACTUAL))_(?P<param>{_PARAM_ALT})(?:_value)?$"
)

# ----------------------------- extractor ---------------------------------- #

def extract_rows(report_obj: Any) -> List[Dict[str, Any]]:
    """
    Return rows in the shape:
      {"page": "plate_mill.html", "system": "Plate Mill (Spec)", "parameter": <Param>, "value": <num>}
    Only numeric values are emitted.
    """
    rows: List[Dict[str, Any]] = []
    if not hasattr(report_obj, "sections"):
        return rows

    for sec in getattr(report_obj, "sections", []) or []:
        for p in getattr(sec, "parameters", []) or []:
            name = getattr(p, "name", "") or ""
            value = getattr(p, "value", None)

            # Only numeric cells participate in range checks
            if _coerce_float(value) is None:
                continue

            m = RE_NAME.match(name)
            if not m:
                continue

            param_label = m.group("param")  # keep exact token as in HTML/JSON

            rows.append({
                "page": PAGE,
                "system": SYSTEM,
                "parameter": param_label,
                "value": value,
            })

    return rows
