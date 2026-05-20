# app/utils/range_notifications.py
# -*- coding: utf-8 -*-
"""
Jindal Steel & Power | Water Quality – Range Notifications (Email)

- Loads canonical ranges from app/app_config/param_ranges_clean.json
- Uses per-department extractors from app.utils.ranges.*
- Evaluates outliers and emails a branded summary (no PDF) to:
  * Department users + admins (excl. Lalit), plus the submitter
- Callable exactly like before: handle_range_alerts(report)
  (now automatically sends email when outliers > 0)

Author: JSPL WQ Platform
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from sqlalchemy import inspect as sqlalchemy_inspect

from flask import current_app, url_for

from app import db
from app.models import User, Department, Report
from app.utils.ranges import (
    get_extractor,
    extract_sms2,
    extract_sms3,
    extract_plate,
    extract_rail,
    extract_spm,
    extract_power,
)

# -----------------------------------------------------------------------------
# SMTP + Branding (mirrors email_notifications.py)
# -----------------------------------------------------------------------------
SENDER_EMAIL = "noreply.digital@jindalsteel.com"
SENDER_NAME = "Water Quality App"
SMTP_SERVER = "172.17.1.17"
SMTP_PORT = 25

BRAND_LOGO_URL = os.environ.get(
    "JINDAL_LOGO_URL",
    "https://www.jindalsteel.com/themes/custom/jindalsteel/logo.svg"
)

BRAND_NAME = "Jindal Steel"
APP_NAME = "Water Quality App"

BRAND_COLOR_SAFFRON = os.environ.get("JINDAL_BRAND_SAFFRON", "#f47b20")
BRAND_COLOR_SAFFRON_SOFT = os.environ.get("JINDAL_BRAND_SAFFRON_SOFT", "#fff1e6")
BRAND_COLOR_SPRING_GREEN = os.environ.get("JINDAL_BRAND_SPRING_GREEN", "#4cb848")
BRAND_COLOR_SPRING_GREEN_SOFT = os.environ.get("JINDAL_BRAND_SPRING_GREEN_SOFT", "#eef9ec")
BRAND_COLOR_GREY = os.environ.get("JINDAL_BRAND_GREY", "#5e5f5e")
BRAND_COLOR_GREY_SOFT = os.environ.get("JINDAL_BRAND_GREY_SOFT", "#f3f4f2")
BRAND_COLOR_WHITE = os.environ.get("JINDAL_BRAND_WHITE", "#ffffff")

BRAND_COLOR_BURGUNDY = os.environ.get("JINDAL_BRAND_BURGUNDY", "#8c3f4c")
BRAND_COLOR_MOSS_GREEN = os.environ.get("JINDAL_BRAND_MOSS_GREEN", "#8ca55d")
BRAND_COLOR_TWILIGHT_BLUE = os.environ.get("JINDAL_BRAND_TWILIGHT_BLUE", "#466684")
BRAND_COLOR_DARK_PEACH = os.environ.get("JINDAL_BRAND_DARK_PEACH", "#d68e5e")
BRAND_COLOR_OYSTER_GREEN = os.environ.get("JINDAL_BRAND_OYSTER_GREEN", "#8c8c6b")
BRAND_COLOR_SKY_BLUE = os.environ.get("JINDAL_BRAND_SKY_BLUE", "#2ca7d4")

BRAND_COLOR_TEXT = os.environ.get("JINDAL_BRAND_TEXT", "#2f3430")
BRAND_COLOR_MUTED = os.environ.get("JINDAL_BRAND_MUTED", "#6d706d")
BRAND_COLOR_LINE = os.environ.get("JINDAL_BRAND_LINE", "rgba(94, 95, 94, 0.18)")
BRAND_COLOR_BG = os.environ.get("JINDAL_BRAND_BG", "#fbfaf6")

BRAND_FONT_STACK = os.environ.get(
    "JINDAL_BRAND_FONT",
    "Poppins, Arial, Helvetica, sans-serif"
)

def _extract_report_id(report_or_id):
    if isinstance(report_or_id, int):
        return report_or_id

    try:
        report_id = getattr(report_or_id, "id", None)
        if report_id is not None:
            return report_id
    except Exception:
        pass

    try:
        identity = sqlalchemy_inspect(report_or_id).identity
        if identity:
            return identity[0]
    except Exception:
        pass

    return None

def _brand_logo_url() -> str:
    """Prefer static logo if present; otherwise fallback URL."""
    try:
        static_dir = os.path.join(current_app.root_path, "static", "images")
        for ext in (".png", ".svg", ".jpg", ".jpeg", ".gif"):
            fname = f"jindal_steel_logo{ext}"
            if os.path.exists(os.path.join(static_dir, fname)):
                return url_for("static", filename=f"images/{fname}", _external=True)
    except Exception:
        pass
    return BRAND_LOGO_URL

def _email_from_header() -> str:
    return formataddr((SENDER_NAME, SENDER_EMAIL))

def _log(msg: str) -> None:
    print(msg, flush=True)

def _brand_header():
    _log("🔧 Jindal RangeChecker ready.")

# -----------------------------------------------------------------------------
# Paths & lazy cache
# -----------------------------------------------------------------------------
_RANGE_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),  # .../utils
    "app_config",
    "param_ranges_clean.json",
)

_RANGES_CACHE: Optional[Dict[str, Any]] = None
_RANGE_INDEX: Optional[Dict[str, Any]] = None

# -----------------------------------------------------------------------------
# Normalization helpers
# -----------------------------------------------------------------------------
_WS = re.compile(r"\s+")
_NONALNUM = re.compile(r"[^a-z0-9]+")

def _norm_token(s: str) -> str:
    s = _WS.sub(" ", str(s or "")).strip().lower()
    return _NONALNUM.sub("", s)

def _page_variants(page: str) -> List[str]:
    p = str(page or "")
    toks = [p, _norm_token(p), _norm_token(p.replace("_", ""))]
    out: List[str] = []
    for t in toks:
        if t and t not in out:
            out.append(t)
    return out or ["", "none"]

def _system_variants(system: str) -> List[str]:
    s = str(system or "").strip()
    out = [s, _norm_token(s)]
    s2 = re.sub(r"\b(?:actual|range|limit)\b", "", s, flags=re.I).strip()
    if s2 != s:
        out.extend([s2, _norm_token(s2)])
    # unique
    seen = set(); uniq=[]
    for t in out:
        if t and t not in seen:
            seen.add(t); uniq.append(t)
    return uniq or [""]

def _param_variants(param: str) -> List[str]:
    p = str(param or "").strip().lower()
    return [p, _norm_token(p)]

# -----------------------------------------------------------------------------
# Load + Index ranges
# -----------------------------------------------------------------------------
def _load_ranges() -> Dict[str, Any]:
    global _RANGES_CACHE
    if _RANGES_CACHE is not None:
        return _RANGES_CACHE
    try:
        with open(_RANGE_JSON_PATH, "r", encoding="utf-8") as f:
            _RANGES_CACHE = json.load(f)
    except Exception as e:
        _log(f"❌ Could not load ranges JSON at '{_RANGE_JSON_PATH}': {e}")
        _RANGES_CACHE = {}

    depts = len(_RANGES_CACHE) if isinstance(_RANGES_CACHE, dict) else 0
    _log(f"🧩 Range JSON loaded: depts={depts} from {_RANGE_JSON_PATH}")
    return _RANGES_CACHE

def _is_param_leaf(node: Any) -> bool:
    if isinstance(node, str):
        return True
    if isinstance(node, dict):
        keys = set(k.lower() for k in node.keys())
        return bool(keys & {"min", "max", "lt", "lte", "gt", "gte", "eq"})
    return False

def _index_ranges() -> Dict[str, Any]:
    global _RANGE_INDEX
    if _RANGE_INDEX is not None:
        return _RANGE_INDEX

    data = _load_ranges()
    index: Dict[Tuple[str, str, str, str], Any] = {}

    def add_entry(dkey: str, pkey: str, skey: str, tkey: str, rule: Any):
        for dv in ([dkey] if not dkey else [dkey, _norm_token(dkey)]):
            for pv in _page_variants(pkey) if pkey else ["", "none"]:
                for sv in _system_variants(skey):
                    for tv in _param_variants(tkey):
                        index[(dv, pv, sv, tv)] = rule

    if isinstance(data, dict):
        for dept, node in data.items():
            if isinstance(node, dict):
                for k1, v1 in node.items():
                    if isinstance(v1, dict):
                        treated_as_page = False
                        for k2, v2 in v1.items():
                            if isinstance(v2, dict):
                                some_leaf = any(_is_param_leaf(v3) for v3 in v2.values())
                                if some_leaf:
                                    for param, rule in v2.items():
                                        if _is_param_leaf(rule):
                                            add_entry(dept, k1, k2, param, rule)
                                    treated_as_page = True
                        if treated_as_page:
                            continue
                        some_leaf = any(_is_param_leaf(v) for v in v1.values())
                        if some_leaf:
                            for param, rule in v1.items():
                                if _is_param_leaf(rule):
                                    add_entry(dept, "", k1, param, rule)
                        else:
                            for sys_name, maybe_params in v1.items():
                                if isinstance(maybe_params, dict):
                                    for param, rule in maybe_params.items():
                                        if _is_param_leaf(rule):
                                            add_entry(dept, k1, sys_name, param, rule)
        # Also accept top-level page → system → param (rare)
        for k_top, v_top in data.items():
            if isinstance(v_top, dict):
                looks_like_page = any(
                    isinstance(x, dict) and any(_is_param_leaf(y) for y in x.values())
                    for x in v_top.values()
                )
                if looks_like_page:
                    for sys_name, params in v_top.items():
                        if isinstance(params, dict):
                            for param, rule in params.items():
                                if _is_param_leaf(rule):
                                    add_entry("", k_top, sys_name, param)

    _RANGE_INDEX = index
    return _RANGE_INDEX

# -----------------------------------------------------------------------------
# Rule parsing & evaluation
# -----------------------------------------------------------------------------
_NUM = re.compile(r"-?\d+(?:\.\d+)?")

def _coerce_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    s = s.replace("F", "5").replace("f", "5")   # tolerate OCR-ish '9.F5'
    m = _NUM.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None

def _parse_rule(rule: Any) -> Optional[Dict[str, float]]:
    if rule is None:
        return None
    if isinstance(rule, dict):
        out: Dict[str, float] = {}
        for k, v in rule.items():
            fv = _coerce_float(v)
            if fv is not None:
                out[k.lower()] = fv
        return out or None

    s = str(rule).strip().lower()
    if not s or s in {"na", "n/a", "-", "as per ph", "asperph"}:
        return None
    if s in {"nil", "zero"}:
        return {"eq": 0.0}

    s_clean = (
        s.replace("ppm", "").replace("ntu", "")
         .replace("µs/cm", "").replace("ms/cm", "")
         .replace("as per ph", "").replace(" ", "")
    )
    if "-" in s_clean and not s_clean.startswith("-"):
        parts = s_clean.split("-")
        if len(parts) == 2:
            a = _coerce_float(parts[0])
            b = _coerce_float(parts[1])
            if a is not None and b is not None:
                lo, hi = (a, b) if a <= b else (b, a)
                return {"min": lo, "max": hi}

    m = re.match(r"^(<=|>=|<|>|=)?(\d+(?:\.\d+)?)$", s_clean)
    if m:
        op, num = m.groups()
        v = float(num)
        return {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "=": "eq"}.get(op, "eq") and {
            {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "=": "eq"}.get(op, "eq"): v
        }

    m2 = re.match(r"^min(\d+(?:\.\d+)?)$", s_clean)
    if m2:
        return {"gte": float(m2.group(1))}

    fv = _coerce_float(s)
    if fv is not None:
        return {"eq": fv}
    return None

def _evaluate(value: float, rule: Dict[str, float]) -> bool:
    if not rule:
        return True
    if "min" in rule and value < rule["min"]:
        return False
    if "max" in rule and value > rule["max"]:
        return False
    if "lt" in rule and not (value < rule["lt"]):
        return False
    if "lte" in rule and not (value <= rule["lte"]):
        return False
    if "gt" in rule and not (value > rule["gt"]):
        return False
    if "gte" in rule and not (value >= rule["gte"]):
        return False
    if "eq" in rule and not (value == rule["eq"]):
        return False
    return True

def _rule_to_text(rule_raw: Any) -> str:
    """Human-friendly rule string for the email table."""
    if isinstance(rule_raw, dict):
        r = {k.lower(): v for k, v in rule_raw.items()}
        if "min" in r and "max" in r:
            return f"{r['min']} to {r['max']}"
        for k in ("lt", "lte", "gt", "gte", "eq"):
            if k in r:
                sym = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "="}[k]
                return f"{sym} {r[k]}"
        # fallback
        try:
            return json.dumps(r)
        except Exception:
            return str(r)
    return str(rule_raw)

# -----------------------------------------------------------------------------
# Dept inference & extractor selection
# -----------------------------------------------------------------------------
_PREFIX_TO_DEPT = [
    ("icw_dcw_", "sms2"),
    ("ccm_eaf_", "sms2"),
    ("sms3_icw_", "sms3"),
    ("sms3_closeloop_", "sms3"),
    ("rail_mill_", "railmill"),
    ("spm_", "spm"),
    ("power_plant_", "powerplant"),
    ("pond07_", "platemill"),
    ("dcw_actual_", "platemill"),
    ("icw_actual_", "platemill"),
]

def _infer_dept(report_obj: Any) -> Optional[str]:
    for attr in ("dept", "department", "dept_name", "dept_display", "dept_key"):
        v = getattr(report_obj, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    try:
        for sec in getattr(report_obj, "sections", []) or []:
            for p in getattr(sec, "parameters", []) or []:
                name = getattr(p, "name", "") or ""
                low = name.lower()
                for prefix, dept in _PREFIX_TO_DEPT:
                    if low.startswith(prefix):
                        return dept
    except Exception:
        pass
    return None

def _choose_extractor(dept: Optional[str]):
    if not dept:
        return None
    fx = get_extractor(dept)
    if fx:
        return fx
    k = _norm_token(dept)
    if k.startswith("sms2"): return extract_sms2
    if k.startswith("sms3"): return extract_sms3
    if k.startswith("platemill"): return extract_plate
    if k.startswith("railmill") or k.startswith("rail"): return extract_rail
    if k.startswith("spm") or k.startswith("specialprofilemill"): return extract_spm
    if k.startswith("power"): return extract_power
    return None

# -----------------------------------------------------------------------------
# Core range check
# -----------------------------------------------------------------------------
def _index_lookup(dept: str, page: str, system: str, param: str) -> Optional[Any]:
    idx = _index_ranges()
    dept_keys = [dept, _norm_token(dept)]
    page_keys = _page_variants(page)
    sys_keys  = _system_variants(system)
    par_keys  = _param_variants(param)

    for dk in dept_keys + ["", "none"]:
        for pk in page_keys:
            for sk in sys_keys:
                for tk in par_keys:
                    rule = idx.get((dk, pk, sk, tk))
                    if rule is not None:
                        return rule
    return None

def check_report_values(dept: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    outliers: List[Dict[str, Any]] = []
    not_found: List[Dict[str, Any]] = []

    for r in rows:
        page = r.get("page", "")
        system = r.get("system", "")
        param = r.get("parameter", "")
        val = r.get("value", None)
        v = _coerce_float(val)
        if v is None:
            continue

        rule_raw = _index_lookup(dept, page, system, param)
        if rule_raw is None:
            not_found.append({"page": page, "system": system, "parameter": param, "value": v})
            continue

        rule = _parse_rule(rule_raw)
        if rule is None:
            continue  # non-enforceable

        if not _evaluate(v, rule):
            outliers.append({
                "page": page, "system": system, "parameter": param, "value": v, "rule": rule_raw
            })

    return {"outliers": outliers, "not_found": not_found, "count": len(rows)}

# -----------------------------------------------------------------------------
# Email helpers (no PDF)
# -----------------------------------------------------------------------------
def _make_range_email_body(report, subject: str, report_url: str, outliers: List[Dict[str, Any]]) -> str:
    """Branded HTML body with an outlier table (no PDF)."""
    logo_url = _brand_logo_url()

    rows_html = []
    for r in outliers:
        sys_name = r.get("system", "-")
        param = r.get("parameter", "-")
        val = r.get("value", "-")
        rule_txt = _rule_to_text(r.get("rule", "-"))
        rows_html.append(
            f"""
            <tr>
              <td style="padding:12px 12px;border-bottom:1px solid rgba(94,95,94,0.14);color:{BRAND_COLOR_TEXT};font-weight:700;">{sys_name}</td>
              <td style="padding:12px 12px;border-bottom:1px solid rgba(94,95,94,0.14);color:{BRAND_COLOR_TEXT};font-weight:800;">{param}</td>
              <td style="padding:12px 12px;border-bottom:1px solid rgba(94,95,94,0.14);color:{BRAND_COLOR_BURGUNDY};font-weight:900;">{val}</td>
              <td style="padding:12px 12px;border-bottom:1px solid rgba(94,95,94,0.14);color:{BRAND_COLOR_GREY};font-weight:900;">{rule_txt}</td>
            </tr>
            """
        )

    table_html = f"""
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="border-collapse:separate;border-spacing:0;border:1px solid rgba(94,95,94,0.16);border-radius:18px;overflow:hidden;background:#ffffff;">
      <thead>
        <tr>
          <th align="left" style="padding:13px 12px;background:linear-gradient(135deg,{BRAND_COLOR_GREY},{BRAND_COLOR_TWILIGHT_BLUE});color:#ffffff;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;">System</th>
          <th align="left" style="padding:13px 12px;background:linear-gradient(135deg,{BRAND_COLOR_GREY},{BRAND_COLOR_TWILIGHT_BLUE});color:#ffffff;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;">Parameter</th>
          <th align="left" style="padding:13px 12px;background:linear-gradient(135deg,{BRAND_COLOR_GREY},{BRAND_COLOR_TWILIGHT_BLUE});color:#ffffff;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;">Value</th>
          <th align="left" style="padding:13px 12px;background:linear-gradient(135deg,{BRAND_COLOR_GREY},{BRAND_COLOR_TWILIGHT_BLUE});color:#ffffff;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;">Allowed Range</th>
        </tr>
      </thead>
      <tbody style="font-size:13px;">
        {''.join(rows_html)}
      </tbody>
    </table>
    """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta http-equiv="x-ua-compatible" content="ie=edge">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{subject}</title>
      <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    </head>
    <body style="margin:0;padding:0;background:{BRAND_COLOR_BG};font-family:{BRAND_FONT_STACK};color:{BRAND_COLOR_TEXT};">
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:linear-gradient(135deg,#ffffff 0%,#fffaf3 42%,#f4faef 100%);">
        <tr>
          <td align="center" style="padding:28px 12px;">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="760" style="max-width:760px;width:100%;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid rgba(94,95,94,0.16);box-shadow:0 18px 44px rgba(94,95,94,0.16);">

              <tr>
                <td style="padding:0;height:7px;background:linear-gradient(90deg,{BRAND_COLOR_SAFFRON} 0%,{BRAND_COLOR_DARK_PEACH} 30%,{BRAND_COLOR_GREY} 58%,{BRAND_COLOR_SPRING_GREEN} 100%);"></td>
              </tr>

              <tr>
                <td style="padding:24px 26px 18px 26px;background:linear-gradient(135deg,#ffffff 0%,{BRAND_COLOR_SAFFRON_SOFT} 50%,{BRAND_COLOR_SPRING_GREEN_SOFT} 100%);">
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                    <tr>
                      <td valign="middle" style="width:88px;">
                        <div style="width:74px;height:74px;border-radius:20px;background:#ffffff;border:1px solid rgba(94,95,94,0.14);box-shadow:0 12px 28px rgba(94,95,94,0.12);display:inline-block;text-align:center;">
                          <img src="{logo_url}" alt="{BRAND_NAME} logo" width="54" style="display:block;height:auto;border:0;margin:20px auto 0 auto;max-width:54px;">
                        </div>
                      </td>
                      <td valign="middle" style="padding-left:14px;">
                        <div style="font-size:12px;font-weight:900;letter-spacing:0.16em;text-transform:uppercase;color:{BRAND_COLOR_SAFFRON};line-height:1.3;">
                          {BRAND_NAME}
                        </div>
                        <div style="font-size:28px;font-weight:900;letter-spacing:-0.04em;line-height:1.08;color:{BRAND_COLOR_GREY};margin-top:4px;">
                          {APP_NAME}
                        </div>
                        <div style="font-size:13px;font-weight:700;color:{BRAND_COLOR_MUTED};margin-top:7px;">
                          Automated Range Alert Notification
                        </div>
                      </td>
                      <td valign="middle" align="right" style="padding-left:12px;">
                        <span style="display:inline-block;padding:10px 14px;border-radius:999px;background:#ffffff;border:1px solid rgba(140,63,76,0.24);color:{BRAND_COLOR_BURGUNDY};font-size:13px;font-weight:900;white-space:nowrap;">
                          ⚠ {len(outliers)} Outlier(s)
                        </span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <tr>
                <td style="padding:24px 26px 8px 26px;background:#ffffff;">
                  <p style="margin:0 0 10px 0;font-size:15px;line-height:1.7;color:{BRAND_COLOR_TEXT};">Hello,</p>
                  <p style="margin:0 0 18px 0;font-size:15px;line-height:1.7;color:{BRAND_COLOR_TEXT};">
                    Out-of-<strong style="color:{BRAND_COLOR_BURGUNDY};">range</strong> parameters were detected after saving a water quality report.
                  </p>

                  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:0 0 18px 0;">
                    <tr>
                      <td width="33.33%" style="padding:0 7px 0 0;">
                        <div style="border:1px solid rgba(244,123,32,0.24);border-radius:18px;background:{BRAND_COLOR_SAFFRON_SOFT};padding:16px 16px;min-height:94px;">
                          <div style="font-size:12px;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;color:{BRAND_COLOR_MUTED};">Report ID</div>
                          <div style="font-size:26px;font-weight:900;color:{BRAND_COLOR_GREY};line-height:1.1;margin-top:8px;">{report.id}</div>
                        </div>
                      </td>
                      <td width="33.33%" style="padding:0 7px;">
                        <div style="border:1px solid rgba(76,184,72,0.24);border-radius:18px;background:{BRAND_COLOR_SPRING_GREEN_SOFT};padding:16px 16px;min-height:94px;">
                          <div style="font-size:12px;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;color:{BRAND_COLOR_MUTED};">Department</div>
                          <div style="font-size:18px;font-weight:900;color:{BRAND_COLOR_GREY};line-height:1.2;margin-top:8px;">{report.department.name}</div>
                        </div>
                      </td>
                      <td width="33.33%" style="padding:0 0 0 7px;">
                        <div style="border:1px solid rgba(140,63,76,0.24);border-radius:18px;background:#fff2f4;padding:16px 16px;min-height:94px;">
                          <div style="font-size:12px;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;color:{BRAND_COLOR_MUTED};">Outliers</div>
                          <div style="font-size:26px;font-weight:900;color:{BRAND_COLOR_BURGUNDY};line-height:1.1;margin-top:8px;">{len(outliers)}</div>
                        </div>
                      </td>
                    </tr>
                  </table>

                  <div style="text-align:center;margin:22px 0 22px 0;">
                    <a href="{report_url}" target="_blank" rel="noopener" style="display:inline-block;padding:14px 24px;border-radius:999px;background:linear-gradient(135deg,{BRAND_COLOR_SAFFRON},{BRAND_COLOR_DARK_PEACH});color:#ffffff;text-decoration:none;font-size:14px;font-weight:900;box-shadow:0 12px 28px rgba(244,123,32,0.22);">
                      View Report
                    </a>
                  </div>

                  {table_html}

                  <p style="margin:18px 0 0 0;font-size:12px;line-height:1.6;color:{BRAND_COLOR_MUTED};text-align:center;">
                    This alert was generated automatically by {APP_NAME}.
                  </p>
                </td>
              </tr>

              <tr>
                <td style="padding:18px 26px 24px 26px;background:#ffffff;">
                  <div style="height:1px;background:rgba(94,95,94,0.14);margin-bottom:16px;"></div>
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                    <tr>
                      <td style="font-size:12px;color:{BRAND_COLOR_MUTED};font-weight:700;">
                        © {BRAND_NAME}. All rights reserved.
                      </td>
                      <td align="right" style="font-size:12px;color:{BRAND_COLOR_MUTED};font-weight:800;">
                        Water Quality Monitoring
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """
    return html

