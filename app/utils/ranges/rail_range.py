# app/utils/ranges/rail_range.py
"""
Rail Mill range row extractor.

From the saved report object, emits rows shaped for the range checker:
    {"page": "rail_mill_report.html", "system": <system>, "parameter": <param>, "value": <num>}

Matches inputs created by rail_mill_report.html:
  name="rail_mill_<URLENCODED_SYSTEM>_<DB_KEY>_value"
where <DB_KEY> is one of:
  pH, Cond, Turb, TH, CaH, MgH, Chloride, M-Alk, Nitrite, IRON, Silica,
  TDS, TSS, Oil_and_Grease, Zinc, Phosphate, Remark

Notes:
- URL-decodes the system so it aligns with JSON keys (e.g., "ICW Mill").
- Canonicalizes parameter tokens to your JSON schema (e.g., "Cond" -> "conductivity",
  "M-Alk" -> "malk", "Oil_and_Grease" -> "oilgrease", "IRON" -> "iron").
- Skips non-numeric cells and the free-text "Remark".
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

PAGE = "rail_mill_report.html"

# ----------------------------- helpers ------------------------------------ #

_NUM_PAT = re.compile(r"(?:(?:\d+(?:\.\d+)?)|(?:\d*\.\d+))")

def _coerce_float(token: Any) -> Optional[float]:
    """Lightweight numeric detector (also tolerates '9.F5' -> 9.55 pattern)."""
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

def _norm_space(s: str) -> str:
    return re.sub(r"\s{2,}", " ", str(s)).strip()

# Canonical parameter tokens as used by param_ranges_clean.json
_PARAM_ALIAS = {
    "ph": "ph",
    "cond": "conductivity",
    "turb": "turbidity",
    "th": "th",
    "cah": "cah",
    "mgh": "mgh",
    "chloride": "chloride",
    "m-alk": "malk",
    "nitrite": "nitrite",
    "iron": "iron",
    "silica": "silica",
    "tds": "tds",
    "tss": "tss",
    "oil_and_grease": "oilgrease",
    "zinc": "zinc",
    "phosphate": "phosphate",
    # "remark" is intentionally not mapped (free text)
}

def _canon_param(label: str) -> Optional[str]:
    n = label.strip()
    # normalize a few spellings/cases seen in the HTML <-> DB keys
    if n.lower() == "ph":
        key = "ph"
    elif n.lower() == "cond":
        key = "cond"
    elif n.lower() == "turb":
        key = "turb"
    elif n.lower() in ("th", "cah", "mgh", "chloride", "nitrite", "silica", "tds", "tss", "zinc", "phosphate"):
        key = n.lower()
    elif n in ("M-Alk", "m-alk", "M-ALK"):
        key = "m-alk"
    elif n.upper() == "IRON":
        key = "iron"
    elif n == "Oil_and_Grease":
        key = "oil_and_grease"
    elif n.lower() == "remark":
        return None
    else:
        # Fallback: lower it and try direct map (defensive)
        key = n.lower()
    return _PARAM_ALIAS.get(key)

# Accept optional "_value" suffix; never matches "_range"
PARAM_ALT = (
    "pH|Cond|Turb|TH|CaH|MgH|Chloride|M-Alk|Nitrite|IRON|Silica|TDS|TSS|"
    "Oil_and_Grease|Zinc|Phosphate|Remark"
)
RE_ROW = re.compile(rf"^rail_mill_(?P<system>.+)_(?P<param>{PARAM_ALT})(?:_value)?$")

# ----------------------------- extractor ---------------------------------- #

def extract_rows(report_obj: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not hasattr(report_obj, "sections"):
        return rows

    for sec in getattr(report_obj, "sections", []):
        for p in getattr(sec, "parameters", []) or []:
            name = getattr(p, "name", "") or ""
            value = getattr(p, "value", None)

            # Only numeric actuals participate in range checks
            if _coerce_float(value) is None:
                continue

            m = RE_ROW.match(name)
            if not m:
                continue

            sys_enc = m.group("system")
            param_label = m.group("param")

            # Skip free-text Remark column
            canonical_param = _canon_param(param_label)
            if not canonical_param:
                continue

            system = _norm_space(unquote(sys_enc))

            rows.append({
                "page": PAGE,
                "system": system,
                "parameter": canonical_param,
                "value": value,
            })

    return rows
