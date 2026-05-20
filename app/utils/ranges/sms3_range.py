# app/utils/ranges/sms3_range.py
"""
SMS-3 range row extractor.

Emits rows consumed by the central checker, shaped as:
    {"page": "sms3_report.html", "system": <system>, "parameter": <param>, "value": <num>}

Covers:
  • ICW & DCW SYSTEM       → inputs named: sms3_icw_<URLENCODED_SYSTEM>_<Param>[_value]
  • CLOSE LOOP (PRIMARY)   → inputs named: sms3_closeloop_<URLENCODED_SYSTEM>_<Param>[_value]

Key fixes vs earlier versions:
  1) Map form system names to the JSON’s canonical keys by appending " (ICW)"
     or " (Closed Loop)" where required (e.g., "Raw Water" → "Raw Water (ICW)",
     "EAF" → "EAF (Closed Loop)"), so ranges resolve correctly.
  2) Use urllib.parse.unquote_plus() to decode '+' as space from |urlencode.
  3) Non-greedy system capture in regex so underscores in param tokens never
     confuse the split.
  4) Comprehensive param canonicalization aligned to param_ranges_clean.json.

Non-numeric / empty cells and sections without ranges (consumption, chemical,
scale pit) are ignored by design.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote_plus

PAGE = "sms3_report.html"

# ----------------------------- helpers ------------------------------------ #

_NUM_PAT = re.compile(r"(?:(?:\d+(?:\.\d+)?)|(?:\d*\.\d+))")

def _coerce_float(token: Any) -> Optional[float]:
    """Detect/coerce numerics; tolerant to minor typos like '9.F5' -> 9.55."""
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

# Canonical parameter tokens used by the ranges JSON
_PARAM_ALIAS = {
    "ph": "ph",
    "th": "th",
    "cah": "cah",
    "mgh": "mgh",
    "p-alk": "palk",
    "m-alk": "malk",
    "chloride": "chloride",
    "conductivity": "conductivity",
    "turbidity": "turbidity",
    "tss": "tss",
    "tds": "tds",
    "iron": "iron",
    "oil/grease": "oilgrease",
    "zinc": "zinc",
    "phosphate": "phosphate",
    "coc": "coc",
    "silica": "silica",
    "nitrite": "nitrite",
}

def _canon_param(label: str) -> Optional[str]:
    n = (label or "").strip().lower()
    # keep slashes/hyphens that matter; normalize dot variants from headers
    n = n.replace(" ", "")
    if n in ("palk", "p-alk"): n = "p-alk"
    if n in ("malk", "m-alk"): n = "m-alk"
    if n == "oilgrease": n = "oil/grease"
    return _PARAM_ALIAS.get(n)

# ------------------------ system name canonicalization --------------------- #
# Map the display system names in the form to the exact JSON keys.

# ICW/DCW table → must include " (ICW)" in JSON
_ICW_SYSTEM_MAP = {
    "Raw Water": "Raw Water (ICW)",
    "CT-1 (EAF)": "CT-1 (EAF) (ICW)",
    "CT-2 (Spray)": "CT-2 (Spray) (ICW)",
    "CT-3 (VD)": "CT-3 (VD) (ICW)",
    "CT-4 (Billet)": "CT-4 (Billet) (ICW)",
}

# Close Loop table → must include " (Closed Loop)" in JSON
_CLOSE_SYSTEM_MAP = {
    "SOFT WATER": "SOFT WATER (Closed Loop)",
    "EAF": "EAF (Closed Loop)",
    "COMBI": "COMBI (Closed Loop)",
    "BILLET": "BILLET (Closed Loop)",
}

def _canon_system_icw(system_label: str) -> Optional[str]:
    s = _norm_space(system_label)
    return _ICW_SYSTEM_MAP.get(s)

def _canon_system_close(system_label: str) -> Optional[str]:
    s = _norm_space(system_label)
    return _CLOSE_SYSTEM_MAP.get(s)

# ----------------------------- patterns ----------------------------------- #

ICW_PARAMS = [
    "pH","TH","CaH","MgH","P-Alk","M-Alk","Chloride","Conductivity","Turbidity",
    "TSS","TDS","Iron","Oil/Grease","Zinc","Phosphate","COC","Silica",
]
CLOSE_PARAMS = [
    "pH","TH","CaH","MgH","P-Alk","M-Alk","Chloride","Conductivity",
    "Turbidity","TSS","TDS","Nitrite",
]

_icw_alt   = "|".join(map(re.escape, ICW_PARAMS))
_close_alt = "|".join(map(re.escape, CLOSE_PARAMS))

# Non-greedy system capture; accept optional "_value" suffix; never match "_range".
RE_ICW   = re.compile(rf"^sms3_icw_(?P<system>.+?)_(?P<param>{_icw_alt})(?:_value)?$")
RE_CLOSE = re.compile(rf"^sms3_closeloop_(?P<system>.+?)_(?P<param>{_close_alt})(?:_value)?$")

# ----------------------------- extractor ---------------------------------- #

def extract_rows(report_obj: Any) -> List[Dict[str, Any]]:
    """
    Extract SMS-3 rows for range checking from the saved report object.
    Returns a list of dicts: {"page", "system", "parameter", "value"}.
    """
    rows: List[Dict[str, Any]] = []
    if not hasattr(report_obj, "sections"):
        return rows

    for sec in getattr(report_obj, "sections", []):
        for p in getattr(sec, "parameters", []) or []:
            name  = getattr(p, "name", "") or ""
            value = getattr(p, "value", None)

            # only numeric "Actual" cells participate in range checks
            if _coerce_float(value) is None:
                continue

            m_icw   = RE_ICW.match(name)
            m_close = RE_CLOSE.match(name)
            if not (m_icw or m_close):
                continue

            if m_icw:
                sys_enc     = m_icw.group("system")
                param_label = m_icw.group("param")
                # URL-decode, including '+' → space
                system_disp = _norm_space(unquote_plus(sys_enc))
                system_key  = _canon_system_icw(system_disp)
            else:
                sys_enc     = m_close.group("system")
                param_label = m_close.group("param")
                system_disp = _norm_space(unquote_plus(sys_enc))
                system_key  = _canon_system_close(system_disp)

            if not system_key:
                # Unknown/unsupported system label → skip defensively
                continue

            param_key = _canon_param(param_label)
            if not param_key:
                continue

            rows.append({
                "page": PAGE,
                "system": system_key,   # exact JSON key, e.g. "Raw Water (ICW)"
                "parameter": param_key, # canonical token, e.g. "conductivity"
                "value": value,
            })

    return rows