def _route_and_template_for_dept(dept_name_lower: str) -> Tuple[str, str]:
    """Matches email_notifications.py (template value unused here but kept for parity)."""
    if "sms-2" in dept_name_lower:
        return 'sms2_reports.view_report_sms2', "pages/sms_pdf.html"
    if "sms-3" in dept_name_lower:
        return 'sms3_reports.view_report_sms3', "pages/sms_pdf.html"
    if "plate" in dept_name_lower:
        return 'reports.view_report', "pdf/platemill_pdf.html"
    if "rail" in dept_name_lower:
        return 'rail_mill_reports.view_report_rail_mill', "pages/rail_mill_pdf.html"
    if "spm" in dept_name_lower:
        return 'spm_reports.view_report_spm', "pages/spm_pdf.html"
    if "power" in dept_name_lower:
        return 'power_plant_reports.view_report_power_plant', "pages/power_plant_pdf.html"
    return 'reports.view_report', "pages/report_pdf_template.html"

def _collect_recipients(report) -> List[str]:
    """Dept users + admins, exclude Lalit; include submitter."""
    dept_users = (
        db.session.query(User)
        .join(User.departments)
        .filter(Department.id == report.department_id)
        .all()
    )
    admins = User.query.filter_by(role='admin').all()

    recipients = {
        u.email for u in dept_users + admins
        if u.email and u.email.lower() != "lalit.goyal@jindalsteel.com"
    }
    if getattr(report, "user", None) and getattr(report.user, "email", None):
        if report.user.email.lower() != "lalit.goyal@jindalsteel.com":
            recipients.add(report.user.email)

    return sorted(recipients)

