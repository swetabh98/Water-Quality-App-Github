# app/utils/ranges/sms2_range.py
"""
SMS-2 range row extractor.

Reads the saved report object's parameters and returns rows in the exact shape
expected by range_notifications.check_report_values():

    {"page": <page_key>, "system": <system>, "parameter": <param>, "value": <num>}

Covers the two SMS-2 tabs that have enforceable ranges:
- icw_dcw.html
- ccm_eaf.html

Notes:
- System names are URL-encoded in the HTML input names; we URL-decode them here.
- We DO NOT include non-numeric or empty values.
- Parameter names are normalized to the canonical tokens used in the ranges JSON.
- We intentionally ignore the other three SMS-2 tabs per your note (no range checks).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_NUM_PAT = re.compile(r"(?:(?:\d+(?:\.\d+)?)|(?:\d*\.\d+))")

def _coerce_float(token: Any) -> Optional[float]:
    """Best-effort numeric coercion used only to decide if a cell is numeric."""
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
    return re.sub(r"\s{2,}", " ", s).strip()

# Canonical parameter tokens used in param_ranges_clean.json
# (right-hand side must match your JSON or its canonicalization in range code)
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
    "iron": "iron",
    "coc": "coc",
    "tds": "tds",
    # --- IMPORTANT: keep phosphate family as 'po4' to match JSON keys
    "po4": "po4",
    "phosphate": "po4",
    "o-phosphate": "po4",
    "nitrite": "nitrite",
    "tbc": "tbc",
    "srb": "srb",
}

def _canon_param(label: str) -> Optional[str]:
    n = (label or "").strip().lower()
    # unify various spellings from the HTML headers
    n = n.replace(" ", "").replace(".", "")
    # common synonyms
    if n in ("palk", "p-alk"):
        n = "p-alk"
    if n in ("malk", "m-alk"):
        n = "m-alk"
    if n in ("po4", "o-phosphate", "phosphate"):
        n = "po4"
    return _PARAM_ALIAS.get(n)

# --------------------------------------------------------------------------- #
# Regex patterns that precisely match the SMS-2 inputs as rendered by Jinja
#    icw_dcw_<URLENCODED_SYSTEM>_<Param>[_value]
#    ccm_eaf_<URLENCODED_SYSTEM>_<Param>[_value]
# We anchor the final token to the known set of parameter captions from HTML.
# --------------------------------------------------------------------------- #

_ICW_DCW_PARAMS = [
    "pH", "TH", "CaH", "MgH", "P-Alk", "M-Alk", "Chloride",
    "Conductivity", "Turbidity", "TSS", "Iron", "COC", "TDS", "PO4",
]
_CCM_EAF_PARAMS = [
    "pH", "TH", "P-Alk", "M-Alk", "Chloride", "Conductivity",
    "Turbidity", "TSS", "Nitrite", "Iron", "TDS", "TBC", "SRB",
]

# build safe alternations (case-sensitive as per HTML)
_icw_param_alt = "|".join(map(re.escape, _ICW_DCW_PARAMS))
_ccm_param_alt = "|".join(map(re.escape, _CCM_EAF_PARAMS))

RE_ICW = re.compile(rf"^icw_dcw_(?P<system>.+)_(?P<param>{_icw_param_alt})(?:_value)?$")
RE_CCM = re.compile(rf"^ccm_eaf_(?P<system>.+)_(?P<param>{_ccm_param_alt})(?:_value)?$")

# Page keys in your JSON
PAGE_ICW = "icw_dcw.html"
PAGE_CCM = "ccm_eaf.html"

# --------------------------------------------------------------------------- #
# Public extractor
# --------------------------------------------------------------------------- #

def extract_rows(report_obj: Any) -> List[Dict[str, Any]]:
    """
    Extract SMS-2 rows for range checking from the saved report object.
    Returns a list of dicts: {"page", "system", "parameter", "value"}
    """
    rows: List[Dict[str, Any]] = []

    if not hasattr(report_obj, "sections"):
        return rows

    # Iterate through persisted parameters
    for sec in getattr(report_obj, "sections", []):
        for p in getattr(sec, "parameters", []) or []:
            name = getattr(p, "name", "") or ""
            value = getattr(p, "value", None)

            # only consider numeric "Actual" cells
            if _coerce_float(value) is None:
                continue

            m_icw = RE_ICW.match(name)
            m_ccm = RE_CCM.match(name)

            if not (m_icw or m_ccm):
                continue

            if m_icw:
                sys_enc = m_icw.group("system")
                param_label = m_icw.group("param")
                page = PAGE_ICW
            else:
                sys_enc = m_ccm.group("system")
                param_label = m_ccm.group("param")
                page = PAGE_CCM

            # URL-decode the system text coming from |urlencode
            system = unquote(sys_enc)
            # Strip any accidental UI tokens (defensive)
            system = re.sub(r"\b(?:Actual|Range|LIMIT)\b", "", system, flags=re.I)
            system = _norm_space(system)

            # Canonicalize parameter token to JSON key
            param_key = _canon_param(param_label)
            if not param_key:
                # Unknown parameter caption; skip defensively
                continue

            rows.append({
                "page": page,
                "system": system,
                "parameter": param_key,
                "value": value,
            })

    return rows
