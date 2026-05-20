# app/utils/range_loader.py
import json, os, re
from functools import lru_cache

RANGE_JSON_RELATIVE_PATH = os.path.join("app_config", "param_ranges_clean.json")

# --- helpers ---------------------------------------------------------------

def _norm(s: str) -> str:
    """Lowercase, strip, remove spaces/underscores/dashes/units—good for fuzzy keys."""
    if s is None:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[^\w\s]", "", s)               # drop punctuation
    s = s.replace(" ", "").replace("_", "").replace("-", "")
    # common unit tails (optional)
    s = re.sub(r"(ppm|ppb|ntu|mgl|mgdl|μs|us|degc|c)$", "", s)
    return s

def _parse_range_str(rng: str):
    """
    Parse strings like:
      '6.5–8.5', '6.5-8.5', '≥7.0', '<= 50', '≤50', '>= 2', 'max 500', 'min 6.5'
    into (low, high) floats (None if open).
    """
    if not rng:
        return (None, None)
    s = rng.strip()
    s = s.replace("–", "-").replace("—", "-")  # normalize dashes
    s = s.replace("≤", "<=").replace("≥", ">=")

    # between, e.g. 6.5 - 8.5
    m = re.match(r"^\s*(\d+(\.\d+)?)\s*-\s*(\d+(\.\d+)?)\s*$", s)
    if m:
        return (float(m.group(1)), float(m.group(3)))

    # <= X or >= X
    m = re.match(r"^\s*(<=|>=|<|>)\s*(\d+(\.\d+)?)\s*$", s)
    if m:
        op, val = m.group(1), float(m.group(2))
        if op in ("<", "<="):
            return (None, val)
        else:
            return (val, None)

    # "max 500" / "min 6.5"
    m = re.match(r"^\s*(max|min)\s*(\d+(\.\d+)?)\s*$", s, re.I)
    if m:
        t, val = m.group(1).lower(), float(m.group(2))
        return (None, val) if t == "max" else (val, None)

    # lone number → treat as max
    m = re.match(r"^\s*(\d+(\.\d+)?)\s*$", s)
    if m:
        return (None, float(m.group(1)))

    return (None, None)

# --- loader / API ----------------------------------------------------------

@lru_cache(maxsize=1)
def _load_json(abs_path: str):
    with open(abs_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _resolve_json_path(flask_app_root: str) -> str:
    return os.path.join(flask_app_root, RANGE_JSON_RELATIVE_PATH)

def init_ranges(flask_app_root: str):
    """Call once at startup if you want to warm the cache."""
    _load_json(_resolve_json_path(flask_app_root))

def get_range(flask_app_root: str, department: str, page: str, system: str, param: str):
    """
    Primary lookup: exact dept → page → system → param.
    Fallback 1: dept → page → param.
    Fallback 2: dept → param.
    Returns dict: {"low": float|None, "high": float|None, "raw": "original string"} or None.
    """
    data = _load_json(_resolve_json_path(flask_app_root))
    if not (department and param):
        return None

    n_dept  = _norm(department)
    n_page  = _norm(page or "")
    n_sys   = _norm(system or "")
    n_param = _norm(param)

    def scan_level(obj):
        # search by fuzzy key at this level
        for k, v in obj.items():
            if _norm(k) == n_param and isinstance(v, str):
                lo, hi = _parse_range_str(v)
                return {"low": lo, "high": hi, "raw": v}
        return None

    # Dept level
    for dept_key, dept_val in (data or {}).items():
        if _norm(dept_key) != n_dept or not isinstance(dept_val, dict):
            continue

        # Page → System → Param
        if page:
            for page_key, page_val in dept_val.items():
                if _norm(page_key) != n_page or not isinstance(page_val, dict):
                    continue

                # system present?
                if system and isinstance(page_val.get(system, {}), dict):
                    hit = scan_level(page_val[system])
                    if hit: return hit

                # fuzzy system search
                for sys_key, sys_val in page_val.items():
                    if isinstance(sys_val, dict) and _norm(sys_key) == n_sys:
                        hit = scan_level(sys_val)
                        if hit: return hit

                # fallback at page → param
                hit = scan_level(page_val)
                if hit: return hit

        # fallback at dept → param
        hit = scan_level(dept_val)
        if hit: return hit

    return None