def _send_range_email(report, outliers: List[Dict[str, Any]]) -> None:
    """Build + send the branded email (no PDF)."""
    if not outliers:
        return

    report_id = _extract_report_id(report)
    if report_id:
        refreshed_report = db.session.get(Report, report_id)
        if refreshed_report:
            report = refreshed_report

    dept_name = (report.department.name or "").lower()
    route_name, _ = _route_and_template_for_dept(dept_name)

    try:
        report_url = url_for(route_name, report_id=report.id, _external=True)
    except Exception as e:
        _log(f"⚠️ URL generation failed for report ID {report.id}: {e}")
        report_url = "#"

    recipients = _collect_recipients(report)
    if not recipients:
        _log(f"⚠️ No recipients for range alert (report ID {report.id}).")
        return

    subject = f"⚠️ Range Alert – {report.department.name} (ID: {report.id}) – {len(outliers)} outliers"
    html_body = _make_range_email_body(report, subject, report_url, outliers)

    message = MIMEMultipart()
    message['From'] = _email_from_header()
    message['To'] = ", ".join(recipients)
    message['Subject'] = subject
    message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.sendmail(SENDER_EMAIL, recipients, message.as_string())
        _log(f"✅ Range email sent to {len(recipients)} recipients for report ID {report.id}.")
    except Exception as e:
        _log(f"❌ Range email sending failed for report ID {report.id}: {e}")

