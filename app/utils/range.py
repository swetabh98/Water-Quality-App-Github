# app/utils/range.py
import json, os, re
from functools import lru_cache

RANGE_JSON_RELATIVE_PATH = os.path.join("app_config", "param_ranges_clean.json")

def _norm(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[^\w\s]", "", s)
    return s.replace(" ", "").replace("_", "").replace("-", "")

def _parse_range_str(r: str):
    """
    Parse a range string into (low, high).
    Supports:
      "6.5-8.5", "6.5 – 8.5", "<= 2000", ">= 7.0", "max 2000", "min 7.5", "2000",
      and also "6.5 to 8.5".
    Tolerates unit suffixes like "mg/L", "µS/cm", "%", etc.
    """
    if not r:
        return (None, None)

    s = r.strip()
    s = s.replace("–", "-").replace("—", "-").replace("≤", "<=").replace("≥", ">=")

    num  = r"(\d+(?:\.\d+)?)"
    unit = r"(?:[a-zA-Z/%µμ]+)?"

    m = re.match(rf"^\s*{num}\s*{unit}\s*-\s*{num}\s*{unit}\s*$", s)
    if m:
        return (float(m.group(1)), float(m.group(2)))

    m = re.match(rf"^\s*{num}\s*to\s*{num}\s*{unit}\s*$", s, re.I)
    if m:
        return (float(m.group(1)), float(m.group(2)))

    m = re.match(rf"^\s*(<=|>=|<|>)\s*{num}\s*{unit}\s*$", s)
    if m:
        op, v = m.group(1), float(m.group(2))
        if op in ("<", "<="):
            return (None, v)
        else:
            return (v, None)

    m = re.match(rf"^\s*(max|min)\s*{num}\s*{unit}\s*$", s, re.I)
    if m:
        return (None, float(m.group(2))) if m.group(1).lower() == "max" else (float(m.group(2)), None)

    m = re.match(rf"^\s*{num}\s*{unit}\s*$", s)
    if m:
        return (None, float(m.group(1)))

    return (None, None)

@lru_cache(maxsize=1)
def _load_json(abs_path: str):
    with open(abs_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _json_path(app_root: str) -> str:
    return os.path.join(app_root, RANGE_JSON_RELATIVE_PATH)

def get_bulk_ranges(app_root: str, department: str, page: str, system: str, params: list[str]):
    """
    Returns: { param_name: {"low": float|None, "high": float|None, "raw": "x-y"|None} }
    Looks up in this priority:
      1) dept → page → system → param
      2) dept → page → param
      3) dept → system → param
      4) dept → param
    """
    res = {}
    data = _load_json(_json_path(app_root))
    nd, np, ns = _norm(department), _norm(page or ""), _norm(system or "")

    dep_node = None
    for dk, dv in (data or {}).items():
        if _norm(dk) == nd and isinstance(dv, dict):
            dep_node = dv
            break
    if not dep_node:
        return {p: None for p in params}

    def pick_from(d, p):
        npn = _norm(p)
        for k, v in (d or {}).items():
            if isinstance(v, str) and _norm(k) == npn:
                lo, hi = _parse_range_str(v)
                return {"low": lo, "high": hi, "raw": v}
        return None

    for p in params:
        hit = None

        if page:
            for pk, pv in dep_node.items():
                if _norm(pk) == np and isinstance(pv, dict):
                    if system and isinstance(pv.get(system), dict):
                        hit = pick_from(pv.get(system), p)
                        if hit:
                            break
                    if not hit and system:
                        for sk, sv in pv.items():
                            if isinstance(sv, dict) and _norm(sk) == ns:
                                hit = pick_from(sv, p)
                                if hit:
                                    break
                    if not hit:
                        hit = pick_from(pv, p)
                    if hit:
                        break

        if not hit and system:
            sys_node = dep_node.get(system)
            if isinstance(sys_node, dict):
                hit = pick_from(sys_node, p)
            if not hit:
                for sk, sv in dep_node.items():
                    if isinstance(sv, dict) and _norm(sk) == ns:
                        hit = pick_from(sv, p)
                        if hit:
                            break

        if not hit:
            hit = pick_from(dep_node, p)

        res[p] = hit

    return res