# -----------------------------------------------------------------------------
# Public entrypoint (compatible with existing call-sites)
# -----------------------------------------------------------------------------
def handle_range_alerts(*args, dept_hint: Optional[str] = None, send_email: bool = True) -> Dict[str, Any]:
    """
    Compatible usage:
      - handle_range_alerts(report)  # now emails automatically if outliers > 0
      - handle_range_alerts(report_id, report_obj)
    """
    _brand_header()

    # Unpack
    if len(args) == 1:
        report_obj = args[0]
        report_id = _extract_report_id(report_obj) or "?"
    elif len(args) >= 2:
        report_id, report_obj = args[0], args[1]
        resolved_report_id = _extract_report_id(report_obj)
        if resolved_report_id:
            report_id = resolved_report_id
    else:
        raise TypeError("handle_range_alerts() expects (report) or (report_id, report_obj)")

    # ✅ FIX: Re-load report inside the active SQLAlchemy session before lazy relationships are accessed.
    if report_id != "?":
        try:
            refreshed_report = db.session.get(Report, report_id)
            if refreshed_report:
                report_obj = refreshed_report
        except Exception as e:
            _log(f"⚠️ RangeCheck: could not refresh report ID {report_id}: {e}")

    # Determine dept/extractor
    dept = dept_hint or _infer_dept(report_obj) or "Unknown"
    extractor = _choose_extractor(dept)
    if extractor is None:
        _log(f"❌ RangeCheck: could not resolve extractor for dept='{dept}'. Skipping.")
        return {"outliers": [], "not_found": [], "count": 0}

    # Extract rows
    try:
        rows = extractor(report_obj)
    except Exception as e:
        _log(f"❌ RangeCheck: extractor crashed for dept='{dept}': {e}")
        return {"outliers": [], "not_found": [], "count": 0}

    _log(f"🔎 RangeCheck: dept={dept}, rows={len(rows)}")

    # Evaluate
    result = check_report_values(dept, rows)
    outliers = result["outliers"]
    not_found = result["not_found"]

    if not_found:
        for nf in not_found:
            _log(f"   • NoRange dept='{_norm_token(dept)}' page='{_norm_token(nf['page'])}' system='{_norm_token(nf['system'])}' param='{nf['parameter']}' value='{nf['value']}'")

    _log(f"🔎 RangeCheck: outliers={len(outliers)}, not_found={len(not_found)}")

    # Email (only if outliers exist)
    if send_email and outliers:
        try:
            # Use current_app context (we're in a request)
            with current_app.app_context():
                _send_range_email(report_obj, outliers)
        except Exception as e:
            _log(f"❌ Range alert email failed for report ID {report_id}: {e}")

    return result

# Convenience for unit tests / manual checks
def check_only(report_obj: Any, dept_hint: Optional[str] = None) -> Dict[str, Any]:
    report_id = _extract_report_id(report_obj)
    if report_id:
        try:
            refreshed_report = db.session.get(Report, report_id)
            if refreshed_report:
                report_obj = refreshed_report
        except Exception:
            pass

    dept = dept_hint or _infer_dept(report_obj) or "Unknown"
    extractor = _choose_extractor(dept)
    rows = extractor(report_obj) if extractor else []
    return check_report_values(dept, rows)